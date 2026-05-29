"""Worker-side bootstrap for Celery task wiring (T-075).

Provides session_factory initialization and CeleryTasks construction
that are independent of the FastAPI application lifecycle.
"""

from __future__ import annotations

from typing import Any

from celery.signals import beat_init, worker_process_init, worker_process_shutdown
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from intellisource.composition import build_worker_composition
from intellisource.core.settings import get_settings
from intellisource.observability.logging import get_logger, setup_logging

# Import signals module for its side-effect: registering task_prerun /
# task_postrun / task_failure handlers (F-22 metrics + F-23 trace_id).
from intellisource.scheduler import signals as _signals_module  # noqa: F401
from intellisource.scheduler.celery_app import celery_app as _module_celery_app
from intellisource.scheduler.lazy_redis import LazyLoopRedis

# Public re-export so `celery -A intellisource.scheduler.boot worker` finds
# the app. boot.py is the canonical worker entry point (registers
# worker_process_init/shutdown signals + composition graph). The internal
# `_module_celery_app` alias is preserved for clarity inside the signal
# handlers that mutate the celery app instance.
celery_app = _module_celery_app
from intellisource.scheduler.idempotency import (  # noqa: E402 — defer until celery_app re-export is bound
    FingerprintChecker,
    IdempotencyGuard,
)
from intellisource.scheduler.tasks import (  # noqa: E402 — defer until celery_app re-export is bound
    CeleryTasks,
)
from intellisource.storage.models import (  # noqa: E402 — defer until celery_app re-export is bound
    RawContent,
)

logger = get_logger(__name__)

_celery_tasks: CeleryTasks | None = None
_worker_engine: AsyncEngine | None = None


class _RawContentFingerprintRepo:
    """FingerprintChecker adapter backed by RawContent.fingerprint.

    Persistence protocol (see arch-intellisource-v1-modules#§M-002 内容指纹持久化协议):
    fingerprint write responsibility lives in the M-002 collection layer — the
    collector inserts RawContent with fingerprint set, and the DB unique constraint
    handles dedup. This adapter exposes exists_by_fingerprint() over that column
    and intentionally keeps record_fingerprint() as a no-op so the
    FingerprintChecker contract stays stable across future protocol changes.
    """

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
        # No-op by design: see class docstring + arch M-002 fingerprint protocol.
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
        if not isinstance(result, dict):
            return result
        content_id_val = result.get("content_id")
        if not content_id_val:
            return result
        try:
            import uuid as _uuid_mod  # noqa: PLC0415
            from datetime import datetime, timezone  # noqa: PLC0415

            raw_id = _uuid_mod.UUID(str(content_id_val))
            async with self._session_factory() as session:
                row = (
                    await session.execute(
                        select(RawContent).where(RawContent.id == raw_id).limit(1)
                    )
                ).scalar_one_or_none()
                if row is not None:
                    row.status = "processed"
                    row.processed_at = datetime.now(tz=timezone.utc)
                    await session.commit()
        except Exception as exc:
            logger.warning(
                "_RawContentResultRepo.create: failed to persist status for %s: %s",
                content_id_val,
                exc,
                exc_info=True,
            )
        return result


