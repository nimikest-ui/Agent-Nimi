"""
Progress Ledger — lightweight metacognitive tracker for the agent loop.

Tracks unique actions taken, detects stalls (repeated failures / no progress),
and provides a concise summary the LLM can consume as a "progress report"
injected every few iterations.

Inspired by Microsoft Magentic-One's dual-ledger architecture.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


@dataclass
class ActionRecord:
    """One recorded action inside the agent loop."""
    iteration: int
    tool: str
    args_hash: str
    success: bool
    output_snippet: str  # first 200 chars of output


class ProgressLedger:
    """Track progress, detect stalls, and generate summaries for the LLM."""

    def __init__(self, max_history: int = 50):
        self.actions: list[ActionRecord] = []
        self.unique_keys: set[str] = set()
        self.completed_goals: list[str] = []
        self.current_goal: str = ""
        self._max_history = max_history

    # ── Recording ─────────────────────────────────────────────────────────

    @staticmethod
    def _hash_args(args: dict) -> str:
        """Deterministic hash of tool arguments for dedup detection."""
        try:
            raw = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            raw = str(args)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def record_action(
        self,
        iteration: int,
        tool: str,
        args: dict,
        success: bool,
        output: str = "",
    ) -> bool:
        """Record an action.  Returns True if this is a *new* unique action."""
        args_hash = self._hash_args(args)
        key = f"{tool}:{args_hash}"
        is_new = key not in self.unique_keys
        self.unique_keys.add(key)

        self.actions.append(ActionRecord(
            iteration=iteration,
            tool=tool,
            args_hash=args_hash,
            success=success,
            output_snippet=output[:200],
        ))
        # Keep bounded
        if len(self.actions) > self._max_history:
            self.actions = self.actions[-self._max_history:]
        return is_new

    # ── Detection ─────────────────────────────────────────────────────────

    def is_repeated(self, tool: str, args: dict, window: int = 5) -> bool:
        """True if the exact same (tool, args) already appeared in the last *window* actions."""
        args_hash = self._hash_args(args)
        key = f"{tool}:{args_hash}"
        recent = self.actions[-window:]
        return any(f"{a.tool}:{a.args_hash}" == key for a in recent)

    def is_stalled(self, window: int = 4) -> bool:
        """True when the last *window* actions show no forward progress.

        Stall = all recent actions are either:
          - repeated (same tool+args already tried), or
          - failures
        """
        if len(self.actions) < window:
            return False
        recent = self.actions[-window:]
        for rec in recent:
            key = f"{rec.tool}:{rec.args_hash}"
            # Count how many times this key appears in ALL history
            count = sum(1 for a in self.actions if f"{a.tool}:{a.args_hash}" == key)
            is_repeat = count > 1
            if rec.success and not is_repeat:
                return False  # at least one new successful action → not stalled
        return True

    def consecutive_failures(self) -> int:
        """Number of consecutive failures at the tail of the history."""
        count = 0
        for rec in reversed(self.actions):
            if not rec.success:
                count += 1
            else:
                break
        return count

    # ── Summaries ─────────────────────────────────────────────────────────

    def summary(self, remaining_iterations: int = 0) -> str:
        """Concise progress summary suitable for injection into LLM context."""
        total = len(self.actions)
        unique = len(self.unique_keys)
        successes = sum(1 for a in self.actions if a.success)
        failures = total - successes

        parts = [
            f"Progress: {unique} unique actions taken ({successes} succeeded, {failures} failed).",
        ]
        if self.completed_goals:
            parts.append(f"Completed goals: {'; '.join(self.completed_goals[-5:])}.")
        if self.current_goal:
            parts.append(f"Current goal: {self.current_goal}.")
        if remaining_iterations > 0:
            parts.append(f"Remaining iterations: {remaining_iterations}.")
        if self.is_stalled():
            parts.append("WARNING: You appear stalled — recent actions are all repeats or failures. Try a different approach.")
        return " ".join(parts)

    def reflection_prompt(self, tool: str, args: dict, success: bool, output: str) -> str:
        """Build a reflection prompt after a tool execution."""
        status = "succeeded" if success else "FAILED"
        snippet = output[:300].replace("\n", " ")

        lines = [
            f"[REFLECT] Last action: {tool}({json.dumps(args, default=str)[:200]}) → {status}.",
            f"Output snippet: {snippet}",
        ]

        if not success:
            lines.append("Consider: What went wrong? Is there an alternative tool or different arguments to try?")

        if self.is_repeated(tool, args):
            lines.append(
                "⚠ You have already tried this exact action before. "
                "You MUST try a different approach or explain why this sub-goal is unachievable."
            )

        return "\n".join(lines)
