"""Response schemas for the clusters router."""

from __future__ import annotations

from datetime import datetime

from intellisource.api.schemas.common import APIModel


class ClusterItem(APIModel):
    """A single content cluster row (mirrors `_serialize_cluster`)."""

    id: str
    topic: str | None = None
    tags: list[str] | None = None
    content_count: int | None = None
    digest: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ClusterListResponse(APIModel):
    """Cursor-paginated cluster list."""

    items: list[ClusterItem]
    next_cursor: str | None = None
    has_more: bool
