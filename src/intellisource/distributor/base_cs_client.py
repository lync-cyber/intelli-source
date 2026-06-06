"""Base customer-service client for platform-specific CS messaging.

Both `WeChatCustomerServiceClient` and `WeWorkCustomerServiceClient` share
the same flow:

1. Redis-backed `access_token` cache.
2. Token endpoint refetch when cache miss, with platform-specific URL.
3. POST a `send_text` payload to a platform-specific endpoint.

The subclass declares the per-platform endpoint URLs, Redis cache key, and
the token-query / send-payload builders. The base class owns the cache +
HTTP plumbing and converts upstream `errcode != 0` responses into
`DistributorError(category=EXTERNAL)` so the retry / degradation logic in
arch §5.3 can engage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from intellisource.core.errors import DistributorError, ErrorCategory
from intellisource.distributor.token_cache import TokenCache

_TOKEN_TTL_BUFFER_SECONDS: int = 200


class BaseCustomerServiceClient(ABC):
    """Shared infrastructure for platform CS clients (token cache + send_text)."""

    api_base: str
    token_path: str
    send_path: str
    token_cache_key: str

    def __init__(
        self,
        *,
        redis_client: Any,
        http_client: Any,
    ) -> None:
        if http_client is None:
            raise ValueError(
                "http_client is required — pass an async HTTP client "
                "(e.g. httpx.AsyncClient)"
            )
        self._redis = redis_client
        self._http = http_client
        self._token_cache = TokenCache(
            redis_client,
            self.token_cache_key,
            self._fetch_token,
            ttl_buffer=_TOKEN_TTL_BUFFER_SECONDS,
        )

    @abstractmethod
    def _build_token_query(self) -> str:
        """Return the query string for the platform's token-fetch endpoint."""

    @abstractmethod
    def _build_send_payload(self, openid: str, content: str) -> dict[str, Any]:
        """Return the JSON payload for the platform's send-text endpoint."""

    async def get_access_token(self) -> str:
        """Return cached token or fetch a fresh one from the platform."""
        return await self._token_cache.get()

    async def _fetch_token(self) -> tuple[str, int]:
        """Fetch a fresh access token from the platform token endpoint."""
        url = f"{self.api_base}{self.token_path}?{self._build_token_query()}"
        resp = await self._http.get(url)
        data: dict[str, Any] = resp.json()

        if data.get("errcode", 0) != 0:
            raise DistributorError(
                f"token fetch failed: errcode={data.get('errcode')}"
                f" errmsg={data.get('errmsg', '')}",
                category=ErrorCategory.EXTERNAL,
            )

        token_value = data.get("access_token")
        if not isinstance(token_value, str) or not token_value:
            raise DistributorError(
                f"token response missing access_token: {data}",
                category=ErrorCategory.EXTERNAL,
            )

        expires_in: int = int(data.get("expires_in", 7200))
        return token_value, expires_in

    async def send_text(self, openid: str, content: str) -> dict[str, Any]:
        """Send a text customer-service message to the given openid."""
        token = await self.get_access_token()
        url = f"{self.api_base}{self.send_path}?access_token={token}"
        payload = self._build_send_payload(openid=openid, content=content)
        resp = await self._http.post(url, json=payload)
        result: dict[str, Any] = resp.json()

        if result.get("errcode", 0) != 0:
            raise DistributorError(
                f"send_text failed: errcode={result.get('errcode')}"
                f" errmsg={result.get('errmsg', '')}",
                category=ErrorCategory.EXTERNAL,
            )
        return result
