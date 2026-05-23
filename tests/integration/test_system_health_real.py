"""Integration tests for /system endpoints backed by real checkers (T099-4/5)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _make_system_app(
    *,
    health_result: Any = None,
    metrics_collector: Any = None,
) -> FastAPI:
    from intellisource.api.routers.system import router as system_router

    app = FastAPI()
    app.include_router(system_router, prefix="/api/v1/system")

    if health_result is not None:
        checker = MagicMock()
        checker.check_health = AsyncMock(return_value=health_result)
        app.state.health_checker = checker
    if metrics_collector is not None:
        app.state.metrics_collector = metrics_collector

    return app


class TestHealthRealChecker:
    """AC-T099-4: /health returns the HealthChecker result rather than a stub."""

    async def test_health_returns_real_check_payload(self) -> None:
        from datetime import datetime, timezone

        from intellisource.observability.health import HealthResult

        result = HealthResult(
            status="healthy",
            version="0.4.0",
            uptime_seconds=12.34,
            checks={"db": "healthy", "redis": "healthy", "celery": "healthy"},
            timestamp=datetime.now(tz=timezone.utc),
        )
        app = _make_system_app(health_result=result)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/system/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["checks"] == {
            "db": "healthy",
            "redis": "healthy",
            "celery": "healthy",
        }
        assert "uptime_seconds" in body

    async def test_health_endpoint_swallows_checker_exception(self) -> None:
        """R-004: /health must never raise even if HealthChecker explodes."""
        app = FastAPI()
        from intellisource.api.routers.system import router as system_router

        app.include_router(system_router, prefix="/api/v1/system")
        bad_checker = MagicMock()
        bad_checker.check_health = AsyncMock(side_effect=RuntimeError("boom"))
        app.state.health_checker = bad_checker

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/system/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "unhealthy"
        assert body["checks"].get("meta") == "checker_failed"

    async def test_health_degraded_passes_through(self) -> None:
        from datetime import datetime, timezone

        from intellisource.observability.health import HealthResult

        result = HealthResult(
            status="degraded",
            version="0.4.0",
            uptime_seconds=1.0,
            checks={"db": "healthy", "redis": "unhealthy"},
            timestamp=datetime.now(tz=timezone.utc),
        )
        app = _make_system_app(health_result=result)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/system/health")

        assert resp.json()["status"] == "degraded"


class TestMetricsRealCollector:
    """AC-T099-4: /metrics renders Prometheus exposition from MetricsCollector."""

    async def test_metrics_renders_counter_and_gauge(self) -> None:
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector._counters = {"requests_total": 42}
        collector._counter_descriptions = {"requests_total": "Total requests"}
        collector._gauges = {"queue_depth": 7}
        collector._gauge_descriptions = {"queue_depth": "Queue depth"}
        collector._histograms = {}
        collector._histogram_descriptions = {}

        app = _make_system_app(metrics_collector=collector)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/system/metrics")

        assert resp.status_code == 200
        text = resp.text
        assert "# TYPE requests_total counter" in text
        assert "requests_total 42" in text
        assert "# TYPE queue_depth gauge" in text
        assert "queue_depth 7" in text


class TestCompositionInstallsObservabilityState:
    """AC-T099-5: composition wires health_checker + metrics + version_manager."""

    def test_install_observability_state_sets_app_state(self) -> None:
        from unittest.mock import patch

        from fastapi import FastAPI as _FastAPI

        from intellisource.composition import _install_observability_state

        app = _FastAPI()
        app.state.celery_app = MagicMock()

        db_manager = MagicMock()
        redis_client = MagicMock()

        _install_observability_state(
            app, db_manager=db_manager, redis_client=redis_client
        )

        # The HealthChecker is registered with three named probes.
        checker = app.state.health_checker
        assert "db" in checker._checks
        assert "redis" in checker._checks
        assert "celery" in checker._checks

        assert app.state.metrics_collector is not None
        assert app.state.config_version_manager is not None
        assert app.state.config_version_manager.current_version == 0

        # Sanity: patch ensures we did not accidentally re-import.
        _ = patch  # keep import alive for tooling
