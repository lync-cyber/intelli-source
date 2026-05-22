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
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.composition import PipelineLoader
from intellisource.scheduler.celery_app import celery_app
from intellisource.scheduler.queues import PRIORITY_QUEUES, TRIGGER_TYPE_QUEUES
from intellisource.storage.models import TaskChain
from intellisource.storage.repositories.task_chain import TaskChainRepository

MAX_RETRIES: int = 3
RETRY_BACKOFF_BASE: int = 1

__all__ = [
    "PRIORITY_QUEUES",
    "TRIGGER_TYPE_QUEUES",
    "CeleryTasks",
    "get_queue_for_priority",
    "get_queue_for_trigger_type",
    "run_pipeline",
]


def get_queue_for_priority(priority: str) -> str:
    """Return the queue name for the given priority level.

    Raises:
        ValueError: If *priority* is not one of low/normal/high.
    """
    try:
        return PRIORITY_QUEUES[priority]
    except KeyError:
        raise ValueError(
            f"Invalid priority '{priority}'. "
            f"Must be one of: {', '.join(PRIORITY_QUEUES)}"
        ) from None


def get_queue_for_trigger_type(trigger_type: str) -> str:
    """Return the queue name for the given trigger type."""
    return TRIGGER_TYPE_QUEUES[trigger_type]


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
    async def _chain_repo_session(self) -> AsyncIterator[TaskChainRepository]:
        """Open a session, yield a TaskChainRepository, close on exit."""
        if self._session_factory is None:
            raise RuntimeError("session_factory not configured")
        session = await self._session_factory()
        try:
            yield TaskChainRepository(session)
        finally:
            await session.close()

    def _create_chain(self, task_chain: TaskChain) -> uuid.UUID | None:
        """Persist a new TaskChain record and return its assigned ID."""
        if self._session_factory is None:
            return None

        async def _do() -> uuid.UUID:
            async with self._chain_repo_session() as repo:
                await repo.create(task_chain)
                return task_chain.id

        result: uuid.UUID = _run_sync(_do())
        return result

    def _update_chain_status(self, chain_id: uuid.UUID, status: str) -> None:
        """Update the status of an existing TaskChain record."""

        async def _do() -> None:
            async with self._chain_repo_session() as repo:
                await repo.update_status(str(chain_id), status)

        _run_sync(_do())

    def run_pipeline(
        self,
        pipeline_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Load a pipeline config and execute it via AgentRunner.

        Retries up to ``MAX_RETRIES`` times on failure with
        exponential backoff.
        """
        task_id: str = params.get("task_id", "")
        fingerprint: str = params.get("fingerprint", "")

        if self._idempotency_guard is not None:
            lock_acquired: bool = _run_sync(self._idempotency_guard.acquire(task_id))
            if not lock_acquired:
                return {"status": "skipped", "reason": "already_running"}

        if self._fingerprint_checker is not None:
            is_dup: bool = _run_sync(
                self._fingerprint_checker.is_duplicate(fingerprint)
            )
            if is_dup:
                return {"status": "skipped", "reason": "duplicate"}

        if self._pipeline_config is None:
            raise RuntimeError(
                "CeleryTasks.run_pipeline: pipeline_config (PipelineLoader) is None; "
                "worker_init_handler must wire it via build_worker_composition()"
            )
        config = self._pipeline_config.load(pipeline_name)
        trigger_type = params.get("trigger_type", "scheduled")
        execution_mode = config.mode
        total_steps = len(config.steps)

        # Persist TaskChain record via session_factory when wired (production path).
        chain_id: uuid.UUID | None = None
        if self._session_factory is not None:
            task_chain = TaskChain(
                pipeline_name=pipeline_name,
                status="pending",
                trigger_type=trigger_type,
                execution_mode=execution_mode,
                total_steps=total_steps,
                completed_steps=0,
            )
            chain_id = self._create_chain(task_chain)

        last_error: Exception | None = None
        for attempt in range(1 + MAX_RETRIES):
            try:
                result = _run_sync(self._agent_runner.execute(config, params=params))
                if self._content_repository is not None:
                    _run_sync(self._content_repository.create(result))
                if self._fingerprint_checker is not None and fingerprint:
                    content_id = (
                        result.get("content_id") if isinstance(result, dict) else None
                    )
                    _run_sync(self._fingerprint_checker.record(fingerprint, content_id))
                if chain_id is not None:
                    self._update_chain_status(chain_id, "success")
                return dict(result)
            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    _run_sync(asyncio.sleep(RETRY_BACKOFF_BASE * (2**attempt)))

        if chain_id is not None:
            self._update_chain_status(chain_id, "failed")

        raise last_error  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Module-level Celery task (AC-4) — delegates to CeleryTasks business logic
# ---------------------------------------------------------------------------


@celery_app.task(name="run_pipeline", bind=True)  # type: ignore[untyped-decorator]
def run_pipeline(self: Any, **kwargs: Any) -> dict[str, Any]:
    """Celery entry point: execute the named pipeline with the given params.

    The ``bind=True`` flag injects the Celery Task instance as ``self``.
    Business logic is delegated to :class:`CeleryTasks` wired during
    worker_process_init via ``celery_app._celery_tasks_instance``.
    """
    pipeline_name: str = kwargs.get("pipeline_name", "default")
    params: dict[str, Any] = kwargs.get("params", kwargs)

    _celery_tasks_instance: CeleryTasks | None = getattr(
        celery_app, "_celery_tasks_instance", None
    )
    if _celery_tasks_instance is None:
        raise RuntimeError(
            "CeleryTasks not wired: worker_process_init handler has not run"
        )
    return _celery_tasks_instance.run_pipeline(pipeline_name, params)
