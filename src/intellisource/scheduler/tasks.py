"""Celery task definitions for IntelliSource scheduler (M-006).

Triggers AgentRunner to execute pipeline configurations with retry
support, priority queues, and task chain persistence.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.core.pipeline_loader import PipelineLoader
from intellisource.observability.logging import get_logger
from intellisource.scheduler.celery_app import celery_app
from intellisource.scheduler.queues import PRIORITY_QUEUES, TRIGGER_TYPE_QUEUES
from intellisource.storage.repositories.task import TaskRepository
from intellisource.storage.repositories.task_chain import TaskChainRepository

logger = get_logger(__name__)

_R = TypeVar("_R")

MAX_RETRIES: int = 3
RETRY_BACKOFF_BASE: int = 1
CHAT_SESSION_TTL_DAYS: int = 30

__all__ = [
    "PRIORITY_QUEUES",
    "TRIGGER_TYPE_QUEUES",
    "CeleryTasks",
    "assemble_daily_weekly_digests",
    "cleanup_chat_sessions",
    "run_pipeline",
]


def _run_sync(coro_or_result: Any) -> Any:
    """Await a coroutine synchronously, or return a plain value."""
    if asyncio.iscoroutine(coro_or_result):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Shouldn't happen in Celery workers but handle gracefully.
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro_or_result).result()
        return asyncio.run(coro_or_result)
    return coro_or_result


def _parse_uuid_param(raw: Any) -> uuid.UUID | None:
    """Return a validated UUID from a dispatch param, or None when absent/malformed.

    Used for both ``params['task_chain_id']`` (the run-correlation id the
    api / agent / mcp dispatch layer returned to the caller) and
    ``params['task_id']`` (the CollectTask row whose lifecycle status the worker
    writes back). Non-UUID lock keys — e.g. ``scheduled-collect:source:...`` —
    parse to None so only real CollectTask rows are touched.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def _task_lock_key(pipeline_name: str, params: dict[str, Any]) -> str:
    """Return a stable, non-empty idempotency lock key for a pipeline run."""
    explicit = str(params.get("task_id") or "").strip()
    if explicit:
        return explicit
    source_id = str(params.get("source_id") or "").strip()
    if source_id:
        return f"{pipeline_name}:source:{source_id}"
    fingerprint = str(params.get("fingerprint") or "").strip()
    if fingerprint:
        return f"{pipeline_name}:fingerprint:{fingerprint}"
    return f"{pipeline_name}:manual"


