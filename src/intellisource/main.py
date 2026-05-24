"""FastAPI application entry point for IntelliSource."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from intellisource.api.middleware import (
    AuthMiddleware,
    RequestLoggerMiddleware,
    TracingMiddleware,
)
from intellisource.api.routers import (
    clusters,
    contents,
    llm,
    pipelines,
    search,
    sources,
    subscriptions,
    system,
    tasks,
    webhooks,
)
from intellisource.composition import build_api_composition
from intellisource.config.loader import ConfigLoader, ConfigWatcher
from intellisource.config.validator import ConfigValidator
from intellisource.storage.database import DatabaseManager
from intellisource.storage.repositories.source import SourceRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (populated by init_* functions)
# ---------------------------------------------------------------------------

_redis_client: Any = None


# ---------------------------------------------------------------------------
# Lifecycle functions
# ---------------------------------------------------------------------------


async def init_redis() -> None:
    """Initialise Redis connection via aioredis.from_url."""
    global _redis_client
    redis_url = os.environ.get("IS_REDIS_URL", "redis://localhost:6379/0")
    _redis_client = await aioredis.from_url(redis_url)


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:
            pass
        _redis_client = None


# ---------------------------------------------------------------------------
# Config change callback (db_manager injected at lifespan startup)
# ---------------------------------------------------------------------------

_db_manager: DatabaseManager | None = None
_config_version_manager: Any = None


async def on_config_change(path: str) -> None:
    """Handle a changed config file: load → validate → upsert each source.

    Records a snapshot via the lifespan-installed `ConfigVersionManager` so
    `record_version` history mirrors the upserted sources (AC-T099-6).
    """
    loader = ConfigLoader()
    validator = ConfigValidator()
    try:
        configs = loader.load_file(path)
    except Exception:
        logger.exception("ConfigLoader.load_file failed for %s", path)
        return
    if _db_manager is None:
        logger.warning(
            "on_config_change called before db_manager is initialised; skipping upsert"
        )
        return
    validated_batch = []
    for cfg in configs:
        try:
            validated = validator.validate(cfg)
            async with _db_manager.get_session() as session:
                repo = SourceRepository(session)
                await repo.upsert(validated)
            validated_batch.append(validated)
        except Exception:
            logger.exception("Validation or upsert failed for config in %s", path)

    version_manager = _config_version_manager
    if version_manager is not None and validated_batch:
        try:
            version_manager.record_version(validated_batch)
        except Exception:
            logger.exception("ConfigVersionManager.record_version failed")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

_SOURCE_CONFIG_DIR: str = os.environ.get("IS_SOURCE_CONFIG_DIR", "config/sources")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[dict[str, Any]]:
    """Manage application startup and shutdown."""
    global _db_manager, _config_version_manager
    db = DatabaseManager()
    _db_manager = db
    app.state.db = db
    watcher = ConfigWatcher(config_dir=_SOURCE_CONFIG_DIR, callback=on_config_change)
    app.state.config_watcher = watcher
    watcher_task = asyncio.create_task(watcher.start())
    app.state.config_watcher_task = watcher_task
    try:
        await init_redis()
        # Single composition root for the API process — installs
        # app.state.celery_app (= module-level singleton), .llm_gateway,
        # .pipeline_loader, and .agent_runner.
        build_api_composition(app, db, _redis_client)
        _config_version_manager = getattr(app.state, "config_version_manager", None)
        yield {}
    finally:
        await watcher.stop()
        await db.close()
        _db_manager = None
        _config_version_manager = None
        await close_redis()


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
    app.include_router(clusters.router, prefix="/api/v1")
    app.include_router(contents.router, prefix="/api/v1")
    app.include_router(search.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(subscriptions.router, prefix="/api/v1")
    app.include_router(llm.router, prefix="/api/v1")
    app.include_router(system.router, prefix="/api/v1/system")
    app.include_router(webhooks.router, prefix="/api/v1")
    app.include_router(pipelines.router, prefix="/api/v1")

    # Health endpoints (root-level + API-versioned per AC-T042-6)
    @app.get("/health")
    async def health_root(request: Request) -> dict[str, Any]:
        return await system.health_payload(request)

    @app.get("/api/v1/health")
    async def health_v1(request: Request) -> dict[str, Any]:
        return await system.health_payload(request)

    @app.get("/api/v1/metrics")
    async def metrics_v1(request: Request) -> PlainTextResponse:
        return system.metrics_response(request)

    return app
