"""Tests for AC-2 (G-008): token errmsg propagation regression guard.

WeChat and WeWork token errors must surface as real error messages, not
generic "network_error".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@dataclass
class StubContent:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = "Test Article"
    body_text: str = "Test body"
    tags: list[str] = field(default_factory=list)
    source_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class StubSubscriptionWeChat:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    channel: str = "wechat"
    channel_config: dict = field(
        default_factory=lambda: {
            "openid": "o_test_openid",
            "template_id": "tpl_001",
            "msg_type": "template",
        }
    )


@dataclass
class StubSubscriptionWeWork:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    channel: str = "wework"
    channel_config: dict = field(
        default_factory=lambda: {
            "user_id": "user001",
            "msg_type": "markdown",
        }
    )


class TestWeChatTokenErrMsgSurfaces:
    """AC-2 WeChat: token failure errmsg reaches distribute() result."""

    @pytest.mark.asyncio
    async def test_token_error_errmsg_in_result_not_network_error(self) -> None:
        """When token API returns business error (no access_token + errmsg),
        distribute() final error_msg contains true errmsg, not 'network_error'."""
        from intellisource.distributor.channels.wechat import WeChatDistributor

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock(return_value=True)
        redis.expire = AsyncMock(return_value=True)

        # Token endpoint returns error: no access_token, errmsg set
        token_resp = MagicMock()
        token_resp.json.return_value = {
            "errcode": 40001,
            "errmsg": "invalid appsecret",
        }
        http_client = AsyncMock()
        http_client.get = AsyncMock(return_value=token_resp)
        http_client.post = AsyncMock()

        dist = WeChatDistributor(
            redis=redis,
            http_client=http_client,
            app_id="wx_app_id",
            app_secret="bad_secret",
        )
        content = StubContent()
        sub = StubSubscriptionWeChat()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await dist.distribute(content, sub)

        assert result["status"] == "failed"
        error_msg: str = result.get("error_msg", "") or result.get("error", "") or ""
        assert "network_error" not in error_msg, (
            f"error_msg must not be generic 'network_error'; got {error_msg!r}"
        )
        # Must surface the real provider errmsg, not the generic fallback
        assert "WeChat token error" in error_msg or "invalid appsecret" in error_msg, (
            f"error_msg should contain true errmsg from token API; got {error_msg!r}"
        )


class TestWeWorkTokenErrMsgSurfaces:
    """AC-2 WeWork: token failure errmsg reaches distribute() result."""

    @pytest.mark.asyncio
    async def test_gettoken_error_in_result_not_network_error(self) -> None:
        """When WeWork gettoken returns errcode!=0 + errmsg,
        distribute() final error contains the real errmsg, not 'network_error'."""
        from intellisource.distributor.channels.wework import WeWorkDistributor

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock(return_value=True)
        redis.expire = AsyncMock(return_value=True)

        # gettoken returns error: errcode != 0
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {
            "errcode": 40001,
            "errmsg": "invalid corpsecret",
        }
        http_client = AsyncMock()
        http_client.get = AsyncMock(return_value=token_resp)
        http_client.post = AsyncMock()

        dist = WeWorkDistributor(
            redis=redis,
            http_client=http_client,
            corp_id="ww_corp",
            corp_secret="bad_secret",
            agent_id=1000001,
        )
        content = StubContent()
        sub = StubSubscriptionWeWork()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await dist.distribute(content, sub)

        assert result["status"] == "failed"
        error_field: str = (
            result.get("error_msg", "")
            or result.get("error", "")
            or result.get("reason", "")
            or ""
        )
        assert "network_error" not in error_field, (
            f"error field must not be generic 'network_error'; got {error_field!r}"
        )
        # Must contain real errmsg trace
        assert (
            "WeWork token error" in error_field or "invalid corpsecret" in error_field
        ), f"error field should contain real token errmsg; got {error_field!r}"
