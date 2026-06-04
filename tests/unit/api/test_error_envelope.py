"""Inc2 P0-2: standardised JSON error envelope for domain + unhandled errors.

The envelope is additive — HTTPException keeps FastAPI's {"detail": ...} shape.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from intellisource.api.errors import install_exception_handlers
from intellisource.core.errors import DistributorError, PipelineError


def _build_app() -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/boom-pipeline")
    async def boom_pipeline() -> dict[str, str]:
        raise PipelineError("pipeline exploded", recovery_hint="retry later")

    @app.get("/boom-distributor")
    async def boom_distributor() -> dict[str, str]:
        raise DistributorError("channel down")

    @app.get("/boom-generic")
    async def boom_generic() -> dict[str, str]:
        raise RuntimeError("unexpected")

    @app.get("/boom-http")
    async def boom_http() -> dict[str, str]:
        raise HTTPException(status_code=404, detail="missing thing")

    return app


@pytest.mark.asyncio
async def test_domain_error_returns_envelope_with_category_status() -> None:
    """UNRECOVERABLE PipelineError → 500 + full envelope."""
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/boom-pipeline")
    assert resp.status_code == 500
    body = resp.json()
    assert set(body) == {"error"}
    err = body["error"]
    assert err["code"] == "PipelineError"
    assert err["message"] == "pipeline exploded"
    assert err["category"] == "UNRECOVERABLE"
    assert err["recovery_hint"] == "retry later"


@pytest.mark.asyncio
async def test_transient_domain_error_maps_to_503() -> None:
    """RECOVERABLE_TRANSIENT DistributorError → 503."""
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/boom-distributor")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "DistributorError"


@pytest.mark.asyncio
async def test_unhandled_exception_returns_500_envelope() -> None:
    """A bare RuntimeError → 500 + envelope with a generic code."""
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://t",
    ) as client:
        resp = await client.get("/boom-generic")
    assert resp.status_code == 500
    err = resp.json()["error"]
    assert err["code"] == "InternalServerError"
    assert err["message"]


@pytest.mark.asyncio
async def test_http_exception_keeps_detail_contract() -> None:
    """Additive guard: HTTPException must still render FastAPI's {"detail": ...}."""
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/boom-http")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "missing thing"}
