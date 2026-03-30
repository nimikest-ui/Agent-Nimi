"""
Learning Memory Store
─────────────────────
Persists task_type → provider → model → score mappings.
Scores are exponentially weighted moving averages (EWMA) so 
the router adapts as models improve or degrade over time.

Storage: ~/.agent-nimi/memory/scores.json
"""
import json
import time
from pathlib import Path
from threading import Lock

MEMORY_DIR = Path.home() / ".agent-nimi" / "memory"
SCORES_FILE = MEMORY_DIR / "scores.json"
HISTORY_FILE = MEMORY_DIR / "history.jsonl"    # raw evaluation log

# EWMA smoothing factor — higher = faster adaptation
ALPHA = 0.3


class LearningMemory:
    """Stores and retrieves learned performance scores for provider/model combos."""

    def __init__(self):
        self._lock = Lock()
        self._scores: dict[str, dict[str, dict]] = {}
        # Structure:  { task_type: { "provider:model": { "quality": float, "latency": float, "cost": float, "composite": float, "n": int } } }
        self._load()

    # ─── Public API ───

    def record(self, task_type: str, provider: str, model: str,
               quality: float, latency: float, cost: float):
        """Record a single evaluation and update the EWMA scores."""
        key = f"{provider}:{model}"
        composite = self._composite(quality, latency, cost)

        with self._lock:
            if task_type not in self._scores:
                self._scores[task_type] = {}
            bucket = self._scores[task_type]

            if key not in bucket:
                bucket[key] = {
                    "quality": quality,
                    "latency": latency,
                    "cost": cost,
                    "composite": composite,
                    "n": 1,
                }
            else:
                prev = bucket[key]
                prev["quality"] = ALPHA * quality + (1 - ALPHA) * prev["quality"]
                prev["latency"] = ALPHA * latency + (1 - ALPHA) * prev["latency"]
                prev["cost"] = ALPHA * cost + (1 - ALPHA) * prev["cost"]
                prev["composite"] = self._composite(prev["quality"], prev["latency"], prev["cost"])
                prev["n"] += 1

            self._save()

        # Append to history log
        self._append_history({
            "ts": time.time(),
            "task_type": task_type,
            "provider": provider,
            "model": model,
            "quality": quality,
            "latency": latency,
            "cost": cost,
            "composite": composite,
        })

    def best_for(self, task_type: str) -> dict | None:
        """Return the best provider:model for a task type, or None if no data.
        
        Returns: {"provider": str, "model": str, "composite": float, "n": int} or None
        """
        with self._lock:
            bucket = self._scores.get(task_type, {})
            if not bucket:
                return None
            # Pick the entry with highest composite score that has at least 2 samples
            candidates = [(k, v) for k, v in bucket.items() if v["n"] >= 2]
            if not candidates:
                candidates = list(bucket.items())
            best_key, best_val = max(candidates, key=lambda kv: kv[1]["composite"])
            provider, model = best_key.split(":", 1)
            return {
                "provider": provider,
                "model": model,
                "composite": round(best_val["composite"], 3),
                "quality": round(best_val["quality"], 3),
                "latency": round(best_val["latency"], 3),
                "cost": round(best_val["cost"], 3),
                "n": best_val["n"],
            }

    def get_all_scores(self) -> dict:
        """Return the full score table for the UI dashboard."""
        with self._lock:
            return json.loads(json.dumps(self._scores))  # deep copy

    def get_history(self, limit: int = 50) -> list[dict]:
        """Return last N evaluation entries."""
        try:
            entries = []
            if HISTORY_FILE.exists():
                with open(HISTORY_FILE) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            entries.append(json.loads(line))
            return entries[-limit:]
        except Exception:
            return []

    def reset(self):
        """Clear all learned data."""
        with self._lock:
            self._scores = {}
            self._save()
        if HISTORY_FILE.exists():
            HISTORY_FILE.unlink()

    # ─── Internals ───

    @staticmethod
    def _composite(quality: float, latency: float, cost: float) -> float:
        """Compute a single composite score.
        
        quality: 0-1 (higher = better)
        latency: 0-1 (higher = FASTER, so better)
        cost:    0-1 (higher = CHEAPER, so better)
        
        Weights: quality 60%, latency 25%, cost 15%
        """
        return 0.60 * quality + 0.25 * latency + 0.15 * cost

    def _load(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        if SCORES_FILE.exists():
            try:
                with open(SCORES_FILE) as f:
                    self._scores = json.load(f)
            except Exception:
                self._scores = {}

    def _save(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(SCORES_FILE, "w") as f:
                json.dump(self._scores, f, indent=2)
        except Exception:
            pass

    def _append_history(self, entry: dict):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(HISTORY_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass
