"""FastAPI application entry point for IntelliSource."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from starlette.types import Receive, Scope, Send

from intellisource.api.middleware import (
    AuthMiddleware,
    RequestLoggerMiddleware,
    TracingMiddleware,
)
from intellisource.api.routers import (
    contents,
    llm,
    search,
    sources,
    subscriptions,
    system,
    tasks,
)

# ---------------------------------------------------------------------------
# Lifecycle stub functions (tests patch these)
# ---------------------------------------------------------------------------


async def init_db_pool() -> None:
    """Initialise database connection pool."""


async def init_redis() -> None:
    """Initialise Redis connection."""


def init_celery() -> None:
    """Initialise Celery application."""


async def close_db_pool() -> None:
    """Close database connection pool."""


async def close_redis() -> None:
    """Close Redis connection."""


def shutdown_celery() -> None:
    """Shutdown Celery application."""


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[dict[str, Any]]:
    """Manage application startup and shutdown."""
    await init_db_pool()
    await init_redis()
    init_celery()
    yield {}
    await close_db_pool()
    await close_redis()
    shutdown_celery()


# ---------------------------------------------------------------------------
# FastAPI subclass with auto-managed lifespan for test transports
# ---------------------------------------------------------------------------


class _AutoLifespanApp(FastAPI):
    """FastAPI subclass that auto-triggers lifespan for transports that
    do not send ASGI lifespan events (e.g. httpx.ASGITransport).

    When a real ASGI server (uvicorn) is used, the server sends lifespan
    events and the auto-trigger is skipped.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._auto_started: bool = False
        self._auto_cm: Any = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            # Real server manages lifespan; skip auto-management.
            self._auto_started = True
            await super().__call__(scope, receive, send)
            return

        if not self._auto_started:
            self._auto_started = True
            lifespan_ctx = self.router.lifespan_context
            self._auto_cm = lifespan_ctx(self)
            state = await self._auto_cm.__aenter__()
            if state:
                scope.setdefault("state", {}).update(state)

        await super().__call__(scope, receive, send)

    async def shutdown(self) -> None:
        """Explicitly trigger lifespan shutdown (called after test client exits)."""
        if self._auto_cm is not None:
            cm = self._auto_cm
            self._auto_cm = None
            self._auto_started = False
            await cm.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    "AI-powered intelligent information aggregation and distribution platform"
)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = _AutoLifespanApp(
        title="IntelliSource",
        description=_DESCRIPTION,
        version="0.1.0",
        lifespan=_lifespan,
    )

    # Register middleware (order matters: last added = outermost)
    app.add_middleware(TracingMiddleware)
    app.add_middleware(RequestLoggerMiddleware)
    app.add_middleware(AuthMiddleware)

    # Register routers
    app.include_router(sources.router, prefix="/api/v1")
    app.include_router(contents.router, prefix="/api/v1")
    app.include_router(search.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(subscriptions.router, prefix="/api/v1")
    app.include_router(llm.router, prefix="/api/v1")
    app.include_router(system.router, prefix="/api/v1/system")

    # Health endpoints (root-level + API-versioned per AC-T042-6)
    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "healthy"}

    @app.get("/api/v1/health")
    async def health_v1() -> dict[str, Any]:
        return {"status": "healthy"}

    return app
