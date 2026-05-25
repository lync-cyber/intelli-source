"""B-003: intellisource_health_status gauge — RED/GREEN tests.

Three acceptance criteria:
  AC-B003-1  Three-state mapping: healthy=0, degraded=1, unhealthy=2 per component.
  AC-B003-2  /metrics HTTP response contains labeled gauge lines.
  AC-B003-3  Gauge value updates on successive check_health() calls.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.observability.metrics import MetricsCollector

_GAUGE = "intellisource_health_status"


def _gauge(mc: MetricsCollector, component: str) -> float:
    """Shorthand: read intellisource_health_status for a component."""
    return mc.get_labeled_gauge_value(_GAUGE, {"component": component})


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Drop MetricsCollector singleton state between tests."""
    MetricsCollector._instance = None
    yield  # type: ignore[misc]
    MetricsCollector._instance = None


# ---------------------------------------------------------------------------
# AC-B003-1  Three-state mapping: mock HealthChecker returns each state →
#            gauge value equals the encoded integer.
# ---------------------------------------------------------------------------


class TestHealthGaugeMapping:
    """Gauge value tracks the STATUS_TO_GAUGE encoding per component."""

    @pytest.mark.asyncio
    async def test_healthy_component_sets_gauge_to_zero(self) -> None:
        from intellisource.observability.health import HealthChecker
        from intellisource.observability.metrics import MetricsCollector

        mc = MetricsCollector.get_instance()
        checker = HealthChecker(metrics_collector=mc)

        async def _ok() -> bool:
            return True

        checker.register_check("db", _ok)
        await checker.check_health()

        assert _gauge(mc, "db") == 0

    @pytest.mark.asyncio
    async def test_unhealthy_component_sets_gauge_to_two(self) -> None:
        from intellisource.observability.health import HealthChecker
        from intellisource.observability.metrics import MetricsCollector

        mc = MetricsCollector.get_instance()
        checker = HealthChecker(metrics_collector=mc)

        async def _fail() -> bool:
            return False

        checker.register_check("redis", _fail)
        await checker.check_health()

        assert _gauge(mc, "redis") == 2

    @pytest.mark.asyncio
    async def test_multiple_components_each_get_own_gauge(self) -> None:
        from intellisource.observability.health import HealthChecker
        from intellisource.observability.metrics import MetricsCollector

        mc = MetricsCollector.get_instance()
        checker = HealthChecker(metrics_collector=mc)

        async def _ok() -> bool:
            return True

        async def _fail() -> bool:
            return False

        checker.register_check("db", _ok)
        checker.register_check("redis", _fail)
        checker.register_check("celery", _ok)
        await checker.check_health()

        assert _gauge(mc, "db") == 0
        assert _gauge(mc, "redis") == 2
        assert _gauge(mc, "celery") == 0


# ---------------------------------------------------------------------------
# AC-B003-2  /metrics HTTP response contains labeled gauge exposition lines.
# ---------------------------------------------------------------------------


class TestHealthGaugeMetricsEndpoint:
    """Prometheus text output includes intellisource_health_status{component=...}."""

    @pytest.mark.asyncio
    async def test_metrics_response_contains_health_status_gauge_line(self) -> None:
        from intellisource.api.routers.system import router
        from intellisource.observability.health import HealthChecker
        from intellisource.observability.metrics import MetricsCollector

        app = FastAPI()
        app.include_router(router)

        mc = MetricsCollector.get_instance()
        checker = HealthChecker(metrics_collector=mc)

        async def _ok() -> bool:
            return True

        checker.register_check("db", _ok)
        await checker.check_health()

        app.state.metrics_collector = mc

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics")

        assert resp.status_code == 200
        body = resp.text
        assert 'intellisource_health_status{component="db"} 0' in body

    @pytest.mark.asyncio
    async def test_metrics_response_contains_all_three_components(self) -> None:
        from intellisource.api.routers.system import router
        from intellisource.observability.health import HealthChecker
        from intellisource.observability.metrics import MetricsCollector

        app = FastAPI()
        app.include_router(router)

        mc = MetricsCollector.get_instance()
        checker = HealthChecker(metrics_collector=mc)

        async def _ok() -> bool:
            return True

        async def _fail() -> bool:
            return False

        checker.register_check("db", _ok)
        checker.register_check("redis", _fail)
        checker.register_check("celery", _ok)
        await checker.check_health()

        app.state.metrics_collector = mc

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics")

        body = resp.text
        assert 'intellisource_health_status{component="db"} 0' in body
        assert 'intellisource_health_status{component="redis"} 2' in body
        assert 'intellisource_health_status{component="celery"} 0' in body


# ---------------------------------------------------------------------------
# AC-B003-3  Gauge updates on successive check_health() calls (state flip).
# ---------------------------------------------------------------------------


class TestHealthGaugeStateFlip:
    """Gauge value for a component reflects the most recent check result."""

    @pytest.mark.asyncio
    async def test_gauge_updates_when_component_recovers(self) -> None:
        from intellisource.observability.health import HealthChecker
        from intellisource.observability.metrics import MetricsCollector

        mc = MetricsCollector.get_instance()
        checker = HealthChecker(metrics_collector=mc)

        state = {"ok": False}

        async def _flapping() -> bool:
            return state["ok"]

        checker.register_check("celery", _flapping)

        # First check — component is down
        await checker.check_health()
        assert _gauge(mc, "celery") == 2

        # Component recovers
        state["ok"] = True
        await checker.check_health()
        assert _gauge(mc, "celery") == 0

    @pytest.mark.asyncio
    async def test_gauge_updates_when_component_degrades(self) -> None:
        from intellisource.observability.health import HealthChecker
        from intellisource.observability.metrics import MetricsCollector

        mc = MetricsCollector.get_instance()
        checker = HealthChecker(metrics_collector=mc)

        state = {"ok": True}

        async def _flapping() -> bool:
            return state["ok"]

        checker.register_check("db", _flapping)

        # First check — healthy
        await checker.check_health()
        assert _gauge(mc, "db") == 0

        # DB goes down
        state["ok"] = False
        await checker.check_health()
        assert _gauge(mc, "db") == 2
