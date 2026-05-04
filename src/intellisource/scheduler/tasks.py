"""Celery task definitions for IntelliSource scheduler (M-006).

Triggers AgentRunner to execute pipeline configurations with retry
support, priority queues, and task chain persistence.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.storage.models import TaskChain
from intellisource.storage.repositories.task_chain import TaskChainRepository

MAX_RETRIES: int = 3
RETRY_BACKOFF_BASE: int = 1

PRIORITY_QUEUES: dict[str, str] = {
    "low": "queue.priority.low",
    "normal": "queue.priority.normal",
    "high": "queue.priority.high",
}

TRIGGER_TYPE_QUEUES: dict[str, str] = {
    "scheduled": "queue.trigger.scheduled",
    "manual": "queue.trigger.manual",
}


# Lazy imports -- patched in tests, resolved at runtime.
TaskRepository: Any = None


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
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro_or_result).result()
        return asyncio.run(coro_or_result)
    return coro_or_result


class CeleryTasks:
    """Celery task wrapper that delegates execution to AgentRunner."""

    def __init__(
        self,
        agent_runner: Any,
        pipeline_config: Any,
        session_factory: Callable[[], Awaitable[AsyncSession]] | None = None,
    ) -> None:
        self._agent_runner = agent_runner
        self._pipeline_config = pipeline_config
        self._session_factory = session_factory

    def run_pipeline(
        self,
        pipeline_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Load a pipeline config and execute it via AgentRunner.

        Retries up to ``MAX_RETRIES`` times on failure with
        exponential backoff.
        """
        config = self._pipeline_config.load(pipeline_name)
        trigger_type = params.get("trigger_type", "scheduled")
        execution_mode = config.get("execution_mode", "strict")
        total_steps = len(config.get("steps", []))

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
            session = _run_sync(self._session_factory())
            try:
                repo = TaskChainRepository(session)
                _run_sync(repo.create(task_chain))
                chain_id = task_chain.id
            finally:
                _run_sync(session.close())

        last_error: Exception | None = None
        for attempt in range(1 + MAX_RETRIES):
            try:
                result = _run_sync(self._agent_runner.execute(config, params=params))
                # Success -- update chain status.
                if chain_id is not None and self._session_factory is not None:
                    session = _run_sync(self._session_factory())
                    try:
                        repo = TaskChainRepository(session)
                        _run_sync(repo.update_status(str(chain_id), "success"))
                    finally:
                        _run_sync(session.close())
                return dict(result)
            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    # In-process retry with exponential backoff.
                    # When integrated with real Celery, replace with
                    # self.retry(countdown=...) for non-blocking retries.
                    _run_sync(asyncio.sleep(RETRY_BACKOFF_BASE * (2**attempt)))

        # All retries exhausted -- record error and propagate.
        if TaskRepository is not None:
            task_repo = TaskRepository()
            _run_sync(
                task_repo.update(
                    error_message=str(last_error),
                )
            )

        if chain_id is not None and self._session_factory is not None:
            session = _run_sync(self._session_factory())
            try:
                repo = TaskChainRepository(session)
                _run_sync(repo.update_status(str(chain_id), "failed"))
            finally:
                _run_sync(session.close())

        raise last_error  # type: ignore[misc]
