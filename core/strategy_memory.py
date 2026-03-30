"""
Strategy Memory (Phase 10.2)
────────────────────────────
Tracks which *execution strategies* work best for each task type so the
agent can chose the optimal approach before even starting.

Strategies:
  - ``direct``          — single agent loop
  - ``multiagent``      — multi-agent orchestration
  - ``workflow:<name>``  — a named workflow pipeline
  - ``reflexion_retry`` — direct + reflexion retry needed (indicates weakness)

Each record stores ``(task_type, strategy, tools_used, quality)`` and uses
EWMA (like LearningMemory) to converge on the best strategy over time.

Storage: ``~/.agent-nimi/memory/strategies.json``
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock

MEMORY_DIR = Path.home() / ".agent-nimi" / "memory"
STRATEGIES_FILE = MEMORY_DIR / "strategies.json"
STRATEGY_HISTORY_FILE = MEMORY_DIR / "strategy_history.jsonl"

# EWMA smoothing — same as LearningMemory
ALPHA = 0.3


class StrategyMemory:
    """Store & query strategy effectiveness per task type."""

    def __init__(self):
        self._lock = Lock()
        # Structure: { task_type: { strategy: { quality, tools_used_freq, n } } }
        self._scores: dict[str, dict[str, dict]] = {}
        self._load()

    # ─── Public API ───────────────────────────────────────────────────────

    def record(
        self,
        task_type: str,
        strategy: str,
        tools_used: list[str],
        quality: float,
    ):
        """Record the outcome of a strategy choice.

        Parameters
        ----------
        task_type : str
            Classified task type (e.g. ``recon``, ``exploit``, ``code``).
        strategy : str
            The execution strategy that was used.
        tools_used : list[str]
            Tool names that were invoked during execution.
        quality : float
            Final quality score (0-1).
        """
        with self._lock:
            if task_type not in self._scores:
                self._scores[task_type] = {}
            bucket = self._scores[task_type]

            if strategy not in bucket:
                bucket[strategy] = {
                    "quality": quality,
                    "tools_freq": _build_freq(tools_used),
                    "n": 1,
                }
            else:
                prev = bucket[strategy]
                prev["quality"] = ALPHA * quality + (1 - ALPHA) * prev["quality"]
                prev["n"] += 1
                # Merge tool frequencies
                prev["tools_freq"] = _merge_freq(prev["tools_freq"], tools_used)

            self._save()

        # Append to history
        self._append_history({
            "ts": time.time(),
            "task_type": task_type,
            "strategy": strategy,
            "tools_used": tools_used,
            "quality": quality,
        })

    def best_for(self, task_type: str) -> dict | None:
        """Return the best strategy for a task type, or None if no data.

        Returns
        -------
        dict or None
            ``{"strategy": str, "quality": float, "n": int,
               "top_tools": list[str]}``
        """
        with self._lock:
            bucket = self._scores.get(task_type, {})
            if not bucket:
                return None

            # Only trust strategies with >=2 observations
            candidates = [(k, v) for k, v in bucket.items() if v["n"] >= 2]
            if not candidates:
                candidates = list(bucket.items())
            if not candidates:
                return None

            best_key, best_val = max(candidates, key=lambda kv: kv[1]["quality"])
            top_tools = _top_tools(best_val.get("tools_freq", {}), limit=5)

            return {
                "strategy": best_key,
                "quality": round(best_val["quality"], 3),
                "n": best_val["n"],
                "top_tools": top_tools,
            }

    def recommend(self, task_type: str) -> str:
        """Return the recommended strategy name, defaulting to ``direct``.

        Requires only 1 observation before making a recommendation (EWMA
        already handles noise from a single sample).  A threshold of >=2
        meant the system never recommended anything for the first interaction
        of each task type.
        """
        best = self.best_for(task_type)
        if best and best["n"] >= 1:
            return best["strategy"]
        return "direct"

    def get_all_scores(self) -> dict:
        """Return full strategy table (for debugging / UI)."""
        with self._lock:
            return json.loads(json.dumps(self._scores))

    def get_history(self, limit: int = 50) -> list[dict]:
        """Return last N strategy history entries."""
        try:
            entries = []
            if STRATEGY_HISTORY_FILE.exists():
                with open(STRATEGY_HISTORY_FILE) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            entries.append(json.loads(line))
            return entries[-limit:]
        except Exception:
            return []

    def reset(self):
        """Clear all strategy data."""
        with self._lock:
            self._scores = {}
            self._save()
        if STRATEGY_HISTORY_FILE.exists():
            STRATEGY_HISTORY_FILE.unlink()

    # ─── Persistence ──────────────────────────────────────────────────────

    def _load(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        if STRATEGIES_FILE.exists():
            try:
                with open(STRATEGIES_FILE) as f:
                    self._scores = json.load(f)
            except Exception:
                self._scores = {}

    def _save(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(STRATEGIES_FILE, "w") as f:
                json.dump(self._scores, f, indent=2)
        except Exception:
            pass

    def _append_history(self, entry: dict):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(STRATEGY_HISTORY_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_freq(tools: list[str]) -> dict[str, int]:
    """Build a frequency dict from a list of tool names."""
    freq: dict[str, int] = {}
    for t in tools:
        freq[t] = freq.get(t, 0) + 1
    return freq


def _merge_freq(existing: dict[str, int], new_tools: list[str]) -> dict[str, int]:
    """Merge new tool uses into an existing frequency dict."""
    merged = dict(existing)
    for t in new_tools:
        merged[t] = merged.get(t, 0) + 1
    return merged


def _top_tools(freq: dict[str, int], limit: int = 5) -> list[str]:
    """Return the most frequently used tools, sorted by count descending."""
    if not freq:
        return []
    return [t for t, _ in sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:limit]]
