"""Render model — the input shape every digest template renders from.

Distinct from ``pipeline``'s per-item summarization result: this is the
distributor-owned presentation model. ``timeline`` entries are kept as plain
``{date, event}`` dicts (read from ``ProcessedContent.structured_data``) since
they are display-only pass-through data.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DigestItem(BaseModel):
    title: str
    summary: str = ""
    body_text: str | None = None
    key_points: list[str] = Field(default_factory=list)
    why_it_matters: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_name: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None


class DigestSection(BaseModel):
    heading: str
    items: list[DigestItem] = Field(default_factory=list)


class DigestBundle(BaseModel):
    title: str
    period_label: str | None = None
    intro: str | None = None
    top_picks: list[DigestItem] = Field(default_factory=list)
    sections: list[DigestSection] = Field(default_factory=list)
    timeline: list[dict[str, str]] = Field(default_factory=list)
    outro: str | None = None
    generated_at: datetime | None = None
