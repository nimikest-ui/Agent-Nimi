"""
Memory Tools — let the agent explicitly read/write persistent fact memory.

These tools give the LLM direct control over the FactMemory store so that
important discoveries (target IPs, discovered credentials, CVEs, open ports,
service versions, etc.) persist across sessions and can be recalled later.
"""
from .registry import tool


def _get_fact_memory():
    """Lazily return the agent's shared FactMemory instance, or a standalone one."""
    try:
        # Try to get the singleton attached to the running AgentNimi instance.
        # This is populated by agent.py after initialization.
        from tools.memory_tools import _AGENT_REF
        if _AGENT_REF is not None:
            return _AGENT_REF.fact_memory
    except Exception:
        pass
    # Fallback: standalone FactMemory using the default persistence path
    from core.fact_memory import FactMemory
    return FactMemory()


# Module-level reference to the agent — set by AgentNimi.__init__()
_AGENT_REF = None


@tool(
    "remember_fact",
    "Store a persistent fact about a target, asset, or engagement for future recall",
    manifest={"action_class": "reversible", "capabilities": ["analysis", "sysadmin"]},
)
def remember_fact(
    subject: str,
    predicate: str,
    value: str,
    confidence: float = 0.9,
) -> str:
    """Store a fact in persistent memory.

    Args:
        subject:    What the fact is about   (e.g. "10.0.0.1", "target_webapp", "engagement")
        predicate:  The property name         (e.g. "open_ports", "os", "cve", "credential")
        value:      The fact value            (e.g. "22,80,443", "Ubuntu 22.04", "CVE-2024-1234")
        confidence: Certainty 0-1 (default 0.9)
    """
    try:
        fm = _get_fact_memory()
        fm.store(
            subject=subject.strip(),
            predicate=predicate.strip(),
            value=value.strip(),
            source="agent",
            confidence=float(confidence),
        )
        return f"[Fact stored] {subject} → {predicate}: {value} (confidence={confidence})"
    except Exception as e:
        return f"[Error storing fact: {e}]"


@tool(
    "recall_facts",
    "Recall stored facts about a subject from persistent memory",
    manifest={"action_class": "read_only", "capabilities": ["analysis"]},
)
def recall_facts(subject: str = "", limit: int = 20) -> str:
    """Retrieve facts from persistent memory.

    Args:
        subject: Filter by subject (e.g. "10.0.0.1"). Empty = return all recent facts.
        limit:   Max number of facts to return (default 20).
    """
    try:
        fm = _get_fact_memory()
        if subject.strip():
            facts = fm.query(subject=subject.strip())
        else:
            facts = fm.query()

        if not facts:
            return f"[No facts stored{' for subject: ' + subject if subject else ''}]"

        lines = [f"[Stored facts{' for ' + subject if subject else ''}]"]
        for f in facts[-int(limit):]:
            conf = f" (conf={f.confidence:.1f})" if f.confidence < 1.0 else ""
            lines.append(f"  {f.subject} | {f.predicate}: {f.value}{conf}")
        return "\n".join(lines)
    except Exception as e:
        return f"[Error recalling facts: {e}]"
