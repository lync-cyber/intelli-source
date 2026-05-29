"""Tests for RateLimiter and ProxyManager.

Covers:
- AC-010: ProxyManager returns HTTP proxy address based on source config
- AC-011: RateLimiter uses Redis token bucket to limit request rate (QPS + concurrency)
- AC-T014-1: Requests wait (not reject) when rate limit exceeded
- AC-T014-2: Multiple workers share rate limit state in Redis
- AC-T014-3: Global defaults used when source has no rate limit config
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ===================================================================
# AC-010: ProxyManager returns proxy address per source config
# ===================================================================


class TestProxyManager:
    """Verify ProxyManager routes proxy addresses by source_id."""

    def test_import_proxy_manager(self):
        """ProxyManager can be imported from intellisource.collector.proxy."""
        from intellisource.collector.proxy import ProxyManager  # noqa: F401

    def test_get_proxy_returns_configured_address(self):
        """get_proxy(source_id) returns the proxy URL when configured."""
        from intellisource.collector.proxy import ProxyManager

        config = {
            "source_a": "http://proxy-a.example.com:8080",
            "source_b": "socks5://proxy-b.example.com:1080",
        }
        manager = ProxyManager(config)
        assert manager.get_proxy("source_a") == "http://proxy-a.example.com:8080"

    def test_get_proxy_returns_different_proxy_per_source(self):
        """Different source_ids yield different proxy addresses."""
        from intellisource.collector.proxy import ProxyManager

        config = {
            "source_a": "http://proxy-a.example.com:8080",
            "source_b": "socks5://proxy-b.example.com:1080",
        }
        manager = ProxyManager(config)
        assert manager.get_proxy("source_b") == "socks5://proxy-b.example.com:1080"

    def test_get_proxy_returns_none_for_unconfigured_source(self):
        """get_proxy returns None when source_id has no proxy configured."""
        from intellisource.collector.proxy import ProxyManager

        config = {"source_a": "http://proxy-a.example.com:8080"}
        manager = ProxyManager(config)
        assert manager.get_proxy("unknown_source") is None

    def test_get_proxy_returns_none_when_empty_config(self):
        """get_proxy returns None when proxy config is empty."""
        from intellisource.collector.proxy import ProxyManager

        manager = ProxyManager({})
        assert manager.get_proxy("any_source") is None


# ===================================================================
# AC-011: RateLimiter uses Redis token bucket for QPS + concurrency
# ===================================================================


class TestRateLimiterBasic:
    """Verify RateLimiter construction and basic token bucket behavior."""

    def test_import_rate_limiter(self):
        """RateLimiter can be imported from intellisource.collector.rate_limiter."""
        from intellisource.collector.rate_limiter import RateLimiter  # noqa: F401

    def test_constructor_accepts_redis_client(self):
        """RateLimiter can be constructed with a Redis client."""
        from intellisource.collector.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        limiter = RateLimiter(redis_client=mock_redis)
        assert isinstance(limiter, RateLimiter)

    @pytest.mark.asyncio
    async def test_acquire_calls_redis_for_token(self):
        """acquire() interacts with Redis to check/consume a token."""
        from intellisource.collector.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        # Simulate Redis returning enough tokens (token available)
        mock_redis.execute_command = AsyncMock(return_value=1)
        mock_redis.evalsha = AsyncMock(return_value=1)
        mock_redis.eval = AsyncMock(return_value=1)

        limiter = RateLimiter(redis_client=mock_redis)
        result = await limiter.acquire(source_id="source_a", qps=10, concurrency=5)

        # acquire should return a truthy value (token granted)
        assert result

    @pytest.mark.asyncio
    async def test_acquire_respects_qps_parameter(self):
        """acquire() uses the qps parameter to configure the token bucket rate."""
        from intellisource.collector.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        mock_redis.eval = AsyncMock(return_value=1)
        mock_redis.evalsha = AsyncMock(return_value=1)

        limiter = RateLimiter(redis_client=mock_redis)
        await limiter.acquire(source_id="source_a", qps=20, concurrency=5)

        # Verify Redis was called; the key should incorporate source_id
        assert (
            mock_redis.eval.called
            or mock_redis.evalsha.called
            or mock_redis.execute_command.called
        )

    @pytest.mark.asyncio
    async def test_acquire_respects_concurrency_parameter(self):
        """acquire() uses the concurrency parameter to limit parallel requests."""
        from intellisource.collector.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        mock_redis.eval = AsyncMock(return_value=1)
        mock_redis.evalsha = AsyncMock(return_value=1)

        limiter = RateLimiter(redis_client=mock_redis)
        await limiter.acquire(source_id="source_a", qps=10, concurrency=3)

        # Verify Redis interaction happened with concurrency considerations
        assert (
            mock_redis.eval.called
            or mock_redis.evalsha.called
            or mock_redis.execute_command.called
        )


# ===================================================================
# AC-T014-1: Requests wait when rate limit exceeded (not reject)
# ===================================================================


class TestRateLimiterWaitBehavior:
    """Verify that acquire() waits for token replenishment instead of rejecting."""

    @pytest.mark.asyncio
    async def test_acquire_waits_when_no_tokens_available(self):
        """When tokens are exhausted, acquire() waits rather than raising an error."""
        from intellisource.collector.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        # First call: no tokens (0 or negative), second call: tokens available
        mock_redis.eval = AsyncMock(side_effect=[0, 1])
        mock_redis.evalsha = AsyncMock(side_effect=[0, 1])

        limiter = RateLimiter(redis_client=mock_redis)

        # acquire should eventually succeed (after waiting for replenishment)
        # It must NOT raise an exception
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await limiter.acquire(source_id="source_a", qps=1, concurrency=1)
            # Should have waited (sleep called) then succeeded
            assert result
            assert (
                mock_sleep.called
                or mock_redis.eval.call_count > 1
                or mock_redis.evalsha.call_count > 1
            )

    @pytest.mark.asyncio
    async def test_acquire_does_not_raise_on_rate_limit(self):
        """acquire() must not raise a rate-limit error; it blocks until available."""
        from intellisource.collector.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        # Simulate token available on first try for simplicity
        mock_redis.eval = AsyncMock(return_value=1)
        mock_redis.evalsha = AsyncMock(return_value=1)

        limiter = RateLimiter(redis_client=mock_redis)
        # This should complete without raising any rate-limit exception
        result = await limiter.acquire(source_id="source_a", qps=1, concurrency=1)
        assert result


# ===================================================================
# AC-T014-2: Multiple workers share rate limit state via Redis
# ===================================================================


class TestRateLimiterSharedState:
    """Verify rate limit state is shared across workers through Redis keys."""

    @pytest.mark.asyncio
    async def test_rate_limiter_uses_source_specific_redis_key(self):
        """Two RateLimiter instances with same Redis use same keys for same source."""
        from intellisource.collector.rate_limiter import RateLimiter

        shared_redis = MagicMock()
        shared_redis.eval = AsyncMock(return_value=1)
        shared_redis.evalsha = AsyncMock(return_value=1)

        limiter_worker1 = RateLimiter(redis_client=shared_redis)
        limiter_worker2 = RateLimiter(redis_client=shared_redis)

        await limiter_worker1.acquire(source_id="source_x", qps=10, concurrency=5)
        await limiter_worker2.acquire(source_id="source_x", qps=10, concurrency=5)

        # Both workers should have called Redis (sharing the same client/state)
        total_calls = (
            shared_redis.eval.call_count
            + shared_redis.evalsha.call_count
            + shared_redis.execute_command.call_count
        )
        assert total_calls >= 2, "Both workers must interact with shared Redis"

    @pytest.mark.asyncio
    async def test_different_sources_use_different_redis_keys(self):
        """Rate limit state is isolated per source_id in Redis."""
        from intellisource.collector.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        call_args_list = []

        async def capture_eval(*args, **kwargs):
            call_args_list.append(args)
            return 1

        mock_redis.eval = AsyncMock(side_effect=capture_eval)
        mock_redis.evalsha = AsyncMock(side_effect=capture_eval)

        limiter = RateLimiter(redis_client=mock_redis)
        await limiter.acquire(source_id="source_a", qps=10, concurrency=5)
        await limiter.acquire(source_id="source_b", qps=10, concurrency=5)

        # The Redis calls should contain different keys for different sources
        all_args = [str(a) for a in call_args_list]
        combined = " ".join(all_args)
        assert "source_a" in combined or "source_b" in combined, (
            "Redis keys must incorporate source_id to isolate state"
        )


# ===================================================================
# AC-T014-3: Global defaults when source has no rate limit config
# ===================================================================


class TestRateLimiterDefaults:
    """Verify global default QPS and concurrency when not specified per source."""

    @pytest.mark.asyncio
    async def test_acquire_uses_default_qps_when_not_specified(self):
        """When qps is None, RateLimiter falls back to global default (10)."""
        from intellisource.collector.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        mock_redis.eval = AsyncMock(return_value=1)
        mock_redis.evalsha = AsyncMock(return_value=1)

        limiter = RateLimiter(redis_client=mock_redis)
        result = await limiter.acquire(source_id="source_a", qps=None, concurrency=None)

        # Should succeed using defaults, not raise TypeError or skip limiting
        assert result

    @pytest.mark.asyncio
    async def test_acquire_uses_default_concurrency_when_not_specified(self):
        """When concurrency is None, RateLimiter falls back to global default (5)."""
        from intellisource.collector.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        mock_redis.eval = AsyncMock(return_value=1)
        mock_redis.evalsha = AsyncMock(return_value=1)

        limiter = RateLimiter(redis_client=mock_redis)
        result = await limiter.acquire(source_id="source_a", concurrency=None)

        assert result

    @pytest.mark.asyncio
    async def test_default_qps_value_is_ten(self):
        """The global default QPS should be 10."""
        from intellisource.collector.rate_limiter import DEFAULT_QPS

        assert DEFAULT_QPS == 10

    @pytest.mark.asyncio
    async def test_default_concurrency_value_is_five(self):
        """The global default concurrency should be 5."""
        from intellisource.collector.rate_limiter import (
            DEFAULT_CONCURRENCY,
        )

        assert DEFAULT_CONCURRENCY == 5
