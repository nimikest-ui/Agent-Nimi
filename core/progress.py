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

    def reflection_prompt(self, tool: str, args: dict, success: bool, output: str) -> str:  # noqa: E501
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


# ── OuterTaskLedger (Phase 15) ────────────────────────────────────────────────

from dataclasses import dataclass as _dc, field as _field
from enum import Enum as _Enum
from typing import Optional as _Optional
import time as _time


class SubtaskStatus(_Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"
    SKIPPED   = "skipped"


@dataclass
class SubtaskRecord:
    """One tracked subtask at the outer (mission) level."""
    subtask_id: str
    description: str
    role: str
    status: SubtaskStatus = SubtaskStatus.PENDING
    started_at: float = field(default_factory=_time.time)
    finished_at: float = 0.0
    outcome_snippet: str = ""      # first 300 chars of output
    validation_score: float = -1.0  # -1 means not validated


class OuterTaskLedger:
    """Mission-level tracker — records each subtask and overall goal status.

    Inspired by Microsoft Magentic-One's OuterLoopAgent ledger architecture.
    The OuterTaskLedger operates at the multiagent level (one per run_mission call),
    while ProgressLedger operates at the inner agent-loop level (one per agent._agent_loop).
    """

    def __init__(self, mission: str = "") -> None:
        self.mission = mission
        self.subtasks: list[SubtaskRecord] = []
        self._started_at: float = _time.time()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def add_subtask(self, subtask_id: str, description: str, role: str) -> SubtaskRecord:
        rec = SubtaskRecord(subtask_id=subtask_id, description=description, role=role)
        self.subtasks.append(rec)
        return rec

    def start_subtask(self, subtask_id: str) -> None:
        rec = self._find(subtask_id)
        if rec:
            rec.status = SubtaskStatus.RUNNING
            rec.started_at = _time.time()

    def complete_subtask(
        self,
        subtask_id: str,
        outcome: str = "",
        success: bool = True,
        validation_score: float = -1.0,
    ) -> None:
        rec = self._find(subtask_id)
        if rec:
            rec.status = SubtaskStatus.DONE if success else SubtaskStatus.FAILED
            rec.finished_at = _time.time()
            rec.outcome_snippet = outcome[:300]
            rec.validation_score = validation_score

    def skip_subtask(self, subtask_id: str) -> None:
        rec = self._find(subtask_id)
        if rec:
            rec.status = SubtaskStatus.SKIPPED
            rec.finished_at = _time.time()

    # ── Status ────────────────────────────────────────────────────────────

    def all_done(self) -> bool:
        return all(
            r.status in (SubtaskStatus.DONE, SubtaskStatus.FAILED, SubtaskStatus.SKIPPED)
            for r in self.subtasks
        )

    def success_rate(self) -> float:
        done = [r for r in self.subtasks if r.status == SubtaskStatus.DONE]
        total = len(self.subtasks)
        return len(done) / total if total else 0.0

    def elapsed(self) -> float:
        return round(_time.time() - self._started_at, 2)

    # ── Summary ───────────────────────────────────────────────────────────

    def summary(self) -> str:
        lines = [f"Mission: {self.mission or '(unnamed)'}  [{self.elapsed()}s elapsed]"]
        for r in self.subtasks:
            icon = {
                SubtaskStatus.PENDING:  "○",
                SubtaskStatus.RUNNING:  "▶",
                SubtaskStatus.DONE:     "✓",
                SubtaskStatus.FAILED:   "✗",
                SubtaskStatus.SKIPPED:  "–",
            }[r.status]
            val_str = f"  val={r.validation_score:.2f}" if r.validation_score >= 0 else ""
            lines.append(f"  {icon} [{r.role}] {r.description[:80]}{val_str}")
        rate = self.success_rate()
        lines.append(f"Success rate: {rate:.0%}  ({sum(1 for r in self.subtasks if r.status == SubtaskStatus.DONE)}/{len(self.subtasks)} done)")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "mission": self.mission,
            "elapsed": self.elapsed(),
            "success_rate": self.success_rate(),
            "subtasks": [
                {
                    "id": r.subtask_id,
                    "role": r.role,
                    "description": r.description,
                    "status": r.status.value,
                    "validation_score": r.validation_score,
                    "outcome_snippet": r.outcome_snippet,
                }
                for r in self.subtasks
            ],
        }

    # ── Internal ──────────────────────────────────────────────────────────

    def _find(self, subtask_id: str) -> _Optional[SubtaskRecord]:
        for r in self.subtasks:
            if r.subtask_id == subtask_id:
                return r
        return None
