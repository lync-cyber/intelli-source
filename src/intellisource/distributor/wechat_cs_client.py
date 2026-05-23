"""WeChat Customer Service client for real-time CS messaging (AC-7/8)."""

from __future__ import annotations

import os
from typing import Any

_WECHAT_API_BASE = "https://api.weixin.qq.com"
_TOKEN_CACHE_KEY = "wechat:access_token"
_TOKEN_TTL = 7000


class WeChatCustomerServiceClient:
    """Send customer service messages via WeChat cgi-bin API."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        redis_client: Any,
        http_client: Any | None = None,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._redis = redis_client
        self._http = http_client

    @classmethod
    def from_env(
        cls, redis_client: Any, http_client: Any | None = None
    ) -> "WeChatCustomerServiceClient":
        """Create instance from IS_WECHAT_APP_ID / IS_WECHAT_APP_SECRET env vars.

        Raises ValueError when either variable is absent.
        """
        app_id = os.environ.get("IS_WECHAT_APP_ID")
        app_secret = os.environ.get("IS_WECHAT_APP_SECRET")
        if not app_id:
            raise ValueError(
                "IS_WECHAT_APP_ID missing — required for WeChatCustomerServiceClient"
            )
        if not app_secret:
            raise ValueError(
                "IS_WECHAT_APP_SECRET missing"
                " — required for WeChatCustomerServiceClient"
            )
        return cls(
            app_id=app_id,
            app_secret=app_secret,
            redis_client=redis_client,
            http_client=http_client,
        )

    async def get_access_token(self) -> str:
        """Return cached token or fetch a fresh one from cgi-bin/token."""
        cached = await self._redis.get(_TOKEN_CACHE_KEY)
        if cached is not None:
            if isinstance(cached, bytes):
                return cached.decode()
            return str(cached)

        url = (
            f"{_WECHAT_API_BASE}/cgi-bin/token"
            f"?grant_type=client_credential"
            f"&appid={self._app_id}"
            f"&secret={self._app_secret}"
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
        url = f"{_WECHAT_API_BASE}/cgi-bin/message/custom/send?access_token={token}"
        payload: dict[str, Any] = {
            "touser": openid,
            "msgtype": "text",
            "text": {"content": content},
        }
        assert self._http is not None, "http_client must be provided"
        resp = await self._http.post(url, json=payload)
        result: dict[str, Any] = resp.json()
        return result
