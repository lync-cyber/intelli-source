"""Integration tests for R-007: LLMGateway injection into app.state via _lifespan.

Verifies that after lifespan startup:
- app.state.llm_gateway is not None
- GET /api/v1/llm/status returns circuit_state != "UNKNOWN" (i.e. "CLOSED")
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.main import create_app

# ---------------------------------------------------------------------------
# Shared lifespan helper - patches all external I/O so tests are self-contained
# ---------------------------------------------------------------------------


def _make_lifespan_patches() -> tuple[MagicMock, MagicMock, AsyncMock]:
    """Return (mock_db, mock_celery, mock_redis) for patching lifespan I/O."""
    mock_db = MagicMock()
    mock_db.close = AsyncMock()
    mock_celery = MagicMock()
    mock_celery.close = MagicMock()
    mock_redis = AsyncMock()
    # CircuitBreaker calls hgetall to read state; return empty dict -> CLOSED
    mock_redis.hgetall = AsyncMock(return_value={})
    mock_redis.hset = AsyncMock(return_value=None)
    return mock_db, mock_celery, mock_redis


class TestLLMGatewayLifespanInjection:
    """R-007: _lifespan injects LLMGateway into app.state.llm_gateway."""

    @pytest.mark.asyncio
    async def test_startup_sets_llm_gateway_on_app_state(self) -> None:
        """After lifespan startup, app.state.llm_gateway is not None."""
        mock_db, mock_celery, mock_redis = _make_lifespan_patches()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch(
                "intellisource.main.aioredis.from_url",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
        ):
            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                assert hasattr(app.state, "llm_gateway"), (
                    "app.state.llm_gateway must be set during lifespan startup"
                )
                assert app.state.llm_gateway is not None, (
                    "app.state.llm_gateway must not be None after startup"
                )

    @pytest.mark.asyncio
    async def test_llm_gateway_has_circuit_breaker(self) -> None:
        """After lifespan startup, app.state.llm_gateway.circuit_breaker is set."""
        from intellisource.llm.circuit_breaker import CircuitBreaker

        mock_db, mock_celery, mock_redis = _make_lifespan_patches()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch(
                "intellisource.main.aioredis.from_url",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
        ):
            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                gw = app.state.llm_gateway
                assert gw.circuit_breaker is not None
                assert isinstance(gw.circuit_breaker, CircuitBreaker)

    @pytest.mark.asyncio
    async def test_llm_gateway_has_priority_queue(self) -> None:
        """After lifespan startup, app.state.llm_gateway._priority_queue is set."""
        from intellisource.llm.priority_queue import PriorityQueue

        mock_db, mock_celery, mock_redis = _make_lifespan_patches()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch(
                "intellisource.main.aioredis.from_url",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
        ):
            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                gw = app.state.llm_gateway
                assert gw._priority_queue is not None
                assert isinstance(gw._priority_queue, PriorityQueue)

    @pytest.mark.asyncio
    async def test_llm_status_endpoint_returns_closed_not_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GET /api/v1/llm/status returns CLOSED (not UNKNOWN) after injection."""
        monkeypatch.delenv("IS_API_KEY", raising=False)

        mock_db, mock_celery, mock_redis = _make_lifespan_patches()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch(
                "intellisource.main.aioredis.from_url",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
        ):
            from httpx import ASGITransport, AsyncClient

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    resp = await ac.get("/api/v1/llm/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["circuit_state"] != "UNKNOWN", (
            "circuit_state must not be UNKNOWN when llm_gateway is injected"
        )
        assert body["circuit_state"] == "CLOSED"

    @pytest.mark.asyncio
    async def test_llm_gateway_not_injected_gives_unknown(self) -> None:
        """Contrasting: without lifespan injection, status returns UNKNOWN."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from intellisource.api.routers.llm import router as llm_router

        bare_app = FastAPI()
        bare_app.include_router(llm_router, prefix="/api/v1")
        # Deliberately omit app.state.llm_gateway

        transport = ASGITransport(app=bare_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/llm/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["circuit_state"] == "UNKNOWN"
