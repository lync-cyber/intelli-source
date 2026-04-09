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

_CHARS_PER_TOKEN = 4
_MAX_SUMMARY_PARTS = 20
_SUMMARY_CONTENT_LIMIT = 100


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

    def __init__(self, session: Any) -> None:
        self._session = session

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
        """Replace old messages with a summary, preserving recent ones.

        [ASSUMPTION] Current implementation uses string concatenation for
        summarisation. Future versions should integrate an LLM-based compactor
        to produce higher-quality semantic summaries.
        """
        messages: list[dict[str, str]] = session_row.context["messages"]

        keep_count = min(max(2, len(messages) // 10), len(messages))
        old_messages = messages[:-keep_count] if keep_count < len(messages) else []
        recent_messages = messages[-keep_count:]

        summary_parts = [
            f"{msg['role']}: {msg['content'][:_SUMMARY_CONTENT_LIMIT]}"
            for msg in old_messages[:_MAX_SUMMARY_PARTS]
        ]
        summary_text = "Summary of previous conversation: " + "; ".join(summary_parts)

        session_row.context["messages"] = [
            {"role": "system", "content": summary_text},
            *recent_messages,
        ]
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
