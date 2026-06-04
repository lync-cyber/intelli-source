"""Aggregation result schema — single source of truth for the digest shape.

``ContentDigest`` is the typed result produced by summarization and persisted
into ``ProcessedContent.structured_data`` (and, later, the ``Digest`` table).
``parse_digest`` validates a raw LLM JSON object into a ``ContentDigest``,
returning ``None`` when required keys are absent or types are invalid so callers
fall back to deterministic truncation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError


class TimelineEntry(BaseModel):
    date: str
    event: str


class ContentDigest(BaseModel):
    title: str
    summary: str
    timeline: list[TimelineEntry] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)


_REQUIRED_KEYS = frozenset({"title", "summary", "timeline", "key_points"})


def parse_digest(parsed: dict[str, Any]) -> ContentDigest | None:
    """Validate a raw LLM JSON object into a ``ContentDigest``.

    All four keys must be present (callers fall back to truncation otherwise);
    types are validated by pydantic. Returns ``None`` on any mismatch.
    """
    if not _REQUIRED_KEYS.issubset(parsed.keys()):
        return None
    try:
        return ContentDigest(
            title=str(parsed["title"]),
            summary=str(parsed["summary"]),
            timeline=parsed["timeline"],
            key_points=parsed["key_points"],
        )
    except (ValidationError, TypeError):
        return None
