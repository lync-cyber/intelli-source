"""ContentRepository -- data access for ProcessedContent entities."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from intellisource.storage.models import ProcessedContent, RawContent
from intellisource.storage.repositories.base import TEXT_TYPE, BaseRepository


class ContentRepository(BaseRepository[ProcessedContent]):
    """CRUD and filtered listing for :class:`ProcessedContent` entities."""

    _model_class = ProcessedContent

    async def get_raw_by_id(self, raw_id: uuid.UUID) -> RawContent | None:
        """Return the RawContent row with the given UUID, or None if not found."""
        result = await self._session.execute(
            select(RawContent).where(RawContent.id == raw_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_raw_by_fingerprint(self, fingerprint: str) -> RawContent | None:
        """Return RawContent with the given fingerprint, or None if not found."""
        result = await self._session.execute(
            select(RawContent).where(RawContent.fingerprint == fingerprint).limit(1)
        )
        return result.scalar_one_or_none()

    async def create_raw(
        self,
        *,
        source_id: uuid.UUID,
        source_url: str,
        fingerprint: str,
        title: str | None = None,
        author: str | None = None,
        body_html: str | None = None,
        body_text: str | None = None,
        published_at: datetime | None = None,
        raw_metadata: dict[str, Any] | None = None,
        collect_task_id: uuid.UUID | None = None,
    ) -> RawContent:
        """Insert a new RawContent row and return the flushed entity."""
        entity = RawContent(
            id=uuid.uuid4(),
            source_id=source_id,
            collect_task_id=collect_task_id,
            title=title,
            author=author,
            body_html=body_html,
            body_text=body_text,
            source_url=source_url,
            published_at=published_at,
            fingerprint=fingerprint,
            raw_metadata=raw_metadata or {},
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def get_processed_by_raw_id(
        self, raw_id: uuid.UUID
    ) -> ProcessedContent | None:
        """Return ProcessedContent linked to the given RawContent id."""
        result = await self._session.execute(
            select(ProcessedContent)
            .where(ProcessedContent.raw_content_id == raw_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        raw_content_id: uuid.UUID,
        title: str,
        body_text: str,
        tags: list[str] | None = None,
        cluster_id: uuid.UUID | None = None,
        published_at: datetime | None = None,
        **kwargs: Any,
    ) -> ProcessedContent:
        return await self._create_entity(
            raw_content_id=raw_content_id,
            title=title,
            body_text=body_text,
            tags=tags or [],
            cluster_id=cluster_id,
            published_at=published_at,
            **kwargs,
        )

    async def list(
        self,
        source_id: uuid.UUID | None = None,
        tag: str | None = None,
        cluster_id: uuid.UUID | None = None,
        published_after: datetime | None = None,
        published_before: datetime | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        stmt = select(ProcessedContent)

        if source_id is not None:
            stmt = stmt.join(
                RawContent, ProcessedContent.raw_content_id == RawContent.id
            ).where(RawContent.source_id == source_id)
        if tag is not None:
            stmt = stmt.where(ProcessedContent.tags.cast(TEXT_TYPE).like(f'%"{tag}"%'))
        if cluster_id is not None:
            stmt = stmt.where(ProcessedContent.cluster_id == cluster_id)
        if published_after is not None:
            stmt = stmt.where(ProcessedContent.published_at >= published_after)
        if published_before is not None:
            stmt = stmt.where(ProcessedContent.published_at < published_before)

        return await self._paginate(stmt, limit=limit, cursor=cursor)
