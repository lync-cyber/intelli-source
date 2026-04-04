"""TaskRepository -- data access for CollectTask entities."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from intellisource.storage.models import CollectTask
from intellisource.storage.repositories.base import BaseRepository


class TaskRepository(BaseRepository[CollectTask]):
    """CRUD and filtered listing for :class:`CollectTask` entities."""

    _model_class = CollectTask

    async def create(
        self,
        source_id: uuid.UUID,
        trigger_type: str,
        **kwargs: Any,
    ) -> CollectTask:
        return await self._create_entity(
            source_id=source_id,
            trigger_type=trigger_type,
            **kwargs,
        )

    async def list(
        self,
        status: str | None = None,
        trigger_type: str | None = None,
        source_id: uuid.UUID | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        stmt = select(CollectTask)

        if status is not None:
            stmt = stmt.where(CollectTask.status == status)
        if trigger_type is not None:
            stmt = stmt.where(CollectTask.trigger_type == trigger_type)
        if source_id is not None:
            stmt = stmt.where(CollectTask.source_id == source_id)

        return await self._paginate(stmt, limit=limit, cursor=cursor)
