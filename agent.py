Agent Core - The main agent loop that ties LLM + Tools together
"""
import json
import datetime
import os
import queue
import re
import time
from pathlib import Path

from config import load_config, SYSTEM_PROMPT
from providers import get_provider
from tools import run_tool, parse_tool_call, list_tools
from tools.registry import get_tool as get_tool_info, ACTION_CLASSES
from core.audit import audit_event
from core.decomposer import decompose_mission
from core.progress import ProgressLedger
from core.episodic_memory import EpisodicMemory
from core.fact_memory import FactMemory
from core.world_state import WorldState
from core.strategy_memory import StrategyMemory


class AgentNimi:
    """Main agent class - manages conversation, LLM calls, and tool execution."""

    def __init__(self, provider_name: str = None, config: dict = None):
        self.config = config or load_config()
        provider_name = provider_name or self.config["default_provider"]
        provider_config = self.config["providers"].get(provider_name, {})
        self.provider = get_provider(provider_name, provider_config)
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.command_log: list[dict] = []
        self.safety = self.config.get("safety", {})
        self.log_dir = Path(self.config.get("logging", {}).get("log_dir", "~/.agent-nimi/logs")).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._cancelled = False
        self._steer_queue = queue.Queue()
        self._mode_switch_queue = queue.Queue()
        mode_conf = self.config.get("architecture", {}).get("mode_controller", {})
        self._current_mode = mode_conf.get("default_mode", "agent")
        # Per-turn tracking (reset in chat())
        self._tool_calls: int = 0
        self._tool_successes: int = 0
        # True after the user manually calls switch_provider() — bypasses routing
        # until re-enabled.  Flipped back to False by enable_routing().
        self._manual_provider: bool = False
        # Smart router (None when routing is disabled in config)
        routing_conf = self.config.get("routing", {})
        if routing_conf.get("enabled", True):
            from core.router import SmartRouter
            self.router: "SmartRouter | None" = SmartRouter(self.config)
        else:
            self.router = None

        # ── Structured memory (Phase 2) ───────────────────────────────────
        self.episodic_memory = EpisodicMemory()
        self.fact_memory = FactMemory()
        mem_conf = self.config.get("memory", {})
        self._max_context_tokens = int(mem_conf.get("max_context_tokens", 12000))
        self._context_summary_model = mem_conf.get("summary_model", "")

        # ── Environment model (Phase 8) ───────────────────────────────────
        self.world_state = WorldState()

        # ── Strategy memory (Phase 10.2) ──────────────────────────────────
        self.strategy_memory = StrategyMemory()

        # ── Workflow support (Phase 9) ────────────────────────────────────
        # Set by run_workflow() to restrict allowed tools during a step
        self._workflow_tools_allowed = None

    def steer(self, message: str):
        """Inject a steering message into the running agent loop."""
        self._steer_queue.put(message)

    def set_mode(self, mode: str):
        """Set current execution mode."""
        if mode not in {"ask", "plan", "agent"}:
            return
        if mode != self._current_mode:
            audit_event("mode_set", {"from": self._current_mode, "to": mode})
        self._current_mode = mode

    def request_mode_switch(self, mode: str):
        """Queue a live mode switch request that can interrupt active workflows."""
        audit_event("mode_switch_requested", {"to": mode})
        self._mode_switch_queue.put(mode)

    @property
    def current_mode(self) -> str:
        return self._current_mode

    def consume_mode_switches(self, stream_callback=None):
        """Apply any queued mode switch requests and emit SSE-friendly events."""
        while True:
            try:
                requested = self._mode_switch_queue.get_nowait()
                if requested not in {"ask", "plan", "agent"}:
                    continue
                if requested != self._current_mode:
                    audit_event("mode_switched", {"from": self._current_mode, "to": requested})
                    self._current_mode = requested
                    if stream_callback:
                        stream_callback({"event": "mode_switched", "mode": requested})
            except queue.Empty:
                break

    def should_interrupt(self, stream_callback=None) -> tuple[bool, str]:
        """Return interrupt state for long-running orchestration calls."""
        self.consume_mode_switches(stream_callback)
        if self._cancelled:
            return True, "cancelled"
        if self._current_mode != "agent":
            return True, f"mode:{self._current_mode}"
        return False, ""

    def chat(self, user_input: str, stream_callback=None) -> str:
        """Process user input through the agent loop.
        
        1. Recall relevant episodic memory and facts
        2. Optionally route to the best provider via SmartRouter
        3. Send user message + history to LLM
        4. Check if response contains a tool call
        5. If yes: execute tool, feed result back, goto 3
        6. If no: return the text response; auto-evaluate, learn, and store episode
        """
        # Reset cancellation flag — a previous cancel() call (e.g. from the
        # blueprint clearing the last request) must not bleed into this new call.
        self._cancelled = False

        # ── Inject episodic + fact memory into context ────────────────────────
        try:
            from core.evaluator import AutoEvaluator
            _classifier = AutoEvaluator()
            _task_type_hint = _classifier.classify_task(user_input)
        except Exception:
            _task_type_hint = "general"

        episodic_context = self.episodic_memory.recall_for_prompt(
            user_input, task_type=_task_type_hint, limit=3,
        )
        # Global facts are NOT auto-injected — the agent uses recall_facts tool
        # explicitly when needed.  Auto-injecting all stored facts causes stale
        # data from past engagements to bleed into unrelated conversations.
        if episodic_context:
            self.messages.append({"role": "user", "content": episodic_context})

        self.messages.append({"role": "user", "content": user_input})

        self.consume_mode_switches(stream_callback)

        if self._needs_target_clarification(user_input):
            response = (
                "I need a concrete target before I run that. "
                "Please provide an exact IP, CIDR, domain, or URL, then I’ll execute the scan and summarize findings."
            )
            self.messages.append({"role": "assistant", "content": response})
            return response

        mconf = self.config.get("multiagent", {})
        multiagent_enabled = bool(mconf.get("enabled_in_agent_mode", True))
        force_single = bool(mconf.get("force_single_agent", False))

        # ── Strategy memory: check recommended approach ───────────────────
        recommended_strategy = self.strategy_memory.recommend(_task_type_hint)

        # ── Workflow detection (Phase 9) ──────────────────────────────────
        workflow_conf = self.config.get("workflow", {})
        if workflow_conf.get("enabled", True) and self._current_mode == "agent":
            from core.workflows import detect_workflow, run_workflow as _run_workflow
            detected_wf = detect_workflow(user_input)
            # Also trigger workflow if strategy memory says so
            if not detected_wf and recommended_strategy.startswith("workflow:"):
                wf_name = recommended_strategy.split(":", 1)[1]
                from core.workflows import get_workflow
                detected_wf = get_workflow(wf_name)
            if detected_wf:
                return self._chat_workflow(
                    user_input, detected_wf, _task_type_hint,
                    stream_callback,
                )

        if (
            self._current_mode == "agent"
            and multiagent_enabled
            and not force_single
            and self.router
            and self.router.enabled
            and self._should_use_multiagent(user_input, mconf)
        ):
            return self._chat_multiagent(user_input, stream_callback)

        # ── Smart routing ─────────────────────────────────────────────────────
        if self.router and self.router.enabled and not self._manual_provider:
            try:
                task_type = self.router.evaluator.classify_task(user_input)
                if stream_callback:
                    stream_callback({