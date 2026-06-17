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
        from unittest.mock import MagicMock

        from intellisource.llm.gateway import LLMGateway, _record_llm_call

        # Instantiating the gateway registers the labeled counters.
        LLMGateway(circuit_breaker=MagicMock())

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
        from unittest.mock import MagicMock

        from intellisource.llm.gateway import LLMGateway, _record_llm_call

        # Instantiating the gateway registers the labeled counters.
        LLMGateway(circuit_breaker=MagicMock())

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

    @pytest.mark.asyncio
    async def test_sent_push_mirrors_into_shared_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The push outcome is mirrored into the cross-process store so the
        API /metrics endpoint can surface it (the prefork worker's local collector
        is never served over HTTP)."""
        import uuid

        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher
        from intellisource.observability.shared_metrics import RedisMetricStore

        class _FakeRedis:
            def __init__(self) -> None:
                self.store: dict[str, dict[str, str]] = {}

            def hset(
                self,
                name: str,
                key: str | None = None,
                value: Any = None,
                mapping: dict[str, Any] | None = None,
            ) -> int:
                h = self.store.setdefault(name, {})
                if mapping:
                    for k, v in mapping.items():
                        h[k] = str(v)
                if key is not None:
                    h[key] = str(value)
                return 1

            def hincrbyfloat(self, name: str, key: str, amount: float) -> str:
                h = self.store.setdefault(name, {})
                cur = float(h.get(key, "0")) + float(amount)
                h[key] = str(cur)
                return h[key]

            def hgetall(self, name: str) -> dict[str, str]:
                return dict(self.store.get(name, {}))

        shared = RedisMetricStore(_FakeRedis())
        monkeypatch.setattr(
            "intellisource.observability.shared_metrics.get_shared_metric_store",
            lambda: shared,
        )

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

        entries = {e["name"]: e for e in shared.read_all()}
        assert "pushes_total" in entries
        assert entries["pushes_total"]["series"].get("channel=email,status=sent") == 1.0


# ---------------------------------------------------------------------------
# register labeled counters at __init__ time, not in hot path
# ---------------------------------------------------------------------------


class TestRegisterAtInit:
    """labeled counters must be registered in __init__, not per-call."""

    def test_distributor_facade_registers_pushes_total_on_init(self) -> None:
        """DistributorFacade.__init__ must register pushes_total immediately."""
        from unittest.mock import MagicMock

        from intellisource.distributor.facade import DistributorFacade
        from intellisource.distributor.matcher import SubscriptionMatcher

        mc = MetricsCollector.get_instance()
        registered_names_before = {name for name, _ in mc.iter_labeled_counters()}
        assert "pushes_total" not in registered_names_before

        _facade = DistributorFacade(
            session_factory=MagicMock(),
            matcher=MagicMock(spec=SubscriptionMatcher),
            channels={},
        )

        registered_names_after = {name for name, _ in mc.iter_labeled_counters()}
        assert "pushes_total" in registered_names_after, (
            "DistributorFacade.__init__ must register 'pushes_total' labeled counter "
            "so the hot-path _record_push_outcome only calls increment"
        )

    def test_llm_gateway_registers_llm_counters_on_init(self) -> None:
        """LLMGateway.__init__ registers llm_calls_total + llm_call_failures_total."""
        from intellisource.llm.circuit_breaker import CircuitBreaker
        from intellisource.llm.gateway import LLMGateway

        mc = MetricsCollector.get_instance()
        registered_names_before = {name for name, _ in mc.iter_labeled_counters()}
        assert "llm_calls_total" not in registered_names_before
        assert "llm_call_failures_total" not in registered_names_before

        _gateway = LLMGateway(circuit_breaker=CircuitBreaker(redis=MagicMock()))

        registered_names_after = {name for name, _ in mc.iter_labeled_counters()}
        assert "llm_calls_total" in registered_names_after, (
            "LLMGateway.__init__ must register 'llm_calls_total' labeled counter"
        )
        assert "llm_call_failures_total" in registered_names_after, (
            "LLMGateway.__init__ must register 'llm_call_failures_total' "
            "labeled counter"
        )
