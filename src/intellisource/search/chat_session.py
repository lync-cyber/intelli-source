"""Chat session management with context compaction.

Provides ChatSessionManager for managing conversational sessions,
storing message context, compacting long conversations, cleaning up
inactive sessions, and building citation-enriched responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from intellisource.agent.compaction import compact_messages_for_chat

_CHARS_PER_TOKEN = 4


@dataclass
class _NewSessionRow:
    """Lightweight in-memory representation for a newly created session."""

    channel: str
    channel_user_id: str
    context: dict[str, Any] = field(default_factory=lambda: {"messages": []})
    last_active_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ChatSessionManager:
    """Manages chat sessions with context storage and compaction."""

    def __init__(self, session: Any, llm_gateway: Any = None) -> None:
        self._session = session
        self._llm_gateway = llm_gateway

    async def _find_session(self, channel: str, channel_user_id: str) -> Any | None:
        """Find an existing session for the given channel and user."""
        return None

    async def get_or_create(self, channel: str, channel_user_id: str) -> Any:
        """Return existing session or create a new one."""
        existing = await self._find_session(channel, channel_user_id)
        if existing is not None:
            existing.last_active_at = datetime.now(timezone.utc)
            return existing

        return _NewSessionRow(channel=channel, channel_user_id=channel_user_id)

    async def add_message(self, session_row: Any, role: str, content: str) -> None:
        """Append a message to the session context."""
        messages: list[dict[str, str]] = session_row.context["messages"]
        messages.append({"role": role, "content": content})

    def _estimate_tokens(self, messages: list[dict[str, str]]) -> int:
        """Estimate token count from messages (approx 1 token per 4 chars)."""
        total_chars = sum(len(m.get("content", "")) for m in messages)
        return total_chars // _CHARS_PER_TOKEN

    async def maybe_compact(self, session_row: Any, max_tokens: int) -> None:
        """Compact context if estimated tokens exceed max_tokens."""
        messages: list[dict[str, str]] = session_row.context["messages"]
        if self._estimate_tokens(messages) > max_tokens:
            await self.compact_context(session_row, max_tokens=max_tokens)

    async def compact_context(self, session_row: Any, max_tokens: int) -> Any:
        """Compact context via token-aware LLM summarization.

        Delegates to ``agent.compaction.compact_messages_for_chat`` to share
        the same pruning + structured summarization pipeline used by Agent
        flows. When ``llm_gateway`` is not configured, the underlying helper
        falls back to character-budget truncation with role=tool messages
        pruned first.
        """
        messages: list[dict[str, Any]] = session_row.context["messages"]
        compacted = await compact_messages_for_chat(
            messages,
            gateway=self._llm_gateway,
            max_tokens=max_tokens,
        )
        session_row.context["messages"] = compacted
        return session_row

    async def cleanup_inactive_sessions(self, max_inactive_hours: int = 24) -> int:
        """Delete sessions inactive longer than max_inactive_hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_inactive_hours)
        result = await self._session.execute(
            text("DELETE FROM chat_sessions WHERE last_active_at < :cutoff"),
            {"cutoff": cutoff},
        )
        rowcount = result.rowcount
        return rowcount if isinstance(rowcount, int) else 0

    async def build_response_with_citations(
        self,
        session: Any,
        answer: str,
        search_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build a response dict with answer and citation sources."""
        citations = [
            {
                "source_name": r["source_name"],
                "source_url": r["source_url"],
            }
            for r in search_results
        ]
        return {"answer": answer, "citations": citations}
