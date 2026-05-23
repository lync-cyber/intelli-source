"""WeChat Customer Service client for real-time CS messaging (AC-7/8)."""

from __future__ import annotations

import os
from typing import Any

from intellisource.distributor.base_cs_client import BaseCustomerServiceClient


class WeChatCustomerServiceClient(BaseCustomerServiceClient):
    """Send customer-service messages via the WeChat cgi-bin API."""

    api_base = "https://api.weixin.qq.com"
    token_path = "/cgi-bin/token"
    send_path = "/cgi-bin/message/custom/send"
    token_cache_key = "wechat:access_token"

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        redis_client: Any,
        http_client: Any,
    ) -> None:
        super().__init__(redis_client=redis_client, http_client=http_client)
        self._app_id = app_id
        self._app_secret = app_secret

    @classmethod
    def from_env(
        cls, redis_client: Any, http_client: Any
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

    def _build_token_query(self) -> str:
        return (
            f"grant_type=client_credential"
            f"&appid={self._app_id}"
            f"&secret={self._app_secret}"
        )

    def _build_send_payload(self, openid: str, content: str) -> dict[str, Any]:
        return {
            "touser": openid,
            "msgtype": "text",
            "text": {"content": content},
        }
