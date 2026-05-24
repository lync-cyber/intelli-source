"""Integration tests: BaseCollector wiring of rate limiter, proxy, and adaptive."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.collector.adaptive import AdaptiveScheduler
from intellisource.collector.base import BaseCollector, RawContent
from intellisource.collector.proxy import ProxyManager
from intellisource.collector.rate_limiter import RateLimiter
from intellisource.config.models import SourceConfig

# ---------------------------------------------------------------------------
# Minimal concrete collector for testing
# ---------------------------------------------------------------------------


class _FakeCollector(BaseCollector):
    """Minimal collector that records proxy passed via _do_fetch."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.captured_proxy: str | None = None

    async def collect(self, source_config: dict[str, object]) -> list[RawContent]:
        return []

    async def _do_fetch(
        self, source_config: SourceConfig, proxy: str | None = None
    ) -> list[RawContent]:
        self.captured_proxy = proxy
        return []


def _make_source(*, proxy: str | None = None) -> SourceConfig:
    return SourceConfig(
        name="test-src",
        type="rss",
        url="https://example.com/feed",
        proxy=proxy,
    )


# ---------------------------------------------------------------------------
# AC: rate_limiter.acquire is called on fetch
# ---------------------------------------------------------------------------


class TestRateLimiterThrottlesConcurrentFetch:
    @pytest.mark.asyncio
    async def test_acquire_called_with_source_name(self) -> None:
        fake_rl = AsyncMock(spec=RateLimiter)
        fake_rl.acquire = AsyncMock(return_value=True)
        collector = _FakeCollector(rate_limiter=fake_rl)
        source = _make_source()

        await collector.fetch(source)

        fake_rl.acquire.assert_awaited_once()
        call_args = fake_rl.acquire.call_args
        assert call_args.args[0] == "test-src"

    @pytest.mark.asyncio
    async def test_acquire_not_called_when_rate_limiter_is_none(self) -> None:
        collector = _FakeCollector(rate_limiter=None)
        source = _make_source()
        # Should not raise
        await collector.fetch(source)

    @pytest.mark.asyncio
    async def test_acquire_passes_qps_from_source_config(self) -> None:
        fake_rl = AsyncMock(spec=RateLimiter)
        fake_rl.acquire = AsyncMock(return_value=True)
        collector = _FakeCollector(rate_limiter=fake_rl)
        source = SourceConfig(
            name="test-src",
            type="rss",
            url="https://example.com/feed",
            rate_limit_qps=5.0,
            rate_limit_concurrency=2,
        )

        await collector.fetch(source)

        fake_rl.acquire.assert_awaited_once_with("test-src", qps=5, concurrency=2)


# ---------------------------------------------------------------------------
# AC: proxy is passed through to _do_fetch when proxy_manager resolves one
# ---------------------------------------------------------------------------


class TestProxyPassedToFetch:
    @pytest.mark.asyncio
    async def test_proxy_resolved_and_forwarded(self) -> None:
        pm = MagicMock(spec=ProxyManager)
        pm.get_proxy.return_value = "http://proxy.example.com:8080"
        collector = _FakeCollector(proxy_manager=pm)
        source = _make_source(proxy="http://proxy.example.com:8080")

        await collector.fetch(source)

        pm.get_proxy.assert_called_once_with("test-src")
        assert collector.captured_proxy == "http://proxy.example.com:8080"

    @pytest.mark.asyncio
    async def test_proxy_not_resolved_when_source_proxy_is_none(self) -> None:
        pm = MagicMock(spec=ProxyManager)
        pm.get_proxy.return_value = "http://proxy.example.com:8080"
        collector = _FakeCollector(proxy_manager=pm)
        source = _make_source(proxy=None)

        await collector.fetch(source)

        pm.get_proxy.assert_not_called()
        assert collector.captured_proxy is None

    @pytest.mark.asyncio
    async def test_no_proxy_when_proxy_manager_is_none(self) -> None:
        collector = _FakeCollector(proxy_manager=None)
        source = _make_source(proxy="http://proxy.example.com:8080")

        await collector.fetch(source)

        assert collector.captured_proxy is None


# ---------------------------------------------------------------------------
# AC: adaptive.record_success / record_failure called on outcomes
# ---------------------------------------------------------------------------


class TestAdaptiveRecordsSuccessAndFailure:
    @pytest.mark.asyncio
    async def test_record_success_on_successful_fetch(self) -> None:
        adaptive = MagicMock(spec=AdaptiveScheduler)
        collector = _FakeCollector(adaptive=adaptive)
        source = _make_source()

        await collector.fetch(source)

        adaptive.record_success.assert_called_once_with("test-src")
        adaptive.record_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_record_failure_on_exception(self) -> None:
        adaptive = MagicMock(spec=AdaptiveScheduler)

        class _FailingCollector(_FakeCollector):
            async def _do_fetch(
                self, source_config: SourceConfig, proxy: str | None = None
            ) -> list[RawContent]:
                raise RuntimeError("fetch failed")

        collector = _FailingCollector(adaptive=adaptive)
        source = _make_source()

        with pytest.raises(RuntimeError):
            await collector.fetch(source)

        adaptive.record_failure.assert_called_once_with("test-src")
        adaptive.record_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_adaptive_not_called_when_none(self) -> None:
        collector = _FakeCollector(adaptive=None)
        source = _make_source()
        # Should not raise
        await collector.fetch(source)
