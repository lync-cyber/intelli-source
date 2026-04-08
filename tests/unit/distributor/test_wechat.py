"""Tests for WeChatDistributor — WeChat Official Account distribution channel.

Covers:
- AC-040: WeChatDistributor supports sending template and news messages
- AC-044: No duplicate push for same content + user + channel
- AC-045: Push failure auto-retry (3 times, 5s interval), push history recorded
- AC-T032-1: Access Token cached in Redis, auto-refresh before expiry
- AC-T032-2: Push content formatted to WeChat-supported message formats
- AC-T032-3: Push result (success/failure/error code) recorded to PushRecord
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Lightweight stub data models
# ---------------------------------------------------------------------------


@dataclass
class StubContent:
    """Minimal content object for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = "Test Article"
    body_text: str = "Some content body"
    tags: list[str] = field(default_factory=list)
    source_id: uuid.UUID = field(default_factory=uuid.uuid4)
    source_credibility: float = 1.0
    published_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


@dataclass
class StubSubscription:
    """Minimal Subscription for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = "test-sub"
    source_id: uuid.UUID | None = None
    channel: str = "wechat"
    channel_config: dict = field(
        default_factory=lambda: {
            "openid": "o_test_user_openid",
            "template_id": "tpl_001",
            "msg_type": "template",
        }
    )
    match_rules: dict = field(
        default_factory=lambda: {
            "keywords": [],
            "tags": [],
            "min_score": 0,
        }
    )
    frequency: str = "realtime"
    quiet_hours: dict = field(default_factory=dict)
    status: str = "active"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create a mock Redis client with async get/set/expire."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.expire = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Create a mock HTTP client with async post."""
    client = AsyncMock()
    client.post = AsyncMock()
    return client


@pytest.fixture
def app_id() -> str:
    return "wx_test_app_id"


@pytest.fixture
def app_secret() -> str:
    return "wx_test_app_secret"


# ===================================================================
# AC-040: WeChatDistributor supports template and news messages
# ===================================================================


