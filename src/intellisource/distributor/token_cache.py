"""Redis-backed access-token cache shared by every platform token path.

``get()`` reads the cached token (decoding ``bytes``); on a miss it fetches a
fresh one via the injected ``fetch`` coroutine and stores it with an atomic
``set(ex=...)`` so a crash can never leave a never-expiring key. The TTL is
``expires_in - ttl_buffer`` floored at ``ttl_floor`` so a short-lived upstream
token can never produce a non-positive TTL.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

TokenFetcher = Callable[[], Awaitable[tuple[str, int]]]


class TokenCache:
    """Cache an access token in Redis with atomic, floored TTL writes."""

    def __init__(
        self,
        redis: Any,
        cache_key: str,
        fetch: TokenFetcher,
        *,
        ttl_buffer: int,
        ttl_floor: int = 60,
    ) -> None:
        self._redis = redis
        self._cache_key = cache_key
        self._fetch = fetch
        self._ttl_buffer = ttl_buffer
        self._ttl_floor = ttl_floor

    async def get(self) -> str:
        """Return the cached token, or fetch + cache a fresh one on miss."""
        cached = await self._redis.get(self._cache_key)
        if cached is not None:
            if isinstance(cached, bytes):
                return cached.decode()
            return str(cached)

        token, expires_in = await self._fetch()
        ttl = max(expires_in - self._ttl_buffer, self._ttl_floor)
        await self._redis.set(self._cache_key, token, ex=ttl)
        return token
