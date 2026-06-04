"""P3: API correctness & robustness hardening.

Covers the parallel-safe P3 bundle:
- pipeline detail response exposes agent_mode / max_tokens_budget / tool_permissions
- /subscriptions list supports channel + status filters
- /llm/stats and /system/llm-stats share one implementation (compute_llm_stats)
- root /metrics is a real route; Swagger /docs + /openapi.json are auth-exempt
- AuthMiddleware fails closed (503) on an unset IS_API_KEY in production
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from intellisource.api.middleware import PUBLIC_EXACT_PATHS, AuthMiddleware
from intellisource.api.routers.pipelines import _pipeline_to_dict
from intellisource.api.schemas.pipelines import PipelineDetail
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.storage.models import Base
from intellisource.storage.repositories.subscription import SubscriptionRepository

TEST_API_KEY = "p3-secret-key"


# ---------------------------------------------------------------------------
# P3-1: pipeline detail exposes the agent-control fields
# ---------------------------------------------------------------------------


def test_pipeline_to_dict_includes_agent_fields() -> None:
    cfg = PipelineConfig.from_dict(
        {
            "name": "admin-agent",
            "mode": "flexible",
            "steps": [],
            "agent_mode": "process",
            "max_tokens_budget": 16000,
            "tool_permissions": {"distribute": "confirm"},
        }
    )
    d = _pipeline_to_dict(cfg)
    assert d["agent_mode"] == "process"
    assert d["max_tokens_budget"] == 16000
    assert d["tool_permissions"] == {"distribute": "confirm"}

    detail = PipelineDetail.model_validate(d)
    assert detail.agent_mode == "process"
    assert detail.max_tokens_budget == 16000
    assert detail.tool_permissions == {"distribute": "confirm"}


# ---------------------------------------------------------------------------
# P3-5a: subscription list channel / status filters
# ---------------------------------------------------------------------------


def _set_sqlite_fk_pragma(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    event.listen(eng.sync_engine, "connect", _set_sqlite_fk_pragma)
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if type(col.type).__name__ == "Vector":
                col.type = Text()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
    db = factory()
    yield db
    await db.close()
    await eng.dispose()


async def _seed_sub(
    session: AsyncSession, name: str, channel: str, status: str
) -> None:
    repo = SubscriptionRepository(session)
    row = await repo.create(
        name=name, channel=channel, channel_config={}, match_rules={}
    )
    row.status = status
    await session.flush()


@pytest.mark.asyncio
async def test_subscription_list_filters_by_channel(session: AsyncSession) -> None:
    await _seed_sub(session, "a", "email", "active")
    await _seed_sub(session, "b", "wework", "active")
    await session.commit()

    repo = SubscriptionRepository(session)
    result = await repo.list(channel="email")
    names = {s.name for s in result["items"]}
    assert names == {"a"}


@pytest.mark.asyncio
async def test_subscription_list_filters_by_status(session: AsyncSession) -> None:
    await _seed_sub(session, "a", "email", "active")
    await _seed_sub(session, "b", "email", "paused")
    await session.commit()

    repo = SubscriptionRepository(session)
    active = await repo.list(status="active")
    assert {s.name for s in active["items"]} == {"a"}
    paused = await repo.list(status="paused")
    assert {s.name for s in paused["items"]} == {"b"}


@pytest.mark.asyncio
async def test_subscription_list_channel_and_status_combined(
    session: AsyncSession,
) -> None:
    await _seed_sub(session, "a", "email", "active")
    await _seed_sub(session, "b", "email", "paused")
    await _seed_sub(session, "c", "wework", "active")
    await session.commit()

    repo = SubscriptionRepository(session)
    result = await repo.list(channel="email", status="active")
    assert {s.name for s in result["items"]} == {"a"}


# ---------------------------------------------------------------------------
# P3-5b: /llm/stats and /system/llm-stats share one implementation
# ---------------------------------------------------------------------------


def test_llm_stats_is_single_implementation() -> None:
    from intellisource.api.routers.llm import compute_llm_stats as canonical
    from intellisource.api.routers.system import compute_llm_stats as alias

    assert alias is canonical


@pytest.mark.asyncio
async def test_system_llm_stats_delegates_to_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake(session: Any, *, period: str, model: Any, call_type: Any) -> Any:
        captured.update(period=period, model=model, call_type=call_type)
        return {"delegated": True}

    monkeypatch.setattr("intellisource.api.routers.system.compute_llm_stats", _fake)
    from intellisource.api.routers.system import system_llm_stats

    result = await system_llm_stats(
        period="week", model="gpt-x", call_type="chat", session=object()
    )
    assert result == {"delegated": True}
    assert captured == {"period": "week", "model": "gpt-x", "call_type": "chat"}


# ---------------------------------------------------------------------------
# P3-5c/d: root /metrics route + Swagger /docs auth exemption
# ---------------------------------------------------------------------------


def test_root_metrics_route_registered() -> None:
    from intellisource.main import create_app

    paths = {getattr(r, "path", None) for r in create_app().routes}
    assert "/metrics" in paths
    assert "/api/v1/metrics" in paths


def test_docs_paths_are_public() -> None:
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert p in PUBLIC_EXACT_PATHS


@pytest.mark.asyncio
async def test_openapi_json_exempt_from_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Swagger schema loads without a key even when IS_API_KEY is set."""
    monkeypatch.setenv("IS_API_KEY", TEST_API_KEY)
    app = FastAPI()

    @app.get("/api/v1/thing")
    async def thing() -> dict[str, str]:
        return {"ok": "yes"}

    app.add_middleware(AuthMiddleware)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        public = await client.get("/openapi.json")
        guarded = await client.get("/api/v1/thing")
    assert public.status_code == 200
    assert guarded.status_code == 401  # control: non-exempt still requires key


# ---------------------------------------------------------------------------
# P3-4: AuthMiddleware fails closed on unset IS_API_KEY in production
# ---------------------------------------------------------------------------


def _auth_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/sources")
    async def sources() -> dict[str, str]:
        return {"sources": "list"}

    app.add_middleware(AuthMiddleware)
    return app


@pytest.mark.asyncio
async def test_unset_key_in_production_rejects_with_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IS_API_KEY", "")
    monkeypatch.setenv("ENV", "production")
    transport = ASGITransport(app=_auth_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/sources")
    assert resp.status_code == 503
    assert "error" in resp.json()


@pytest.mark.asyncio
async def test_unset_key_in_production_still_allows_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IS_API_KEY", "")
    monkeypatch.setenv("ENV", "production")
    transport = ASGITransport(app=_auth_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_unset_key_in_dev_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IS_API_KEY", "")
    monkeypatch.delenv("ENV", raising=False)
    transport = ASGITransport(app=_auth_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/sources")
    assert resp.status_code == 200
