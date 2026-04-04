"""SourceRepository -- data access for Source entities."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from intellisource.storage.models import Source
from intellisource.storage.repositories.base import TEXT_TYPE, BaseRepository


class SourceRepository(BaseRepository[Source]):
    """CRUD and filtered listing for :class:`Source` entities."""

    _model_class = Source

    async def create(
        self,
        name: str,
        type: str,
        url: str,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> Source:
        return await self._create_entity(
            name=name,
            type=type,
            url=url,
            tags=tags or [],
            **kwargs,
        )

    async def list(
        self,
        type: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        stmt = select(Source)

        if type is not None:
            stmt = stmt.where(Source.type == type)
        if status is not None:
            stmt = stmt.where(Source.status == status)
        if tag is not None:
            # SQLite-compatible: cast JSON array to Text and use LIKE
            stmt = stmt.where(Source.tags.cast(TEXT_TYPE).like(f'%"{tag}"%'))

        return await self._paginate(stmt, limit=limit, cursor=cursor)
