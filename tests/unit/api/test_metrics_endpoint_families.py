"""The /api/v1/metrics endpoint must expose every advertised metric family.

A fresh API process scrape must surface the API-owned families (registered
eagerly at startup, not only after first traffic) plus the worker-owned
``celery_*`` families (recorded in worker processes, surfaced via the shared
Redis store).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from httpx import ASGITransport, AsyncClient

from intellisource.observability.metrics import MetricsCollector


@pytest.fixture(autouse=True)
def reset_metrics_singleton() -> Any:
    """Drop MetricsCollector singleton state between tests."""
    MetricsCollector._instance = None
    yield
    MetricsCollector._instance = None


class _FakeRedis:
    """In-memory sync redis hash API for the shared metric store."""

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


def _build_app_with_metrics() -> FastAPI:
    """Assemble a minimal app whose /api/v1/metrics mirrors production wiring."""
    from intellisource.api.middleware import RequestLoggerMiddleware
    from intellisource.llm.circuit_breaker import CircuitBreaker
    from intellisource.llm.gateway import LLMGateway
    from intellisource.observability.shared_metrics import RedisMetricStore

    app = FastAPI()

    # API-owned families register at construction time (eager):
    #   - http_requests_total via RequestLoggerMiddleware.__init__
    #   - llm_calls_total / llm_call_failures_total via LLMGateway.__init__
    #   - llm_circuit_open via CircuitBreaker.__init__
    LLMGateway(circuit_breaker=CircuitBreaker(redis=MagicMock()))

    # Worker-owned families surfaced via the shared Redis store.
    fake_redis = _FakeRedis()
    shared = RedisMetricStore(fake_redis)
    shared.seed_counter("celery_tasks_total", "Total Celery tasks executed")
    shared.seed_counter("celery_task_failures_total", "Total Celery tasks failed")
    # pushes_total{channel,status} is recorded in the prefork worker and merged
    # in from the shared store (a labeled family — meta registered here, sample
    # lines come from real pushes).
    shared.register_counter("pushes_total", "Push attempts by channel and outcome")

    app.state.metrics_collector = MetricsCollector.get_instance()
    app.state.shared_metrics = shared

    app.add_middleware(RequestLoggerMiddleware)

    from intellisource.api.routers import system

    @app.get("/api/v1/metrics")
    async def metrics_v1(request: Request) -> PlainTextResponse:
        return system.metrics_response(request)

    return app


B014_FAMILIES = [
    "http_requests_total",
    "llm_calls_total",
    "pushes_total",
    "celery_tasks_total",
    "llm_circuit_open",
]


class TestMetricsEndpointExposesAllFamilies:
    """The metric families must all be present on a fresh scrape."""

    @pytest.mark.asyncio
    async def test_all_b014_families_present(self) -> None:
        app = _build_app_with_metrics()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/metrics")

        assert resp.status_code == 200
        body = resp.text
        missing = [fam for fam in B014_FAMILIES if fam not in body]
        assert not missing, f"missing metric families on /api/v1/metrics: {missing}"

    @pytest.mark.asyncio
    async def test_http_family_present_on_first_scrape(self) -> None:
        """Eager registration: the first scrape already lists http_requests_total."""
        app = _build_app_with_metrics()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/metrics")

        assert "http_requests_total" in resp.text

    @pytest.mark.asyncio
    async def test_worker_family_value_surfaced_from_shared_store(self) -> None:
        """celery_tasks_total increments in the shared store reach the API endpoint."""
        from intellisource.observability.shared_metrics import RedisMetricStore

        app = _build_app_with_metrics()
        store: RedisMetricStore = app.state.shared_metrics
        store.increment_counter("celery_tasks_total")
        store.increment_counter("celery_tasks_total")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/metrics")

        assert "celery_tasks_total 2.0" in resp.text
