"""Response schemas for the subscriptions router."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from intellisource.api.schemas.common import APIModel


class SubscriptionItem(APIModel):
    """A single subscription row (mirrors `_serialize`)."""

    id: str
    name: str
    source_id: str | None = None
    channel: str
    channel_config: dict[str, Any] | None = None
    match_rules: dict[str, Any] | None = None
    frequency: str | None = None
    quiet_hours: dict[str, Any] | None = None
    timezone: str | None = None
    discipline_tags: list[str] = []
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SubscriptionListResponse(APIModel):
    """Cursor-paginated subscription list."""

    items: list[SubscriptionItem]
    next_cursor: str | None = None
    has_more: bool
