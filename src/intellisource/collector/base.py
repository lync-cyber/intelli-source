"""BaseCollector abstract base class and RawContent data model."""

from __future__ import annotations

import abc
import hashlib
from dataclasses import dataclass, field
from datetime import datetime

import httpx


def compute_fingerprint(
    source_url: str, title: str | None, published_at: datetime | None
) -> str:
    """Compute SHA-256 hex digest from source_url + title + published_at."""
    raw = (
        source_url + (title or "") + (published_at.isoformat() if published_at else "")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class RawContent:
    """Unified data model for collected raw content."""

    source_url: str
    fingerprint: str
    title: str | None = None
    author: str | None = None
    body_html: str | None = None
    body_text: str | None = None
    published_at: datetime | None = None
    raw_metadata: dict[str, object] = field(default_factory=dict)


class BaseCollector(abc.ABC):
    """Abstract base class for all content collectors."""

    @abc.abstractmethod
    async def collect(self, source_config: dict[str, object]) -> list[RawContent]:
        """Collect content from a source defined by source_config."""
        ...

    async def conditional_fetch(
        self,
        url: str,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> httpx.Response | None:
        """Perform an HTTP GET with conditional request headers.

        Returns None if the server responds with 304 Not Modified.
        """
        headers: dict[str, str] = {}
        if etag is not None:
            headers["If-None-Match"] = etag
        if last_modified is not None:
            headers["If-Modified-Since"] = last_modified

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)

        if response.status_code == 304:
            return None
        return response
