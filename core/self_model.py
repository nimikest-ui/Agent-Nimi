"""
Self-model generation for AgentNimi.
Builds a current snapshot of identity, capabilities, constraints, and performance,
plus a concise conclusion for decision support.
"""
from __future__ import annotations

import datetime
from typing import Any

from tools import list_tools
from tools.registry import list_tool_manifests


def _performance_summary(router_stats: dict | None) -> dict[str, Any]:
    if not router_stats:
        return {
            "learned_task_types": 0,
            "learned_provider_model_pairs": 0,
            "current_provider": "",
            "current_model": "",
        }

    scores = router_stats.get("scores", {}) or {}
    learned_task_types = len(scores)
    learned_pairs = 0
    for entries in scores.values():
        learned_pairs += len(entries or {})

    return {
        "learned_task_types": learned_task_types,
        "learned_provider_model_pairs": learned_pairs,
        "current_provider": router_stats.get("current_provider", ""),
        "current_model": router_stats.get("current_model", ""),
    }


def _derive_conclusion(snapshot: dict[str, Any]) -> str:
    perf = snapshot.get("performance", {})
    learned_tasks = perf.get("learned_task_types", 0)
    learned_pairs = perf.get("learned_provider_model_pairs", 0)
    mode = snapshot.get("mode", "agent")
    provider = snapshot.get("provider", "")

    if learned_tasks >= 8 and learned_pairs >= 15:
        learning_state = "adaptive"
    elif learned_tasks >= 3:
        learning_state = "developing"
    else:
        learning_state = "cold-start"

    return (
        f"Self-assessment: mode={mode}, provider={provider}. "
        f"Learning state={learning_state} with {learned_tasks} task families and "
        f"{learned_pairs} learned provider/model score entries."
    )


def build_self_model(agent, config: dict) -> dict[str, Any]:
    """Build a full self-model snapshot for API/UI consumption."""
    architecture = config.get("architecture", {})
    identity = architecture.get("identity", {})
    constraints = architecture.get("hardware_constraints", {})
    trust_tiers = architecture.get("trust_tiers", {})

    providers = []
    for pname, pconf in (config.get("providers", {}) or {}).items():
        providers.append(
            {
                "name": pname,
                "model": pconf.get("model", ""),
                "configured": True,
                "has_key": bool(pconf.get("api_key")) if pname not in {"copilot"} else True,
            }
        )

    router_stats = agent.router_stats() if agent else None
    perf = _performance_summary(router_stats)

    snapshot = {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "identity": {
            "name": identity.get("agent_name", "AgentNimi"),
            "version": identity.get("agent_version", "0.0.0"),
            "codename": identity.get("codename", ""),
        },
        "mode": getattr(agent, "current_mode", "agent") if agent else "agent",
        "provider": agent.provider.name() if agent else "",
        "routing_active": bool(agent.routing_active) if agent else False,
        "constraints": constraints,
        "trust_tiers": trust_tiers,
        "inventory": {
            "providers": providers,
            "tools": (_tools := sorted(list_tools())),
            "tool_count": len(_tools),
            "tool_manifests": list_tool_manifests(),
        },
        "performance": perf,
    }
    snapshot["conclusion"] = _derive_conclusion(snapshot)
    return snapshot
