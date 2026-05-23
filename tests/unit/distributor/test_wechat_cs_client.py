"""Unit tests for WeChatCustomerServiceClient (AC-7/8).

AC-7: from_env raises ValueError when IS_WECHAT_APP_ID or IS_WECHAT_APP_SECRET absent;
      returns WeChatCustomerServiceClient instance when both present.
AC-8: access_token Redis cache — first call fetches from API and writes SETEX;
      second call hits Redis cache and skips HTTP.
      send_text calls cgi-bin/message/custom/send with correct openid + content.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# AC-7: from_env hard-fail on missing env vars
# ---------------------------------------------------------------------------


class TestWeChatCsClientFromEnv:
    """AC-7: from_env raises ValueError when credentials are missing."""

    def test_from_env_raises_when_app_id_missing(self) -> None:
        """from_env raises ValueError when IS_WECHAT_APP_ID is not set."""
        from intellisource.distributor.wechat_cs_client import (
            WeChatCustomerServiceClient,
        )

        env_without_app_id = {
            k: v
            for k, v in os.environ.items()
            if k not in ("IS_WECHAT_APP_ID", "IS_WECHAT_APP_SECRET")
        }
        env_without_app_id["IS_WECHAT_APP_SECRET"] = "test_secret"
        # IS_WECHAT_APP_ID intentionally absent

        mock_redis = MagicMock()
        with patch.dict(os.environ, env_without_app_id, clear=True):
            with pytest.raises(ValueError, match="IS_WECHAT_APP_ID"):
                WeChatCustomerServiceClient.from_env(redis_client=mock_redis)

    def test_from_env_raises_when_app_secret_missing(self) -> None:
        """from_env raises ValueError when IS_WECHAT_APP_SECRET is not set."""
        from intellisource.distributor.wechat_cs_client import (
            WeChatCustomerServiceClient,
        )

        env_without_secret = {
            k: v
            for k, v in os.environ.items()
            if k not in ("IS_WECHAT_APP_ID", "IS_WECHAT_APP_SECRET")
        }
        env_without_secret["IS_WECHAT_APP_ID"] = "test_app_id"
        # IS_WECHAT_APP_SECRET intentionally absent

        mock_redis = MagicMock()
        with patch.dict(os.environ, env_without_secret, clear=True):
            with pytest.raises(ValueError, match="IS_WECHAT_APP_SECRET"):
                WeChatCustomerServiceClient.from_env(redis_client=mock_redis)

    def test_from_env_returns_instance_when_both_present(self) -> None:
        """from_env returns WeChatCustomerServiceClient when both env vars are set."""
        from intellisource.distributor.wechat_cs_client import (
            WeChatCustomerServiceClient,
        )

        mock_redis = MagicMock()
        with patch.dict(
            os.environ,
            {
                "IS_WECHAT_APP_ID": "wx_test_app_id",
                "IS_WECHAT_APP_SECRET": "wx_test_secret",
            },
        ):
            client = WeChatCustomerServiceClient.from_env(redis_client=mock_redis)

        assert isinstance(client, WeChatCustomerServiceClient), (
            "from_env must return WeChatCustomerServiceClient instance"
        )


# ---------------------------------------------------------------------------
# AC-8: access_token Redis cache behaviour
# ---------------------------------------------------------------------------


class TestWeChatCsClientAccessToken:
    """AC-8: Access token fetched from API on miss; served from cache on hit."""

    async def test_first_call_fetches_token_and_writes_redis(self) -> None:
        """First get_access_token call hits cgi-bin/token and writes Redis SETEX."""
        from intellisource.distributor.wechat_cs_client import (
            WeChatCustomerServiceClient,
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # cache miss
        mock_redis.set = AsyncMock(return_value=True)

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = {
            "access_token": "fetched_token_abc",
            "expires_in": 7200,
        }
        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_http_response)

        client = WeChatCustomerServiceClient(
            app_id="wx_app_id",
            app_secret="wx_secret",
            redis_client=mock_redis,
            http_client=mock_http_client,
        )

        token = await client.get_access_token()

        assert token == "fetched_token_abc", f"Expected fetched token, got: {token}"
        mock_http_client.get.assert_awaited_once()
        http_call_url = str(mock_http_client.get.call_args)
        assert "cgi-bin/token" in http_call_url, (
            f"Expected cgi-bin/token in HTTP call URL, got: {http_call_url}"
        )
        # Redis write must use TTL ≈ 7000s (7200 - 200 buffer tolerance)
        mock_redis.set.assert_awaited_once()
        set_call_args = mock_redis.set.call_args
        set_args_str = str(set_call_args)
        assert (
            "wechat:access_token" in set_args_str or "fetched_token_abc" in set_args_str
        ), f"Redis set called with unexpected args: {set_args_str}"

    async def test_second_call_uses_redis_cache_no_http(self) -> None:
        """Second get_access_token call returns cached value without HTTP request."""
        from intellisource.distributor.wechat_cs_client import (
            WeChatCustomerServiceClient,
        )

        cached_token = "cached_token_xyz"
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=cached_token)

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock()  # must not be called

        client = WeChatCustomerServiceClient(
            app_id="wx_app_id",
            app_secret="wx_secret",
            redis_client=mock_redis,
            http_client=mock_http_client,
        )

        token = await client.get_access_token()

        assert token == cached_token, (
            f"Expected cached token '{cached_token}', got: {token}"
        )
        (
            mock_http_client.get.assert_not_awaited(),
            ("HTTP must NOT be called when token is in Redis cache"),
        )

    async def test_redis_set_uses_ttl_near_7000s(self) -> None:
        """Redis TTL for cached token is approximately 7000s (7200 - buffer)."""
        from intellisource.distributor.wechat_cs_client import (
            WeChatCustomerServiceClient,
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = {
            "access_token": "ttl_test_token",
            "expires_in": 7200,
        }
        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_http_response)

        client = WeChatCustomerServiceClient(
            app_id="wx_app_id",
            app_secret="wx_secret",
            redis_client=mock_redis,
            http_client=mock_http_client,
        )

        await client.get_access_token()

        set_call = mock_redis.set.call_args
        # Extract TTL — may be ex= kwarg or positional
        set_str = str(set_call)
        # TTL should be between 6800 and 7200 (approximately 7000)
        import re

        ttl_matches = re.findall(r"\b(6[8-9]\d\d|7[0-2]\d\d)\b", set_str)
        assert ttl_matches, f"Expected TTL ≈ 7000s in Redis set call, got: {set_str}"


# ---------------------------------------------------------------------------
# AC-8: send_text calls correct endpoint
# ---------------------------------------------------------------------------


class TestWeChatCsClientSendText:
    """AC-8: send_text calls cgi-bin/message/custom/send with openid + content."""

    async def test_send_text_posts_to_custom_send_endpoint(self) -> None:
        """send_text calls POST cgi-bin/message/custom/send."""
        from intellisource.distributor.wechat_cs_client import (
            WeChatCustomerServiceClient,
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="send_test_token")

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)

        client = WeChatCustomerServiceClient(
            app_id="wx_app_id",
            app_secret="wx_secret",
            redis_client=mock_redis,
            http_client=mock_http_client,
        )

        await client.send_text(openid="o_test_openid", content="你好，以下是 RAG 综述…")

        mock_http_client.post.assert_awaited_once()
        post_call_str = str(mock_http_client.post.call_args)
        assert "message/custom/send" in post_call_str, (
            f"Expected cgi-bin/message/custom/send in POST URL, got: {post_call_str}"
        )

    async def test_send_text_includes_openid_in_payload(self) -> None:
        """send_text payload contains the target openid."""
        from intellisource.distributor.wechat_cs_client import (
            WeChatCustomerServiceClient,
        )

        target_openid = "o_target_user_openid"
        target_content = "测试消息内容"

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="send_token_abc")

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)

        client = WeChatCustomerServiceClient(
            app_id="wx_app_id",
            app_secret="wx_secret",
            redis_client=mock_redis,
            http_client=mock_http_client,
        )

        await client.send_text(openid=target_openid, content=target_content)

        post_call_str = str(mock_http_client.post.call_args)
        assert target_openid in post_call_str, (
            f"openid '{target_openid}' missing from POST payload: {post_call_str}"
        )
        assert target_content in post_call_str, (
            f"content '{target_content}' missing from POST payload: {post_call_str}"
        )
