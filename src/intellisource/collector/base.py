"""BaseCollector abstract base class and RawContent data model."""

from __future__ import annotations

import abc
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from intellisource.collector.adaptive import AdaptiveScheduler
    from intellisource.collector.proxy import ProxyManager
    from intellisource.collector.rate_limiter import RateLimiter
    from intellisource.config.models import SourceConfig


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

    def __init__(
        self,
        *,
        rate_limiter: RateLimiter | None = None,
        proxy_manager: ProxyManager | None = None,
        adaptive: AdaptiveScheduler | None = None,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._proxy_manager = proxy_manager
        self._adaptive = adaptive

    @abc.abstractmethod
    async def collect(self, source_config: dict[str, object]) -> list[RawContent]:
        """Collect content from a source defined by source_config."""
        ...

    async def fetch(self, source_config: SourceConfig) -> list[RawContent]:
        """Fetch with rate limiting, proxy routing, and adaptive recording."""
        if self._rate_limiter:
            await self._rate_limiter.acquire(
                source_config.name,
                qps=int(source_config.rate_limit_qps)
                if source_config.rate_limit_qps is not None
                else None,
                concurrency=source_config.rate_limit_concurrency,
            )
        proxy: str | None = None
        if self._proxy_manager and source_config.proxy:
            proxy = self._proxy_manager.get_proxy(source_config.name)
        try:
            result = await self._do_fetch(source_config, proxy=proxy)
            if self._adaptive:
                self._adaptive.record_success(source_config.name)
            return result
        except Exception:
            if self._adaptive:
                self._adaptive.record_failure(source_config.name)
            raise

    async def _do_fetch(
        self, source_config: SourceConfig, proxy: str | None = None
    ) -> list[RawContent]:
        """Default implementation delegates to collect() with dict config.

        Subclasses can override to consume the proxy argument directly.
        """
        cfg: dict[str, object] = source_config.model_dump()
        return await self.collect(cfg)

    async def conditional_fetch(
        self,
        url: str,
        etag: str | None = None,
        last_modified: str | None = None,
        timeout: float = 30.0,
        proxy: str | None = None,
    ) -> httpx.Response | None:
        """Perform an HTTP GET with conditional request headers.

        Returns None if the server responds with 304 Not Modified.
        """
        headers: dict[str, str] = {}
        if etag is not None:
            headers["If-None-Match"] = etag
        if last_modified is not None:
            headers["If-Modified-Since"] = last_modified

        async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
            response = await client.get(url, headers=headers)

        if response.status_code == 304:
            return None
        return response
