"""Integration tests for /system endpoints backed by real checkers (T099-4/5)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, Text, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from intellisource.storage.models import Base, LLMCallLog


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
        """/health must never raise even if HealthChecker explodes."""
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

    async def test_missing_checker_is_unhealthy_not_false_green(self) -> None:
        """P1-8: a missing health checker must not report healthy."""
        app = _make_system_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/system/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "unhealthy"
        assert body["checks"]["meta"] == "checker_missing"


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
        assert "version=0.0.4" in resp.headers.get("content-type", "")

    async def test_versioned_legacy_metrics_path_uses_same_collector(self) -> None:
        """P1-8: /api/v1/metrics is backed by MetricsCollector, not a stub."""
        from intellisource.api.routers.system import router as system_router
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector._counters = {"legacy_path_total": 3}
        collector._counter_descriptions = {"legacy_path_total": "Legacy path hits"}
        collector._gauges = {}
        collector._gauge_descriptions = {}
        collector._histograms = {}
        collector._histogram_descriptions = {}

        app = FastAPI()
        app.include_router(system_router, prefix="/api/v1")
        app.state.metrics_collector = collector

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/metrics")

        assert resp.status_code == 200
        assert "legacy_path_total 3" in resp.text


def _remove_pg_only_indexes(base: type) -> None:
    for table in base.metadata.tables.values():
        indexes_to_remove = []
        for idx in table.indexes:
            pg_opts = getattr(idx, "dialect_options", {}).get("postgresql", {})
            if pg_opts.get("using") or pg_opts.get("ops"):
                indexes_to_remove.append(idx)
        for idx in indexes_to_remove:
            table.indexes.discard(idx)


def _set_sqlite_fk_pragma(dbapi_conn: Any, connection_record: Any) -> None:
    del connection_record
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture()
async def sqlite_session() -> AsyncIterator[AsyncSession]:
    """Real SQLite session for route-level LLM stats tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    event.listen(engine.sync_engine, "connect", _set_sqlite_fk_pragma)
    _remove_pg_only_indexes(Base)
    # Coerce PG-only column types to portable SQLite equivalents for create_all.
    # Base.metadata is a process-global shared by every test, so snapshot the
    # originals and restore them in teardown — otherwise the mutation leaks and
    # later tests (e.g. storage.test_models column-type assertions) see JSON
    # where they expect JSONB.
    original_types: dict[tuple[str, str], Any] = {}
    for table in Base.metadata.tables.values():
        for col in table.columns:
            type_name = type(col.type).__name__
            if type_name in {"Vector", "JSONB", "ARRAY"}:
                original_types[(table.name, col.name)] = col.type
                col.type = Text() if type_name == "Vector" else JSON()

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            yield session

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    finally:
        for (table_name, col_name), original in original_types.items():
            Base.metadata.tables[table_name].columns[col_name].type = original
        await engine.dispose()


class TestSystemLLMStatsRealRoute:
    """P1-6: /api/v1/system/llm-stats uses real repository aggregation."""

    async def test_system_llm_stats_reads_real_llm_call_log_rows(
        self, sqlite_session: AsyncSession
    ) -> None:
        from intellisource.api.deps import get_db_session
        from intellisource.api.routers.system import router as system_router

        sqlite_session.add_all(
            [
                LLMCallLog(
                    id=uuid.uuid4(),
                    model="gpt-4o-mini",
                    provider="openai",
                    call_type="chat",
                    input_tokens=100,
                    output_tokens=50,
                    latency_ms=200,
                    input_length=10,
                    output_length=5,
                    status="success",
                    created_at=datetime.now(timezone.utc),
                ),
                LLMCallLog(
                    id=uuid.uuid4(),
                    model="gpt-4o-mini",
                    provider="openai",
                    call_type="chat",
                    input_tokens=20,
                    output_tokens=10,
                    latency_ms=100,
                    input_length=2,
                    output_length=1,
                    status="error",
                    error_message="boom",
                    created_at=datetime.now(timezone.utc),
                ),
            ]
        )
        await sqlite_session.commit()

        app = FastAPI()
        app.include_router(system_router, prefix="/api/v1/system")

        async def _override_session() -> AsyncIterator[AsyncSession]:
            yield sqlite_session

        app.dependency_overrides[get_db_session] = _override_session

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/system/llm-stats",
                params={"period": "day", "model": "gpt-4o-mini", "call_type": "chat"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_calls"] == 2
        assert body["total_tokens"] == 180
        assert body["by_model"][0]["error_rate"] == 0.5


class TestCompositionInstallsObservabilityState:
    """AC-T099-5: composition wires health_checker + metrics + version_manager."""

    def test_install_observability_state_sets_app_state(self) -> None:
        from unittest.mock import patch

        from fastapi import FastAPI as _FastAPI

        from intellisource.composition import _install_observability_state
        from intellisource.observability.metrics import MetricsCollector

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

        assert isinstance(app.state.metrics_collector, MetricsCollector)
        assert app.state.config_version_manager is not None
        assert app.state.config_version_manager.current_version == 0

        # Sanity: patch ensures we did not accidentally re-import.
        _ = patch  # keep import alive for tooling
