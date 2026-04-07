"""
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
from tools.shell_tools import start_network_watchdog, is_network_disconnect_command
from core.audit import audit_event
from core.progress import ProgressLedger
from core.episodic_memory import EpisodicMemory
from core.fact_memory import FactMemory
from core.world_state import WorldState
from core.strategy_memory import StrategyMemory
from core.mixins import ModeControlMixin, SafetyMixin, MemoryMixin, OrchestrationMixin


class AgentNimi(ModeControlMixin, SafetyMixin, MemoryMixin, OrchestrationMixin):
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

        # ── Network watchdog (disconnect failsafe) ────────────────────────
        start_network_watchdog(self.config)

        # Active todo list — populated by run_mission at decomposition time
        self._active_todo: list[dict] = []

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
            # Use system role to avoid consecutive user messages (rejected by most LLM APIs)
            self.messages.append({"role": "system", "content": episodic_context})

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
            min_score = workflow_conf.get("min_keyword_score", 2)
            detected_wf = detect_workflow(user_input, min_keyword_score=min_score)
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
                        "event": "task_classified",
                        "task_type": task_type,
                    })
                pname, model, prov = self.router.route(user_input)
                self.provider = prov
                if stream_callback:
                    stream_callback({
                        "event": "routed",
                        "provider": pname,
                        "model": model,
                        "task_type": task_type,
                    })
            except Exception:
                pass  # fall back to currently set provider
        else:
            # Even without routing, classify so the user sees it
            if stream_callback:
                try:
                    from core.evaluator import AutoEvaluator
                    _ev = AutoEvaluator()
                    task_type = _ev.classify_task(user_input)
                    stream_callback({
                        "event": "task_classified",
                        "task_type": task_type,
                    })
                except Exception:
                    pass

        # ── Run the agent loop (with Reflexion retry) ─────────────────────────
        self._tool_calls = 0
        self._tool_successes = 0
        _start = time.time()

        reflexion_conf = self.config.get("reflexion", {})
        max_refinements = int(reflexion_conf.get("max_refinements", 2))
        quality_threshold = float(reflexion_conf.get("quality_threshold", 0.55))

        if stream_callback:
            stream_callback({
                "event": "agent_start",
                "provider": self.provider.name(),
                "max_iterations": 20,
            })

        response = self._agent_loop(stream_callback)

        # ── Reflexion: evaluate and optionally retry ──────────────────────────
        from core.evaluator import AutoEvaluator
        _reflexion_evaluator = AutoEvaluator()
        final_issues: list[str] = []
        retry_ran: bool = False  # True only when _agent_loop is actually called a second time

        for attempt in range(max_refinements):
            quick = _reflexion_evaluator.evaluate_quick(
                prompt=user_input,
                response=response,
                tool_calls=self._tool_calls,
                tool_successes=self._tool_successes,
            )
            final_issues = quick.get("issues", [])

            if quick["quality"] >= quality_threshold:
                break  # good enough

            # Feed critique back and retry
            retry_ran = True
            issues_text = ", ".join(final_issues) if final_issues else "low overall quality"
            audit_event("reflexion_retry", {
                "attempt": attempt + 1,
                "quality": quick["quality"],
                "issues": final_issues,
            })
            if stream_callback:
                stream_callback({
                    "event": "reflexion_retry",
                    "attempt": attempt + 1,
                    "quality": quick["quality"],
                    "issues": final_issues,
                })

            self.messages.append({"role": "assistant", "content": response})
            self.messages.append({
                "role": "user",
                "content": (
                    f"[SELF-CRITIQUE] Your previous answer scored {quick['quality']:.0%} on quality. "
                    f"Issues detected: {issues_text}. "
                    "Please improve your response — address the issues above and provide a better answer."
                ),
            })

            response = self._agent_loop(stream_callback)

        elapsed = time.time() - _start
        if stream_callback:
            stream_callback({
                "event": "agent_done",
                "elapsed": round(elapsed, 2),
                "tool_calls": self._tool_calls,
                "tool_successes": self._tool_successes,
                "response_length": len(response),
            })

        # ── Auto-evaluate, learn, and store episode ──────────────────────────────
        _final_quality = 0.5
        _final_task_type = _task_type_hint
        _final_issues: list[str] = []
        routing_conf = self.config.get("routing", {})
        if (self.router and self.router.enabled
                and not self._manual_provider
                and routing_conf.get("auto_learn", True)):
            try:
                scores = self.router.evaluate_and_learn(
                    prompt=user_input,
                    response=response,
                    latency_seconds=elapsed,
                    tool_calls=self._tool_calls,
                    tool_successes=self._tool_successes,
                )
                _final_quality = scores.get("quality", 0.5)
                _final_task_type = scores.get("task_type", _task_type_hint)
                _final_issues = scores.get("issues", [])
                if stream_callback and scores:
                    stream_callback({
                        "event": "learning",
                        "quality": scores.get("quality", 0),
                        "latency": scores.get("latency", 0),
                        "cost": scores.get("cost", 0),
                        "task_type": scores.get("task_type", ""),
                    })
            except Exception:
                pass

        # ── Store episode in episodic memory ──────────────────────────────────
        tools_used = list({e["tool"] for e in self.command_log[-20:]})
        strategy = "reflexion_retry" if retry_ran else "direct"
        self._store_episode(user_input, response, _final_task_type, _final_quality,
                            tools_used, strategy, _final_issues)
        self._record_strategy(_final_task_type, strategy, tools_used, _final_quality)
        self._manage_context_window()

        return response

    # _needs_target_clarification, _is_simple_request, _should_use_multiagent,
    # _chat_multiagent, _chat_workflow,
    # _CONVERSATIONAL_PATTERNS, _SIMPLE_ACTION_PATTERNS
    #   → all live in OrchestrationMixin (core/mixins/orchestration.py)

    def cancel(self):
        """Signal the agent loop to stop after the current step."""
        self._cancelled = True

    def _agent_loop(self, stream_callback=None, max_iterations: int = 20) -> str:
        """Run the agent loop until LLM returns a plain text response.

        Includes:
        - ProgressLedger for tracking unique actions and detecting stalls
        - Reflection prompts after each tool execution
        - Repetition warnings when the same tool+args are tried again
        - Progress summaries injected every N iterations
        - Safeguards against stuck loops (unrecognized tools, repeated failures)
        """
        full_response_parts = []
        ledger = ProgressLedger()
        reflection_conf = self.config.get("reflexion", {})
        progress_interval = int(reflection_conf.get("progress_summary_interval", 5))
        stall_window = int(reflection_conf.get("stall_window", 4))
        
        consecutive_unknown_tools = 0  # Counter for unrecognized tool calls
        consecutive_tool_failures = 0  # Counter for failed tool executions

        # ── Inject active mission todo into context (if any) ──────────────
        if self._active_todo:
            icon_map = {"pending": "○", "running": "▶", "done": "✓", "failed": "✗"}
            todo_lines = ["[MISSION TODO — current progress]"]
            for t in self._active_todo:
                status = t.get("status", "pending")
                icon = icon_map.get(status, "○")
                role_badge = f" [{t['role']}]" if t.get("role") else ""
                todo_lines.append(f"  {icon} {t.get('description', t.get('id', '?'))}{role_badge}")
            self.messages.append({"role": "system", "content": "\n".join(todo_lines)})

        for iteration in range(max_iterations):
            self.consume_mode_switches(stream_callback)
            if self._current_mode != "agent":
                return f"[Mode switched to {self._current_mode}; agent loop paused.]"
            if self._cancelled:
                self.messages.append({"role": "assistant", "content": "[Cancelled by user]"})
                return "[Cancelled by user]"

            # Drain any pending steer messages before calling LLM
            self._drain_steer_messages(stream_callback)

            # Notify iteration start
            if stream_callback:
                stream_callback({
                    "event": "iteration",
                    "current": iteration + 1,
                    "max": max_iterations,
                    "provider": self.provider.name(),
                })

            # Get LLM response — use a smart streaming wrapper:
            # If the response starts with '{' it's a tool-call JSON and must NOT
            # be shown as text in the UI.  Stream text live only when we can
            # confirm it isn't a tool call (first non-whitespace char is not '{').
            _llm_start = time.time()
            if stream_callback:
                stream_callback({"event": "llm_call_start", "provider": self.provider.name()})

            _streaming_live = False   # True once we confirmed non-tool response
            if stream_callback:
                _buf: list[str] = []
                _decided = False          # True once we've seen the first real char

                def _smart_stream(chunk: str):
                    nonlocal _streaming_live, _decided
                    if isinstance(chunk, dict):
                        # Pass through structured events unchanged
                        stream_callback(chunk)
                        return
                    _buf.append(chunk)
                    if not _decided:
                        combined = "".join(_buf).lstrip()
                        if combined:
                            _decided = True
                            if not combined.startswith("{"):
                                # Plain text — flush buffer and stream live
                                _streaming_live = True
                                for c in _buf:
                                    stream_callback(c)
                            # else: tool-call JSON — stay silent, don't stream
                    elif _streaming_live:
                        stream_callback(chunk)

                response_text = self._call_llm(_smart_stream)
            else:
                response_text = self._call_llm(None)

            _llm_elapsed = time.time() - _llm_start
            if stream_callback:
                stream_callback({
                    "event": "llm_call_done",
                    "elapsed": round(_llm_elapsed, 2),
                    "response_length": len(response_text),
                })

            # Try to parse a tool call
            tool_call = parse_tool_call(response_text)

            if tool_call is None:
                # Regular text response — if we were suppressing (shouldn't happen
                # here since plain text doesn't start with '{', but just in case),
                # emit the full text now as a single chunk so the UI shows it.
                if stream_callback and not _streaming_live:
                    stream_callback(response_text)
                self.messages.append({"role": "assistant", "content": response_text})

                # If operator steered during this LLM call, loop again
                # so the LLM can react to the steering
                if not self._steer_queue.empty():
                    self._drain_steer_messages(stream_callback)
                    continue

                return response_text

            # We have a tool call
            tool_name = tool_call["tool"]
            tool_args = tool_call["args"]

            # ── Tool diversity gate ───────────────────────────────────────────
            recent_same_tool = [a for a in ledger.actions[-5:] if a.tool == tool_name]
            if len(recent_same_tool) >= 2:
                redirect_msg = (
                    f"[DIVERSITY GATE] You have called '{tool_name}' {len(recent_same_tool)} times "
                    "in the last 5 actions. This call is being blocked to prevent looping. "
                    "You must try a DIFFERENT approach:\n"
                    "  - Write a custom script with shell_exec\n"
                    "  - Use searchsploit, curl, or wget to search online\n"
                    "  - Pick a different tool from the Kali catalog\n"
                    "  - Read an existing file or log for clues\n"
                    "Do not attempt to call this tool again until you have tried something else."
                )
                self.messages.append({"role": "assistant", "content": response_text})
                self.messages.append({"role": "user", "content": redirect_msg})
                if stream_callback:
                    stream_callback({"event": "tool_diversity_blocked", "tool": tool_name, "recent_count": len(recent_same_tool)})
                continue  # skip to next iteration, let LLM rethink

            # ── Check if tool exists ──────────────────────────────────────
            if tool_name not in list_tools():
                consecutive_unknown_tools += 1
                consecutive_tool_failures = 0
                error_msg = (
                    f"[TOOL NOT FOUND] Unknown tool: {tool_name}. "
                    f"Available tools: {', '.join(list_tools()[:10])}... "
                    f"(and more). Please check the tool name and try again."
                )
                self.messages.append({"role": "assistant", "content": response_text})
                self.messages.append({"role": "user", "content": f"Tool result:\n{error_msg}"})
                audit_event("tool_not_found", {"tool": tool_name, "attempt": consecutive_unknown_tools})
                if stream_callback:
                    stream_callback({"event": "tool_not_found", "tool": tool_name})
                
                # Bail out if stuck on unknown tools
                if consecutive_unknown_tools >= 3:
                    msg = (
                        f"[ABORT] Tried calling non-existent tool '{tool_name}' multiple times. "
                        f"I don't have this capability. Stopping here."
                    )
                    self.messages.append({"role": "assistant", "content": msg})
                    audit_event("agent_abort_unknown_tool", {"tool": tool_name})
                    return msg
                continue

            consecutive_unknown_tools = 0  # Reset on successful tool lookup
            if self._workflow_tools_allowed is not None:
                if tool_name not in self._workflow_tools_allowed:
                    wl_msg = (
                        f"[WORKFLOW RESTRICTION] Tool '{tool_name}' is not allowed in this "
                        f"workflow step. Allowed tools: {self._workflow_tools_allowed or '(none)'}. "
                        "Please complete this step using only the allowed tools or plain reasoning."
                    )
                    self.messages.append({"role": "assistant", "content": response_text})
                    self.messages.append({"role": "user", "content": wl_msg})
                    if stream_callback:
                        stream_callback({
                            "event": "workflow_tool_blocked",
                            "tool": tool_name,
                            "allowed": self._workflow_tools_allowed,
                        })
                    continue

            # Safety check
            if not self._safety_check(tool_name, tool_args):
                blocked_msg = f"[BLOCKED] Command blocked by safety policy."
                self.messages.append({"role": "assistant", "content": response_text})
                self.messages.append({"role": "user", "content": f"Tool result:\n{blocked_msg}"})
                if stream_callback:
                    stream_callback({"event": "safety_check", "tool": tool_name, "passed": False})
                    stream_callback({"event": "tool_blocked", "tool": tool_name, "message": blocked_msg})
                continue

            # Safety check passed
            if stream_callback:
                stream_callback({"event": "safety_check", "tool": tool_name, "passed": True})

            # ── Destructive-action confirmation gate ───────────────────────
            if self._needs_confirmation(tool_name):
                confirmed = self._request_confirmation(tool_name, tool_args, stream_callback)
                if not confirmed:
                    declined_msg = f"[DECLINED] User declined execution of {tool_name}."
                    self.messages.append({"role": "assistant", "content": response_text})
                    self.messages.append({"role": "user", "content": f"Tool result:\n{declined_msg}"})
                    audit_event("tool_declined", {"tool": tool_name, "args": str(tool_args)[:500]})
                    if stream_callback:
                        stream_callback({"event": "tool_declined", "tool": tool_name})
                    continue

            # Notify tool start
            if stream_callback:
                stream_callback({"event": "tool_start", "tool": tool_name, "args": tool_args})

            _tool_start = time.time()
            result = run_tool(tool_name, tool_args)
            _tool_elapsed = time.time() - _tool_start
            self._tool_calls += 1
            if result["success"]:
                self._tool_successes += 1
                consecutive_tool_failures = 0  # Reset on success
            else:
                consecutive_tool_failures += 1

            # If the same tool keeps failing, give up
            if consecutive_tool_failures >= 3:
                msg = (
                    f"[ABORT] Tool '{tool_name}' has failed 3 times in a row: {result['output']}. "
                    f"Stopping to avoid infinite loop."
                )
                self.messages.append({"role": "assistant", "content": response_text})
                self.messages.append({"role": "user", "content": f"Tool result:\n{msg}"})
                self.messages.append({"role": "assistant", "content": msg})
                audit_event("agent_abort_tool_failures", {"tool": tool_name, "failures": consecutive_tool_failures})
                return msg

            # If a custom tool was created/deleted, refresh our system prompt
            if tool_name in ("create_tool", "delete_tool") and result["success"]:
                from tools.custom_loader import refresh_agent_prompt
                refresh_agent_prompt(self)

            # Log the command
            self._log_command(tool_name, tool_args, result)

            # Truncate very long outputs for the LLM context
            output = result["output"]
            if len(output) > 15000:
                output = output[:15000] + "\n\n[...output truncated for context length...]"

            # ── Vision: describe screenshots via LLM (Phase 11) ──────────────
            _vision_enabled = self.config.get("vision", {}).get("enabled", True)
            if _vision_enabled and tool_name == "browser_screenshot" and result["success"] and output.startswith("data:image"):
                try:
                    vision_prompt = (
                        "Describe this browser screenshot in detail. "
                        "Identify visible UI elements, text content, URLs, form fields, "
                        "error messages, and anything security-relevant. "
                        "Be specific and thorough — your description will be used for further analysis."
                    )
                    vision_messages = list(self.messages) + [
                        {"role": "assistant", "content": response_text},
                        {"role": "user", "content": vision_prompt},
                    ]
                    vision_provider = self.provider
                    description = vision_provider.chat_vision(
                        messages=vision_messages,
                        images=[output],
                        stream=False,
                    )
                    if stream_callback:
                        stream_callback({
                            "event": "vision_description",
                            "session_id": tool_args.get("session_id", ""),
                            "description": description[:500],
                        })
                    output = f"[Screenshot captured — vision analysis]\n{description}"
                except Exception as _vision_err:
                    # Vision unavailable: fall back to noting the screenshot was captured
                    output = f"[Screenshot captured — vision analysis unavailable: {_vision_err}]\nRaw data URI length: {len(result['output'])} chars."

            # Notify tool result
            if stream_callback:
                stream_callback({
                    "event": "tool_result",
                    "tool": tool_name,
                    "success": result["success"],
                    "output": output,
                    "elapsed": round(_tool_elapsed, 2),
                    "output_length": len(result["output"]),
                })

            # ── Record in progress ledger ──────────────────────────────────────
            is_new = ledger.record_action(
                iteration=iteration,
                tool=tool_name,
                args=tool_args,
                success=result["success"],
                output=result["output"],
            )

            # ── Update world-state model (Phase 8) ────────────────────────────
            self.world_state.update_from_tool_result(
                tool_name, tool_args, result["output"], result["success"],
            )

            # ── Feed result back to LLM ───────────────────────────────────────
            self.messages.append({"role": "assistant", "content": response_text})
            self.messages.append({
                "role": "user",
                "content": f"Tool execution result ({tool_name}):\n{output}"
            })

            # ── Reflection prompt ─────────────────────────────────────────────
            reflection = ledger.reflection_prompt()
            self.messages.append({"role": "user", "content": reflection})

            if stream_callback:
                stream_callback({
                    "event": "reflection",
                    "iteration": iteration + 1,
                    "is_new_action": is_new,
                    "is_stalled": ledger.is_stalled(stall_window),
                })

            # ── Reasoning trace (Phase 7) ─────────────────────────────────────
            self._emit_reasoning_trace(
                step=iteration + 1,
                thought=response_text,
                action=f"{tool_name}({json.dumps(tool_args, default=str)[:300]})",
                observation=output,
                reflection=reflection,
                stream_callback=stream_callback,
            )

            # ── Stall detection: break early if truly stuck ───────────────────
            if ledger.is_stalled(stall_window):
                audit_event("stall_detected", {
                    "iteration": iteration + 1,
                    "unique_actions": len(ledger.unique_keys),
                    "consecutive_failures": ledger.consecutive_failures(),
                })
                if stream_callback:
                    stream_callback({"event": "stall_detected", "iteration": iteration + 1})

                # Pull fresh alternatives from the tool catalog
                try:
                    recent_tools = [a.tool for a in ledger.actions[-4:] if a.tool]
                    used_str = ", ".join(set(recent_tools)) if recent_tools else "none"
                    all_tools = list_tools()
                    alternatives = [t for t in all_tools if t not in recent_tools][:8]
                    alt_str = ", ".join(alternatives) if alternatives else "write a custom script"
                    stall_injection = (
                        f"[STALL DETECTED] You have been stuck using: {used_str}. "
                        f"These have not solved the problem. "
                        f"Available alternatives you have NOT tried: {alt_str}. "
                        "You may also write a custom Python script using shell_exec, "
                        "or search online with: "
                        "shell_exec(command=\"curl 'https://cve.circl.lu/api/search/KEYWORD'\") "
                        "or shell_exec(command=\"searchsploit KEYWORD\"). "
                        "Choose a different path now."
                    )
                    self.messages.append({"role": "user", "content": stall_injection})
                except Exception:
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "[STALL DETECTED] Your recent actions are all repeats or failures. "
                            "You MUST either try a completely different approach, "
                            "or provide your best answer with what you have so far."
                        ),
                    })

            # ── Periodic progress summary ─────────────────────────────────────
            if (iteration + 1) % progress_interval == 0 and iteration + 1 < max_iterations:
                remaining = max_iterations - iteration - 1
                summary = ledger.summary(remaining_iterations=remaining)

                # Include world-state snapshot when available
                ws_summary = self.world_state.summary()
                if ws_summary:
                    summary += f"\n\n[ENVIRONMENT STATE]\n{ws_summary}"

                self.messages.append({
                    "role": "user",
                    "content": f"[PROGRESS REPORT] {summary}",
                })
                audit_event("progress_summary", {
                    "iteration": iteration + 1,
                    "summary": summary,
                })

            # Check for steering messages injected mid-execution
            self._drain_steer_messages(stream_callback)

        return "[Agent reached maximum iterations. Please break your task into smaller steps.]"

    def _call_llm(self, stream_callback=None) -> str:
        """Call the LLM provider and collect the response.

        Includes graceful degradation (Phase 10.1): if the current provider
        fails with a connection/API error, the router transparently switches
        to the next available provider and retries once.
        """
        try:
            response = self.provider.chat(self.messages, stream=True)

            if isinstance(response, str):
                if stream_callback:
                    stream_callback(response)
                return response

            # Streaming response
            chunks = []
            for chunk in response:
                chunks.append(chunk)
                if stream_callback:
                    stream_callback(chunk)
            return "".join(chunks)

        except Exception as e:
            # ── Graceful degradation attempt ───────────────────────────────
            if self.router and self.router.enabled and not self._manual_provider:
                try:
                    failed_name = self.provider.name()
                    pname, model, prov = self.router.degrade(
                        failed_provider=failed_name,
                        prompt=self.messages[-1].get("content", "") if self.messages else "",
                        stream_callback=stream_callback,
                    )
                    self.provider = prov
                    audit_event("llm_degraded", {
                        "from": failed_name,
                        "to": pname,
                        "error": str(e)[:200],
                    })
                    # Retry with new provider
                    response = self.provider.chat(self.messages, stream=True)
                    if isinstance(response, str):
                        if stream_callback:
                            stream_callback(response)
                        return response
                    chunks = []
                    for chunk in response:
                        chunks.append(chunk)
                        if stream_callback:
                            stream_callback(chunk)
                    return "".join(chunks)
                except Exception:
                    pass  # degradation also failed — return error below

            error_msg = f"[LLM Error: {type(e).__name__}: {e}]"
            if stream_callback:
                stream_callback(error_msg)
            return error_msg

    def _log_command(self, tool_name: str, args: dict, result: dict):
        """Log a tool execution."""
        if not self.config.get("logging", {}).get("enabled", True):
            return

        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "tool": tool_name,
            "args": args,
            "success": result["success"],
            "output_length": len(result["output"]),
        }
        audit_event("tool_executed", entry)
        self.command_log.append(entry)

        # Write to log file
        try:
            log_file = self.log_dir / f"agent-{datetime.date.today().isoformat()}.jsonl"
            with open(log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────
    # Reasoning Trace (Phase 7)
    # ─────────────────────────────────────────────────────────────────────

    def _emit_reasoning_trace(
        self,
        step: int,
        thought: str,
        action: str,
        observation: str,
        reflection: str,
        stream_callback=None,
    ):
        """Record a structured reasoning step in audit and optionally SSE."""
        trace = {
            "step": step,
            "thought": thought[:500],
            "action": action[:300],
            "observation": observation[:500],
            "reflection": reflection[:300],
        }
        audit_event("reasoning_trace", trace)
        if stream_callback:
            stream_callback({"event": "reasoning_trace", **trace})

    def switch_provider(self, provider_name: str):
        """Switch to a different LLM provider (disables smart routing until re-enabled)."""
        provider_config = self.config["providers"].get(provider_name, {})
        self.provider = get_provider(provider_name, provider_config)
        self._manual_provider = True  # user has taken explicit control

    def reset_conversation(self):
        """Clear conversation history."""
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def get_history_summary(self) -> str:
        """Get a summary of the conversation."""
        user_msgs = [m for m in self.messages if m["role"] == "user"]
        assistant_msgs = [m for m in self.messages if m["role"] == "assistant"]
        return (
            f"Messages: {len(self.messages)} total "
            f"({len(user_msgs)} user, {len(assistant_msgs)} assistant)\n"
            f"Tools executed: {len(self.command_log)}\n"
            f"Provider: {self.provider.name()}"
        )

    # ─────────────────────────────────────────────────────────────────────
    # Smart Router helpers
    # ─────────────────────────────────────────────────────────────────────

    def router_stats(self) -> dict | None:
        """Return smart router stats (scores, history, current provider).
        Returns None when routing is disabled.
        """
        if self.router:
            return self.router.get_stats()
        return None

    def enable_routing(self):
        """Re-enable smart routing (clears the manual-provider override flag)."""
        self._manual_provider = False
        if self.router:
            self.router.enabled = True

    def disable_routing(self):
        """Disable smart routing so the current provider is always used."""
        self._manual_provider = True
        if self.router:
            self.router.enabled = False

    @property
    def routing_active(self) -> bool:
        """True when smart routing will be applied on the next chat() call."""
        return bool(self.router and self.router.enabled and not self._manual_provider)
