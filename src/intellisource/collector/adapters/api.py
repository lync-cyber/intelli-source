"""API collector adapter for generic HTTP API integration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from intellisource.collector.base import BaseCollector, RawContent, compute_fingerprint

logger = logging.getLogger(__name__)


def _resolve_path(data: object, path: str) -> object | None:
    """Resolve a simple dot-notation JSONPath on a dict.

    Supports paths like ``"$.data.articles"`` or ``"data.articles"``.
    Returns *None* when any segment is missing.
    """
    if isinstance(path, str) and path.startswith("$."):
        path = path[2:]

    current: object = data
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def _resolve_str(item: object, mapping: dict[str, str], key: str) -> str | None:
    """Resolve a field mapping key to a string value, or None."""
    if key not in mapping:
        return None
    val = _resolve_path(item, mapping[key])
    return str(val) if val is not None else None


def _parse_datetime(value: object) -> datetime | None:
    """Parse an ISO-8601 datetime string, returning *None* on failure."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class APICollector(BaseCollector):
    """Collector for generic HTTP/JSON APIs."""

    async def _request(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Send an HTTP request and return the response."""
        async with httpx.AsyncClient() as client:
            if method.upper() == "POST":
                return await client.post(
                    url,
                    headers=headers or {},
                    params=params,
                    json=body,
                )
            # Default to GET
            return await client.get(
                url,
                headers=headers or {},
                params=params,
            )

    async def collect(self, source_config: dict[str, object]) -> list[RawContent]:
        """Collect content items from an HTTP API endpoint."""
        url = source_config.get("url")
        if not isinstance(url, str):
            return []

        metadata: dict[str, Any] = {}
        raw_meta = source_config.get("metadata")
        if isinstance(raw_meta, dict):
            metadata = dict(raw_meta)

        method: str = metadata.get("method", "GET")
        headers: dict[str, str] | None = metadata.get("headers")
        params: dict[str, Any] | None = metadata.get("params")
        body: dict[str, Any] | None = metadata.get("body")
        field_mapping: dict[str, str] = metadata.get("field_mapping", {})

        try:
            response = await self._request(
                url,
                method,
                headers,
                params=params,
                body=body,
            )
        except Exception:
            logger.error("Request failed for %s", url)
            return []

        if response.status_code >= 400:
            return []

        try:
            data = response.json()
        except Exception:
            logger.error("Failed to parse JSON from %s", url)
            return []

        # Extract items array
        items_path = field_mapping.get("items_path", "")
        items = _resolve_path(data, items_path)
        if not isinstance(items, list):
            return []

        results: list[RawContent] = []
        for item in items:
            title = _resolve_str(item, field_mapping, "title")
            author = _resolve_str(item, field_mapping, "author")
            body_text = _resolve_str(item, field_mapping, "body_text")
            source_url_str = _resolve_str(item, field_mapping, "source_url") or url
            published_at = _parse_datetime(
                _resolve_path(item, field_mapping["published_at"])
                if "published_at" in field_mapping
                else None
            )

            fingerprint = compute_fingerprint(source_url_str, title, published_at)

            results.append(
                RawContent(
                    source_url=source_url_str,
                    fingerprint=fingerprint,
                    title=title,
                    author=author,
                    body_text=body_text,
                    published_at=published_at,
                )
            )

        return results
