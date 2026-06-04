"""Response schemas for the distribution control-plane router."""

from __future__ import annotations

from datetime import datetime

from intellisource.api.schemas.common import APIModel


class ChannelInfo(APIModel):
    """A distribution channel and whether its credentials are present."""

    name: str
    display_name: str
    required_env: list[str]
    configured: bool


class ChannelListResponse(APIModel):
    """All registered distribution channels."""

    items: list[ChannelInfo]


class TemplateInfo(APIModel):
    """A digest output template and the formats it renders."""

    name: str
    formats: list[str]
    default_format: str


class TemplateListResponse(APIModel):
    """All registered digest templates."""

    items: list[TemplateInfo]


class PushRecordItem(APIModel):
    """A single push record (recipient_id is PII-masked)."""

    id: str
    subscription_id: str | None = None
    content_id: str | None = None
    channel: str
    status: str
    retry_count: int | None = None
    error_message: str | None = None
    recipient: str | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime | None = None


class PushRecordListResponse(APIModel):
    """Cursor-paginated push records."""

    items: list[PushRecordItem]
    next_cursor: str | None = None
    has_more: bool


class AssembleTriggerResponse(APIModel):
    """Dispatch result for POST /distributions/assemble."""

    task_id: str
