"""Tests for LLM result cache.

Covers:
- LLMCache.cache_key() format
- LLMCache.get() returns None on miss
- LLMCache.get() returns LLMResult on hit
- LLMCache.set() stores with correct TTL
- LLMGateway integration with cache
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.llm.cache import LLMCache
from intellisource.llm.gateway import LLMGateway, LLMResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeRedis:
    """In-memory async Redis mock for testing."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value
        self._ttls[key] = ttl


@pytest.fixture
def fake_redis() -> FakeRedis:
    """Return a fresh FakeRedis instance."""
    return FakeRedis()


@pytest.fixture
def cache(fake_redis: FakeRedis) -> LLMCache:
    """Return an LLMCache backed by FakeRedis with default TTL."""
    return LLMCache(redis=fake_redis, ttl=3600)


@pytest.fixture
def sample_result() -> LLMResult:
    """Return a sample LLMResult for testing."""
    return LLMResult(
        content="Summary of the article.",
        metadata={"model": "gpt-4o-mini", "input_tokens": 100},
    )


# ===================================================================
# cache_key format
# ===================================================================


class TestCacheKey:
    """Verify cache_key() produces the correct format."""

    def test_cache_key_format(self, cache: LLMCache) -> None:
        """cache_key() returns llm:cache:{call_type}:{prompt_version}:{fingerprint}."""
        key = cache.cache_key(
            content_fingerprint="abc123",
            call_type="summarize",
            prompt_version="v1",
        )
        assert key == "llm:cache:summarize:v1:abc123"

    def test_cache_key_different_inputs_differ(self, cache: LLMCache) -> None:
        """Different inputs produce different cache keys."""
        key1 = cache.cache_key("fp1", "extract", "v1")
        key2 = cache.cache_key("fp2", "extract", "v1")
        key3 = cache.cache_key("fp1", "summarize", "v1")
        assert key1 != key2
        assert key1 != key3


# ===================================================================
# get() - cache miss / hit
# ===================================================================


class TestCacheGet:
    """Verify get() returns None on miss and LLMResult on hit."""

    async def test_get_returns_none_on_miss(self, cache: LLMCache) -> None:
        """get() returns None when key does not exist."""
        result = await cache.get("nonexistent", "extract", "v1")
        assert result is None

    async def test_get_returns_result_on_hit(
        self,
        cache: LLMCache,
        fake_redis: FakeRedis,
        sample_result: LLMResult,
    ) -> None:
        """get() returns LLMResult when key exists in Redis."""
        key = cache.cache_key("fp1", "extract", "v1")
        payload = json.dumps(
            {"content": sample_result.content, "metadata": sample_result.metadata}
        )
        fake_redis._store[key] = payload

        result = await cache.get("fp1", "extract", "v1")
        assert result is not None
        assert result.content == sample_result.content
        assert result.metadata == sample_result.metadata

    async def test_get_returns_none_on_redis_error(
        self, sample_result: LLMResult
    ) -> None:
        """get() returns None when Redis raises an exception."""
        broken_redis = AsyncMock()
        broken_redis.get = AsyncMock(side_effect=ConnectionError("connection lost"))
        error_cache = LLMCache(redis=broken_redis, ttl=3600)

        result = await error_cache.get("fp1", "extract", "v1")
        assert result is None


# ===================================================================
# set() - storage with TTL
# ===================================================================


class TestCacheSet:
    """Verify set() stores result with correct TTL."""

    async def test_set_stores_result(
        self,
        cache: LLMCache,
        fake_redis: FakeRedis,
        sample_result: LLMResult,
    ) -> None:
        """set() stores serialized LLMResult in Redis."""
        await cache.set("fp1", "extract", "v1", sample_result)

        key = cache.cache_key("fp1", "extract", "v1")
        assert key in fake_redis._store
        stored = json.loads(fake_redis._store[key])
        assert stored["content"] == sample_result.content
        assert stored["metadata"] == sample_result.metadata

    async def test_set_uses_configured_ttl(
        self,
        cache: LLMCache,
        fake_redis: FakeRedis,
        sample_result: LLMResult,
    ) -> None:
        """set() passes the configured TTL to Redis setex."""
        await cache.set("fp1", "extract", "v1", sample_result)

        key = cache.cache_key("fp1", "extract", "v1")
        assert fake_redis._ttls[key] == 3600

    async def test_set_silently_handles_redis_error(
        self, sample_result: LLMResult
    ) -> None:
        """set() does not raise when Redis fails."""
        broken_redis = AsyncMock()
        broken_redis.setex = AsyncMock(side_effect=ConnectionError("connection lost"))
        error_cache = LLMCache(redis=broken_redis, ttl=3600)

        # Should not raise
        await error_cache.set("fp1", "extract", "v1", sample_result)


# ===================================================================
# LLMGateway integration with cache
# ===================================================================


