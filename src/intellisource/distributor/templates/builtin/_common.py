"""Shared helpers for building render items from content rows."""

from __future__ import annotations

from typing import Any

from intellisource.distributor.templates.schemas import DigestItem


def to_item(content: Any) -> DigestItem:
    """Map a content row (ProcessedContent or push-view) to a DigestItem.

    ``key_points`` are read from the persisted ``structured_data`` digest when
    present; everything else comes from top-level attributes.
    """
    structured = getattr(content, "structured_data", None)
    key_points: list[str] = []
    if isinstance(structured, dict):
        raw = structured.get("key_points")
        if isinstance(raw, list):
            key_points = [str(k) for k in raw]
    return DigestItem(
        title=str(getattr(content, "title", "") or ""),
        summary=str(getattr(content, "summary", "") or ""),
        body_text=getattr(content, "body_text", None),
        key_points=key_points,
        why_it_matters=getattr(content, "why_it_matters", None),
        tags=list(getattr(content, "tags", []) or []),
        source_name=getattr(content, "source_name", None),
        source_url=getattr(content, "source_url", None),
        published_at=getattr(content, "published_at", None),
    )


def timeline_from(content: Any) -> list[dict[str, str]]:
    """Extract a ``[{date, event}]`` timeline from a content row's structured_data."""
    structured = getattr(content, "structured_data", None)
    out: list[dict[str, str]] = []
    if isinstance(structured, dict):
        entries = structured.get("timeline")
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and "date" in entry and "event" in entry:
                    out.append(
                        {"date": str(entry["date"]), "event": str(entry["event"])}
                    )
    return out
