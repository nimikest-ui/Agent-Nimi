"""Engagement-scoped session memory (ephemeral, per conversation)."""
from __future__ import annotations

import datetime
from typing import Any

_STORE: dict[str, dict[str, Any]] = {}


def start_engagement(conv_id: str, title: str = "") -> dict[str, Any]:
    """Start (or return) an engagement-scoped memory state."""
    if conv_id not in _STORE:
        _STORE[conv_id] = {
            "conversation_id": conv_id,
            "title": title,
            "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "in_flight": [],
            "raw_recon": [],
            "findings": [],
            "patterns": [],
        }
    return _STORE[conv_id]


def get_engagement(conv_id: str) -> dict[str, Any] | None:
    return _STORE.get(conv_id)


def add_in_flight(conv_id: str, item: str):
    state = start_engagement(conv_id)
    state.setdefault("in_flight", []).append(item)


def add_raw_recon(conv_id: str, item: str):
    state = start_engagement(conv_id)
    state.setdefault("raw_recon", []).append(item)


def add_finding(conv_id: str, finding: str):
    state = start_engagement(conv_id)
    state.setdefault("findings", []).append(finding)


def clear_engagement(conv_id: str):
    _STORE.pop(conv_id, None)


def clear_all():
    _STORE.clear()
