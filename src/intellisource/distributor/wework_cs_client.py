"""WeWork Customer Service client for real-time CS messaging (AC-10)."""

from __future__ import annotations

import os
from typing import Any

_WEWORK_API_BASE = "https://qyapi.weixin.qq.com"
_TOKEN_CACHE_KEY = "wework:access_token"


class WeWorkCustomerServiceClient:
    """Send customer service messages via WeWork cgi-bin API."""

    def __init__(
        self,
        corp_id: str,
        corp_secret: str,
        redis_client: Any,
        http_client: Any | None = None,
    ) -> None:
        self._corp_id = corp_id
        self._corp_secret = corp_secret
        self._redis = redis_client
        self._http = http_client

    @classmethod
    def from_env(
        cls, redis_client: Any, http_client: Any | None = None
    ) -> "WeWorkCustomerServiceClient":
        """Create instance from IS_WEWORK_CORP_ID / IS_WEWORK_CORP_SECRET env vars.

        Raises ValueError when either variable is absent.
        """
        corp_id = os.environ.get("IS_WEWORK_CORP_ID")
        corp_secret = os.environ.get("IS_WEWORK_CORP_SECRET")
        if not corp_id:
            raise ValueError(
                "IS_WEWORK_CORP_ID missing — required for WeWorkCustomerServiceClient"
            )
        if not corp_secret:
            raise ValueError(
                "IS_WEWORK_CORP_SECRET missing"
                " — required for WeWorkCustomerServiceClient"
            )
        return cls(
            corp_id=corp_id,
            corp_secret=corp_secret,
            redis_client=redis_client,
            http_client=http_client,
        )

    async def get_access_token(self) -> str:
        """Return cached token or fetch a fresh one from cgi-bin/gettoken."""
        cached = await self._redis.get(_TOKEN_CACHE_KEY)
        if cached is not None:
            if isinstance(cached, bytes):
                return cached.decode()
            return str(cached)

        url = (
            f"{_WEWORK_API_BASE}/cgi-bin/gettoken"
            f"?corpid={self._corp_id}"
            f"&corpsecret={self._corp_secret}"
        )
        assert self._http is not None, "http_client must be provided"
        resp = await self._http.get(url)
        data: dict[str, Any] = resp.json()

        token: str = data["access_token"]
        expires_in: int = int(data.get("expires_in", 7200))
        ttl = expires_in - 200

        await self._redis.set(_TOKEN_CACHE_KEY, token, ex=ttl)
        return token

    async def send_text(self, openid: str, content: str) -> dict[str, Any]:
        """Send a text customer service message to the given openid."""
        token = await self.get_access_token()
        url = f"{_WEWORK_API_BASE}/cgi-bin/message/send?access_token={token}"
        payload: dict[str, Any] = {
            "touser": openid,
            "msgtype": "text",
            "text": {"content": content},
        }
        assert self._http is not None, "http_client must be provided"
        resp = await self._http.post(url, json=payload)
        result: dict[str, Any] = resp.json()
        return result
