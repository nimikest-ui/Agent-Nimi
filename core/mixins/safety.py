"""SafetyMixin — pre-execution tool safety checks and confirmation gates."""
from __future__ import annotations

import queue

from core.audit import audit_event
from tools.registry import get_tool as get_tool_info, ACTION_CLASSES
from tools.shell_tools import is_network_disconnect_command


class SafetyMixin:
    """Pre-execution safety checks, blocklist enforcement, and confirmation gates.

    Expects these instance attributes set by AgentNimi.__init__:
        self.safety (dict), self.config (dict), self._steer_queue
    """

    def _safety_check(self, tool_name: str, args: dict) -> bool:
        """Return False if the tool call is blocked by safety policy."""
        blocked = self.safety.get("blocked_commands", [])

        if tool_name in blocked:
            return False

        if tool_name in ("shell_exec", "shell_exec_background"):
            cmd = args.get("command", "")
            for blocked_cmd in blocked:
                if blocked_cmd in cmd:
                    return False

            if self.safety.get("block_network_disconnect", True):
                if is_network_disconnect_command(cmd):
                    audit_event("network_disconnect_blocked", {"command": cmd[:200]})
                    return False

        return True

    def _needs_confirmation(self, tool_name: str) -> bool:
        """Return True if the tool's action_class requires user confirmation."""
        if not self.config.get("safety", {}).get("confirm_destructive", True):
            return False
        info = get_tool_info(tool_name)
        if not info:
            return False
        manifest = info.get("manifest", {})
        action_class = manifest.get("action_class", "read_only")
        threshold = ACTION_CLASSES.get(
            self.config.get("safety", {}).get("confirm_threshold", "irreversible"),
            2,
        )
        return ACTION_CLASSES.get(action_class, 0) >= threshold

    def _request_confirmation(self, tool_name: str, tool_args: dict, stream_callback=None) -> bool:
        """Request user confirmation for a destructive action via SSE steer queue.

        Returns True if confirmed, False if declined or timed-out.
        In non-interactive (CLI) mode, auto-approves.
        """
        info = get_tool_info(tool_name)
        manifest = info.get("manifest", {}) if info else {}
        action_class = manifest.get("action_class", "unknown")
        confirm_timeout = self.config.get("safety", {}).get("confirm_timeout", 60)

        if stream_callback:
            stream_callback({
                "event": "confirm_request",
                "tool": tool_name,
                "args": {k: str(v)[:200] for k, v in (tool_args or {}).items()},
                "action_class": action_class,
                "timeout": confirm_timeout,
            })
            try:
                msg = self._steer_queue.get(timeout=confirm_timeout)
                return str(msg).strip().lower() in ("yes", "y", "confirm", "approved", "ok")
            except queue.Empty:
                if stream_callback:
                    stream_callback({"event": "confirm_timeout", "tool": tool_name})
                return False
        else:
            # CLI / non-interactive: auto-approve (safety check already passed)
            return True
