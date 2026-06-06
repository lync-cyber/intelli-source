"""Data transfer objects for agent tool return values."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProcessedContentDTO(BaseModel):
    """Serializable representation of a ProcessedContent ORM row.

    ``model_validate`` reads attributes off a ProcessedContent ORM row
    (``from_attributes``); ``model_dump(mode="json")`` renders UUID / datetime
    fields as plain JSON scalars natively.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    raw_content_id: uuid.UUID | None = None
    title: str | None = None
    body_text: str | None = None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    fingerprint: str | None = None
    source_url: str | None = None
    created_at: datetime | None = None
