"""RSS/Atom feed collector adapter."""

from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime

import feedparser

from intellisource.collector.base import BaseCollector, RawContent, compute_fingerprint
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)


def _strip_html(html: str) -> str:
    """Remove HTML tags and return plain text."""
    return re.sub(r"<[^>]+>", "", html).strip()


def _parse_published(entry: dict[str, object]) -> datetime | None:
    """Extract and parse the published date from a feed entry."""
    raw = entry.get("published") or entry.get("updated")
    if not raw or not isinstance(raw, str):
        return None
    try:
        return parsedate_to_datetime(raw)
    except (ValueError, TypeError):
        pass
    # Try ISO 8601 format (common in Atom feeds)
    try:
        raw_str = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(raw_str)
    except (ValueError, TypeError):
        return None


def _extract_body_html(entry: dict[str, object]) -> str | None:
    """Extract HTML body from a feed entry."""
    # Atom: content field
    content_list = entry.get("content")
    if isinstance(content_list, list) and len(content_list) > 0:
        first = content_list[0]
        if isinstance(first, dict):
            value = first.get("value")
        else:
            value = None
        if isinstance(value, str):
            return value
    # RSS: description or summary
    for key in ("description", "summary"):
        val = entry.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _extract_link(entry: dict[str, object]) -> str:
    """Extract the link URL from a feed entry."""
    link = entry.get("link")
    if isinstance(link, str):
        return link
    return ""


class RSSCollector(BaseCollector):
    """Collector for RSS 2.0 and Atom 1.0 feeds."""

    async def collect(self, source_config: dict[str, object]) -> list[RawContent]:
        """Collect content items from an RSS/Atom feed URL."""
        url = source_config.get("url")
        if not isinstance(url, str):
            return []

        response = await self.conditional_fetch(url)
        if response is None:
            return []

        try:
            feed = feedparser.parse(response.content)
        except Exception:
            logger.error("Failed to parse feed from %s", url)
            return []

        if not feed.entries:
            return []

        results: list[RawContent] = []
        for entry in feed.entries:
            title = entry.get("title")
            author = entry.get("author")
            source_url = _extract_link(entry)
            body_html = _extract_body_html(entry)
            body_text = _strip_html(body_html) if body_html else None
            published_at = _parse_published(entry)
            fingerprint = compute_fingerprint(source_url, title, published_at)

            results.append(
                RawContent(
                    source_url=source_url,
                    fingerprint=fingerprint,
                    title=title,
                    author=author,
                    body_html=body_html,
                    body_text=body_text,
                    published_at=published_at,
                )
            )

        return results
