"""SourceRepository -- data access for Source entities."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from intellisource.config.models import SourceConfig
from intellisource.storage.models import Source
from intellisource.storage.repositories.base import TEXT_TYPE, BaseRepository

logger = logging.getLogger(__name__)


class SourceRepository(BaseRepository[Source]):
    """CRUD and filtered listing for :class:`Source` entities."""

    _model_class = Source

    async def upsert(self, config: SourceConfig) -> Source:
        """Create or update a Source from a SourceConfig.

        Finds by name and updates if exists, creates otherwise.
        """
        stmt = select(Source).where(Source.name == config.name)
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.type = config.type
            existing.url = config.url
            existing.tags = config.tags
            existing.schedule_interval = config.schedule_interval
            existing.schedule_adaptive = config.schedule_adaptive
            existing.proxy = config.proxy
            existing.rate_limit_qps = config.rate_limit_qps
            existing.rate_limit_concurrency = config.rate_limit_concurrency
            existing.metadata_ = config.metadata
            await self._session.flush()
            return existing
        source = Source(
            name=config.name,
            type=config.type,
            url=config.url,
            tags=config.tags,
            status="active",
            schedule_interval=config.schedule_interval,
            schedule_adaptive=config.schedule_adaptive,
            proxy=config.proxy,
            rate_limit_qps=config.rate_limit_qps,
            rate_limit_concurrency=config.rate_limit_concurrency,
            metadata_=config.metadata,
        )
        self._session.add(source)
        await self._session.flush()
        return source

    async def bulk_upsert(self, configs: list[SourceConfig]) -> int:
        """Create or update Sources for each SourceConfig; returns count upserted."""
        count = 0
        for cfg in configs:
            await self.upsert(cfg)
            count += 1
        return count

    async def list_active_source_ids(self) -> list[uuid.UUID]:
        """Return the IDs of all sources with status='active'."""
        stmt = select(Source.id).where(Source.status == "active")
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

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
