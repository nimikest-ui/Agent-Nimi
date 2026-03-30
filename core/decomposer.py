"""Mission decomposition into typed subtasks and context bundle construction.

Supports two strategies:
  1. **LLM-assisted** (default) — ask a cheap LLM to produce structured subtasks
     with dependency ordering.  Falls back to regex if the LLM call fails.
  2. **Regex-based** (fallback) — sentence-split + classify each segment.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any

from core.evaluator import AutoEvaluator
from tools.registry import discover_tools


# ── Subtask dataclass ─────────────────────────────────────────────────────────

@dataclass
class Subtask:
    """One decomposed subtask with dependency tracking."""
    index: int
    description: str
    task_type: str
    depends_on: list[int] = field(default_factory=list)
    recommended_tools: list[str] = field(default_factory=list)
    complexity: str = "medium"  # low | medium | high

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── LLM decomposition prompt ─────────────────────────────────────────────────

_DECOMPOSE_PROMPT = """You are a task decomposition engine.  Break the following mission into ordered subtasks.

For each subtask return a JSON object with these keys:
- "description": what to do (1-2 sentences)
- "task_type": one of [{task_types}]
- "depends_on": list of subtask indices (0-based) that must complete first, [] if independent
- "complexity": "low", "medium", or "high"

Return ONLY a JSON array of subtask objects.  No markdown, no explanation.
Max {max_subtasks} subtasks.  Merge trivial steps.

Mission:
{mission}"""


# ── Public API ────────────────────────────────────────────────────────────────

def build_context_bundle(agent, mission: str) -> dict[str, Any]:
    """Build lightweight context that travels with each subtask."""
    return {
        "mission": mission,
        "mode": getattr(agent, "current_mode", "agent"),
        "provider": agent.provider.name() if agent else "",
        "routing_active": bool(agent.routing_active) if agent else False,
    }


def decompose_mission(
    agent,
    mission: str,
    max_subtasks: int = 5,
    use_llm: bool = True,
) -> list[dict[str, Any]]:
    """Split a mission into typed segments.

    Returns list of dicts compatible with the original API:
        {segment, task_type, recommended_tools, depends_on, complexity, index}

    When *use_llm* is True, attempts LLM-assisted decomposition first and
    falls back to regex-based splitting on failure.
    """
    text = (mission or "").strip()
    if not text:
        return []

    # Try LLM-assisted decomposition
    if use_llm and agent:
        try:
            subtasks = _llm_decompose(agent, text, max_subtasks)
            if subtasks and len(subtasks) > 0:
                return [_enrich_subtask(st) for st in subtasks]
        except Exception:
            pass  # fall through to regex

    # Regex fallback (original logic)
    return _regex_decompose(text, max_subtasks)


def decompose_mission_structured(
    agent,
    mission: str,
    max_subtasks: int = 5,
    use_llm: bool = True,
) -> list[Subtask]:
    """Like decompose_mission but returns Subtask dataclasses."""
    raw = decompose_mission(agent, mission, max_subtasks, use_llm=use_llm)
    result = []
    for i, item in enumerate(raw):
        result.append(Subtask(
            index=item.get("index", i),
            description=item.get("segment", ""),
            task_type=item.get("task_type", "general"),
            depends_on=item.get("depends_on", []),
            recommended_tools=item.get("recommended_tools", []),
            complexity=item.get("complexity", "medium"),
        ))
    return result


def estimate_complexity(subtasks: list[dict | Subtask]) -> str:
    """Estimate overall mission complexity from subtask list.

    Used by multiagent to decide how many roles to activate.
    """
    n = len(subtasks)
    if n <= 1:
        return "low"
    if n <= 3:
        complexities = []
        for st in subtasks:
            c = st.get("complexity", "medium") if isinstance(st, dict) else st.complexity
            complexities.append(c)
        if "high" in complexities:
            return "high"
        return "medium"
    return "high"


# ── Replanning ────────────────────────────────────────────────────────────────

_REPLAN_PROMPT = """You are a replanning engine.  Given the original plan and results so far,
decide whether the remaining plan needs adjustment.

