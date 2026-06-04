"""FastAPI application entry point for IntelliSource."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from intellisource.api.errors import install_exception_handlers
from intellisource.api.middleware import (
    AuthMiddleware,
    RequestLoggerMiddleware,
    TracingMiddleware,
)
from intellisource.api.openapi import install_openapi
from intellisource.api.routers import (
    agent,
    clusters,
    contents,
    distribution,
    llm,
    pipelines,
    search,
    sources,
    subscriptions,
    system,
    tasks,
    topics,
    webhooks,
)
from intellisource.api.schemas.observability import HealthResponse
from intellisource.composition import build_api_composition
from intellisource.config.loader import ConfigLoader, ConfigWatcher
from intellisource.config.validator import ConfigValidator
from intellisource.core.settings import get_settings, load_provider_env
from intellisource.observability.logging import get_logger, setup_logging
from intellisource.pipeline.definition_service import PipelineDefinitionService
from intellisource.storage.database import DatabaseManager
from intellisource.storage.repositories.source import SourceRepository

logger = get_logger(__name__)

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
    redis_url = get_settings().redis_url or "redis://localhost:6379/0"
    _redis_client = await aioredis.from_url(redis_url)


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception as exc:
            logger.warning("redis client close failed", exc_info=exc)
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

_API_KEY_PLACEHOLDER = "change-me-in-production"


def _collect_startup_warnings() -> list[str]:
    """Scan environment and filesystem for missing or misconfigured items.

    Returns human-readable warning strings.  The IS_API_KEY placeholder check
    is intentionally NOT included here — that check raises at startup instead.
    """
    warnings: list[str] = []

    api_key = get_settings().api_key
    if not api_key:
        warnings.append(
            "IS_API_KEY not set — all /api/v1/* requests skip auth (dev only)"
        )

    src_dir = get_settings().source_config_dir or "config/sources"
    if not os.path.isdir(src_dir):
        warnings.append(
            f"sources directory {src_dir!r} missing — no sources will be loaded"
            " (run: mkdir -p config/sources && cp config/sources.example.yaml"
            " config/sources/sources.yaml)"
        )
    else:
        yamls = [
            f
            for f in os.listdir(src_dir)
            if f.endswith((".yaml", ".yml"))
            and os.path.isfile(os.path.join(src_dir, f))
        ]
        if not yamls:
            warnings.append(
                f"sources directory {src_dir!r} contains no YAML files"
                " — no sources will be loaded"
            )

    llm_keys = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "AZURE_API_KEY",
    ]
    if not any(os.environ.get(k) for k in llm_keys):
        warnings.append(
            "no LLM provider key set (OPENAI_API_KEY / ANTHROPIC_API_KEY /"
            " DEEPSEEK_API_KEY) — LLM pipeline steps will fail"
        )

    for channel, env_vars in [
        ("wechat", ["IS_WECHAT_APP_ID", "IS_WECHAT_APP_SECRET"]),
        (
            "wework",
            ["IS_WEWORK_CORP_ID", "IS_WEWORK_CORP_SECRET", "IS_WEWORK_AGENT_ID"],
        ),
        ("email", ["IS_SMTP_HOST", "IS_SMTP_USER", "IS_SMTP_PASSWORD"]),
    ]:
        missing = [v for v in env_vars if not os.environ.get(v)]
        if missing:
            warnings.append(
                f"channel {channel!r} disabled: {', '.join(missing)} not set"
            )

    return warnings


async def _seed_pipeline_definitions(db: DatabaseManager) -> None:
    """Import YAML pipeline seeds into the DB (system of record) on startup.

    Idempotent and non-destructive (see ``PipelineDefinitionService.seed_from_yaml``).
    A failure here must not abort startup — the worker run path falls back to
    the YAML seed files when a definition is absent from the database.
    """
    try:
        async with db.get_session() as session:
            created = await PipelineDefinitionService(session).seed_from_yaml()
        if created:
            logger.info("seeded %d pipeline definition(s) from yaml", created)
    except Exception:
        logger.exception("pipeline seed_from_yaml failed; continuing startup")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[dict[str, Any]]:
    """Manage application startup and shutdown."""
    global _db_manager, _config_version_manager
    load_provider_env()
    setup_logging()

    api_key = get_settings().api_key
    if api_key == _API_KEY_PLACEHOLDER:
        raise RuntimeError(
            "IS_API_KEY is set to the default placeholder"
            f" {_API_KEY_PLACEHOLDER!r} — set a real secret before starting."
            ' Hint: python -c "import secrets; print(secrets.token_hex(32))"'
        )

    startup_warnings = _collect_startup_warnings()
    for w in startup_warnings:
        logger.warning("startup: %s", w)
    app.state.missing_config = startup_warnings

    db = DatabaseManager()
    _db_manager = db
    app.state.db = db
    source_config_dir = get_settings().source_config_dir or "config/sources"
    watcher = ConfigWatcher(config_dir=source_config_dir, callback=on_config_change)
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
        await _seed_pipeline_definitions(db)
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

    # Standard error envelope for domain + unhandled errors; X-API-Key surfaced
    # as an OpenAPI security scheme (enforcement stays in AuthMiddleware).
    install_exception_handlers(app)
    install_openapi(app)

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
    app.include_router(topics.router, prefix="/api/v1")
    app.include_router(distribution.router, prefix="/api/v1")
    app.include_router(agent.router, prefix="/api/v1")

    # Health endpoints (root-level + API-versioned per AC-T042-6)
    @app.get("/health", response_model=HealthResponse)
    async def health_root(request: Request) -> dict[str, Any]:
        return await system.health_payload(request)

    @app.get("/api/v1/health", response_model=HealthResponse)
    async def health_v1(request: Request) -> dict[str, Any]:
        return await system.health_payload(request)

    @app.get("/api/v1/metrics")
    async def metrics_v1(request: Request) -> PlainTextResponse:
        return system.metrics_response(request)

    return app
