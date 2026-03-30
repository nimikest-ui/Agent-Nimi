"""
Episodic Memory — stores complete interaction episodes for long-term recall.

Each episode captures what was asked, which strategy/tools/provider were used,
whether it succeeded, and any lessons derived.  On subsequent tasks the agent
retrieves the most relevant past episodes and injects them into context so it
can learn from its own history.

Storage: ~/.agent-nimi/memory/episodes.jsonl  (append-only, one JSON per line)
"""
from __future__ import annotations

import datetime
import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


EPISODES_DIR = Path.home() / ".agent-nimi" / "memory"
EPISODES_FILE = EPISODES_DIR / "episodes.jsonl"
MAX_EPISODES = 500  # Keep at most this many; older ones are pruned on load


@dataclass
class Episode:
    """One recorded interaction episode."""
    timestamp: str
    task_summary: str          # 1-line summary of what was asked
    task_type: str             # from evaluator.classify_task()
    strategy: str              # "direct" | "multiagent" | "reflexion_retry"
    tools_used: list[str]      # which tools were invoked
    provider_model: str        # e.g. "grok:grok-3"
    outcome: str               # "success" | "partial" | "failure"
    quality_score: float       # from evaluator (0-1)
    lessons: list[str]         # extracted insights
    keywords: list[str]        # keywords for retrieval matching


class EpisodicMemory:
    """Persistent episodic memory backed by a JSONL file."""

    def __init__(self, path: Path | None = None, max_episodes: int = MAX_EPISODES):
        self._path = path or EPISODES_FILE
        self._max = max_episodes
        self._episodes: list[Episode] = []
        self._loaded = False

    # ── Persistence ───────────────────────────────────────────────────────

    def _ensure_dir(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self):
        """Lazy-load episodes from disk (once)."""
        if self._loaded:
            return
        self._loaded = True
        if not self._path.exists():
            return
        try:
            with open(self._path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        self._episodes.append(Episode(**data))
                    except (json.JSONDecodeError, TypeError):
                        continue
            # Prune to max
            if len(self._episodes) > self._max:
                self._episodes = self._episodes[-self._max:]
        except OSError:
            pass

    def _append_to_disk(self, episode: Episode):
        self._ensure_dir()
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(asdict(episode)) + "\n")
        except OSError:
            pass

    # ── Store ─────────────────────────────────────────────────────────────

    def store(self, episode: Episode):
        """Store a new episode (in memory + on disk)."""
        self._load()
        self._episodes.append(episode)
        self._append_to_disk(episode)
        # In-memory prune
        if len(self._episodes) > self._max:
            self._episodes = self._episodes[-self._max:]

    def store_from_interaction(
        self,
        user_input: str,
        response: str,
        task_type: str,
        provider_model: str,
        quality_score: float,
        tools_used: list[str] | None = None,
        strategy: str = "direct",
        issues: list[str] | None = None,
    ):
        """Convenience: build and store an episode from raw interaction data."""
        # Derive outcome from quality
        if quality_score >= 0.7:
            outcome = "success"
        elif quality_score >= 0.4:
            outcome = "partial"
        else:
            outcome = "failure"

        # Build lessons from issues
        lessons = []
        if issues:
            for issue in issues:
                if "code_task_missing_code" in issue:
                    lessons.append("Should include code blocks for code tasks")
                elif "action_task_no_tool_use" in issue:
                    lessons.append("Should use tools for action-oriented tasks")
                elif "hallucination_marker" in issue:
                    lessons.append("Avoid AI disclaimers; act directly")
                elif "response_too_short" in issue:
                    lessons.append("Provide more detailed responses")
                elif "error_in_short_response" in issue:
                    lessons.append("Previous approach produced errors; try alternative")

        # Extract keywords from user input
        keywords = self._extract_keywords(user_input)

        # Build summary (first 120 chars of input)
        summary = user_input[:120].replace("\n", " ").strip()
        if len(user_input) > 120:
            summary += "..."

        episode = Episode(
            timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
            task_summary=summary,
            task_type=task_type,
            strategy=strategy,
            tools_used=tools_used or [],
            provider_model=provider_model,
            outcome=outcome,
            quality_score=round(quality_score, 4),
            lessons=lessons,
            keywords=keywords,
        )
        self.store(episode)

    # ── Recall ────────────────────────────────────────────────────────────

    def recall(
        self,
        task_type: str = "",
        keywords: list[str] | None = None,
        limit: int = 3,
    ) -> list[Episode]:
        """Retrieve the most relevant past episodes.

        Matching is based on:
          1. Same task_type (strong signal)
          2. Keyword overlap (weaker signal)
          3. Recency as tiebreaker
        """
        self._load()
        if not self._episodes:
            return []

        query_kws = set(kw.lower() for kw in (keywords or []))

        scored: list[tuple[float, int, Episode]] = []
        for idx, ep in enumerate(self._episodes):
            score = 0.0
            # Task type match
            if task_type and ep.task_type == task_type:
                score += 3.0
            # Keyword overlap (Jaccard-ish)
            ep_kws = set(kw.lower() for kw in ep.keywords)
            if query_kws and ep_kws:
                overlap = len(query_kws & ep_kws)
                score += overlap * 1.0
            # Recency bonus (newer = higher idx)
            score += idx * 0.001
            # Quality bonus — successful episodes are more useful
            if ep.outcome == "success":
                score += 1.0
            scored.append((score, idx, ep))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [ep for _, _, ep in scored[:limit]]

    def recall_for_prompt(
        self,
        user_input: str,
        task_type: str = "",
        limit: int = 3,
    ) -> str:
        """Return a formatted string suitable for injection into the LLM system prompt."""
        keywords = self._extract_keywords(user_input)
        episodes = self.recall(task_type=task_type, keywords=keywords, limit=limit)
        if not episodes:
            return ""

        lines = ["[PAST EXPERIENCE — relevant episodes from previous sessions]"]
        for ep in episodes:
            tools_str = ", ".join(ep.tools_used[:5]) if ep.tools_used else "none"
            lessons_str = "; ".join(ep.lessons) if ep.lessons else "none"
            lines.append(
                f"- Task: \"{ep.task_summary}\" (type={ep.task_type}, "
                f"strategy={ep.strategy}, provider={ep.provider_model}, "
                f"outcome={ep.outcome}, quality={ep.quality_score:.0%}). "
                f"Tools: {tools_str}. Lessons: {lessons_str}"
            )
        return "\n".join(lines)

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """Extract meaningful keywords from text for retrieval matching."""
        # Remove common stop words and keep meaningful tokens
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "need", "dare", "ought",
            "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
            "into", "through", "during", "before", "after", "above", "below",
            "between", "under", "again", "further", "then", "once", "here",
            "there", "when", "where", "why", "how", "all", "both", "each",
            "few", "more", "most", "other", "some", "such", "no", "nor", "not",
            "only", "own", "same", "so", "than", "too", "very", "just", "and",
            "but", "or", "if", "this", "that", "these", "those", "it", "its",
            "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
            "she", "her", "they", "them", "their", "what", "which", "who",
            "please", "help", "want", "like", "get", "make", "use", "know",
        }
        words = re.findall(r"[a-z0-9_.-]+", text.lower())
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        # Deduplicate while preserving order
        seen = set()
        result = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                result.append(kw)
        return result[:20]  # Cap at 20 keywords

    def count(self) -> int:
        self._load()
        return len(self._episodes)

    def recent(self, n: int = 10) -> list[Episode]:
        """Return the N most recent episodes."""
        self._load()
        return self._episodes[-n:]
