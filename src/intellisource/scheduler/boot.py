"""Worker-side bootstrap for Celery task wiring (T-075).

Provides session_factory initialization and CeleryTasks construction
that are independent of the FastAPI application lifecycle.
"""

from __future__ import annotations

import os
from typing import Any

from celery.signals import worker_process_init, worker_process_shutdown
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from intellisource.scheduler.tasks import CeleryTasks

_celery_tasks: CeleryTasks | None = None
_worker_engine: AsyncEngine | None = None


def init_worker_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create an independent async session_factory from IS_DATABASE_URL.

    Does not import or access intellisource.main or app.state.db.
    """
    global _worker_engine
    url = os.environ.get("IS_DATABASE_URL")
    if not url:
        raise ValueError("IS_DATABASE_URL must be set for the worker process")
    _worker_engine = create_async_engine(url)
    return async_sessionmaker(
        bind=_worker_engine, class_=AsyncSession, expire_on_commit=False
    )


def build_celery_tasks(
    celery_app: Any,
    agent_runner: Any,
    pipeline_config: Any,
    session_factory: async_sessionmaker[AsyncSession],
) -> CeleryTasks:
    """Instantiate CeleryTasks and register run_pipeline as a Celery task."""
    factory = session_factory

    async def _make_session() -> AsyncSession:
        return factory()

    tasks = CeleryTasks(
        agent_runner=agent_runner,
        pipeline_config=pipeline_config,
        session_factory=_make_session,
    )

    @celery_app.task(name="intellisource.scheduler.run_pipeline")  # type: ignore[untyped-decorator]
    def _run_pipeline_task(
        pipeline_name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        return tasks.run_pipeline(pipeline_name, params)

    return tasks


def worker_init_handler(
    *,
    celery_app: Any = None,
    agent_runner: Any = None,
    pipeline_config: Any = None,
    **_: Any,
) -> None:
    """Celery worker_process_init signal entry point; idempotent singleton."""
    global _celery_tasks
    factory = init_worker_session_factory()
    _celery_tasks = build_celery_tasks(
        celery_app, agent_runner, pipeline_config, factory
    )


def worker_shutdown_handler(**_: Any) -> None:
    """Dispose worker engine on shutdown."""
    global _worker_engine, _celery_tasks
    if _worker_engine is not None:
        import asyncio  # noqa: PLC0415

        try:
            asyncio.run(_worker_engine.dispose())
        except RuntimeError:
            # Already in event loop — best-effort
            pass
        _worker_engine = None
    _celery_tasks = None


def get_celery_tasks() -> CeleryTasks | None:
    """Return the initialized CeleryTasks singleton, or None if not yet wired."""
    return _celery_tasks


if not getattr(worker_process_init, "_intellisource_connected", False):
    worker_process_init.connect(worker_init_handler)
    worker_process_shutdown.connect(worker_shutdown_handler)
    worker_process_init._intellisource_connected = True