def init_worker_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create an independent async session_factory from IS_DATABASE_URL.

    Uses ``poolclass=NullPool`` so each session checkout opens a fresh DB
    connection. Celery prefork worker tasks drive coroutines via
    ``asyncio.run()``: each invocation opens a new event loop, so any
    connection pool that was bound to a prior loop is dead. NullPool
    avoids that by not pooling at all.

    Does not import or access intellisource.main or app.state.db.
    """
    global _worker_engine
    settings = get_settings()
    url = settings.database_url or settings.is_database_url  # 12-factor §III Config
    if not url:
        raise ValueError("DATABASE_URL must be set for the worker process")
    _worker_engine = create_async_engine(url, poolclass=NullPool)
    return async_sessionmaker(
        bind=_worker_engine, class_=AsyncSession, expire_on_commit=False
    )


def _build_redis_client() -> Any:
    """Construct a per-loop aioredis client from IS_REDIS_URL.

    Returns a ``LazyLoopRedis`` wrapper that caches one ``aioredis.Redis``
    per running event loop, so worker tasks calling
    ``_run_sync(asyncio.run(coro))`` repeatedly never reuse a client whose
    connection pool was bound to an already-closed loop.
    """
    redis_url = get_settings().redis_url
    if not redis_url:
        raise ValueError("IS_REDIS_URL must be set for the worker process")
    return LazyLoopRedis(redis_url)


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
    """Celery worker_process_init signal entry point.

    Assembles the full composition graph via
    `intellisource.composition.build_worker_composition` and installs the
    resulting `CeleryTasks` instance on the module-level Celery singleton
    so the @celery_app.task body can reach it.

    Idempotent across repeated signal firings: if `_celery_tasks` is already
    set (e.g. signal fires twice in pool restart / test fixture scenarios)
    the handler returns early without re-creating engines or redis clients.
    Reset via `worker_shutdown_handler` (or `_celery_tasks = None` in tests)
    before re-invoking.

    Beat sync (AC-T100-2): after composition is built, walk the DB `Source`
    rows to populate `SchedulerManager`, then project that state onto
    `celery_app.conf.beat_schedule` via `sync_beat_schedules`. Empty DB or
    sources with null `schedule_interval` log a warning rather than raising
    so the worker still boots when no schedules are configured.
    """
    global _celery_tasks
    # Configure logging per worker process before the composition idempotency
    # guard: with worker_hijack_root_logger=False, Celery no longer installs a
    # root handler, so a child that short-circuits below would otherwise run
    # with an unconfigured root logger and drop every INFO line (trace_id=).
    setup_logging()
    if _celery_tasks is not None:
        return
    factory = init_worker_session_factory()
    redis_client = _build_redis_client()
    composition = build_worker_composition(
        session_factory=factory,
        redis_client=redis_client,
    )
    _celery_tasks = build_celery_tasks(
        composition.agent_runner,
        composition.pipeline_loader,
        factory,
    )
    setattr(_module_celery_app, "_celery_tasks_instance", _celery_tasks)

    _bootstrap_beat_schedule(factory)


def _bootstrap_beat_schedule(factory: async_sessionmaker[AsyncSession]) -> None:
    """Populate SchedulerManager from Source rows and write to beat_schedule.

    Exposed as a helper so unit tests can exercise the boot-time sync path
    without spinning up a Celery worker. Beat sync is gated by the
    ``IS_BEAT_DISABLED`` env flag to allow workers that never need to act
    as Beat producers (e.g. CI test workers) to skip the DB walk entirely.
    """
    import asyncio  # noqa: PLC0415

    from intellisource.scheduler.beat_sync import (  # noqa: PLC0415
        populate_scheduler_from_sources,
        sync_beat_schedules,
    )
    from intellisource.scheduler.state_machine import (  # noqa: PLC0415
        SchedulerManager,
    )

    logger = get_logger(__name__)

    if get_settings().beat_disabled == "1":
        logger.info("IS_BEAT_DISABLED=1 — skipping Beat schedule sync")
        return

    scheduler_manager = SchedulerManager()
    # Hold the coroutine in a named variable so the outer `finally` can
    # `.close()` it even when `run_until_complete` raises before scheduling
    # (e.g. test-time mocks where the loop never actually runs the coro).
    # `.close()` on an already-awaited coroutine is a no-op, so this is
    # safe on the happy path and prevents the "coroutine was never awaited"
    # GC warning otherwise.
    coro = populate_scheduler_from_sources(scheduler_manager, factory)
    try:
        try:
            # `asyncio.run` rejects nested event loops. We deliberately use
            # `new_event_loop`+`run_until_complete` so the helper still works
            # when this boot hook fires inside an event-loop-pool worker
            # (gevent/eventlet) — falling back to the warning path leaves the
            # whole Beat schedule unsynced, which is a startup-level defect.
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(coro)
            finally:
                loop.close()
        except RuntimeError as exc:
            logger.error(
                "populate_scheduler_from_sources failed (loop init): %s — Beat"
                " schedule will be empty for this worker",
                exc,
            )
            return
        except Exception:
            logger.exception(
                "populate_scheduler_from_sources failed — Beat schedule empty"
            )
            from intellisource.observability.metrics import (
                MetricsCollector,  # noqa: PLC0415
            )

            mc = MetricsCollector.get_instance()
            if "scheduler_beat_sync_failed_total" not in mc._counters:
                mc.register_counter(
                    "scheduler_beat_sync_failed_total",
                    "Total Beat schedule sync failures",
                )
            mc.increment_counter("scheduler_beat_sync_failed_total")
            if get_settings().beat_sync_hard_fail.lower() == "true":
                raise
            return
    finally:
        coro.close()

    sync_beat_schedules(_module_celery_app, scheduler_manager)
    setattr(_module_celery_app, "_scheduler_manager", scheduler_manager)


def beat_init_handler(**_: Any) -> None:
    """Celery beat_init signal entry point.

    The beat process does not fire `worker_process_init`, so without this
    handler the DB-driven `beat_schedule` would never be populated and Beat
    would idle indefinitely. This mirrors the worker init path but skips
    the full composition graph — Beat only needs the session_factory to
    read Source rows.
    """
    setup_logging()
    logger.info("beat_init signal received — bootstrapping schedule from DB")
    factory = init_worker_session_factory()
    _bootstrap_beat_schedule(factory)
    entry_count = len(_module_celery_app.conf.beat_schedule)
    logger.info("beat schedule bootstrap complete — %d entries loaded", entry_count)


def worker_shutdown_handler(**_: Any) -> None:
    """Dispose worker engine on shutdown."""
    global _worker_engine, _celery_tasks
    if _worker_engine is not None:
        import asyncio  # noqa: PLC0415

        try:
            asyncio.run(_worker_engine.dispose())
        except RuntimeError as exc:
            get_logger(__name__).warning("engine.dispose skipped: %s", exc)
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

if not getattr(beat_init, "_intellisource_connected", False):
    beat_init.connect(beat_init_handler)
    beat_init._intellisource_connected = True
