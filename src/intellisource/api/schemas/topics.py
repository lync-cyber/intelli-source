"""Response schemas for the topics router."""

from __future__ import annotations

from typing import Any

from intellisource.api.schemas.common import APIModel


class TopicSummary(APIModel):
    """A built-in topic catalog entry (mirrors `_serialize_topic`)."""

    id: str
    name: str
    dimension: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    discipline_tags: list[str] | None = None
    source_count: int


class TopicDetail(TopicSummary):
    """Topic detail adds resolved sources + the subscription template."""

    sources: list[dict[str, Any]] = []
    subscription_template: dict[str, Any] | None = None


class TopicListResponse(APIModel):
    """All built-in topics."""

    items: list[TopicSummary]
