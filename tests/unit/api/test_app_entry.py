"""Tests for T-045: FastAPI application entry point and deployment.

Covers:
  AC-065:    /docs provides OpenAPI/Swagger documentation automatically
  AC-T045-1: main.py registers all route groups and middleware
  AC-T045-2: App startup initialises database pool, Redis connection, Celery app
  AC-T045-3: App shutdown releases all resources correctly
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Import guard: create_app may not exist yet during RED phase.
# ---------------------------------------------------------------------------
try:
    from intellisource.main import create_app  # type: ignore[import-untyped]
except ImportError:
    create_app = None  # type: ignore[assignment]

_MODULE_MISSING = create_app is None

_SKIP_REASON = "intellisource.main.create_app not implemented"

# ---------------------------------------------------------------------------
# Expected route prefixes and middleware (from dev-plan / architecture)
# ---------------------------------------------------------------------------

_EXPECTED_ROUTE_PREFIXES = [
    "/api/v1/sources",
    "/api/v1/contents",
    "/api/v1/search",
    "/api/v1/tasks",
    "/api/v1/subscriptions",
    "/api/v1/llm",
    "/api/v1/system",
]

_EXPECTED_MIDDLEWARE_NAMES = [
    "AuthMiddleware",
    "RequestLoggerMiddleware",
    "TracingMiddleware",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_all_route_paths(app: FastAPI) -> set[str]:
    """Extract all registered route paths from a FastAPI application."""
    paths: set[str] = set()
    for route in app.routes:
        if hasattr(route, "path"):
            paths.add(route.path)
    return paths


# ===========================================================================
# AC-065: OpenAPI / Swagger documentation
# ===========================================================================


class TestOpenAPIDocs:
    """Verify that /docs and /openapi.json are served automatically."""

    @pytest.mark.asyncio
    async def test_docs_endpoint_returns_200(self) -> None:
        """AC-065: GET /docs returns HTTP 200 (Swagger UI)."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/docs")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi_json_returns_200_with_paths(self) -> None:
        """AC-065: GET /openapi.json returns 200 and contains paths."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        body = resp.json()
        assert "paths" in body
        assert len(body["paths"]) > 0, "OpenAPI spec should contain at least one path"


# ===========================================================================
# AC-T045-1: Route groups and middleware registration
# ===========================================================================


class TestRouteRegistration:
    """Verify that create_app registers all expected routers."""

    @pytest.mark.asyncio
    async def test_all_expected_route_prefixes_registered(self) -> None:
        """AC-T045-1: App includes routes for sources, contents, search,
        tasks, subscriptions, llm, and system."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = create_app()
        registered_paths = _get_all_route_paths(app)
        for prefix in _EXPECTED_ROUTE_PREFIXES:
            matching = [p for p in registered_paths if p.startswith(prefix)]
            assert matching, (
                f"No routes found with prefix '{prefix}'. "
                f"Registered paths: {sorted(registered_paths)}"
            )

    @pytest.mark.asyncio
    async def test_middleware_classes_registered(self) -> None:
        """AC-T045-1: App registers Auth, RequestLogger, and Tracing middleware."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = create_app()
        middleware_class_names = [
            m.cls.__name__ for m in app.user_middleware if hasattr(m, "cls")
        ]
        for expected_name in _EXPECTED_MIDDLEWARE_NAMES:
            assert expected_name in middleware_class_names, (
                f"Middleware '{expected_name}' not registered. "
                f"Found: {middleware_class_names}"
            )

    @pytest.mark.asyncio
    async def test_health_endpoint_accessible(self) -> None:
        """AC-T045-1: /health endpoint is accessible and returns 200."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_app_returns_fastapi_instance(self) -> None:
        """AC-T045-1: create_app() returns a FastAPI instance."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = create_app()
        assert isinstance(app, FastAPI)


# ===========================================================================
# AC-T045-2: Startup initialisation
# ===========================================================================


class TestStartupInitialisation:
    """Verify that app startup initialises database, Redis, and Celery."""

    @pytest.mark.asyncio
    async def test_app_has_lifespan_handler(self) -> None:
        """AC-T045-2: App has a lifespan context manager configured."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = create_app()
        # FastAPI lifespan is stored in app.router.lifespan_context
        lifespan = getattr(app.router, "lifespan_context", None)
        assert lifespan is not None, (
            "App should have a lifespan context manager for startup/shutdown"
        )

    @pytest.mark.asyncio
    async def test_startup_initialises_db_redis_celery(self) -> None:
        """AC-T045-2: Startup triggers database pool, Redis, and Celery init."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        app = create_app()

        # Patch the initialisation functions that should be called on startup
        with (
            patch("intellisource.main.init_db_pool", new_callable=AsyncMock) as mock_db,
            patch(
                "intellisource.main.init_redis", new_callable=AsyncMock
            ) as mock_redis,
            patch(
                "intellisource.main.init_celery", new_callable=MagicMock
            ) as mock_celery,
        ):
            # Trigger lifespan startup by entering the ASGI app lifecycle
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                await client.get("/health")

            # Verify all init functions were called during startup
            mock_db.assert_called_once()
            mock_redis.assert_called_once()
            mock_celery.assert_called_once()


# ===========================================================================
# AC-T045-3: Shutdown resource release
# ===========================================================================


class TestShutdownResourceRelease:
    """Verify that app shutdown releases database, Redis, and Celery resources."""

    @pytest.mark.asyncio
    async def test_shutdown_releases_resources(self) -> None:
        """AC-T045-3: Shutdown triggers cleanup for db pool, Redis, Celery."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        app = create_app()

        with (
            patch(
                "intellisource.main.close_db_pool", new_callable=AsyncMock
            ) as mock_close_db,
            patch(
                "intellisource.main.close_redis", new_callable=AsyncMock
            ) as mock_close_redis,
            patch(
                "intellisource.main.shutdown_celery", new_callable=MagicMock
            ) as mock_shutdown_celery,
            # Also patch startup functions so they don't fail
            patch("intellisource.main.init_db_pool", new_callable=AsyncMock),
            patch("intellisource.main.init_redis", new_callable=AsyncMock),
            patch("intellisource.main.init_celery", new_callable=MagicMock),
        ):
            # Enter and exit the ASGI lifecycle to trigger startup+shutdown
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                await client.get("/health")

            # Explicitly trigger shutdown (auto-lifespan defers cleanup)
            await app.shutdown()

            # After shutdown, cleanup should have been called
            mock_close_db.assert_called_once()
            mock_close_redis.assert_called_once()
            mock_shutdown_celery.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_yields_correctly(self) -> None:
        """AC-T045-3: Lifespan context manager yields (startup) then
        cleans up (shutdown) without errors."""
        if _MODULE_MISSING:
            pytest.fail(_SKIP_REASON)

        app = create_app()
        lifespan = getattr(app.router, "lifespan_context", None)
        assert lifespan is not None, "App must have a lifespan context manager"

        # Patch all init/close functions to avoid real connections
        with (
            patch("intellisource.main.init_db_pool", new_callable=AsyncMock),
            patch("intellisource.main.init_redis", new_callable=AsyncMock),
            patch("intellisource.main.init_celery", new_callable=MagicMock),
            patch("intellisource.main.close_db_pool", new_callable=AsyncMock),
            patch("intellisource.main.close_redis", new_callable=AsyncMock),
            patch("intellisource.main.shutdown_celery", new_callable=MagicMock),
        ):
            # Directly invoke the lifespan to confirm it yields
            async with lifespan(app) as state:
                # After yield the app should be in "running" state
                # state may be None or a dict -- either is acceptable
                pass
            # If we reach here without error, shutdown completed successfully
