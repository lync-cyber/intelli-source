"""Task management API router."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.composition import SOURCE_TYPE_TO_PIPELINE
from intellisource.scheduler.dispatch import send_task_with_trace
from intellisource.scheduler.queues import PRIORITY_QUEUES
from intellisource.storage.repositories.source import SourceRepository
from intellisource.storage.repositories.task import TaskRepository
from intellisource.storage.repositories.task_chain import TaskChainRepository

router = APIRouter(tags=["tasks"])

_VALID_PRIORITIES: frozenset[str] = frozenset(PRIORITY_QUEUES.keys())


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CollectRequest(BaseModel):
    source_ids: list[str] | None = None
    priority: str = "normal"


class TaskUpdateRequest(BaseModel):
    status: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_task(task: Any) -> dict[str, Any]:
    """Convert a CollectTask ORM object to a JSON-serializable dict.

    `pipeline_name` / `execution_mode` live on the parent TaskChain row;
    callers who need them should follow `task_chain_id` and query
    /tasks/chains/{id} (when available) rather than expecting them inlined
    here. Including them inline previously caused AttributeError on every
    GET /tasks/{id} call.
    """
    return {
        "id": str(task.id),
        "source_id": str(task.source_id),
        "task_chain_id": str(task.task_chain_id) if task.task_chain_id else None,
        "status": task.status,
        "priority": task.priority,
        "trigger_type": task.trigger_type,
        "items_collected": task.items_collected,
        "error_message": task.error_message,
        "retry_count": task.retry_count,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "created_at": task.created_at,
    }


def _task_brief(task: Any) -> dict[str, Any]:
    """Return a TaskBrief dict for use in TaskTriggerResponse."""
    return {
        "id": str(task.id),
        "type": "collect",
        "status": task.status,
        "created_at": task.created_at,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/tasks")
async def list_tasks(
    status: str | None = None,
    trigger_type: str | None = None,
    source_id: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    limit = min(limit, 100)
    repo = TaskRepository(session)
    sid = uuid.UUID(source_id) if source_id else None
    result = await repo.list(
        status=status,
        trigger_type=trigger_type,
        source_id=sid,
        limit=limit,
        cursor=cursor,
    )
    items = result["items"]
    serialized = [_serialize_task(t) for t in items]
    return {
        "items": serialized,
        "next_cursor": result["next_cursor"],
        "has_more": result["has_more"],
    }


@router.post("/tasks/collect", status_code=202)
async def trigger_collect(
    request: Request,
    body: CollectRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    source_repo = SourceRepository(session)
    task_repo = TaskRepository(session)
    priority = body.priority

    if priority not in _VALID_PRIORITIES:
        return JSONResponse(
            status_code=400,
            content={
                "detail": (
                    f"invalid priority {priority!r}; "
                    f"must be one of {sorted(_VALID_PRIORITIES)}"
                )
            },
        )

    target_queue = PRIORITY_QUEUES[priority]

    if body.source_ids:
        # Validate all requested source IDs.
        invalid: list[str] = []
        resolved: list[uuid.UUID] = []
        for raw in body.source_ids:
            try:
                resolved.append(uuid.UUID(raw))
            except ValueError:
                invalid.append(raw)
        if invalid:
            return JSONResponse(
                status_code=400,
                content={"detail": f"invalid source_ids: {invalid}"},
            )
        source_uuids = resolved
    else:
        source_uuids = await source_repo.list_active_source_ids()

    if not source_uuids:
        return JSONResponse(
            status_code=202,
            content={
                "task_chain_id": str(uuid.uuid4()),
                "tasks": [],
                "message": "无活跃信源可采集",
            },
        )

    task_chain_id = str(uuid.uuid4())
    # Persist the parent TaskChain row before creating CollectTask children —
    # collect_tasks.task_chain_id has a FK constraint to task_chains.id, so
    # the parent must exist (and the INSERT must be flushed) before any child
    # can be inserted. Repository.create() flushes inside the same async
    # session so the FK is visible to subsequent INSERTs.
    task_chain_repo = TaskChainRepository(session)
    await task_chain_repo.create(
        id=uuid.UUID(task_chain_id),
        pipeline_name="collect",
        status="pending",
        trigger_type="manual",
        execution_mode="parallel",
        total_steps=len(source_uuids),
        completed_steps=0,
    )

    tasks: list[Any] = []
    for sid in source_uuids:
        task = await task_repo.create(
            source_id=sid,
            trigger_type="manual",
            priority=priority,
            task_chain_id=uuid.UUID(task_chain_id),
        )
        tasks.append(task)

    celery_instance = getattr(request.app.state, "celery_app", None)
    if celery_instance is not None:
        # Resolve source_type for each task in one query so SOURCE_TYPE_TO_PIPELINE
        # routes by actual type rather than a hardcoded "rss" fallback. Tasks
        # whose source row is missing fall back to "scheduled-collect".
        source_type_by_id = await source_repo.get_types_by_ids(
            [task.source_id for task in tasks]
        )
        for task in tasks:
            source_type = source_type_by_id.get(task.source_id)
            pipeline_name = (
                SOURCE_TYPE_TO_PIPELINE.get(source_type, "scheduled-collect")
                if source_type is not None
                else "scheduled-collect"
            )
            send_task_with_trace(
                "run_pipeline",
                kwargs={
                    "pipeline_name": pipeline_name,
                    "params": {
                        "task_id": str(task.id),
                        "task_chain_id": task_chain_id,
                        "source_id": str(task.source_id),
                        "trigger_type": task.trigger_type or "manual",
                        "priority": priority,
                        "fingerprint": "",
                    },
                },
                queue=target_queue,
                celery_instance=celery_instance,
            )

    return {
        "task_chain_id": task_chain_id,
        "tasks": [_task_brief(t) for t in tasks],
        "message": f"已创建 {len(tasks)} 个采集任务",
    }


@router.get("/tasks/{id}")
async def get_task(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    repo = TaskRepository(session)
    task = await repo.get_by_id(id)
    if task is None:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return _serialize_task(task)


@router.patch("/tasks/{id}")
async def update_task(
    id: uuid.UUID,
    body: TaskUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    repo = TaskRepository(session)
    fields = body.model_dump(exclude_unset=True)
    updated = await repo.update(id, **fields)
    if updated is None:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return _serialize_task(updated)
