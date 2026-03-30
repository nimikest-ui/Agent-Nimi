"""Append-only audit pipeline for AgentNimi."""
from __future__ import annotations

import json
import datetime
from pathlib import Path
from typing import Any

AUDIT_DIR = Path.home() / ".agent-nimi" / "audit"
AUDIT_FILE = AUDIT_DIR / "events.jsonl"


def audit_event(event_type: str, payload: dict[str, Any] | None = None):
    """Append one immutable audit event."""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "type": event_type,
        "payload": _trim_payload(payload or {}),
    }
    with open(AUDIT_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_audit(limit: int = 200) -> list[dict[str, Any]]:
    """Read the newest audit events."""
    if not AUDIT_FILE.exists():
        return []
    entries: list[dict[str, Any]] = []
    with open(AUDIT_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return entries[-max(1, min(limit, 2000)):]


def _trim_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Trim very large fields to keep audit file bounded."""
    out = {}
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > 5000:
            out[key] = value[:5000] + "... [truncated]"
        else:
            out[key] = value
    return out
