"""Inc2 P0-2: standardised JSON error envelope for every API error.

Domain, framework 4xx (HTTPException / validation) and unhandled errors all
render as the single ``{"error": {...}}`` envelope.
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
async def test_http_exception_renders_unified_envelope() -> None:
    """HTTPException renders the unified envelope, not FastAPI's {"detail"}."""
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/boom-http")
    assert resp.status_code == 404
    assert resp.json() == {"error": {"code": "NotFound", "message": "missing thing"}}


@pytest.mark.asyncio
async def test_request_validation_error_renders_unified_envelope() -> None:
    """Request validation failures use the envelope with the raw errors detail."""
    app = _build_app()

    @app.get("/needs-param")
    async def needs_param(n: int) -> dict[str, int]:  # noqa: ARG001
        return {"n": n}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/needs-param")  # missing required ?n=
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "ValidationError"
    # the original per-field validation errors are preserved under detail
    assert isinstance(err["detail"], list) and err["detail"]
