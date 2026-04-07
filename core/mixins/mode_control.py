"""ModeControlMixin — interrupt, steering, and cancellation primitives."""
from __future__ import annotations

import queue

from core.audit import audit_event


class ModeControlMixin:
    """Handles mode switching, operator steering, and loop cancellation.

    Expects these instance attributes set by AgentNimi.__init__:
        self._current_mode, self._mode_switch_queue, self._steer_queue,
        self._cancelled, self.messages
    """

    def steer(self, message: str):
        """Inject a steering message into the running agent loop."""
        self._steer_queue.put(message)

    def set_mode(self, mode: str):
        """Set current execution mode (ask | plan | agent)."""
        if mode not in {"ask", "plan", "agent"}:
            return
        if mode != self._current_mode:
            audit_event("mode_set", {"from": self._current_mode, "to": mode})
        self._current_mode = mode

    def request_mode_switch(self, mode: str):
        """Queue a live mode switch that can interrupt an active workflow."""
        audit_event("mode_switch_requested", {"to": mode})
        self._mode_switch_queue.put(mode)

    @property
    def current_mode(self) -> str:
        return self._current_mode

    def consume_mode_switches(self, stream_callback=None):
        """Apply any queued mode-switch requests and emit SSE events."""
        while True:
            try:
                requested = self._mode_switch_queue.get_nowait()
                if requested not in {"ask", "plan", "agent"}:
                    continue
                if requested != self._current_mode:
                    audit_event("mode_switched", {"from": self._current_mode, "to": requested})
                    self._current_mode = requested
                    if stream_callback:
                        stream_callback({"event": "mode_switched", "mode": requested})
            except queue.Empty:
                break

    def should_interrupt(self, stream_callback=None) -> tuple[bool, str]:
        """Return (interrupted, reason) for long-running orchestration calls."""
        self.consume_mode_switches(stream_callback)
        if self._cancelled:
            return True, "cancelled"
        if self._current_mode != "agent":
            return True, f"mode:{self._current_mode}"
        return False, ""

    def cancel(self):
        """Signal the agent loop to stop after the current step."""
        self._cancelled = True

    def _drain_steer_messages(self, stream_callback=None):
        """Pull all pending steer messages and append to the conversation."""
        while True:
            try:
                msg = self._steer_queue.get_nowait()
                self.messages.append({"role": "user", "content": f"[OPERATOR STEERING]: {msg}"})
                if stream_callback:
                    stream_callback({"event": "steer_ack", "message": msg})
            except queue.Empty:
                break