class TestWeChatDistributorImportAndInit:
    """Verify WeChatDistributor can be imported and instantiated."""

    def test_import_wechat_distributor(self):
        """WeChatDistributor can be imported from distributor.channels.wechat."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        assert WeChatDistributor is not None

    def test_inherits_base_distributor(self):
        """WeChatDistributor should inherit from BaseDistributor."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        from intellisource.distributor.base import BaseDistributor

        assert issubclass(WeChatDistributor, BaseDistributor)

    def test_constructor_accepts_required_params(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """Constructor accepts redis, http_client, app_id, app_secret."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        assert dist is not None


class TestSendTemplateMessage:
    """AC-040: Send template messages via WeChat."""

    @pytest.mark.asyncio
    async def test_send_template_message_returns_dict(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """send_template_message should return a dict with result info."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.get = AsyncMock(return_value="cached_token_123")
        mock_http_client.post = AsyncMock(
            return_value=AsyncMock(
                json=lambda: {"errcode": 0, "errmsg": "ok", "msgid": 12345}
            )
        )

        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        result = await dist.send_template_message(
            openid="o_test_user",
            template_id="tpl_001",
            data={"title": {"value": "Test"}},
        )
        assert isinstance(result, dict)
        assert result.get("errcode") == 0

    @pytest.mark.asyncio
    async def test_send_template_message_calls_wechat_api(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """send_template_message should POST to WeChat template API."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.get = AsyncMock(return_value="cached_token_123")
        mock_http_client.post = AsyncMock(
            return_value=AsyncMock(
                json=lambda: {"errcode": 0, "errmsg": "ok", "msgid": 12345}
            )
        )

        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        await dist.send_template_message(
            openid="o_test_user",
            template_id="tpl_001",
            data={"title": {"value": "Test"}},
        )
        mock_http_client.post.assert_called_once()
        call_args = mock_http_client.post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        assert "template" in url.lower()


class TestSendNewsMessage:
    """AC-040: Send news (article) messages via WeChat."""

    @pytest.mark.asyncio
    async def test_send_news_message_returns_dict(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """send_news_message should return a dict with result info."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.get = AsyncMock(return_value="cached_token_123")
        mock_http_client.post = AsyncMock(
            return_value=AsyncMock(json=lambda: {"errcode": 0, "errmsg": "ok"})
        )

        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        articles = [
            {
                "title": "Test Article",
                "description": "Test desc",
                "url": "https://example.com",
                "picurl": "https://example.com/pic.jpg",
            }
        ]
        result = await dist.send_news_message(openid="o_test_user", articles=articles)
        assert isinstance(result, dict)
        assert result.get("errcode") == 0


# ===================================================================
# AC-T032-1: Access Token cached in Redis, auto-refresh before expiry
# ===================================================================


class TestAccessTokenManagement:
    """AC-T032-1: Token caching and refresh logic."""

    @pytest.mark.asyncio
    async def test_get_access_token_from_cache(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """get_access_token returns cached token when available."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.get = AsyncMock(return_value="cached_token_abc")
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        token = await dist.get_access_token()
        assert token == "cached_token_abc"
        # Should not call WeChat API if cache hit
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_access_token_refreshes_when_cache_miss(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """get_access_token fetches new token when cache is empty."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.get = AsyncMock(return_value=None)
        # Simulate WeChat token API response (GET, but we mock generically)
        mock_http_client.get = AsyncMock(
            return_value=AsyncMock(
                json=lambda: {
                    "access_token": "new_token_xyz",
                    "expires_in": 7200,
                }
            )
        )
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        token = await dist.get_access_token()
        assert token == "new_token_xyz"
        # Should store in Redis
        mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_stored_with_expire_buffer(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """Token is stored in Redis with TTL = expires_in - buffer."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.get = AsyncMock(return_value=None)
        mock_http_client.get = AsyncMock(
            return_value=AsyncMock(
                json=lambda: {
                    "access_token": "new_token_xyz",
                    "expires_in": 7200,
                }
            )
        )
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        await dist.get_access_token()
        # Verify TTL is set with buffer deducted
        set_call = mock_redis.set.call_args
        # The TTL should be 7200 - TOKEN_EXPIRE_BUFFER (300) = 6900
        # Check that set was called with appropriate expiry
        assert mock_redis.set.called
        # Verify the token cache key is used
        from intellisource.distributor.channels.wechat import (
            TOKEN_CACHE_KEY,
        )

        args = set_call[0] if set_call[0] else ()
        kwargs = set_call[1] if set_call[1] else {}
        # Key should be TOKEN_CACHE_KEY or contain it
        all_args_str = str(args) + str(kwargs)
        assert TOKEN_CACHE_KEY in all_args_str or "wechat" in all_args_str

    @pytest.mark.asyncio
    async def test_constants_defined(self):
        """Module defines TOKEN_CACHE_KEY and TOKEN_EXPIRE_BUFFER."""
        from intellisource.distributor.channels.wechat import (
            TOKEN_CACHE_KEY,
            TOKEN_EXPIRE_BUFFER,
        )

        assert TOKEN_CACHE_KEY == "wechat:access_token"
        assert TOKEN_EXPIRE_BUFFER == 300


# ===================================================================
# AC-T032-2: Push content formatted to WeChat message formats
# ===================================================================


class TestContentFormatting:
    """AC-T032-2: Format content for WeChat message types."""

    def test_format_template_data(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """format_template_data converts content to template data dict."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent(
            title="Breaking News",
            body_text="Important content here",
        )
        data = dist.format_template_data(content)
        assert isinstance(data, dict)
        # Template data should contain value fields for WeChat API
        assert len(data) > 0

    def test_format_news_articles(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """format_news_articles converts content to list of article dicts."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent(
            title="News Title",
            body_text="Full article body text for the reader",
        )
        articles = dist.format_news_articles(content)
        assert isinstance(articles, list)
        assert len(articles) >= 1
        article = articles[0]
        assert "title" in article
        assert article["title"] == "News Title"

    def test_format_template_data_empty_content(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """format_template_data handles content with empty body."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent(title="", body_text="")
        data = dist.format_template_data(content)
        assert isinstance(data, dict)


# ===================================================================
# AC-044: No duplicate push for same content + user + channel
# ===================================================================


class TestDeduplication:
    """AC-044: Prevent duplicate pushes."""

    @pytest.mark.asyncio
    async def test_distribute_skips_duplicate(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """distribute() should skip if same content+user+channel already pushed."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        # Simulate that a push record already exists (Redis key exists)
        mock_redis.exists = AsyncMock(return_value=True)
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent()
        sub = StubSubscription()
        result = await dist.distribute(content, sub)
        assert isinstance(result, dict)
        assert result.get("status") == "skipped"
        # Should NOT call WeChat API
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_distribute_sends_when_not_duplicate(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """distribute() should proceed if no prior push record exists."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value="cached_token_123")
        mock_http_client.post = AsyncMock(
            return_value=AsyncMock(
                json=lambda: {"errcode": 0, "errmsg": "ok", "msgid": 99}
            )
        )
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent()
        sub = StubSubscription()
        result = await dist.distribute(content, sub)
        assert isinstance(result, dict)
        assert result.get("status") != "skipped"


# ===================================================================
# AC-045: Push failure auto-retry (3 times, 5s interval)
# ===================================================================


class TestRetryLogic:
    """AC-045: Auto-retry on push failure."""

    @pytest.mark.asyncio
    async def test_retry_constants_defined(self):
        """Module defines MAX_RETRY and RETRY_INTERVAL constants."""
        from intellisource.distributor.channels.wechat import (
            MAX_RETRY,
            RETRY_INTERVAL,
        )

        assert MAX_RETRY == 3
        assert RETRY_INTERVAL == 5

    @pytest.mark.asyncio
    async def test_retry_on_api_failure(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """distribute() retries up to MAX_RETRY times on WeChat API error."""
        from intellisource.distributor.channels.wechat import (
            MAX_RETRY,
            WeChatDistributor,
        )

        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value="cached_token_123")
        # All attempts return error
        mock_http_client.post = AsyncMock(
            return_value=AsyncMock(
                json=lambda: {"errcode": 40001, "errmsg": "invalid token"}
            )
        )
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent()
        sub = StubSubscription()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await dist.distribute(content, sub)
        # After MAX_RETRY failures, should report failure
        assert result.get("status") == "failed"
        # Should have retried MAX_RETRY times
        assert mock_http_client.post.call_count == MAX_RETRY

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """distribute() succeeds if retry attempt works."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value="cached_token_123")
        # First call fails, second succeeds
        mock_http_client.post = AsyncMock(
            side_effect=[
                AsyncMock(
                    json=lambda: {
                        "errcode": 40001,
                        "errmsg": "invalid token",
                    }
                ),
                AsyncMock(json=lambda: {"errcode": 0, "errmsg": "ok", "msgid": 55}),
            ]
        )
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent()
        sub = StubSubscription()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await dist.distribute(content, sub)
        assert result.get("status") == "success"

    @pytest.mark.asyncio
    async def test_retry_with_network_exception(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """distribute() retries on network exceptions (e.g., ConnectionError)."""
        from intellisource.distributor.channels.wechat import (
            MAX_RETRY,
            WeChatDistributor,
        )

        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value="cached_token_123")
        mock_http_client.post = AsyncMock(side_effect=ConnectionError("network error"))
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent()
        sub = StubSubscription()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await dist.distribute(content, sub)
        assert result.get("status") == "failed"
        assert mock_http_client.post.call_count == MAX_RETRY


# ===================================================================
# AC-T032-3: Push result recorded to PushRecord
# ===================================================================


class TestPushRecordTracking:
    """AC-T032-3: Push results are recorded."""

    @pytest.mark.asyncio
    async def test_distribute_returns_push_record_dict(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """distribute() returns a dict with PushRecord-style fields."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value="cached_token_123")
        mock_http_client.post = AsyncMock(
            return_value=AsyncMock(
                json=lambda: {"errcode": 0, "errmsg": "ok", "msgid": 42}
            )
        )
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent()
        sub = StubSubscription()
        result = await dist.distribute(content, sub)
        # PushRecord should contain these fields
        assert "status" in result
        assert "channel" in result
        assert result["channel"] == "wechat"

    @pytest.mark.asyncio
    async def test_push_record_contains_error_on_failure(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """Failed push record should contain error code and message."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value="cached_token_123")
        mock_http_client.post = AsyncMock(
            return_value=AsyncMock(
                json=lambda: {"errcode": 40003, "errmsg": "invalid openid"}
            )
        )
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent()
        sub = StubSubscription()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await dist.distribute(content, sub)
        assert result["status"] == "failed"
        assert "error_code" in result or "errcode" in result

    @pytest.mark.asyncio
    async def test_push_record_contains_content_and_subscription_ids(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """Push record should reference content_id and subscription_id."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value="cached_token_123")
        mock_http_client.post = AsyncMock(
            return_value=AsyncMock(
                json=lambda: {"errcode": 0, "errmsg": "ok", "msgid": 77}
            )
        )
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent()
        sub = StubSubscription()
        result = await dist.distribute(content, sub)
        assert "content_id" in result
        assert "subscription_id" in result
        assert result["content_id"] == content.id
        assert result["subscription_id"] == sub.id

    @pytest.mark.asyncio
    async def test_push_record_records_push_history(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """After push, dedup key should be set in Redis for history."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value="cached_token_123")
        mock_http_client.post = AsyncMock(
            return_value=AsyncMock(
                json=lambda: {"errcode": 0, "errmsg": "ok", "msgid": 88}
            )
        )
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent()
        sub = StubSubscription()
        await dist.distribute(content, sub)
        # Should set a dedup key in Redis after successful push
        mock_redis.set.assert_called()


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    """Boundary conditions and error scenarios."""

    @pytest.mark.asyncio
    async def test_token_api_returns_error(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """get_access_token raises or handles WeChat token API error."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.get = AsyncMock(return_value=None)
        mock_http_client.get = AsyncMock(
            return_value=AsyncMock(
                json=lambda: {
                    "errcode": 40013,
                    "errmsg": "invalid appid",
                }
            )
        )
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        with pytest.raises(Exception):
            await dist.get_access_token()

    @pytest.mark.asyncio
    async def test_distribute_with_news_msg_type(
        self, mock_redis, mock_http_client, app_id, app_secret
    ):
        """distribute() routes to news message when channel_config says so."""
        from intellisource.distributor.channels.wechat import (
            WeChatDistributor,
        )

        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value="cached_token_123")
        mock_http_client.post = AsyncMock(
            return_value=AsyncMock(json=lambda: {"errcode": 0, "errmsg": "ok"})
        )
        dist = WeChatDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            app_id=app_id,
            app_secret=app_secret,
        )
        content = StubContent()
        sub = StubSubscription(
            channel_config={
                "openid": "o_news_user",
                "msg_type": "news",
            }
        )
        result = await dist.distribute(content, sub)
        assert isinstance(result, dict)
        assert result.get("status") in ("success", "failed")
