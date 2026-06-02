"""Tests for WeWorkDistributor (enterprise WeChat application message push).

Covers:
- AC-041: WeWorkDistributor supports sending app messages via enterprise WeChat
- AC-044: No duplicate push for the same content
- AC-045: Auto-retry on push failure
- AC-T033-1: Access Token caching and refresh
- AC-T033-2: Text/Markdown/News card message formats
- AC-T033-3: Push result tracking
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub data models
# ---------------------------------------------------------------------------


@dataclass
class StubContent:
    """Minimal content object for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = "Test Article"
    summary: str = "A brief summary of the article."
    body_text: str = "Full article body content in markdown."
    source_url: str = "https://example.com/article/1"
    tags: list[str] = field(default_factory=lambda: ["tech", "ai"])


@dataclass
class StubSubscription:
    """Minimal subscription object for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = "wework-sub"
    channel: str = "wework"
    channel_config: dict = field(
        default_factory=lambda: {
            "user_id": "user001",
            "msg_type": "markdown",
        },
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock Redis client with async get/set/expire."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.expire = AsyncMock(return_value=True)
    redis.exists = AsyncMock(return_value=False)
    return redis


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Mock HTTP client that simulates WeWork API responses."""
    client = AsyncMock()
    # Default: successful token response
    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {
        "errcode": 0,
        "errmsg": "ok",
        "access_token": "fake-access-token-12345",
        "expires_in": 7200,
    }
    client.get = AsyncMock(return_value=token_response)

    # Default: successful message send response
    send_response = MagicMock()
    send_response.status_code = 200
    send_response.json.return_value = {
        "errcode": 0,
        "errmsg": "ok",
    }
    client.post = AsyncMock(return_value=send_response)
    return client


@pytest.fixture
def corp_id() -> str:
    return "ww_test_corp_id"


@pytest.fixture
def corp_secret() -> str:
    return "test_corp_secret_key"


@pytest.fixture
def agent_id() -> int:
    return 1000002


@pytest.fixture
def distributor(
    mock_redis: AsyncMock,
    mock_http_client: AsyncMock,
    corp_id: str,
    corp_secret: str,
    agent_id: int,
) -> Any:
    """Create a WeWorkDistributor instance via lazy import."""
    from intellisource.distributor.channels.wework import WeWorkDistributor

    return WeWorkDistributor(
        redis=mock_redis,
        http_client=mock_http_client,
        corp_id=corp_id,
        corp_secret=corp_secret,
        agent_id=agent_id,
    )


# ===========================================================================
# AC-041: WeWorkDistributor supports sending app messages
# ===========================================================================


class TestWeWorkDistributorBasic:
    """AC-041: WeWorkDistributor sends application messages via enterprise WeChat."""

    def test_import_wework_distributor(self) -> None:
        """WeWorkDistributor can be imported from the channels module."""
        from intellisource.distributor.channels.wework import WeWorkDistributor

        assert isinstance(WeWorkDistributor, type)

    def test_inherits_base_distributor(self, distributor: Any) -> None:
        """WeWorkDistributor inherits from BaseDistributor."""
        from intellisource.distributor.base import BaseDistributor

        assert isinstance(distributor, BaseDistributor)

    def test_constructor_stores_config(self, distributor: Any) -> None:
        """Constructor stores corp_id, corp_secret, and agent_id."""
        assert distributor.corp_id == "ww_test_corp_id"
        assert distributor.corp_secret == "test_corp_secret_key"
        assert distributor.agent_id == 1000002

    @pytest.mark.asyncio
    async def test_distribute_returns_push_record_dict(self, distributor: Any) -> None:
        """distribute() returns a dict with push record fields."""
        content = StubContent()
        subscription = StubSubscription()
        result = await distributor.distribute(content, subscription)

        assert isinstance(result, dict)
        assert "status" in result
        assert "channel" in result
        assert result["channel"] == "wework"

    @pytest.mark.asyncio
    async def test_distribute_calls_http_post(
        self, distributor: Any, mock_http_client: AsyncMock
    ) -> None:
        """distribute() makes an HTTP POST to the WeWork message API."""
        content = StubContent()
        subscription = StubSubscription()
        await distributor.distribute(content, subscription)

        mock_http_client.post.assert_called()


# ===========================================================================
# AC-T033-1: Access Token caching and refresh
# ===========================================================================


