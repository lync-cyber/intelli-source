"""TaskChainPersister — encapsulates TaskChain DB write and pipeline_complete event."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from intellisource.storage.models import TaskChain

if TYPE_CHECKING:
    from intellisource.agent.events import PipelineEventLogger
    from intellisource.storage.repositories.task_chain import TaskChainRepository


class TaskChainPersister:
    """Handles persistence of pipeline execution results.

    Writes a TaskChain record (when repo is supplied) and emits
    pipeline_complete via the optional event_logger.
    """

    def __init__(self, event_logger: PipelineEventLogger | None = None) -> None:
        self._event_logger = event_logger

    async def persist(
        self,
        *,
        status: str,
        steps_executed: int,
        results: list[dict[str, Any]],
        pipeline_name: str,
        task_chain_id: str | None = None,
        repo: TaskChainRepository | None = None,
        trigger_type: str = "manual",
        execution_mode: str = "strict",
    ) -> dict[str, Any]:
        """Persist result and return payload with task_chain_id."""
        if task_chain_id is not None:
            chain_id = task_chain_id
        elif repo is not None:
            task_chain = TaskChain(
                id=uuid.uuid4(),
                pipeline_name=pipeline_name,
                status=status,
                trigger_type=trigger_type,
                execution_mode=execution_mode,
                total_steps=steps_executed,
                completed_steps=steps_executed,
            )
            persisted = await repo.create(task_chain)
            chain_id = str(persisted.id)
        else:
            raise ValueError(
                "_persist requires either task_chain_id or repo; both were None. "
                "Internal run_strict/run_batch/run_flexible always pre-generate "
                "chain_id, so this indicates an unexpected external caller."
            )

        await self._emit_pipeline_complete(
            pipeline_name, chain_id, status, steps_executed
        )

        return {
            "status": status,
            "steps_executed": steps_executed,
            "results": results,
            "pipeline_name": pipeline_name,
            "task_chain_id": chain_id,
        }

    async def _emit_pipeline_complete(
        self,
        pipeline_name: str,
        chain_id: str,
        status: str,
        steps_executed: int,
    ) -> None:
        if self._event_logger is None:
            return
        await self._event_logger.pipeline_complete(
            pipeline_name=pipeline_name,
            task_chain_id=chain_id,
            status=status,
            steps_executed=steps_executed,
        )
