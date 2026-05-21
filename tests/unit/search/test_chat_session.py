"""Tests for T-038: ChatSessionManager and context compaction.

Covers:
  AC-T038-1: ChatSessionManager.get_or_create(channel, channel_user_id)
             returns existing or new session
  AC-T038-2: Context stored in ChatSession.context JSONB field
             (messages list with role/content)
  AC-T038-3: Token limit triggers compaction (when context exceeds
             max_tokens, old messages are compacted)
  AC-T038-4: Compacted summary becomes system prompt prefix
  AC-T038-5: 24h inactive session cleanup
             (cleanup_inactive_sessions removes sessions older than 24h)
  AC-T038-6: Citation sources included in responses
             (search results cited with source_name + source_url)

All tests FAIL in RED phase because intellisource.search.chat_session
does not exist yet.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import guard: module does not exist yet during RED phase.
# ---------------------------------------------------------------------------
try:
    from intellisource.search.chat_session import (  # type: ignore[import-untyped]
        ChatSessionManager,
    )
except ImportError:
    ChatSessionManager = None  # type: ignore[assignment,misc]

_MODULE_MISSING = ChatSessionManager is None
_SKIP_REASON = (
    "intellisource.search.chat_session not implemented: "
    "cannot import ChatSessionManager"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_row(
    *,
    channel: str = "slack",
    channel_user_id: str = "U12345",
    context: dict[str, Any] | None = None,
    last_active_at: datetime | None = None,
    session_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build a mock ChatSession row matching the DB model schema."""
    row = MagicMock()
    row.id = session_id or uuid.uuid4()
    row.channel = channel
    row.channel_user_id = channel_user_id
    row.context = context if context is not None else {"messages": []}
    row.last_active_at = last_active_at or datetime.now(timezone.utc)
    row.created_at = datetime.now(timezone.utc)
    return row


# ===========================================================================
# AC-T038-1: ChatSessionManager.get_or_create returns existing or new session
# ===========================================================================


class TestChatSessionGetOrCreate:
    """AC-T038-1: get_or_create returns existing session or creates new."""

    async def test_get_or_create_returns_existing_session(self) -> None:
        """When a session already exists for channel+user, return it."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        existing = _make_session_row(channel="slack", channel_user_id="U12345")
        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)

        with patch.object(manager, "_find_session", return_value=existing):
            session = await manager.get_or_create(
                channel="slack", channel_user_id="U12345"
            )

        assert session.id == existing.id
        assert session.channel == "slack"
        assert session.channel_user_id == "U12345"

    async def test_get_or_create_creates_new_when_none(self) -> None:
        """When no session exists, create and return a new one."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)

        with patch.object(manager, "_find_session", return_value=None):
            session = await manager.get_or_create(
                channel="teams", channel_user_id="U99999"
            )

        assert session is not None
        assert session.channel == "teams"
        assert session.channel_user_id == "U99999"

    async def test_get_or_create_updates_last_active_at(self) -> None:
        """get_or_create must update last_active_at to current time."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        old_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        existing = _make_session_row(last_active_at=old_time)
        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)

        with patch.object(manager, "_find_session", return_value=existing):
            session = await manager.get_or_create(
                channel="slack", channel_user_id="U12345"
            )

        assert session.last_active_at is not None
        assert session.last_active_at > old_time


# ===========================================================================
# AC-T038-2: Context stored in ChatSession.context JSONB field
# ===========================================================================


class TestContextStorage:
    """AC-T038-2: Messages stored as list with role/content in context JSONB."""

    async def test_add_message_stores_in_context(self) -> None:
        """Adding a user message populates context['messages'] list."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)
        session_row = _make_session_row()

        await manager.add_message(session_row, role="user", content="Hello")

        messages = session_row.context.get("messages", [])
        assert len(messages) >= 1

    async def test_context_preserves_role_and_content(self) -> None:
        """Each message in context must contain 'role' and 'content' keys."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)
        session_row = _make_session_row()

        await manager.add_message(session_row, role="user", content="Test question")

        messages = session_row.context["messages"]
        last_msg = messages[-1]
        assert last_msg["role"] == "user"
        assert last_msg["content"] == "Test question"

    async def test_context_append_multiple_messages(self) -> None:
        """Multiple messages are appended in order."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)
        session_row = _make_session_row()

        await manager.add_message(session_row, role="user", content="First")
        await manager.add_message(session_row, role="assistant", content="Second")
        await manager.add_message(session_row, role="user", content="Third")

        messages = session_row.context["messages"]
        assert len(messages) == 3
        assert messages[0]["content"] == "First"
        assert messages[1]["content"] == "Second"
        assert messages[2]["content"] == "Third"


# ===========================================================================
# AC-T038-3 & AC-T038-4: Token limit triggers compaction;
# compacted summary becomes system prompt prefix
# ===========================================================================


