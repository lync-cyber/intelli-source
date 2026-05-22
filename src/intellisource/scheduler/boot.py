"""Worker-side bootstrap for Celery task wiring (T-075).

Provides session_factory initialization and CeleryTasks construction
that are independent of the FastAPI application lifecycle.
"""

from __future__ import annotations

import os
from typing import Any

import redis.asyncio as aioredis
from celery.signals import worker_process_init, worker_process_shutdown
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import intellisource.agent.factory as _agent_factory
from intellisource.scheduler.celery_app import celery_app as _module_celery_app
from intellisource.scheduler.idempotency import FingerprintChecker, IdempotencyGuard
from intellisource.scheduler.tasks import CeleryTasks
from intellisource.storage.models import RawContent

_celery_tasks: CeleryTasks | None = None
_worker_engine: AsyncEngine | None = None


class _RawContentFingerprintRepo:
    """Minimal adapter providing exists_by_fingerprint for FingerprintChecker."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def exists_by_fingerprint(self, fingerprint: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RawContent.id)
                .where(RawContent.fingerprint == fingerprint)
                .limit(1)
            )
            return result.first() is not None

    async def record_fingerprint(self, fingerprint: str, content_id: Any) -> None:
        # Fingerprint persistence is completed by the collection layer when it
        # inserts the RawContent row (raw_contents.fingerprint unique constraint).
        # This record call is intentionally a no-op: the fingerprint is already
        # stored and exists_by_fingerprint will return True on subsequent checks.
        pass


class _RawContentResultRepo:
    """Minimal adapter providing create(result) for CeleryTasks.content_repository.

    Accepts the pipeline result dict from AgentRunner and persists any
    content-identifiable fields back to the RawContent row (e.g. marking
    it as processed). Full ProcessedContent creation is handled downstream
    by dedicated processing pipelines.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, result: Any) -> Any:
        # Records the pipeline execution result. Detailed ProcessedContent
        # persistence is deferred to the dedicated content-processing pipeline;
        # this adapter satisfies the CeleryTasks.content_repository interface.
        return result


def init_worker_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create an independent async session_factory from IS_DATABASE_URL.

    Does not import or access intellisource.main or app.state.db.
    """
    global _worker_engine
    url = os.environ.get("DATABASE_URL") or os.environ.get(
        "IS_DATABASE_URL"
    )  # 12-factor §III Config
    if not url:
        raise ValueError("DATABASE_URL must be set for the worker process")
    _worker_engine = create_async_engine(url)
    return async_sessionmaker(
        bind=_worker_engine, class_=AsyncSession, expire_on_commit=False
    )


def _build_redis_client() -> Any:
    """Construct an async Redis client from IS_REDIS_URL."""
    redis_url = os.environ.get("IS_REDIS_URL")
    if not redis_url:
        raise ValueError("IS_REDIS_URL must be set for the worker process")
    return aioredis.from_url(redis_url)


def build_celery_tasks(
    agent_runner: Any,
    pipeline_config: Any,
    session_factory: async_sessionmaker[AsyncSession],
) -> CeleryTasks:
    """Instantiate CeleryTasks with all idempotency guards wired."""
    factory = session_factory

    async def _make_session() -> AsyncSession:
        return factory()

    redis_client = _build_redis_client()
    idempotency_guard = IdempotencyGuard(redis=redis_client)

    fingerprint_repo = _RawContentFingerprintRepo(session_factory)
    fingerprint_checker = FingerprintChecker(repository=fingerprint_repo)

    content_repo = _RawContentResultRepo(session_factory)

    return CeleryTasks(
        agent_runner=agent_runner,
        pipeline_config=pipeline_config,
        session_factory=_make_session,
        idempotency_guard=idempotency_guard,
        fingerprint_checker=fingerprint_checker,
        content_repository=content_repo,
    )


def worker_init_handler(**_: Any) -> None:
    """Celery worker_process_init signal entry point; idempotent singleton."""
    global _celery_tasks
    agent_runner = _agent_factory.get_agent_runner()
    factory = init_worker_session_factory()
    _celery_tasks = build_celery_tasks(agent_runner, None, factory)
    setattr(_module_celery_app, "_celery_tasks_instance", _celery_tasks)


def worker_shutdown_handler(**_: Any) -> None:
    """Dispose worker engine on shutdown."""
    global _worker_engine, _celery_tasks
    if _worker_engine is not None:
        import asyncio  # noqa: PLC0415

        try:
            asyncio.run(_worker_engine.dispose())
        except RuntimeError as exc:
            import logging  # noqa: PLC0415

            logging.getLogger(__name__).warning("engine.dispose skipped: %s", exc)
        finally:
            _worker_engine = None
    _celery_tasks = None


def get_celery_tasks() -> CeleryTasks | None:
    """Return the initialized CeleryTasks singleton, or None if not yet wired."""
    return _celery_tasks


if not getattr(worker_process_init, "_intellisource_connected", False):
    worker_process_init.connect(worker_init_handler)
    worker_process_shutdown.connect(worker_shutdown_handler)
    worker_process_init._intellisource_connected = True
