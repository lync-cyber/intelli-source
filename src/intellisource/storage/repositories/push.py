"""PushRepository -- data access for PushRecord entities."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from intellisource.storage.models import PushRecord
from intellisource.storage.repositories.base import BaseRepository


class PushRepository(BaseRepository[PushRecord]):
    """CRUD and deduplication queries for :class:`PushRecord` entities."""

    _model_class = PushRecord

    async def create(
        self,
        subscription_id: uuid.UUID,
        content_id: uuid.UUID,
        channel: str,
        **kwargs: Any,
    ) -> PushRecord:
        return await self._create_entity(
            subscription_id=subscription_id,
            content_id=content_id,
            channel=channel,
            **kwargs,
        )

    async def exists(
        self,
        subscription_id: uuid.UUID,
        content_id: uuid.UUID,
        channel: str,
    ) -> bool:
        """Check whether a push record already exists (deduplication)."""
        stmt = (
            select(PushRecord.id)
            .where(
                PushRecord.subscription_id == subscription_id,
                PushRecord.content_id == content_id,
                PushRecord.channel == channel,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list(
        self,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        stmt = select(PushRecord)
        return await self._paginate(stmt, limit=limit, cursor=cursor)
