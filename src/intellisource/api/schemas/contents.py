"""Response schemas for the contents router."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from intellisource.api.schemas.common import APIModel


class ContentItem(APIModel):
    """A single processed-content row (mirrors `_serialize_content`)."""

    id: str
    title: str | None = None
    summary: str | None = None
    tags: list[str] | None = None
    source_name: str | None = None
    published_at: datetime | None = None
    body_text: str | None = None
    source_url: str | None = None
    processing_status: str | None = None
    raw_content_id: str | None = None
    created_at: datetime | None = None
    cluster_id: str | None = None


class ContentListResponse(APIModel):
    """Cursor-paginated content list."""

    items: list[ContentItem]
    next_cursor: str | None = None
    has_more: bool


class BackfillEmbeddingsResponse(APIModel):
    """Response for the backfill-embeddings async task dispatch."""

    status: Literal["accepted"]
    task_id: str