class TestLLMGatewayWithCache:
    """Verify LLMGateway uses cache when configured."""

    @pytest.fixture
    def mock_litellm_response(self) -> MagicMock:
        """Build a mock litellm completion response."""
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "LLM generated text"
        response.usage.prompt_tokens = 50
        response.usage.completion_tokens = 30
        response.model = "gpt-4o-mini"
        return response

    async def test_gateway_returns_cached_result_without_llm_call(
        self,
        fake_redis: FakeRedis,
        mock_litellm_response: MagicMock,
    ) -> None:
        """Gateway returns cached result and does not call litellm."""
        llm_cache = LLMCache(redis=fake_redis, ttl=3600)

        # Pre-populate cache
        cached_result = LLMResult(
            content="cached content",
            metadata={"model": "gpt-4o-mini"},
        )
        await llm_cache.set("fp1", "extract", "v1", cached_result)

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway(cache=llm_cache)
            result = await gw.complete(
                prompt="test",
                model="gpt-4o-mini",
                cache_key_parts={
                    "content_fingerprint": "fp1",
                    "call_type": "extract",
                    "prompt_version": "v1",
                },
            )
            mock_litellm.acompletion.assert_not_awaited()

        assert result.content == "cached content"

    async def test_gateway_calls_llm_and_caches_on_miss(
        self,
        fake_redis: FakeRedis,
        mock_litellm_response: MagicMock,
    ) -> None:
        """Gateway calls litellm on cache miss and stores result."""
        llm_cache = LLMCache(redis=fake_redis, ttl=3600)

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            mock_litellm.token_counter = MagicMock(return_value=10)
            gw = LLMGateway(cache=llm_cache)
            result = await gw.complete(
                prompt="test",
                model="gpt-4o-mini",
                cache_key_parts={
                    "content_fingerprint": "fp1",
                    "call_type": "extract",
                    "prompt_version": "v1",
                },
            )
            mock_litellm.acompletion.assert_awaited_once()

        assert result.content == "LLM generated text"
        # Verify it was cached
        key = llm_cache.cache_key("fp1", "extract", "v1")
        assert key in fake_redis._store

    async def test_gateway_works_without_cache(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """Gateway works normally when no cache is configured."""
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            mock_litellm.token_counter = MagicMock(return_value=10)
            gw = LLMGateway()
            result = await gw.complete(prompt="test", model="gpt-4o-mini")

        assert result.content == "LLM generated text"

    async def test_gateway_ignores_cache_when_no_key_parts(
        self,
        fake_redis: FakeRedis,
        mock_litellm_response: MagicMock,
    ) -> None:
        """Gateway skips cache when cache_key_parts is not provided."""
        llm_cache = LLMCache(redis=fake_redis, ttl=3600)

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            mock_litellm.token_counter = MagicMock(return_value=10)
            gw = LLMGateway(cache=llm_cache)
            result = await gw.complete(prompt="test", model="gpt-4o-mini")
            mock_litellm.acompletion.assert_awaited_once()

        assert result.content == "LLM generated text"
        # Nothing should be cached
        assert len(fake_redis._store) == 0


# ===================================================================
# AC-T052-4: Cache hit logging to LLMCallLog
# ===================================================================


class TestCacheHitLogging:
    """AC-T052-4: Gateway records cache hits to LLMCallLog via CostTracker.

    status='cached', input_tokens=0.
    """

    async def test_cache_hit_logs_with_status_cached_and_zero_input_tokens(
        self, fake_redis: FakeRedis
    ) -> None:
        """Cache hit triggers log_call with status=cached, input_tokens=0."""
        llm_cache = LLMCache(redis=fake_redis, ttl=3600)
        cached_result = LLMResult(
            content="cached content",
            metadata={"model": "gpt-4o-mini", "output_tokens": 42},
        )
        await llm_cache.set("fp1", "extract", "v1", cached_result)

        tracker = AsyncMock()
        tracker.log_call = AsyncMock()

        gw = LLMGateway(cache=llm_cache, cost_tracker=tracker)
        result = await gw.complete(
            prompt="test prompt body",
            model="gpt-4o-mini",
            cache_key_parts={
                "content_fingerprint": "fp1",
                "call_type": "extract",
                "prompt_version": "v1",
            },
        )

        assert result.content == "cached content"
        tracker.log_call.assert_awaited_once()
        record = tracker.log_call.await_args.args[0]
        assert record.status == "cached"
        assert record.input_tokens == 0
        assert record.output_tokens == 42
        assert record.call_type == "extract"
        assert record.model == "gpt-4o-mini"
        assert record.latency_ms == 0

    async def test_cache_miss_logs_success_not_cached(
        self, fake_redis: FakeRedis
    ) -> None:
        """On cache miss complete() falls through to the LLM and the cost
        tracker records a status='success' row (not 'cached')."""
        llm_cache = LLMCache(redis=fake_redis, ttl=3600)
        tracker = AsyncMock()
        tracker.log_call = AsyncMock()

        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "fresh"
        response.usage.prompt_tokens = 10
        response.usage.completion_tokens = 5
        response.model = "gpt-4o-mini"

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=response)
            mock_litellm.token_counter = MagicMock(return_value=5)
            gw = LLMGateway(cache=llm_cache, cost_tracker=tracker)
            await gw.complete(
                prompt="fresh prompt",
                model="gpt-4o-mini",
                cache_key_parts={
                    "content_fingerprint": "fp-miss",
                    "call_type": "extract",
                    "prompt_version": "v1",
                },
            )

        tracker.log_call.assert_awaited_once()
        record = tracker.log_call.await_args.args[0]
        assert record.status == "success"
        assert record.call_type == "complete"
        assert record.input_tokens == 10
        assert record.output_tokens == 5

    async def test_cache_hit_without_cost_tracker_does_not_raise(
        self, fake_redis: FakeRedis
    ) -> None:
        """Gateway with cache but no cost_tracker returns cached result silently."""
        llm_cache = LLMCache(redis=fake_redis, ttl=3600)
        cached_result = LLMResult(
            content="cached content",
            metadata={"model": "gpt-4o-mini"},
        )
        await llm_cache.set("fp1", "extract", "v1", cached_result)

        gw = LLMGateway(cache=llm_cache, cost_tracker=None)
        result = await gw.complete(
            prompt="x",
            model="gpt-4o-mini",
            cache_key_parts={
                "content_fingerprint": "fp1",
                "call_type": "extract",
                "prompt_version": "v1",
            },
        )
        assert result.content == "cached content"
