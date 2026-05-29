"""WeWork Customer Service client for real-time CS messaging (AC-10)."""

from __future__ import annotations

from typing import Any

from intellisource.core.settings import get_settings
from intellisource.distributor.base_cs_client import BaseCustomerServiceClient


class WeWorkCustomerServiceClient(BaseCustomerServiceClient):
    """Send customer-service messages via the WeWork cgi-bin API."""

    api_base = "https://qyapi.weixin.qq.com"
    token_path = "/cgi-bin/gettoken"
    send_path = "/cgi-bin/message/send"
    token_cache_key = "wework:access_token"

    def __init__(
        self,
        corp_id: str,
        corp_secret: str,
        agent_id: int,
        redis_client: Any,
        http_client: Any,
    ) -> None:
        super().__init__(redis_client=redis_client, http_client=http_client)
        self._corp_id = corp_id
        self._corp_secret = corp_secret
        self._agent_id = agent_id

    @classmethod
    def from_env(
        cls, redis_client: Any, http_client: Any
    ) -> "WeWorkCustomerServiceClient":
        """Create instance from IS_WEWORK_* env vars (corp id / secret / agent id).

        Raises ValueError when any of IS_WEWORK_CORP_ID,
        IS_WEWORK_CORP_SECRET, IS_WEWORK_AGENT_ID is absent.
        """
        settings = get_settings()
        corp_id = settings.wework_corp_id
        corp_secret = settings.wework_corp_secret
        agent_id_str = settings.wework_agent_id
        if not corp_id:
            raise ValueError(
                "IS_WEWORK_CORP_ID missing — required for WeWorkCustomerServiceClient"
            )
        if not corp_secret:
            raise ValueError(
                "IS_WEWORK_CORP_SECRET missing"
                " — required for WeWorkCustomerServiceClient"
            )
        if not agent_id_str:
            raise ValueError(
                "IS_WEWORK_AGENT_ID missing — required for WeWorkCustomerServiceClient"
            )
        return cls(
            corp_id=corp_id,
            corp_secret=corp_secret,
            agent_id=int(agent_id_str),
            redis_client=redis_client,
            http_client=http_client,
        )

    def _build_token_query(self) -> str:
        return f"corpid={self._corp_id}&corpsecret={self._corp_secret}"

    def _build_send_payload(self, openid: str, content: str) -> dict[str, Any]:
        return {
            "touser": openid,
            "msgtype": "text",
            "agentid": self._agent_id,
            "text": {"content": content},
        }