class TestAccessTokenManagement:
    """AC-T033-1: Access Token caching with Redis and auto-refresh."""

    @pytest.mark.asyncio
    async def test_get_access_token_from_api(
        self, distributor: Any, mock_redis: AsyncMock
    ) -> None:
        """When cache is empty, fetches token from WeWork API."""
        mock_redis.get.return_value = None
        token = await distributor.get_access_token()

        assert token == "fake-access-token-12345"

    @pytest.mark.asyncio
    async def test_get_access_token_from_cache(
        self,
        distributor: Any,
        mock_redis: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        """When cache has a valid token, returns it without API call."""
        mock_redis.get.return_value = b"cached-token-abc"
        token = await distributor.get_access_token()

        assert token == "cached-token-abc"
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_token_stored_in_redis_with_expiry(
        self, distributor: Any, mock_redis: AsyncMock
    ) -> None:
        """After fetching from API, token is cached in Redis with buffer."""
        from intellisource.distributor.channels.wework import (
            TOKEN_CACHE_KEY,
        )

        mock_redis.get.return_value = None
        await distributor.get_access_token()

        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == TOKEN_CACHE_KEY or (
            call_args[1].get("name") == TOKEN_CACHE_KEY if call_args[1] else False
        )

    @pytest.mark.asyncio
    async def test_token_cache_key_constant(self) -> None:
        """TOKEN_CACHE_KEY is defined as expected."""
        from intellisource.distributor.channels.wework import TOKEN_CACHE_KEY

        assert TOKEN_CACHE_KEY == "wework:access_token"

    @pytest.mark.asyncio
    async def test_token_expire_buffer_constant(self) -> None:
        """TOKEN_EXPIRE_BUFFER is 300 seconds."""
        from intellisource.distributor.channels.wework import (
            TOKEN_EXPIRE_BUFFER,
        )

        assert TOKEN_EXPIRE_BUFFER == 300

    @pytest.mark.asyncio
    async def test_token_refresh_on_api_error(
        self,
        distributor: Any,
        mock_redis: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        """When API returns errcode != 0, raises an appropriate error."""
        mock_redis.get.return_value = None
        error_response = MagicMock()
        error_response.status_code = 200
        error_response.json.return_value = {
            "errcode": 40013,
            "errmsg": "invalid corpid",
        }
        mock_http_client.get.return_value = error_response

        with pytest.raises(Exception):
            await distributor.get_access_token()


# ===========================================================================
# AC-T033-2: Text/Markdown/News card message formats
# ===========================================================================


class TestMessageFormats:
    """AC-T033-2: Support text, markdown, and news card message formats."""

    @pytest.mark.asyncio
    async def test_send_text_message(
        self, distributor: Any, mock_http_client: AsyncMock
    ) -> None:
        """send_text_message sends a text-type message to the user."""
        result = await distributor.send_text_message("user001", "Hello World")

        assert isinstance(result, dict)
        mock_http_client.post.assert_called()
        call_args = mock_http_client.post.call_args
        # Verify the payload includes msgtype=text
        if call_args[1] and "json" in call_args[1]:
            payload = call_args[1]["json"]
        else:
            payload = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert payload.get("msgtype") == "text"

    @pytest.mark.asyncio
    async def test_send_markdown_message(
        self, distributor: Any, mock_http_client: AsyncMock
    ) -> None:
        """send_markdown_message sends a markdown-type message."""
        result = await distributor.send_markdown_message("user001", "# Title\nBody")

        assert isinstance(result, dict)
        mock_http_client.post.assert_called()
        call_args = mock_http_client.post.call_args
        if call_args[1] and "json" in call_args[1]:
            payload = call_args[1]["json"]
        else:
            payload = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert payload.get("msgtype") == "markdown"

    @pytest.mark.asyncio
    async def test_send_news_card(
        self, distributor: Any, mock_http_client: AsyncMock
    ) -> None:
        """send_news_card sends a news-type message with articles."""
        articles = [
            {
                "title": "Article 1",
                "description": "Desc 1",
                "url": "https://example.com/1",
                "picurl": "https://example.com/pic1.jpg",
            }
        ]
        result = await distributor.send_news_card("user001", articles)

        assert isinstance(result, dict)
        mock_http_client.post.assert_called()
        call_args = mock_http_client.post.call_args
        if call_args[1] and "json" in call_args[1]:
            payload = call_args[1]["json"]
        else:
            payload = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert payload.get("msgtype") == "news"

    def test_format_content_markdown(self, distributor: Any) -> None:
        """format_content with msg_type='markdown' returns a string."""
        content = StubContent(title="Test", summary="Summary", body_text="Body")
        result = distributor.format_content(content, msg_type="markdown")

        assert isinstance(result, str)
        assert "Test" in result
        assert "Body" in result

    def test_format_content_text(self, distributor: Any) -> None:
        """format_content with msg_type='text' returns a plain string."""
        content = StubContent(title="Test", summary="Summary")
        result = distributor.format_content(content, msg_type="text")

        assert isinstance(result, str)

    def test_format_content_news(self, distributor: Any) -> None:
        """format_content with msg_type='news' returns a list of articles."""
        content = StubContent(
            title="Test",
            summary="Summary",
            source_url="https://example.com/1",
        )
        result = distributor.format_content(content, msg_type="news")

        assert isinstance(result, list)
        assert len(result) >= 1
        assert "title" in result[0]
        assert result[0]["url"] == "https://example.com/1"


# ===========================================================================
# AC-044: No duplicate push for same content
# ===========================================================================


class TestDeduplication:
    """AC-044: Deduplication is handled by PushRepository (see test_push_dedup.py)."""

    @pytest.mark.asyncio
    async def test_duplicate_push_via_push_repo(
        self,
        mock_redis: AsyncMock,
        mock_http_client: AsyncMock,
        corp_id: str,
        corp_secret: str,
        agent_id: int,
    ) -> None:
        """Second distribute() skipped when push_repo.exists() returns True."""
        from unittest.mock import MagicMock

        from intellisource.distributor.channels.wework import WeWorkDistributor

        push_repo = MagicMock()
        push_repo.exists = AsyncMock(side_effect=[False, True])
        push_repo.create = AsyncMock(return_value=MagicMock())

        dist = WeWorkDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            corp_id=corp_id,
            corp_secret=corp_secret,
            agent_id=agent_id,
            push_repo=push_repo,
        )
        content = StubContent()
        subscription = StubSubscription()

        first = await dist.distribute(content, subscription)
        second = await dist.distribute(content, subscription)

        assert first["status"] == "success"
        assert second["status"] in ("skipped", "duplicate", "deduplicated")

    @pytest.mark.asyncio
    async def test_dedup_uses_push_repo_not_redis(
        self,
        mock_redis: AsyncMock,
        mock_http_client: AsyncMock,
        corp_id: str,
        corp_secret: str,
        agent_id: int,
    ) -> None:
        """Deduplication check uses push_repo.exists(), not redis.exists()."""
        from unittest.mock import MagicMock

        from intellisource.distributor.channels.wework import WeWorkDistributor

        push_repo = MagicMock()
        push_repo.exists = AsyncMock(return_value=False)
        push_repo.create = AsyncMock(return_value=MagicMock())

        dist = WeWorkDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            corp_id=corp_id,
            corp_secret=corp_secret,
            agent_id=agent_id,
            push_repo=push_repo,
        )
        content = StubContent()
        subscription = StubSubscription()

        await dist.distribute(content, subscription)

        push_repo.exists.assert_awaited_once()
        # Redis should not be used for dedup anymore
        mock_redis.exists.assert_not_called()


