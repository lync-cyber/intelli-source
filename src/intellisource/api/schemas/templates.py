"""Response schemas for the templates CRUD router."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from intellisource.api.schemas.common import APIModel


class TemplateDetail(APIModel):
    """A digest template — a DB-backed custom one or a built-in catalog entry.

    ``source`` is ``"db"`` for custom templates (carrying the full definition)
    or ``"builtin"`` for the packaged catalog entries (definition fields absent).
    """

    name: str
    source: str
    formats: list[str] = []
    default_format: str
    base_template: str | None = None
    status: str | None = None
    jinja_source: dict[str, str] | None = None
    aggregate_config: dict[str, Any] | None = None
    id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
