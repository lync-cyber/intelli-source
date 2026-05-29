"""WeChat Official Account distributor channel."""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any

from intellisource.distributor.base import BaseDistributor
from intellisource.distributor.channels.constants import (
    MAX_RETRY,
    RETRY_INTERVAL,
    TOKEN_EXPIRE_BUFFER,
)

if TYPE_CHECKING:
    from intellisource.storage.repositories.push import PushRepository

TOKEN_CACHE_KEY: str = "wechat:access_token"

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
        push_repo: "PushRepository | None" = None,
    ) -> None:
        if http_client is None:
            raise ValueError("http_client is required for WeChatDistributor")
        self._redis = redis
        self._http = http_client
        self._app_id = app_id
        self._app_secret = app_secret
        self._push_repo = push_repo

    @classmethod
    def from_env(cls, *, redis: Any, http_client: Any = None) -> WeChatDistributor:
        """Create instance from IS_WECHAT_* environment variables.

        Raises ValueError when IS_WECHAT_APP_ID or IS_WECHAT_APP_SECRET are absent.
        """
        app_id = os.environ.get("IS_WECHAT_APP_ID")
        app_secret = os.environ.get("IS_WECHAT_APP_SECRET")
        if not app_id:
            raise ValueError(
                "IS_WECHAT_APP_ID missing — required for WeChatDistributor"
            )
        if not app_secret:
            raise ValueError(
                "IS_WECHAT_APP_SECRET missing — required for WeChatDistributor"
            )
        return cls(
            redis=redis,
            http_client=http_client,
            app_id=app_id,
            app_secret=app_secret,
        )

    # ----------------------------------------------------------
    # Token management
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
    # Message sending
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
    # Content formatting
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
        channel = "wechat"

        async def attempt_fn(
            _attempt: int, is_last: bool
        ) -> tuple[bool, str | None, dict[str, Any]]:
            exc_ref: list[Exception] = []
            try:
                if msg_type == "news":
                    articles = self.format_news_articles(content)
                    raw = await self.send_news_message(openid=openid, articles=articles)
                else:
                    tpl_id: str = channel_cfg.get("template_id", "")
                    tpl_data = self.format_template_data(content)
                    raw = await self.send_template_message(
                        openid=openid, template_id=tpl_id, data=tpl_data
                    )
            except Exception as exc:
                exc_ref.append(exc)
                raw = {"errcode": -1, "errmsg": "network_error"}

            if raw.get("errcode", -1) == 0:
                return True, None, raw
            error = str(exc_ref[0]) if exc_ref else raw.get("errmsg", "unknown error")
            if not is_last:
                await asyncio.sleep(RETRY_INTERVAL)
            return False, error, raw

        was_deduped, succeeded, _, error, raw = await self._send_with_dedup_lifecycle(
            sub_id,
            content_id,
            channel,
            attempt_fn=attempt_fn,
            max_retry=MAX_RETRY,
        )

        if was_deduped:
            return {
                "status": "deduplicated",
                "channel": channel,
                "content_id": content_id,
                "subscription_id": sub_id,
            }
        if succeeded:
            return {
                "status": "success",
                "channel": channel,
                "content_id": content_id,
                "subscription_id": sub_id,
                **raw,
            }
        return {
            "status": "failed",
            "channel": channel,
            "content_id": content_id,
            "subscription_id": sub_id,
            "error_code": raw.get("errcode"),
            "error_msg": error,
        }
