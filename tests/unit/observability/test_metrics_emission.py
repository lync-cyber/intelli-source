"""Tests for F-22 MetricsCollector emission across HTTP / LLM / distributor paths."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.observability.metrics import MetricsCollector


@pytest.fixture(autouse=True)
def reset_metrics_singleton() -> Any:
    """Drop MetricsCollector singleton state between tests."""
    MetricsCollector._instance = None
    yield
    MetricsCollector._instance = None


# ---------------------------------------------------------------------------
# HTTP middleware metrics — RequestLoggerMiddleware records every request
# ---------------------------------------------------------------------------


class TestHttpRequestMetrics:
    """F-22 HTTP path: each served request increments counter + observes latency."""

    @pytest.mark.asyncio
    async def test_request_increments_total_counter(self) -> None:
        from intellisource.api.middleware import RequestLoggerMiddleware

        app = FastAPI()

        @app.get("/ping")
        async def ping() -> dict[str, str]:
            return {"pong": "ok"}

        app.add_middleware(RequestLoggerMiddleware)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/ping")
            await client.get("/ping")

        mc = MetricsCollector.get_instance()
        assert mc.get_counter_value("http_requests_total") == 2.0

    @pytest.mark.asyncio
    async def test_request_observes_duration_histogram(self) -> None:
        from intellisource.api.middleware import RequestLoggerMiddleware

        app = FastAPI()

        @app.get("/p")
        async def ping() -> dict[str, str]:
            return {"pong": "ok"}

        app.add_middleware(RequestLoggerMiddleware)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/p")

        mc = MetricsCollector.get_instance()
        summary = mc.get_histogram_summary("http_request_duration_seconds")
        assert summary["count"] == 1
        assert summary["sum"] >= 0


# ---------------------------------------------------------------------------
# LLM gateway metrics — complete / chat / stream all emit through _record_llm_call
# ---------------------------------------------------------------------------


class TestLlmGatewayMetrics:
    """F-22 LLM path: labeled counters and latency histogram on success/failure."""

    def test_record_llm_call_success_path(self) -> None:
        from intellisource.llm.gateway import _record_llm_call

        _record_llm_call(latency_seconds=0.12, success=True, model="gpt-4o-mini")

        mc = MetricsCollector.get_instance()
        assert (
            mc.get_labeled_counter_value("llm_calls_total", {"model": "gpt-4o-mini"})
            == 1.0
        )
        assert (
            mc.get_labeled_counter_value(
                "llm_call_failures_total", {"model": "gpt-4o-mini"}
            )
            == 0.0
        )
        summary = mc.get_histogram_summary("llm_call_latency_seconds")
        assert summary["count"] == 1

    def test_record_llm_call_failure_path(self) -> None:
        from intellisource.llm.gateway import _record_llm_call

        _record_llm_call(latency_seconds=0.05, success=False, model="gpt-4o-mini")

        mc = MetricsCollector.get_instance()
        assert (
            mc.get_labeled_counter_value("llm_calls_total", {"model": "gpt-4o-mini"})
            == 1.0
        )
        assert (
            mc.get_labeled_counter_value(
                "llm_call_failures_total", {"model": "gpt-4o-mini"}
            )
            == 1.0
        )

    def test_record_llm_call_does_not_raise_on_metric_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defensive: a broken metrics path must never break LLM caller flow."""
        from intellisource.llm.gateway import _record_llm_call

        def _broken_get_instance(cls: type) -> Any:
            raise RuntimeError("collector unavailable")

        monkeypatch.setattr(
            "intellisource.observability.metrics.MetricsCollector.get_instance",
            classmethod(_broken_get_instance),
        )
        # Must not raise — the gateway is allowed to keep serving requests
        _record_llm_call(latency_seconds=0.01, success=True)


# ---------------------------------------------------------------------------
# Distributor metrics — facade emits per-outcome counters
# ---------------------------------------------------------------------------


def _make_session_factory(content: Any, subs: list[Any]) -> MagicMock:
    mock_scalars_result = MagicMock()
    mock_scalars_result.all = MagicMock(return_value=subs)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=content)
    mock_session.scalars = AsyncMock(return_value=mock_scalars_result)
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_execute_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


class TestDistributorMetrics:
    """F-22 distributor path: pushes_total{channel,status} labeled counter."""

    @pytest.mark.asyncio
    async def test_sent_push_increments_labeled_sent(self) -> None:
        import uuid

        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        cid = str(uuid.uuid4())
        content = MagicMock()
        content.id = uuid.UUID(cid)

        sub = MagicMock()
        sub.id = uuid.uuid4()
        sub.status = "active"
        sub.channel = "email"
        sub.channel_config = {"to_addr": "u@example.com"}

        matcher = MagicMock(spec=SubscriptionMatcher)
        matcher.match.return_value = [sub]

        channel = MagicMock()
        channel.distribute = AsyncMock(return_value={"status": "sent"})

        facade = DistributorFacade(
            session_factory=_make_session_factory(content, [sub]),
            matcher=matcher,
            channels={"email": channel},
        )

        await facade.distribute(content_id=cid)

        mc = MetricsCollector.get_instance()
        assert (
            mc.get_labeled_counter_value(
                "pushes_total", {"channel": "email", "status": "sent"}
            )
            == 1.0
        )
        assert (
            mc.get_labeled_counter_value(
                "pushes_total", {"channel": "email", "status": "failed"}
            )
            == 0.0
        )

    @pytest.mark.asyncio
    async def test_channel_failure_increments_labeled_failed(self) -> None:
        import uuid

        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        cid = str(uuid.uuid4())
        content = MagicMock()
        content.id = uuid.UUID(cid)

        sub = MagicMock()
        sub.id = uuid.uuid4()
        sub.status = "active"
        sub.channel = "email"
        sub.channel_config = {"to_addr": "u@example.com"}

        matcher = MagicMock(spec=SubscriptionMatcher)
        matcher.match.return_value = [sub]

        channel = MagicMock()
        channel.distribute = AsyncMock(side_effect=RuntimeError("smtp down"))

        facade = DistributorFacade(
            session_factory=_make_session_factory(content, [sub]),
            matcher=matcher,
            channels={"email": channel},
        )

        await facade.distribute(content_id=cid)

        mc = MetricsCollector.get_instance()
        assert (
            mc.get_labeled_counter_value(
                "pushes_total", {"channel": "email", "status": "failed"}
            )
            == 1.0
        )
        assert (
            mc.get_labeled_counter_value(
                "pushes_total", {"channel": "email", "status": "sent"}
            )
            == 0.0
        )

    @pytest.mark.asyncio
    async def test_missing_channel_increments_labeled_skipped(self) -> None:
        import uuid

        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        cid = str(uuid.uuid4())
        content = MagicMock()
        content.id = uuid.UUID(cid)

        sub = MagicMock()
        sub.id = uuid.uuid4()
        sub.channel = "telegram"  # no implementation wired

        matcher = MagicMock(spec=SubscriptionMatcher)
        matcher.match.return_value = [sub]

        facade = DistributorFacade(
            session_factory=_make_session_factory(content, [sub]),
            matcher=matcher,
            channels={},  # no channels registered
        )

        await facade.distribute(content_id=cid)

        mc = MetricsCollector.get_instance()
        assert (
            mc.get_labeled_counter_value(
                "pushes_total", {"channel": "telegram", "status": "skipped"}
            )
            == 1.0
        )
        assert (
            mc.get_labeled_counter_value(
                "pushes_total", {"channel": "telegram", "status": "sent"}
            )
            == 0.0
        )
