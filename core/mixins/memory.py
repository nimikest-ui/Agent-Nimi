"""MemoryMixin — context window management and episode/strategy persistence."""
from __future__ import annotations

from core.audit import audit_event


class MemoryMixin:
    """Working memory management and post-interaction persistence helpers.

    Expects these instance attributes set by AgentNimi.__init__:
        self.messages, self._max_context_tokens, self.episodic_memory,
        self.strategy_memory, self.provider, self.command_log
    """

    # ── Context window ────────────────────────────────────────────────────────

    @staticmethod
    def _estimate_tokens(msg: dict) -> int:
        """Rough token estimate: ~1.3 tokens per word."""
        content = msg.get("content", "")
        return int(len(content.split()) * 1.3)

    def _manage_context_window(self):
        """Keep self.messages within the token budget.

        Strategy: keep system prompt + last 8 messages intact.
        If over budget, heuristically compress the middle section.
        """
        total = sum(self._estimate_tokens(m) for m in self.messages)
        if total <= self._max_context_tokens:
            return

        if len(self.messages) <= 10:
            return

        system = self.messages[0]
        recent = self.messages[-8:]
        middle = self.messages[1:-8]

        if not middle:
            return

        summary_parts = []
        for msg in middle:
            role = msg.get("role", "")
            content = msg.get("content", "")
            snippet = content[:120].replace("\n", " ").strip()
            if len(content) > 120:
                snippet += "..."
            if role == "user" and not content.startswith("["):
                summary_parts.append(f"User: {snippet}")
            elif role == "assistant" and len(content) > 30:
                summary_parts.append(f"Agent: {snippet}")

        if summary_parts:
            compressed = "\n".join(summary_parts[-15:])
            summary_msg = {
                "role": "system",
                "content": f"[CONTEXT SUMMARY — earlier conversation compressed]\n{compressed}",
            }
            self.messages = [system, summary_msg] + recent
            audit_event("context_compressed", {
                "original_messages": len(middle) + len(recent) + 1,
                "after_messages": len(self.messages),
                "estimated_tokens_before": total,
                "estimated_tokens_after": sum(self._estimate_tokens(m) for m in self.messages),
            })

    # ── Persistence helpers (deduplicate post-chat blocks) ────────────────────

    def _store_episode(
        self,
        user_input: str,
        response: str,
        task_type: str,
        quality: float,
        tools_used: list[str],
        strategy: str,
        issues: list[str],
    ):
        """Persist interaction to episodic memory. Silently swallows errors."""
        try:
            self.episodic_memory.store_from_interaction(
                user_input=user_input,
                response=response,
                task_type=task_type,
                provider_model=f"{self.provider.name()}:{getattr(self.provider, 'model', '')}",
                quality_score=quality,
                tools_used=tools_used,
                strategy=strategy,
                issues=issues,
            )
        except Exception:
            pass

    def _record_strategy(
        self,
        task_type: str,
        strategy: str,
        tools_used: list[str],
        quality: float,
    ):
        """Record strategy outcome to strategy memory. Silently swallows errors."""
        try:
            self.strategy_memory.record(
                task_type=task_type,
                strategy=strategy,
                tools_used=tools_used,
                quality=quality,
            )
        except Exception:
            pass
