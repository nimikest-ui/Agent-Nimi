"""
Fact Memory — persistent key-value store for learned facts.

The agent discovers facts during interactions (e.g. "target runs nginx 1.25",
"nmap found port 22 open on 10.0.0.1").  These are stored as structured tuples
and can be queried by subject or predicate for injection into future prompts.

Two scopes:
  - **global**: persists across all sessions  (~/.agent-nimi/memory/facts.json)
  - **engagement**: scoped to a conversation_id (in-memory only, cleared on end)

Storage format:  list of Fact dicts in JSON.
"""
from __future__ import annotations

import datetime
import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional


FACTS_DIR = Path.home() / ".agent-nimi" / "memory"
FACTS_FILE = FACTS_DIR / "facts.json"
MAX_GLOBAL_FACTS = 1000


@dataclass
class Fact:
    """A single learned fact."""
    subject: str                # e.g. "10.0.0.1", "target_app", "agent_config"
    predicate: str              # e.g. "runs_service", "has_vuln", "os_version"
    value: str                  # e.g. "nginx/1.25", "CVE-2024-1234", "Ubuntu 22.04"
    source: str = "agent"       # who/what produced this fact
    confidence: float = 0.8     # 0-1 confidence score
    timestamp: str = ""         # ISO timestamp
    engagement_id: str = ""     # empty = global scope

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.datetime.now(datetime.UTC).isoformat()


class FactMemory:
    """Persistent fact store with global and engagement scopes."""

    def __init__(self, path: Path | None = None, max_facts: int = MAX_GLOBAL_FACTS):
        self._path = path or FACTS_FILE
        self._max = max_facts
        self._global_facts: list[Fact] = []
        self._engagement_facts: dict[str, list[Fact]] = {}  # engagement_id → facts
        self._loaded = False

    # ── Persistence ───────────────────────────────────────────────────────

    def _ensure_dir(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        if not self._path.exists():
            return
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
            for item in data:
                try:
                    self._global_facts.append(Fact(**item))
                except TypeError:
                    continue
            if len(self._global_facts) > self._max:
                self._global_facts = self._global_facts[-self._max:]
        except (OSError, json.JSONDecodeError):
            pass

    def _save(self):
        self._ensure_dir()
        try:
            with open(self._path, "w") as f:
                json.dump([asdict(fact) for fact in self._global_facts[-self._max:]], f, indent=2)
        except OSError:
            pass

    # ── Store ─────────────────────────────────────────────────────────────

    def store(
        self,
        subject: str,
        predicate: str,
        value: str,
        source: str = "agent",
        confidence: float = 0.8,
        engagement_id: str = "",
    ):
        """Store a fact.  If engagement_id is provided, scoped to that engagement."""
        self._load()
        fact = Fact(
            subject=subject,
            predicate=predicate,
            value=value,
            source=source,
            confidence=confidence,
            engagement_id=engagement_id,
        )

        if engagement_id:
            self._engagement_facts.setdefault(engagement_id, []).append(fact)
        else:
            # Check for duplicates (same subject+predicate) — update in place
            for i, existing in enumerate(self._global_facts):
                if existing.subject == subject and existing.predicate == predicate:
                    self._global_facts[i] = fact
                    self._save()
                    return
            self._global_facts.append(fact)
            if len(self._global_facts) > self._max:
                self._global_facts = self._global_facts[-self._max:]
            self._save()

    def store_many(self, facts: list[dict], engagement_id: str = ""):
        """Store multiple facts from a list of dicts with keys: subject, predicate, value."""
        for f in facts:
            if "subject" in f and "predicate" in f and "value" in f:
                self.store(
                    subject=f["subject"],
                    predicate=f["predicate"],
                    value=f["value"],
                    source=f.get("source", "agent"),
                    confidence=f.get("confidence", 0.8),
                    engagement_id=engagement_id,
                )

    # ── Query ─────────────────────────────────────────────────────────────

    def query(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        engagement_id: str = "",
        min_confidence: float = 0.0,
    ) -> list[Fact]:
        """Find matching facts.  Searches engagement scope first, then global."""
        self._load()
        results = []

        # Engagement-scoped facts first
        if engagement_id:
            for fact in self._engagement_facts.get(engagement_id, []):
                if self._matches(fact, subject, predicate, min_confidence):
                    results.append(fact)

        # Global facts
        for fact in self._global_facts:
            if self._matches(fact, subject, predicate, min_confidence):
                results.append(fact)

        return results

    def query_for_prompt(
        self,
        subjects: list[str] | None = None,
        engagement_id: str = "",
        limit: int = 15,
    ) -> str:
        """Return a formatted string of relevant facts for LLM context injection."""
        self._load()
        facts: list[Fact] = []

        if subjects:
            for subj in subjects:
                facts.extend(self.query(subject=subj, engagement_id=engagement_id))
        else:
            # Return most recent global + engagement facts
            if engagement_id:
                facts.extend(self._engagement_facts.get(engagement_id, [])[-limit:])
            facts.extend(self._global_facts[-limit:])

        if not facts:
            return ""

        # Deduplicate
        seen = set()
        unique = []
        for f in facts:
            key = f"{f.subject}:{f.predicate}"
            if key not in seen:
                seen.add(key)
                unique.append(f)

        unique = unique[:limit]
        lines = ["[KNOWN FACTS — previously learned information]"]
        for f in unique:
            lines.append(f"- {f.subject} {f.predicate}: {f.value} (confidence={f.confidence:.0%})")
        return "\n".join(lines)

    # ── Management ────────────────────────────────────────────────────────

    def forget(self, subject: str, predicate: str | None = None):
        """Remove fact(s) matching subject (and optionally predicate)."""
        self._load()
        before = len(self._global_facts)
        self._global_facts = [
            f for f in self._global_facts
            if not (f.subject == subject and (predicate is None or f.predicate == predicate))
        ]
        if len(self._global_facts) != before:
            self._save()

    def clear_engagement(self, engagement_id: str):
        """Clear all facts scoped to an engagement."""
        self._engagement_facts.pop(engagement_id, None)

    def count(self, engagement_id: str = "") -> int:
        self._load()
        eng_count = len(self._engagement_facts.get(engagement_id, [])) if engagement_id else 0
        return eng_count + len(self._global_facts)

    # ── Internal ──────────────────────────────────────────────────────────

    @staticmethod
    def _matches(fact: Fact, subject: str | None, predicate: str | None, min_confidence: float) -> bool:
        if subject and fact.subject.lower() != subject.lower():
            return False
        if predicate and fact.predicate.lower() != predicate.lower():
            return False
        if fact.confidence < min_confidence:
            return False
        return True
