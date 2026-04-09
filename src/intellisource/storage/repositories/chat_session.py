"""ChatSessionRepository -- data access for ChatSession entities."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from intellisource.storage.models import ChatSession
from intellisource.storage.repositories.base import BaseRepository


class ChatSessionRepository(BaseRepository[ChatSession]):
    """CRUD and lifecycle queries for :class:`ChatSession` entities.

    Provides session lookup by channel+user, timeout-based cleanup,
    and standard paginated listing.
    """

    _model_class = ChatSession

    async def create(
        self,
        channel: str,
        channel_user_id: str,
        **kwargs: Any,
    ) -> ChatSession:
        return await self._create_entity(
            channel=channel,
            channel_user_id=channel_user_id,
            **kwargs,
        )

    async def find_by_channel_user(
        self,
        channel: str,
        channel_user_id: str,
    ) -> ChatSession | None:
        """Look up an active session for a specific channel + user pair."""
        stmt = select(ChatSession).where(
            ChatSession.channel == channel,
            ChatSession.channel_user_id == channel_user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_context(
        self,
        id: uuid.UUID,  # noqa: A002
        context: dict[str, Any],
    ) -> ChatSession | None:
        """Update session context and touch last_active_at."""
        return await self.update(
            id,
            context=context,
            last_active_at=datetime.now(timezone.utc),
        )

    async def cleanup_expired(
        self,
        before: datetime,
    ) -> int:
        """Delete sessions inactive since *before*. Returns count deleted."""
        stmt = select(ChatSession).where(
            ChatSession.last_active_at < before,
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        for row in rows:
            await self._session.delete(row)
        await self._session.flush()
        return len(rows)

    async def list(
        self,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        stmt = select(ChatSession)
        return await self._paginate(stmt, limit=limit, cursor=cursor)
