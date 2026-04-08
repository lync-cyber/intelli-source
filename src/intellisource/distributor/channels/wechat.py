"""WeChat Official Account distributor channel."""

from __future__ import annotations

import asyncio
from typing import Any

from intellisource.distributor.base import BaseDistributor

TOKEN_CACHE_KEY: str = "wechat:access_token"
TOKEN_EXPIRE_BUFFER: int = 300
MAX_RETRY: int = 3
RETRY_INTERVAL: int = 5

_WECHAT_TOKEN_URL = (
    "https://api.weixin.qq.com/cgi-bin/token"
    "?grant_type=client_credential&appid={app_id}"
    "&secret={app_secret}"
)
_WECHAT_TEMPLATE_URL = (
    "https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={token}"
)
_WECHAT_NEWS_URL = (
    "https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
)


class WeChatDistributor(BaseDistributor):
    """Distribute content via WeChat Official Account."""

    def __init__(
        self,
        *,
        redis: Any,
        http_client: Any,
        app_id: str,
        app_secret: str,
    ) -> None:
        self._redis = redis
        self._http = http_client
        self._app_id = app_id
        self._app_secret = app_secret

    # ----------------------------------------------------------
    # Token management (AC-T032-1)
    # ----------------------------------------------------------

    async def get_access_token(self) -> str:
        """Return cached token or fetch a new one."""
        cached: str | None = await self._redis.get(TOKEN_CACHE_KEY)
        if cached is not None:
            return cached

        url = _WECHAT_TOKEN_URL.format(
            app_id=self._app_id,
            app_secret=self._app_secret,
        )
        resp = await self._http.get(url)
        data: dict[str, Any] = resp.json()

        if "access_token" not in data:
            msg = data.get("errmsg", "unknown error")
            raise RuntimeError(f"WeChat token error: {msg}")

        token: str = data["access_token"]
        expires_in: int = int(data.get("expires_in", 7200))
        ttl = expires_in - TOKEN_EXPIRE_BUFFER

        await self._redis.set(TOKEN_CACHE_KEY, token, ex=ttl)
        return token

    # ----------------------------------------------------------
    # Message sending (AC-040)
    # ----------------------------------------------------------

    async def send_template_message(
        self,
        *,
        openid: str,
        template_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a template message to a user."""
        token = await self.get_access_token()
        url = _WECHAT_TEMPLATE_URL.format(token=token)
        payload = {
            "touser": openid,
            "template_id": template_id,
            "data": data,
        }
        resp = await self._http.post(url, json=payload)
        result: dict[str, Any] = resp.json()
        return result

    async def send_news_message(
        self,
        *,
        openid: str,
        articles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Send a news (article) message to a user."""
        token = await self.get_access_token()
        url = _WECHAT_NEWS_URL.format(token=token)
        payload = {
            "touser": openid,
            "msgtype": "news",
            "news": {"articles": articles},
        }
        resp = await self._http.post(url, json=payload)
        result: dict[str, Any] = resp.json()
        return result

    # ----------------------------------------------------------
    # Content formatting (AC-T032-2)
    # ----------------------------------------------------------

    def format_template_data(self, content: Any) -> dict[str, Any]:
        """Convert content to WeChat template data dict."""
        return {
            "title": {"value": getattr(content, "title", "")},
            "content": {"value": getattr(content, "body_text", "")},
        }

    def format_news_articles(self, content: Any) -> list[dict[str, Any]]:
        """Convert content to a list of article dicts."""
        return [
            {
                "title": getattr(content, "title", ""),
                "description": getattr(content, "body_text", ""),
                "url": "",
                "picurl": "",
            }
        ]

    # ----------------------------------------------------------
    # Core distribute (dedup + retry + record)
    # ----------------------------------------------------------

    async def distribute(self, content: Any, subscription: Any) -> dict[str, Any]:
        """Distribute content with dedup, retry, and recording."""
        content_id = getattr(content, "id", None)
        sub_id = getattr(subscription, "id", None)
        channel_cfg: dict[str, Any] = getattr(subscription, "channel_config", {})
        openid: str = channel_cfg.get("openid", "")
        msg_type: str = channel_cfg.get("msg_type", "template")

        # --- dedup check (AC-044) ---
        dedup_key = f"push:dedup:{content_id}:{sub_id}:wechat"
        if await self._redis.exists(dedup_key):
            return {
                "status": "skipped",
                "channel": "wechat",
                "content_id": content_id,
                "subscription_id": sub_id,
                "reason": "duplicate",
            }

        # --- send with retry (AC-045) ---
        last_result: dict[str, Any] = {}
        for attempt in range(MAX_RETRY):
            try:
                if msg_type == "news":
                    articles = self.format_news_articles(content)
                    last_result = await self.send_news_message(
                        openid=openid,
                        articles=articles,
                    )
                else:
                    tpl_id: str = channel_cfg.get("template_id", "")
                    tpl_data = self.format_template_data(content)
                    last_result = await self.send_template_message(
                        openid=openid,
                        template_id=tpl_id,
                        data=tpl_data,
                    )

                if last_result.get("errcode", -1) == 0:
                    await self._redis.set(dedup_key, "1", ex=86400)
                    return {
                        "status": "success",
                        "channel": "wechat",
                        "content_id": content_id,
                        "subscription_id": sub_id,
                        **last_result,
                    }

            except Exception:
                last_result = {
                    "errcode": -1,
                    "errmsg": "network_error",
                }

            # Retry delay (skip after final attempt)
            if attempt < MAX_RETRY - 1:
                await asyncio.sleep(RETRY_INTERVAL)

        # all retries exhausted
        return {
            "status": "failed",
            "channel": "wechat",
            "content_id": content_id,
            "subscription_id": sub_id,
            "error_code": last_result.get("errcode"),
            "error_msg": last_result.get("errmsg"),
        }