Original plan (JSON):
{plan}

Completed subtasks and their outcomes:
{completed}

Last result:
{last_result}

If the remaining plan is still correct, respond with exactly: NO_CHANGE
If changes are needed, respond with ONLY a JSON array of revised remaining subtasks
(same format as original: description, task_type, depends_on, complexity).
No markdown, no explanation."""


def replan_if_needed(
    agent,
    original_plan: list[dict],
    completed: list[dict],
    last_result: str,
    remaining: list[dict],
) -> list[dict] | None:
    """Ask the LLM whether the remaining plan needs adjustment.

    Returns None if no change needed, otherwise the revised remaining subtasks.
    """
    if not agent or not remaining:
        return None

    try:
        provider = _get_cheap_provider(agent)
        if not provider:
            return None

        prompt = _REPLAN_PROMPT.format(
            plan=json.dumps(original_plan, default=str)[:2000],
            completed=json.dumps(completed, default=str)[:2000],
            last_result=last_result[:1000],
        )
        messages = [{"role": "user", "content": prompt}]
        response = provider.chat(messages, stream=False)
        if isinstance(response, str):
            text = response.strip()
        else:
            text = "".join(response).strip()

        if "NO_CHANGE" in text.upper():
            return None

        # Try to parse revised subtasks
        parsed = _parse_json_array(text)
        if parsed and isinstance(parsed, list):
            evaluator = AutoEvaluator()
            result = []
            for i, item in enumerate(parsed[:5]):
                task_type = item.get("task_type", evaluator.classify_task(item.get("description", "")))
                result.append({
                    "index": i,
                    "segment": item.get("description", ""),
                    "task_type": task_type,
                    "depends_on": item.get("depends_on", []),
                    "recommended_tools": _discover_tools_for_type(task_type),
                    "complexity": item.get("complexity", "medium"),
                })
            return result if result else None
    except Exception:
        pass
    return None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _llm_decompose(agent, mission: str, max_subtasks: int) -> list[dict]:
    """Use an LLM to decompose the mission into structured subtasks.

    Tries lower-cost providers first, then falls back to the agent's current
    provider so decomposition works even when preferred providers are
    unavailable or returning auth errors.
    """
    cheap = _get_cheap_provider(agent)
    # Build provider list: cheap first, then current provider as fallback
    providers_to_try = []
    if cheap is not None:
        providers_to_try.append(cheap)
    if agent.provider and (not providers_to_try or agent.provider is not cheap):
        providers_to_try.append(agent.provider)

    if not providers_to_try:
        return []

    evaluator = AutoEvaluator()
    task_types = ", ".join(sorted(evaluator.TASK_PATTERNS.keys()))
    prompt = _DECOMPOSE_PROMPT.format(
        task_types=task_types,
        max_subtasks=max_subtasks,
        mission=mission,
    )
    messages = [{"role": "user", "content": prompt}]

    for provider in providers_to_try:
        try:
            response = provider.chat(messages, stream=False)
            if not isinstance(response, str):
                response = "".join(response)

            parsed = _parse_json_array(response)
            if not parsed or not isinstance(parsed, list):
                continue

            result = []
            for i, item in enumerate(parsed[:max_subtasks]):
                if not isinstance(item, dict):
                    continue
                task_type = item.get("task_type", "general")
                if task_type not in evaluator.TASK_PATTERNS and task_type != "general":
                    task_type = evaluator.classify_task(item.get("description", ""))
                result.append({
                    "index": i,
                    "segment": item.get("description", ""),
                    "task_type": task_type,
                    "depends_on": item.get("depends_on", []),
                    "recommended_tools": _discover_tools_for_type(task_type),
                    "complexity": item.get("complexity", "medium"),
                })
            if result:
                return result
        except Exception:
            continue  # try next provider

    return []


def _get_cheap_provider(agent):
    """Get the cheapest available provider for decomposition/replanning calls."""
    from providers import get_provider

    # Priority: copilot (included quota) -> grok -> current provider fallback.
    cheap_order = ["copilot", "grok"]
    providers_conf = agent.config.get("providers", {})
    for pname in cheap_order:
        if pname in providers_conf:
            try:
                prov = get_provider(pname, providers_conf[pname])
                return prov
            except Exception:
                continue
    # Fallback to current provider
    return agent.provider


def _regex_decompose(text: str, max_subtasks: int) -> list[dict[str, Any]]:
    """Regex-based sentence-splitting decomposition (fallback).

    Splits on sentence boundaries first; if still one segment, also tries
    splitting on comma+connective clause patterns common in multi-step
    security mission prompts (e.g. "scan ports, enumerate services, find CVEs").
    """
    normalized = text.replace("\n", ". ")
    raw_segments = [
        seg.strip(" -•\n\t")
        for seg in re.split(r"(?<=[!?])\s+|(?<=\.)\s+(?=[A-Za-z])", normalized)
        if seg.strip()
    ]

    # If only one segment, try splitting on comma+connective/verb patterns.
    # Handles prompts like: "Scan X, enumerate services, find CVEs, write exploit"
    if len(raw_segments) <= 1:
        clause_parts = re.split(
            r",\s*(?:then|and|next|after(?:\s+that)?|also|followed\s+by|finally)?\s+",
            normalized,
            flags=re.I,
        )
        # Only use if we got more meaningful pieces
        if len(clause_parts) > 1:
            raw_segments = [p.strip() for p in clause_parts if p.strip()]

    if not raw_segments:
        raw_segments = [text]
    raw_segments = raw_segments[:max(1, max_subtasks)]

    evaluator = AutoEvaluator()
    result: list[dict[str, Any]] = []
    for i, segment in enumerate(raw_segments):
        task_type = evaluator.classify_task(segment)
        result.append({
            "index": i,
            "segment": segment,
            "task_type": task_type,
            "recommended_tools": _discover_tools_for_type(task_type),
            "depends_on": [i - 1] if i > 0 else [],  # simple sequential deps
            "complexity": "medium",
        })
    return result


def _discover_tools_for_type(task_type: str) -> list[str]:
    """Find recommended tools for a given task type."""
    capability = _task_capability(task_type)
    trust_tier = _task_trust_tier(task_type)
    discovered = discover_tools(capability=capability, trust_tier=trust_tier)
    return [item.get("name", "") for item in discovered][:5]


def _enrich_subtask(raw: dict) -> dict:
    """Ensure an LLM-produced subtask has all required fields."""
    task_type = raw.get("task_type", "general")
    if "recommended_tools" not in raw or not raw["recommended_tools"]:
        raw["recommended_tools"] = _discover_tools_for_type(task_type)
    raw.setdefault("depends_on", [])
    raw.setdefault("complexity", "medium")
    return raw


def _parse_json_array(text: str) -> list | None:
    """Try hard to extract a JSON array from LLM output."""
    text = text.strip()
    # Direct parse
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    # Try extracting from code fences
    for pattern in [r'```json\s*(\[.*?\])\s*```', r'```\s*(\[.*?\])\s*```', r'(\[.*\])']:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                continue
    return None


def _task_capability(task_type: str) -> str:
    aliases = {
        "summarize": "analysis",
        "reason": "analysis",
        "refactor": "code",
        "debug": "code",
        "test": "code",
    }
    normalized = (task_type or "").strip().lower()
    return aliases.get(normalized, normalized)


def _task_trust_tier(task_type: str) -> str:
    task = (task_type or "").strip().lower()
    tier2_tasks = {
        "exploit",
        "privesc",
        "scan",
        "recon",
        "sysadmin",
        "password",
        "web",
        "malware_re",
        "exploit_chain",
    }
    return "tier_2" if task in tier2_tasks else "tier_1"
