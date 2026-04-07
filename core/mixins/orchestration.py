"""OrchestrationMixin — multiagent dispatch, workflow routing, and request routing."""
from __future__ import annotations

import re
import time

from core.audit import audit_event


class OrchestrationMixin:
    """Handles multiagent missions, workflow execution, and request routing heuristics.

    Expects AgentNimi attributes: config, provider, messages, command_log,
    router, _manual_provider, _tool_calls, _tool_successes, _current_mode,
    episodic_memory, strategy_memory, world_state, _active_todo.
    """

    # ── Conversational / simple-request classifiers ──────────────────────────

    _CONVERSATIONAL_PATTERNS = {
        "hi", "hey", "hello", "yo", "sup", "howdy",
        "ok", "okay", "k", "yep", "yes", "no", "nope", "nah",
        "thanks", "thank you", "thx", "ty",
        "great", "nice", "cool", "perfect", "good", "got it", "noted",
        "sure", "fine", "alright", "sounds good",
        "stop", "quit", "exit", "done",
        "help", "?",
    }

    _SIMPLE_ACTION_PATTERNS = [
        "ping ", "uptime", "whoami", "hostname",
        "show wifi", "list wifi", "scan wifi", "wifi networks",
        "show interfaces", "list interfaces",
        "show ports", "list ports",
        "show ip", "my ip", "what is my ip",
        "show processes", "list processes",
        "disk usage", "df -",
        "show version", "uname",
    ]

    def _needs_target_clarification(self, user_input: str) -> bool:
        """Detect scan/recon requests missing a concrete target."""
        text = (user_input or "").strip().lower()
        if not text:
            return False

        action_words = ("scan", "recon", "enumerate", "probe", "sweep", "summarize findings")
        if not any(word in text for word in action_words):
            return False

        has_ip = bool(re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text))
        has_cidr = bool(re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}\b", text))
        has_url = bool(re.search(r"https?://", text))
        has_domain = bool(re.search(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\b", text))
        if has_ip or has_cidr or has_url or has_domain:
            return False

        deictic = bool(re.search(r"\b(this|that|current|same|here|there)\b", text))
        asset_noun = bool(re.search(r"\b(target|site|page|website|domain|url|host)\b", text))
        viewing_phrase = bool(
            re.search(
                r"\bthe one (?:we are|we're) viewing\b"
                r"|\bthe (?:site|page|website) (?:we are|we're) viewing\b",
                text,
            )
        )
        return viewing_phrase or (deictic and asset_noun)

    def _is_simple_request(self, user_input: str) -> bool:
        """Return True only for genuinely trivial single-tool requests."""
        text = (user_input or "").strip().lower()
        if not text:
            return True
        if text in self._CONVERSATIONAL_PATTERNS:
            return True
        words = text.split()
        if len(words) <= 3 and not any(
            kw in text for kw in (
                "scan", "run", "exec", "find", "show", "list", "get",
                "install", "check", "enum", "recon", "exploit",
            )
        ):
            return True
        multi_markers = [" then ", " and then ", " after that ", " next ", " finally ",
                         "step 1", "step 2", "first,", "second,", " and also ",
                         "recon", "exploit", "enumerate", "privesc", "pivot",
                         "vulnerabilit", "attack", "pentest", "hack", "compromise",
                         "audit", "assess", "report", "analyse", "analyze"]
        if re.search(r'(?:^|\s)\d+\.\s+\w', text):
            return False
        for marker in multi_markers:
            if marker in text:
                return False
        for pattern in self._SIMPLE_ACTION_PATTERNS:
            if pattern in text:
                return True
        return False

    def _should_use_multiagent(self, user_input: str, mconf: dict) -> bool:
        """Use multiagent only when the mission decomposes into multiple segments."""
        if self._is_simple_request(user_input):
            return False
        if len((user_input or "").split()) < 5:
            return False
        try:
            from core.decomposer import decompose_mission
            max_subtasks = int(mconf.get("max_subtasks", 5) or 5)
            segments = decompose_mission(self, user_input, max_subtasks=max_subtasks)
            return len(segments) > 1
        except Exception:
            return False

    # ── Multiagent mission loop ───────────────────────────────────────────────

    def _chat_multiagent(self, user_input: str, stream_callback=None) -> str:
        """Agentred-style autonomous mission loop.

        Nimi's team plans → Nimi executes with tools → results feed back →
        if blockers exist, boss pivots to a creative alternative → repeat.
        """
        _start = time.time()
        audit_event("multiagent_mission_start", {"message": user_input[:800]})
        if stream_callback:
            stream_callback({"event": "agent_start", "provider": "Nimi Boss (multiagent)", "max_iterations": 1})

        from core.multiagent import MultiAgentOrchestrator

        orchestrator = MultiAgentOrchestrator(self)
        mconf = self.config.get("multiagent", {})
        max_mission_iters = int(mconf.get("max_mission_iterations", 4))

        mission_state: dict = {
            "iteration": 0,
            "blockers": [],
            "intel": [],
            "successes": [],
            "failed_tools": [],
        }

        tool_keywords = (
            "nmap", "scan", "search", "enum", "nikto", "gobuster", "hydra",
            "shell", "exec", "install", "searchsploit", "recon", "exploit",
            "brute", "check", "run", "start", "perform", "execute", "audit",
            "list", "find", "get", "show", "display", "curl", "wget",
            "dig", "whois", "ping", "ssh", "ftp", "http",
        )

        final_response = ""
        meta: dict = {}

        for mission_iter in range(max_mission_iters):
            mission_state["iteration"] = mission_iter + 1

            if stream_callback:
                stream_callback({
                    "event": "mission_iteration",
                    "iteration": mission_iter + 1,
                    "max": max_mission_iters,
                    "blockers": len(mission_state["blockers"]),
                    "intel": len(mission_state["intel"]),
                })

            plan, meta = orchestrator.run_mission(
                user_input,
                stream_callback=stream_callback,
                mission_state=mission_state,
            )
            audit_event("multiagent_mission_done", {
                "elapsed": meta.get("elapsed", 0),
                "boss_provider": meta.get("boss_provider", ""),
                "iteration": mission_iter + 1,
            })

            if meta.get("interrupted"):
                return plan

            is_trivial = len(plan.strip()) < 40
            plan_lower = plan.lower()
            looks_actionable = any(kw in plan_lower for kw in tool_keywords)

            cmd_log_before = len(self.command_log)
            tool_calls_before = self._tool_calls

            if not is_trivial and looks_actionable:
                self.messages.append({"role": "assistant", "content": plan})
                exec_lines = [
                    f"[Mission iteration {mission_iter + 1}/{max_mission_iters}] "
                    "Execute the action plan above NOW. "
                    "Call tools immediately — no more planning, no descriptions. ACT FIRST.",
                ]
                if mission_state["failed_tools"]:
                    failed_str = ", ".join(mission_state["failed_tools"])
                    exec_lines.append(
                        f"\nDO NOT retry any of these — they already failed: {failed_str}. "
                        "Use completely different tools and techniques."
                    )
                if stream_callback:
                    stream_callback({"event": "iteration", "current": 1, "max": 20, "provider": self.provider.name()})
                self.messages.append({"role": "user", "content": "\n".join(exec_lines)})
                response = self._agent_loop(stream_callback=stream_callback, max_iterations=20)
            else:
                response = plan

            final_response = response

            new_entries = self.command_log[cmd_log_before:]
            new_tool_calls = self._tool_calls - tool_calls_before
            this_iter_blockers = 0

            for entry in new_entries:
                tool_name = entry.get("tool", "unknown")
                success = entry.get("success", False)
                args_repr = str(entry.get("args", ""))[:120]
                if success:
                    mission_state["successes"].append({
                        "tool": tool_name, "args": args_repr, "iteration": mission_iter + 1,
                    })
                    if args_repr:
                        mission_state["intel"].append(f"[{tool_name}] {args_repr}")
                else:
                    this_iter_blockers += 1
                    if tool_name not in mission_state["failed_tools"]:
                        mission_state["failed_tools"].append(tool_name)
                    mission_state["blockers"].append({
                        "tool": tool_name, "args": args_repr, "iteration": mission_iter + 1,
                    })

            resp_lower = response.lower()
            mission_done = any(phrase in resp_lower for phrase in (
                "mission complete", "objective achieved",
                "successfully completed", "task complete", "all done",
            ))
            if mission_done or mission_iter == max_mission_iters - 1:
                break

            if new_tool_calls == 0 and not looks_actionable:
                break

            if new_tool_calls > 0 and this_iter_blockers == 0:
                break

            if stream_callback:
                stream_callback({
                    "event": "mission_adapting",
                    "iteration": mission_iter + 1,
                    "blockers": len(mission_state["blockers"]),
                })

            failed_str = ", ".join(dict.fromkeys(b["tool"] for b in mission_state["blockers"])) or "none"
            success_str = ", ".join(dict.fromkeys(s["tool"] for s in mission_state["successes"])) or "none"
            self.messages.append({
                "role": "user",
                "content": (
                    f"[Mission Adaptation — Iteration {mission_iter + 1} results]\n"
                    f"Tools that FAILED (do NOT retry): {failed_str}\n"
                    f"Tools that SUCCEEDED: {success_str}\n\n"
                    f"Mission objective is NOT yet complete: {user_input}\n\n"
                    "Boss: pivot to a completely different approach. "
                    "Use different tools, creative scripted alternatives, or unexpected attack vectors. "
                    "Do NOT retry anything that already failed."
                ),
            })

        # ── Final events ──────────────────────────────────────────────────
        elapsed = time.time() - _start
        if stream_callback:
            stream_callback({
                "event": "agent_done",
                "elapsed": round(elapsed, 2),
                "tool_calls": self._tool_calls,
                "tool_successes": self._tool_successes,
                "response_length": len(final_response),
                "mission_iterations": mission_state["iteration"],
            })

        # Router learning
        scores: dict = {}
        if self.router and self.router.enabled and not self._manual_provider:
            try:
                boss_provider = meta.get("boss_provider", "")
                boss_model = meta.get("boss_model", "")
                scores = self.router.evaluator.evaluate(
                    prompt=user_input,
                    response=final_response,
                    provider=boss_provider,
                    model=boss_model,
                    latency_seconds=elapsed,
                    tool_calls=self._tool_calls,
                    tool_successes=self._tool_successes,
                )
                self.router.memory.record(
                    task_type=scores["task_type"],
                    provider=boss_provider,
                    model=boss_model,
                    quality=scores["quality"],
                    latency=scores["latency"],
                    cost=scores["cost"],
                )
                if stream_callback:
                    stream_callback({
                        "event": "learning",
                        "quality": scores.get("quality", 0),
                        "latency": scores.get("latency", 0),
                        "cost": scores.get("cost", 0),
                        "task_type": scores.get("task_type", ""),
                    })
            except Exception:
                pass

        tools_used = list({e["tool"] for e in self.command_log[-20:]})
        _ma_quality = scores.get("quality", 0.5) if scores else 0.5
        _ma_task_type = scores.get("task_type", "general") if scores else "general"
        self._record_strategy(_ma_task_type, "multiagent", tools_used, _ma_quality)
        return final_response

    # ── Workflow dispatch ─────────────────────────────────────────────────────

    def _chat_workflow(self, user_input: str, workflow, task_type: str,
                       stream_callback=None) -> str:
        """Execute a detected workflow pipeline."""
        from core.workflows import run_workflow as _run_workflow

        _start = time.time()
        audit_event("workflow_invoke", {"workflow": workflow.name, "message": user_input[:400]})
        if stream_callback:
            stream_callback({
                "event": "agent_start",
                "provider": f"Nimi Workflow ({workflow.name})",
                "max_iterations": len(workflow.steps),
            })

        result = _run_workflow(self, workflow, initial_input=user_input, stream_callback=stream_callback)
        response = result.final_output
        self.messages.append({"role": "assistant", "content": response})

        elapsed = time.time() - _start
        if stream_callback:
            stream_callback({
                "event": "agent_done",
                "elapsed": round(elapsed, 2),
                "tool_calls": self._tool_calls,
                "tool_successes": self._tool_successes,
                "response_length": len(response),
            })

        _final_quality = 0.5
        _final_task_type = task_type
        if self.router and self.router.enabled and not self._manual_provider:
            try:
                sc = self.router.evaluate_and_learn(
                    prompt=user_input, response=response,
                    latency_seconds=elapsed,
                    tool_calls=self._tool_calls,
                    tool_successes=self._tool_successes,
                )
                _final_quality = sc.get("quality", 0.5)
                _final_task_type = sc.get("task_type", task_type)
                if stream_callback and sc:
                    stream_callback({
                        "event": "learning",
                        "quality": sc.get("quality", 0),
                        "latency": sc.get("latency", 0),
                        "cost": sc.get("cost", 0),
                        "task_type": sc.get("task_type", ""),
                    })
            except Exception:
                pass

        tools_used = list({e["tool"] for e in self.command_log[-20:]})
        self._store_episode(user_input, response, _final_task_type, _final_quality,
                            tools_used, f"workflow:{workflow.name}", [])
        self._record_strategy(_final_task_type, f"workflow:{workflow.name}", tools_used, _final_quality)
        self._manage_context_window()
        return response
