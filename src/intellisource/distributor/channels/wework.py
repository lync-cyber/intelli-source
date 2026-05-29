"""WeWork (enterprise WeChat) distributor implementation."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from intellisource.core.errors import DistributorError
from intellisource.distributor.base import BaseDistributor
from intellisource.distributor.channels.constants import (
    MAX_RETRY,
    RETRY_INTERVAL,
    TOKEN_EXPIRE_BUFFER,
)

if TYPE_CHECKING:
    from intellisource.storage.repositories.push import PushRepository

TOKEN_CACHE_KEY: str = "wework:access_token"

_WEWORK_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"


class WeWorkDistributor(BaseDistributor):
    """Distribute content via enterprise WeChat app messages."""

    def __init__(
        self,
        redis: Any,
        http_client: Any,
        corp_id: str,
        corp_secret: str,
        agent_id: int,
        push_repo: "PushRepository | None" = None,
    ) -> None:
        if http_client is None:
            raise ValueError("http_client is required for WeWorkDistributor")
        self.redis = redis
        self.http_client = http_client
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.agent_id = agent_id
        self._push_repo = push_repo

    @classmethod
    def from_env(cls, *, redis: Any, http_client: Any = None) -> "WeWorkDistributor":
        """Create instance from IS_WEWORK_* environment variables.

        Raises ValueError when IS_WEWORK_CORP_ID, IS_WEWORK_CORP_SECRET, or
        IS_WEWORK_AGENT_ID are absent.
        """
        corp_id = os.environ.get("IS_WEWORK_CORP_ID")
        corp_secret = os.environ.get("IS_WEWORK_CORP_SECRET")
        agent_id_str = os.environ.get("IS_WEWORK_AGENT_ID")
        if not corp_id:
            raise ValueError(
                "IS_WEWORK_CORP_ID missing — required for WeWorkDistributor"
            )
        if not corp_secret:
            raise ValueError(
                "IS_WEWORK_CORP_SECRET missing — required for WeWorkDistributor"
            )
        if not agent_id_str:
            raise ValueError(
                "IS_WEWORK_AGENT_ID missing — required for WeWorkDistributor"
            )
        return cls(
            redis=redis,
            http_client=http_client,
            corp_id=corp_id,
            corp_secret=corp_secret,
            agent_id=int(agent_id_str),
        )

    # ------------------------------------------------------------------
    # distribute (ABC entry-point)
    # ------------------------------------------------------------------

    async def distribute(
        self,
        content: Any,
        subscription: Any,
    ) -> dict[str, Any]:
        """Distribute *content* to *subscription* via WeWork."""
        content_id = getattr(content, "id", None)
        sub_id = getattr(subscription, "id", None)
        channel = "wework"

        cfg = subscription.channel_config
        msg_type: str = cfg.get("msg_type", "text")
        user_id: str = cfg.get("user_id", "@all")
        formatted = self.format_content(content, msg_type=msg_type)

        async def attempt_fn(
            _attempt: int, is_last: bool
        ) -> tuple[bool, str | None, dict[str, Any]]:
            exc_ref: list[Exception] = []
            try:
                if msg_type == "markdown":
                    res = await self.send_markdown_message(user_id, formatted)
                elif msg_type == "news":
                    res = await self.send_news_card(user_id, formatted)
                else:
                    res = await self.send_text_message(user_id, formatted)
            except Exception as exc:
                exc_ref.append(exc)
                res = {"errcode": -1, "errmsg": "network_error"}

            if res.get("errcode", -1) == 0:
                return True, None, res
            error = str(exc_ref[0]) if exc_ref else res.get("errmsg", "unknown error")
            if not is_last:
                await asyncio.sleep(RETRY_INTERVAL)
            return False, error, res

        was_deduped, succeeded, _, error, _ = await self._send_with_dedup_lifecycle(
            sub_id,
            content_id,
            channel,
            attempt_fn=attempt_fn,
            max_retry=MAX_RETRY,
        )

        if was_deduped:
            return self._build_result("duplicate", content, subscription)
        if succeeded:
            return self._build_result("success", content, subscription)
        return self._build_result("failed", content, subscription, error=error)

    # ------------------------------------------------------------------
    # Access token
    # ------------------------------------------------------------------

    async def get_access_token(self) -> str:
        """Return a valid access token (cached or freshly fetched)."""
        cached = await self.redis.get(TOKEN_CACHE_KEY)
        if cached is not None:
            if isinstance(cached, bytes):
                return cached.decode()
            return str(cached)

        url = (
            f"{_WEWORK_API_BASE}/gettoken"
            f"?corpid={self.corp_id}"
            f"&corpsecret={self.corp_secret}"
        )
        resp = await self.http_client.get(url)
        data: dict[str, Any] = resp.json()

        if data.get("errcode", -1) != 0:
            raise DistributorError(f"WeWork token error: {data.get('errmsg', '')}")

        token: str = data["access_token"]
        expires_in: int = data.get("expires_in", 7200)

        await self.redis.set(TOKEN_CACHE_KEY, token)
        await self.redis.expire(TOKEN_CACHE_KEY, expires_in - TOKEN_EXPIRE_BUFFER)
        return token

    # ------------------------------------------------------------------
    # Message senders
    # ------------------------------------------------------------------

    async def _send_message(
        self,
        user_id: str,
        msg_type: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Low-level helper: send a message of *msg_type*."""
        token = await self.get_access_token()
        url = f"{_WEWORK_API_BASE}/message/send?access_token={token}"
        payload: dict[str, Any] = {
            "touser": user_id,
            "msgtype": msg_type,
            "agentid": self.agent_id,
            **body,
        }
        resp = await self.http_client.post(url, json=payload)
        return dict(resp.json())

    async def send_text_message(
        self,
        user_id: str,
        text: str,
    ) -> dict[str, Any]:
        """Send a text message to *user_id*."""
        return await self._send_message(
            user_id,
            "text",
            {"text": {"content": text}},
        )

    async def send_markdown_message(
        self,
        user_id: str,
        markdown: str,
    ) -> dict[str, Any]:
        """Send a markdown message to *user_id*."""
        return await self._send_message(
            user_id,
            "markdown",
            {"markdown": {"content": markdown}},
        )

    async def send_news_card(
        self,
        user_id: str,
        articles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Send a news card message to *user_id*."""
        return await self._send_message(
            user_id,
            "news",
            {"news": {"articles": articles}},
        )

    # ------------------------------------------------------------------
    # Result / formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_result(
        status: str,
        content: Any,
        subscription: Any,
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Build a standardised push-result dict."""
        result: dict[str, Any] = {
            "status": status,
            "channel": "wework",
            "content_id": content.id,
            "subscription_id": subscription.id,
            "pushed_at": _now_iso(),
        }
        if error is not None:
            result["error"] = error
        return result

    def format_content(self, content: Any, *, msg_type: str = "text") -> Any:
        """Format *content* for the given *msg_type*."""
        if msg_type == "markdown":
            return f"# {content.title}\n\n{content.summary}\n\n{content.body}"
        if msg_type == "news":
            return [
                {
                    "title": content.title,
                    "description": content.summary,
                    "url": content.url,
                }
            ]
        # default: text
        return f"{content.title}\n{content.summary}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
