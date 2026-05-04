"""ClusterRepository -- data access for ContentCluster entities."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Union

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from intellisource.storage.models import ContentCluster
from intellisource.storage.repositories.base import BaseRepository


class ClusterRepository(BaseRepository[ContentCluster]):
    """Filtered listing for :class:`ContentCluster` entities."""

    _model_class = ContentCluster

    async def list_clusters(
        self,
        *,
        tag: str | None = None,
        date_from: Union[datetime, str, None] = None,
        date_to: Union[datetime, str, None] = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        stmt = select(ContentCluster).options(selectinload(ContentCluster.digests))

        if tag is not None:
            stmt = stmt.where(ContentCluster.tags.contains([tag]))
        if date_from is not None:
            stmt = stmt.where(ContentCluster.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(ContentCluster.created_at < date_to)

        return await self._paginate(stmt, limit=limit, cursor=cursor)