class TestContextCompaction:
    """AC-T038-3/4: Context compaction triggered by token limit."""

    async def test_compaction_triggered_when_exceeding_token_limit(self) -> None:
        """When context exceeds max_tokens, compact_context is invoked."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)

        # Build a context with many messages to exceed token limit
        large_messages = [
            {"role": "user", "content": f"Message {i} " * 100} for i in range(50)
        ]
        session_row = _make_session_row(context={"messages": large_messages})

        with patch.object(
            manager, "compact_context", new_callable=AsyncMock
        ) as mock_compact:
            mock_compact.return_value = session_row
            await manager.maybe_compact(session_row, max_tokens=1000)
            mock_compact.assert_called_once()

    async def test_compacted_summary_becomes_system_prefix(self) -> None:
        """After compaction, first message is a system message with summary."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)

        large_messages = [
            {"role": "user", "content": f"Long message {i} " * 100} for i in range(50)
        ]
        session_row = _make_session_row(context={"messages": large_messages})

        compacted = await manager.compact_context(session_row, max_tokens=1000)

        messages = compacted.context["messages"]
        assert len(messages) > 0
        assert messages[0]["role"] == "system"
        assert len(messages[0]["content"]) > 0  # summary is not empty

    async def test_compaction_preserves_recent_messages(self) -> None:
        """After compaction, the most recent messages are preserved."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)

        messages = [
            {"role": "user", "content": f"Old message {i} " * 100} for i in range(40)
        ]
        messages.append({"role": "user", "content": "Recent important question"})
        messages.append({"role": "assistant", "content": "Recent answer"})
        session_row = _make_session_row(context={"messages": messages})

        compacted = await manager.compact_context(session_row, max_tokens=1000)

        compacted_msgs = compacted.context["messages"]
        contents = [m["content"] for m in compacted_msgs]
        assert "Recent important question" in contents
        assert "Recent answer" in contents

    async def test_no_compaction_when_under_token_limit(self) -> None:
        """When context is under max_tokens, no compaction occurs."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)

        small_messages = [{"role": "user", "content": "Short"}]
        session_row = _make_session_row(context={"messages": small_messages})

        with patch.object(
            manager, "compact_context", new_callable=AsyncMock
        ) as mock_compact:
            await manager.maybe_compact(session_row, max_tokens=100000)
            mock_compact.assert_not_called()


# ===========================================================================
# AC-T038-5: 24h inactive session cleanup
# ===========================================================================


class TestSessionCleanup:
    """AC-T038-5: cleanup_inactive_sessions removes old sessions."""

    async def test_cleanup_removes_sessions_inactive_over_24h(self) -> None:
        """Sessions inactive for >24h are deleted by cleanup."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)

        deleted_count = await manager.cleanup_inactive_sessions(
            max_inactive_hours=24,
        )

        assert isinstance(deleted_count, int)
        assert deleted_count >= 0
        # Verify that a delete was executed against the DB session
        assert mock_db.execute.called or mock_db.delete.called

    async def test_cleanup_keeps_recently_active_sessions(self) -> None:
        """Sessions active within the last 24h must NOT be deleted."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)

        old_session = _make_session_row(
            last_active_at=datetime.now(timezone.utc) - timedelta(hours=48)
        )

        # Mock: only old session should be returned for deletion
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [old_session]
        mock_db.execute.return_value = mock_result

        deleted_count = await manager.cleanup_inactive_sessions(
            max_inactive_hours=24,
        )

        # The recent session must not appear in deleted items
        assert deleted_count <= 1

    async def test_cleanup_with_no_inactive_sessions_returns_zero(self) -> None:
        """When all sessions are active, cleanup returns 0."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute.return_value = mock_result

        deleted_count = await manager.cleanup_inactive_sessions(
            max_inactive_hours=24,
        )

        assert deleted_count == 0


# ===========================================================================
# AC-T038-6: Citation sources included in responses
# ===========================================================================


class TestCitationSources:
    """AC-T038-6: Search results include source_name and source_url."""

    async def test_response_includes_citation_sources(self) -> None:
        """Response from chat must include citation sources with required fields."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)
        session_row = _make_session_row()

        mock_search_results = [
            {
                "content": "Some relevant content",
                "source_name": "Wikipedia",
                "source_url": "https://en.wikipedia.org/wiki/Test",
            },
            {
                "content": "Another source",
                "source_name": "ArXiv",
                "source_url": "https://arxiv.org/abs/1234.5678",
            },
        ]

        response = await manager.build_response_with_citations(
            session=session_row,
            answer="Here is the answer.",
            search_results=mock_search_results,
        )

        assert "citations" in response
        citations = response["citations"]
        assert len(citations) == 2
        assert citations[0]["source_name"] == "Wikipedia"
        assert citations[0]["source_url"] == "https://en.wikipedia.org/wiki/Test"

    async def test_citations_extracted_from_search_results(self) -> None:
        """Each search result contributes a citation entry."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)
        session_row = _make_session_row()

        mock_search_results = [
            {
                "content": "Result 1",
                "source_name": "Source A",
                "source_url": "https://example.com/a",
            },
        ]

        response = await manager.build_response_with_citations(
            session=session_row,
            answer="Answer text",
            search_results=mock_search_results,
        )

        citations = response["citations"]
        assert len(citations) == 1
        assert citations[0]["source_name"] == "Source A"
        assert citations[0]["source_url"] == "https://example.com/a"

    async def test_empty_search_results_yields_no_citations(self) -> None:
        """When there are no search results, citations list is empty."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        mock_db = AsyncMock()
        manager = ChatSessionManager(session=mock_db)
        session_row = _make_session_row()

        response = await manager.build_response_with_citations(
            session=session_row,
            answer="No sources found.",
            search_results=[],
        )

        assert response["citations"] == []
