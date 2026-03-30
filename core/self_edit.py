"""Governed self-edit engine with rollback metadata and protected boundaries."""
from __future__ import annotations

from typing import Any

from config import save_config
from core.audit import audit_event

PROTECTED_PATH_PREFIXES = (
    "architecture.trust_tiers",
    "scope",
    "authorization",
    "audit",
)


class SelfEditError(Exception):
    pass


def apply_self_edit(config: dict, operation: dict[str, Any]) -> dict[str, Any]:
    """Apply a constrained self-edit operation and persist config.

    Supported operations:
      - set_default_provider: {provider}
      - set_provider_model: {provider, model}
      - update_config_path: {path, value}
    """
    op_type = str(operation.get("type", "")).strip()
    if not op_type:
        raise SelfEditError("Operation type is required")

    if op_type == "set_default_provider":
        provider = str(operation.get("provider", "")).strip()
        if not provider:
            raise SelfEditError("provider is required")
        old = config.get("default_provider")
        config["default_provider"] = provider
        rollback = {"type": "set_default_provider", "provider": old}

    elif op_type == "set_provider_model":
        provider = str(operation.get("provider", "")).strip()
        model = str(operation.get("model", "")).strip()
        if not provider or not model:
            raise SelfEditError("provider and model are required")
        old = (config.get("providers", {}).get(provider, {}) or {}).get("model")
        config.setdefault("providers", {}).setdefault(provider, {})["model"] = model
        rollback = {"type": "set_provider_model", "provider": provider, "model": old}

    elif op_type == "update_config_path":
        path = str(operation.get("path", "")).strip()
        if not path:
            raise SelfEditError("path is required")
        _assert_path_allowed(path)
        value = operation.get("value")
        old = _deep_get(config, path)
        _deep_set(config, path, value)
        rollback = {"type": "update_config_path", "path": path, "value": old}

    else:
        raise SelfEditError(f"Unsupported self-edit operation: {op_type}")

    save_config(config)
    audit_event(
        "self_edit_applied",
        {
            "operation": operation,
            "rollback": rollback,
        },
    )
    return {
        "success": True,
        "operation": operation,
        "rollback": rollback,
    }


def _assert_path_allowed(path: str):
    lowered = path.lower()
    for pref in PROTECTED_PATH_PREFIXES:
        if lowered.startswith(pref):
            raise SelfEditError(f"Protected path is not editable: {path}")


def _deep_get(data: dict, path: str):
    parts = path.split(".")
    cur = data
    for p in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _deep_set(data: dict, path: str, value: Any):
    parts = path.split(".")
    cur = data
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value
