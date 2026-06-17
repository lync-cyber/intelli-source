"""Unit tests for WeWorkCustomerServiceClient (AC-10).

AC-10: WeWork CS client mirrors WeChatCustomerServiceClient structure:
       - from_env raises ValueError on missing IS_WEWORK_CORP_ID / IS_WEWORK_CORP_SECRET
       - access_token fetched from cgi-bin/gettoken, cached in Redis
       - send_text calls cgi-bin/message/send with openid + content
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# AC-10: from_env — credential validation
# ---------------------------------------------------------------------------


class TestWeWorkCsClientFromEnv:
    """AC-10: from_env raises ValueError when corp credentials are missing."""

    def test_from_env_raises_when_corp_id_missing(self) -> None:
        """from_env raises ValueError when IS_WEWORK_CORP_ID is not set."""
        from intellisource.distributor.wework_cs_client import (
            WeWorkCustomerServiceClient,
        )

        env_without_corp_id = {
            k: v
            for k, v in os.environ.items()
            if k not in ("IS_WEWORK_CORP_ID", "IS_WEWORK_CORP_SECRET")
        }
        env_without_corp_id["IS_WEWORK_CORP_SECRET"] = "test_corp_secret"

        mock_redis = MagicMock()
        with patch.dict(os.environ, env_without_corp_id, clear=True):
            with pytest.raises(ValueError, match="IS_WEWORK_CORP_ID"):
                WeWorkCustomerServiceClient.from_env(
                    redis_client=mock_redis, http_client=MagicMock()
                )

    def test_from_env_raises_when_corp_secret_missing(self) -> None:
        """from_env raises ValueError when IS_WEWORK_CORP_SECRET is not set."""
        from intellisource.distributor.wework_cs_client import (
            WeWorkCustomerServiceClient,
        )

        env_without_secret = {
            k: v
            for k, v in os.environ.items()
            if k not in ("IS_WEWORK_CORP_ID", "IS_WEWORK_CORP_SECRET")
        }
        env_without_secret["IS_WEWORK_CORP_ID"] = "test_corp_id"

        mock_redis = MagicMock()
        with patch.dict(os.environ, env_without_secret, clear=True):
            with pytest.raises(ValueError, match="IS_WEWORK_CORP_SECRET"):
                WeWorkCustomerServiceClient.from_env(
                    redis_client=mock_redis, http_client=MagicMock()
                )

    def test_from_env_raises_when_agent_id_missing(self) -> None:
        """from_env raises ValueError when IS_WEWORK_AGENT_ID is not set."""
        from intellisource.distributor.wework_cs_client import (
            WeWorkCustomerServiceClient,
        )

        env_without_agent_id = {
            k: v
            for k, v in os.environ.items()
            if k
            not in (
                "IS_WEWORK_CORP_ID",
                "IS_WEWORK_CORP_SECRET",
                "IS_WEWORK_AGENT_ID",
            )
        }
        env_without_agent_id["IS_WEWORK_CORP_ID"] = "test_corp_id"
        env_without_agent_id["IS_WEWORK_CORP_SECRET"] = "test_corp_secret"

        mock_redis = MagicMock()
        with patch.dict(os.environ, env_without_agent_id, clear=True):
            with pytest.raises(ValueError, match="IS_WEWORK_AGENT_ID"):
                WeWorkCustomerServiceClient.from_env(
                    redis_client=mock_redis, http_client=MagicMock()
                )

    def test_from_env_returns_instance_when_credentials_present(self) -> None:
        """from_env returns WeWorkCustomerServiceClient when env vars are set."""
        from intellisource.distributor.wework_cs_client import (
            WeWorkCustomerServiceClient,
        )

        mock_redis = MagicMock()
        with patch.dict(
            os.environ,
            {
                "IS_WEWORK_CORP_ID": "ww_test_corp_id",
                "IS_WEWORK_CORP_SECRET": "ww_test_secret",
                "IS_WEWORK_AGENT_ID": "1000002",
            },
        ):
            client = WeWorkCustomerServiceClient.from_env(
                redis_client=mock_redis, http_client=MagicMock()
            )

        assert isinstance(client, WeWorkCustomerServiceClient), (
            "from_env must return WeWorkCustomerServiceClient instance"
        )


# ---------------------------------------------------------------------------
# AC-10: access_token Redis cache behaviour
# ---------------------------------------------------------------------------


class TestWeWorkCsClientAccessToken:
    """AC-10: Access token cache mirrors WeChatCustomerServiceClient behaviour."""

    async def test_first_call_fetches_from_gettoken_and_caches(self) -> None:
        """First get_access_token call hits cgi-bin/gettoken and writes Redis."""
        from intellisource.distributor.wework_cs_client import (
            WeWorkCustomerServiceClient,
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = {
            "errcode": 0,
            "errmsg": "ok",
            "access_token": "wework_fetched_token",
            "expires_in": 7200,
        }
        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_http_response)

        client = WeWorkCustomerServiceClient(
            corp_id="ww_corp_id",
            corp_secret="ww_secret",
            agent_id=1000002,
            redis_client=mock_redis,
            http_client=mock_http_client,
        )

        token = await client.get_access_token()

        assert token == "wework_fetched_token", f"Expected fetched token, got: {token}"
        mock_http_client.get.assert_awaited_once()
        http_call_str = str(mock_http_client.get.call_args)
        assert "gettoken" in http_call_str, (
            f"Expected cgi-bin/gettoken in HTTP GET URL, got: {http_call_str}"
        )
        mock_redis.set.assert_awaited_once(), "Redis must cache the fetched token"

    async def test_second_call_serves_from_redis_cache(self) -> None:
        """Second call returns cached value without hitting the WeWork API."""
        from intellisource.distributor.wework_cs_client import (
            WeWorkCustomerServiceClient,
        )

        cached_token = "wework_cached_token_xyz"
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=cached_token)

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock()  # must not be called

        client = WeWorkCustomerServiceClient(
            corp_id="ww_corp_id",
            corp_secret="ww_secret",
            agent_id=1000002,
            redis_client=mock_redis,
            http_client=mock_http_client,
        )

        token = await client.get_access_token()

        assert token == cached_token, f"Expected '{cached_token}', got: {token}"
        (
            mock_http_client.get.assert_not_awaited(),
            ("HTTP must NOT be called when token is in Redis cache"),
        )


# ---------------------------------------------------------------------------
# AC-10: send_text — WeWork message/send endpoint
# ---------------------------------------------------------------------------


class TestWeWorkCsClientSendText:
    """AC-10: send_text calls cgi-bin/message/send with correct payload."""

    async def test_send_text_calls_message_send_endpoint(self) -> None:
        """send_text calls POST cgi-bin/message/send."""
        from intellisource.distributor.wework_cs_client import (
            WeWorkCustomerServiceClient,
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="wework_send_token")

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)

        client = WeWorkCustomerServiceClient(
            corp_id="ww_corp_id",
            corp_secret="ww_secret",
            agent_id=1000002,
            redis_client=mock_redis,
            http_client=mock_http_client,
        )

        await client.send_text(openid="ww_user_openid", content="企微客服回复内容")

        mock_http_client.post.assert_awaited_once()
        post_call_str = str(mock_http_client.post.call_args)
        assert "message/send" in post_call_str, (
            f"Expected cgi-bin/message/send in POST URL, got: {post_call_str}"
        )

    async def test_send_text_includes_openid_and_content(self) -> None:
        """send_text payload contains openid (touser) and content (text)."""
        from intellisource.distributor.wework_cs_client import (
            WeWorkCustomerServiceClient,
        )

        target_openid = "ww_target_user"
        target_content = "企微测试消息"

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="wework_token_abc")

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)

        client = WeWorkCustomerServiceClient(
            corp_id="ww_corp_id",
            corp_secret="ww_secret",
            agent_id=1000002,
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

    async def test_send_text_payload_contains_agentid(self) -> None:
        """WeWork message/send payload must include agentid (required by API).

        Without agentid the WeWork API returns errcode=40056 invalid agentid.
        """
        from intellisource.distributor.wework_cs_client import (
            WeWorkCustomerServiceClient,
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="wework_token_xyz")

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)

        client = WeWorkCustomerServiceClient(
            corp_id="ww_corp_id",
            corp_secret="ww_secret",
            agent_id=1000007,
            redis_client=mock_redis,
            http_client=mock_http_client,
        )

        await client.send_text(openid="u", content="hi")

        payload = (
            mock_http_client.post.call_args.kwargs.get("json")
            or mock_http_client.post.call_args.args[1]
        )
        assert payload.get("agentid") == 1000007, (
            f"Expected agentid=1000007 in send payload, got: {payload}"
        )


class TestWeWorkCsClientErrcodeHandling:
    """get_access_token + send_text raise DistributorError on errcode != 0."""

    async def test_get_access_token_raises_on_errcode_response(self) -> None:
        """Token fetch returning errcode=40013 must raise DistributorError."""
        from intellisource.core.errors import DistributorError
        from intellisource.distributor.wework_cs_client import (
            WeWorkCustomerServiceClient,
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = {
            "errcode": 40013,
            "errmsg": "invalid corpid",
        }
        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_http_response)

        client = WeWorkCustomerServiceClient(
            corp_id="bad_corp",
            corp_secret="bad",
            agent_id=1,
            redis_client=mock_redis,
            http_client=mock_http_client,
        )

        with pytest.raises(DistributorError, match="40013"):
            await client.get_access_token()

    async def test_send_text_raises_on_errcode_response(self) -> None:
        """send_text receiving errcode=40056 must raise DistributorError."""
        from intellisource.core.errors import DistributorError
        from intellisource.distributor.wework_cs_client import (
            WeWorkCustomerServiceClient,
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="tok")

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = {
            "errcode": 40056,
            "errmsg": "invalid agentid",
        }
        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)

        client = WeWorkCustomerServiceClient(
            corp_id="ww",
            corp_secret="ww",
            agent_id=99,
            redis_client=mock_redis,
            http_client=mock_http_client,
        )

        with pytest.raises(DistributorError, match="40056"):
            await client.send_text(openid="u", content="c")