# ===========================================================================
# AC-045: Auto-retry on push failure
# ===========================================================================


class TestAutoRetry:
    """AC-045: Push failures trigger automatic retries."""

    @pytest.mark.asyncio
    async def test_retry_on_http_error(
        self,
        distributor: Any,
        mock_http_client: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """On HTTP error, distributor retries up to MAX_RETRY times."""

        error_response = MagicMock()
        error_response.status_code = 200
        error_response.json.return_value = {
            "errcode": 60011,
            "errmsg": "no privilege to access",
        }
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "errcode": 0,
            "errmsg": "ok",
        }

        # Fail twice, then succeed
        mock_http_client.post.side_effect = [
            error_response,
            error_response,
            success_response,
        ]
        mock_redis.exists.return_value = False

        content = StubContent()
        subscription = StubSubscription()
        result = await distributor.distribute(content, subscription)

        assert result["status"] == "success"
        assert mock_http_client.post.call_count >= 3

    @pytest.mark.asyncio
    async def test_max_retry_exceeded_returns_failure(
        self,
        distributor: Any,
        mock_http_client: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """When all retries exhausted, returns failure status."""
        error_response = MagicMock()
        error_response.status_code = 200
        error_response.json.return_value = {
            "errcode": 60011,
            "errmsg": "no privilege to access",
        }
        mock_http_client.post.return_value = error_response
        mock_redis.exists.return_value = False

        content = StubContent()
        subscription = StubSubscription()
        result = await distributor.distribute(content, subscription)

        assert result["status"] == "failed"

    def test_max_retry_constant(self) -> None:
        """MAX_RETRY is 3."""
        from intellisource.distributor.channels.wework import MAX_RETRY

        assert MAX_RETRY == 3

    def test_retry_interval_constant(self) -> None:
        """RETRY_INTERVAL is 5 seconds."""
        from intellisource.distributor.channels.wework import RETRY_INTERVAL

        assert RETRY_INTERVAL == 5


# ===========================================================================
# AC-T033-3: Push result tracking
# ===========================================================================


class TestPushResultTracking:
    """AC-T033-3: Push results are tracked with relevant metadata."""

    @pytest.mark.asyncio
    async def test_distribute_result_has_timestamp(
        self, distributor: Any, mock_redis: AsyncMock
    ) -> None:
        """Push result dict includes a timestamp."""
        mock_redis.exists.return_value = False
        content = StubContent()
        subscription = StubSubscription()
        result = await distributor.distribute(content, subscription)

        assert "timestamp" in result or "pushed_at" in result

    @pytest.mark.asyncio
    async def test_distribute_result_has_content_id(
        self, distributor: Any, mock_redis: AsyncMock
    ) -> None:
        """Push result dict includes the content id."""
        mock_redis.exists.return_value = False
        content = StubContent()
        subscription = StubSubscription()
        result = await distributor.distribute(content, subscription)

        assert "content_id" in result
        assert result["content_id"] == content.id

    @pytest.mark.asyncio
    async def test_distribute_result_has_subscription_id(
        self, distributor: Any, mock_redis: AsyncMock
    ) -> None:
        """Push result dict includes the subscription id."""
        mock_redis.exists.return_value = False
        content = StubContent()
        subscription = StubSubscription()
        result = await distributor.distribute(content, subscription)

        assert "subscription_id" in result
        assert result["subscription_id"] == subscription.id

    @pytest.mark.asyncio
    async def test_distribute_failure_result_has_error_info(
        self,
        distributor: Any,
        mock_http_client: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Failed push result includes error information."""
        error_response = MagicMock()
        error_response.status_code = 200
        error_response.json.return_value = {
            "errcode": 40014,
            "errmsg": "invalid access_token",
        }
        mock_http_client.post.return_value = error_response
        mock_redis.exists.return_value = False

        content = StubContent()
        subscription = StubSubscription()
        result = await distributor.distribute(content, subscription)

        assert result["status"] == "failed"
        assert "error" in result or "errmsg" in result


# ===========================================================================
# R-005: WeWork attempt_fn try/except symmetry
# ===========================================================================


class TestWeWorkExceptionSymmetry:
    """R-005: Network exceptions in attempt_fn produce a failed record."""

    @pytest.mark.asyncio
    async def test_network_exception_produces_failed_result(
        self,
        mock_redis: AsyncMock,
        mock_http_client: AsyncMock,
        corp_id: str,
        corp_secret: str,
        agent_id: int,
    ) -> None:
        """When http_client.post raises a network exception, returns failed."""
        from intellisource.distributor.channels.wework import WeWorkDistributor

        mock_http_client.post.side_effect = OSError("Connection refused")

        dist = WeWorkDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            corp_id=corp_id,
            corp_secret=corp_secret,
            agent_id=agent_id,
        )
        content = StubContent()
        subscription = StubSubscription()

        result = await dist.distribute(content, subscription)

        assert result["status"] == "failed"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_network_exception_records_push_failed_in_repo(
        self,
        mock_redis: AsyncMock,
        mock_http_client: AsyncMock,
        corp_id: str,
        corp_secret: str,
        agent_id: int,
    ) -> None:
        """When http_client.post raises, a failed PushRecord is written to the repo."""
        from unittest.mock import MagicMock

        from intellisource.distributor.channels.wework import WeWorkDistributor

        mock_http_client.post.side_effect = RuntimeError("aiohttp.ClientError: timeout")

        push_repo = MagicMock()
        push_repo.exists = AsyncMock(return_value=False)
        push_repo.create = AsyncMock(return_value=MagicMock())

        dist = WeWorkDistributor(
            redis=mock_redis,
            http_client=mock_http_client,
            corp_id=corp_id,
            corp_secret=corp_secret,
            agent_id=agent_id,
            push_repo=push_repo,
        )
        content = StubContent()
        subscription = StubSubscription()

        await dist.distribute(content, subscription)

        push_repo.create.assert_awaited_once()
        create_kwargs = push_repo.create.await_args[1]
        assert create_kwargs.get("status") == "failed"
        assert create_kwargs.get("error_message") is not None
