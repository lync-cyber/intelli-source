"""Response schemas for the sources router."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from intellisource.api.schemas.common import APIModel


class SourceItem(APIModel):
    """A single source configuration row (mirrors `_serialize_source`)."""

    id: str
    name: str
    type: str
    url: str | None = None
    tags: list[str] = []
    discipline_tags: list[str] = []
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    schedule_interval: int | None = None
    schedule_adaptive: bool | None = None
    proxy: str | None = None
    rate_limit_qps: float | None = None
    rate_limit_concurrency: int | None = None
    metadata: dict[str, Any] | None = None
    last_collected_at: datetime | None = None
    next_collect_at: datetime | None = None
    error_count: int | None = None
    avg_update_interval: float | None = None
    http_etag: str | None = None
    http_last_modified: str | None = None
    config_version: int | None = None


class SourceListResponse(APIModel):
    """Cursor-paginated source list."""

    items: list[SourceItem]
    next_cursor: str | None = None
    has_more: bool
