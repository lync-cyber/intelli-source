"""Task management API router."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.storage.repositories.source import SourceRepository
from intellisource.storage.repositories.task import TaskRepository

router = APIRouter(tags=["tasks"])


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
    """Convert a CollectTask ORM object to a JSON-serializable dict."""
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
        "pipeline_name": task.pipeline_name,
        "execution_mode": task.execution_mode,
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
        for task in tasks:
            celery_instance.send_task(
                "run_pipeline",
                kwargs={
                    "source_id": str(task.source_id),
                    "task_id": str(task.id),
                    "task_chain_id": task_chain_id,
                    "priority": priority,
                },
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