class CeleryTasks:
    """Celery task wrapper that delegates execution to AgentRunner."""

    def __init__(
        self,
        agent_runner: Any,
        pipeline_config: PipelineLoader | None,
        session_factory: Callable[[], Awaitable[AsyncSession]] | None = None,
        *,
        idempotency_guard: Any = None,
        fingerprint_checker: Any = None,
        content_repository: Any = None,
    ) -> None:
        self._agent_runner = agent_runner
        self._pipeline_config: PipelineLoader | None = pipeline_config
        self._session_factory = session_factory
        self._idempotency_guard = idempotency_guard
        self._fingerprint_checker = fingerprint_checker
        self._content_repository = content_repository

    @asynccontextmanager
    async def _repo_session(
        self, repo_cls: Callable[[AsyncSession], _R]
    ) -> AsyncIterator[_R]:
        """Open a session, yield ``repo_cls(session)``, commit/rollback/close."""
        if self._session_factory is None:
            raise RuntimeError("session_factory not configured")
        session = await self._session_factory()
        try:
            yield repo_cls(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    @asynccontextmanager
    async def _chain_repo_session(self) -> AsyncIterator[TaskChainRepository]:
        """Open a session, yield a TaskChainRepository, close on exit."""
        async with self._repo_session(TaskChainRepository) as repo:
            yield repo

    def _set_task_status(
        self,
        raw_task_id: Any,
        new_status: str,
        *,
        only_from: tuple[str, ...],
        **fields: Any,
    ) -> None:
        """Best-effort CollectTask lifecycle write keyed by ``params['task_id']``.

        No-op when session_factory is unwired or the id is not a real CollectTask
        UUID (non-UUID lock keys parse to None). The *only_from* guard means a
        status the API set out-of-band (paused / cancelled) is never clobbered by
        a worker still finishing the run. Persistence errors are swallowed so a
        status-write hiccup never fails the pipeline run itself.
        """
        if self._session_factory is None:
            return
        uid = _parse_uuid_param(raw_task_id)
        if uid is None:
            return

        async def _do() -> None:
            async with self._repo_session(TaskRepository) as repo:
                task = await repo.get_by_id(uid)
                if task is None or task.status not in only_from:
                    return
                await repo.update(uid, status=new_status, **fields)

        try:
            _run_sync(_do())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "CollectTask status write failed task=%s status=%s: %s",
                uid,
                new_status,
                exc,
            )

    def _create_chain(
        self,
        *,
        pipeline_name: str,
        trigger_type: str,
        execution_mode: str,
        total_steps: int,
    ) -> uuid.UUID | None:
        """Persist a new TaskChain record and return its assigned ID."""
        if self._session_factory is None:
            return None

        async def _do() -> uuid.UUID:
            async with self._chain_repo_session() as repo:
                created = await repo.create(
                    pipeline_name=pipeline_name,
                    status="pending",
                    trigger_type=trigger_type,
                    execution_mode=execution_mode,
                    total_steps=total_steps,
                    completed_steps=0,
                )
                chain_uuid: uuid.UUID = created.id
                return chain_uuid

        result: uuid.UUID = _run_sync(_do())
        return result

    def _update_chain_status(
        self, chain_id: uuid.UUID, status: str, completed_steps: int | None = None
    ) -> None:
        """Update the status (and optionally completed_steps) of a TaskChain."""

        async def _do() -> None:
            async with self._chain_repo_session() as repo:
                await repo.update_status(str(chain_id), status, completed_steps)

        _run_sync(_do())

    def _create_chain_with_id(
        self,
        chain_id: uuid.UUID,
        *,
        pipeline_name: str,
        trigger_type: str,
        execution_mode: str,
        total_steps: int,
    ) -> uuid.UUID | None:
        """Create this run's TaskChain under an externally supplied id.

        The id is adopted only when it is free, so the id the dispatch layer
        (api / agent / mcp) returned to the caller is the one get_task_status
        polls. When a row already owns that id — the collect endpoint
        pre-creates a batch-parent chain and fans the same id out to its
        children — a fresh per-run row is created instead so a child run never
        hijacks the parent's status.
        """
        if self._session_factory is None:
            return None

        async def _do() -> uuid.UUID:
            async with self._chain_repo_session() as repo:
                row_id = chain_id if await repo.get(str(chain_id)) is None else None
                fields: dict[str, Any] = {
                    "pipeline_name": pipeline_name,
                    "status": "pending",
                    "trigger_type": trigger_type,
                    "execution_mode": execution_mode,
                    "total_steps": total_steps,
                    "completed_steps": 0,
                }
                if row_id is not None:
                    fields["id"] = row_id
                created = await repo.create(**fields)
                created_id: uuid.UUID = created.id
                return created_id

        result: uuid.UUID = _run_sync(_do())
        return result

    def run_pipeline(
        self,
        pipeline_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Load a pipeline config and execute it via AgentRunner.

        Retries up to ``MAX_RETRIES`` times on failure with
        exponential backoff.
        """
        task_id = _task_lock_key(pipeline_name, params)
        fingerprint: str = params.get("fingerprint", "")
        lock_acquired = False

        if self._idempotency_guard is not None:
            # A resume re-dispatch (params["force"]) clears any stale lock left by
            # the run that was revoked on pause — without it the resumed run would
            # be deduped as "already_running" until the lock TTL elapses.
            if params.get("force"):
                _run_sync(self._idempotency_guard.release(task_id))
            lock_acquired = bool(_run_sync(self._idempotency_guard.acquire(task_id)))
            if not lock_acquired:
                return {"status": "skipped", "reason": "already_running"}

        try:
            if self._fingerprint_checker is not None:
                is_dup: bool = _run_sync(
                    self._fingerprint_checker.is_duplicate(fingerprint)
                )
                if is_dup:
                    return {"status": "skipped", "reason": "duplicate"}

            if self._pipeline_config is None:
                raise RuntimeError(
                    "CeleryTasks.run_pipeline: pipeline_config (PipelineLoader) is "
                    "None; worker_init_handler must wire it via "
                    "build_worker_composition()"
                )
            config = self._pipeline_config.load(pipeline_name)
            trigger_type = params.get("trigger_type", "scheduled")
            execution_mode = config.mode
            total_steps = len(config.steps)

            # Persist TaskChain record via session_factory when wired. When the
            # dispatch layer (api / agent / mcp) supplied params["task_chain_id"],
            # reuse that id so the id returned to the caller correlates with this
            # row; otherwise generate one worker-side as before.
            chain_id: uuid.UUID | None = None
            if self._session_factory is not None:
                explicit_chain_id = _parse_uuid_param(params.get("task_chain_id"))
                if explicit_chain_id is not None:
                    chain_id = self._create_chain_with_id(
                        explicit_chain_id,
                        pipeline_name=pipeline_name,
                        trigger_type=trigger_type,
                        execution_mode=execution_mode,
                        total_steps=total_steps,
                    )
                else:
                    chain_id = self._create_chain(
                        pipeline_name=pipeline_name,
                        trigger_type=trigger_type,
                        execution_mode=execution_mode,
                        total_steps=total_steps,
                    )

            self._set_task_status(
                params.get("task_id"), "running", only_from=("pending",)
            )

            last_error: Exception | None = None
            for attempt in range(1 + MAX_RETRIES):
                try:
                    result = _run_sync(
                        self._agent_runner.execute(config, params=params)
                    )
                    if self._content_repository is not None:
                        _run_sync(self._content_repository.create(result))
                    if self._fingerprint_checker is not None and fingerprint:
                        content_id = (
                            result.get("content_id")
                            if isinstance(result, dict)
                            else None
                        )
                        _run_sync(
                            self._fingerprint_checker.record(fingerprint, content_id)
                        )
                    if chain_id is not None:
                        self._update_chain_status(
                            chain_id, "success", completed_steps=total_steps
                        )
                    self._set_task_status(
                        params.get("task_id"), "success", only_from=("running",)
                    )
                    return dict(result)
                except Exception as exc:
                    last_error = exc
                    if attempt < MAX_RETRIES:
                        _run_sync(asyncio.sleep(RETRY_BACKOFF_BASE * (2**attempt)))

            if chain_id is not None:
                self._update_chain_status(chain_id, "failed")
            self._set_task_status(
                params.get("task_id"),
                "failed",
                only_from=("running",),
                error_message=str(last_error) if last_error else None,
            )

            raise last_error  # type: ignore[misc]
        finally:
            if self._idempotency_guard is not None and lock_acquired:
                _run_sync(self._idempotency_guard.release(task_id))


# ---------------------------------------------------------------------------
# Module-level Celery task (AC-4) — delegates to CeleryTasks business logic
# ---------------------------------------------------------------------------


def _run_pipeline_body(**kwargs: Any) -> dict[str, Any]:
    """Validate kwargs shape and delegate to the wired CeleryTasks instance.

    Extracted out of the @celery_app.task decorator so unit tests can call
    the validation + dispatch logic without going through Celery's Task
    wrapper (which masks the underlying signature).
    """
    if "params" not in kwargs:
        raise RuntimeError(
            "send_task kwargs missing 'params'; the legacy flat-kwargs shape "
            "is rejected (T-095 AC-8). Use kwargs={'pipeline_name': ..., "
            "'params': {...}} instead."
        )
    pipeline_name: str = kwargs.get("pipeline_name", "default")
    params: dict[str, Any] = kwargs["params"]

    _celery_tasks_instance: CeleryTasks | None = getattr(
        celery_app, "_celery_tasks_instance", None
    )
    if _celery_tasks_instance is None:
        raise RuntimeError(
            "CeleryTasks not wired: worker_process_init handler has not run"
        )
    return _celery_tasks_instance.run_pipeline(pipeline_name, params)


@celery_app.task(name="run_pipeline", bind=True)  # type: ignore[untyped-decorator]
def run_pipeline(self: Any, **kwargs: Any) -> dict[str, Any]:
    """Celery entry point: execute the named pipeline with the given params.

    The ``bind=True`` flag injects the Celery Task instance as ``self``.
    Validation + dispatch live in :func:`_run_pipeline_body` so tests can
    cover them without invoking the Celery Task wrapper.
    """
    return _run_pipeline_body(**kwargs)


def _assemble_digests_body() -> dict[str, Any]:
    """Run the wired PeriodicDigestRunner; raise if the Worker never wired one."""
    runner = getattr(celery_app, "_periodic_digest_runner", None)
    if runner is None:
        raise RuntimeError(
            "PeriodicDigestRunner not wired: build_worker_composition() must run"
            " in the worker_process_init handler"
        )
    result: dict[str, Any] = _run_sync(runner.run())
    return result


@celery_app.task(  # type: ignore[untyped-decorator]
    name="assemble_daily_weekly_digests", bind=True
)
def assemble_daily_weekly_digests(self: Any, **kwargs: Any) -> dict[str, Any]:
    """Beat entry point: assemble + send every due daily/weekly digest.

    Self-gating — each subscription's :class:`FrequencyController` decides
    whether it is due, so this can fire as often as hourly without over-sending.
    """
    del kwargs
    return _assemble_digests_body()


def _cleanup_chat_sessions_body() -> dict[str, Any]:
    """Purge chat sessions inactive past the TTL; raise if the Worker never wired."""
    factory = getattr(celery_app, "_chat_session_cleanup_factory", None)
    if factory is None:
        raise RuntimeError(
            "chat session cleanup not wired: build_worker_composition() must run"
            " in the worker_process_init handler"
        )

    async def _do() -> int:
        from datetime import datetime, timedelta, timezone  # noqa: PLC0415

        from intellisource.storage.repositories.chat_session import (  # noqa: PLC0415
            ChatSessionRepository,
        )

        before = datetime.now(timezone.utc) - timedelta(days=CHAT_SESSION_TTL_DAYS)
        async with factory() as session:
            deleted = await ChatSessionRepository(session).cleanup_expired(before)
            await session.commit()
            return deleted

    return {"deleted": _run_sync(_do())}


@celery_app.task(name="cleanup_chat_sessions", bind=True)  # type: ignore[untyped-decorator]
def cleanup_chat_sessions(self: Any, **kwargs: Any) -> dict[str, Any]:
    """Beat entry point: delete chat sessions inactive past the TTL."""
    del kwargs
    return _cleanup_chat_sessions_body()
