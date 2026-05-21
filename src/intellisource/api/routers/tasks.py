"""Task management API router."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.storage.repositories.task import TaskRepository

router = APIRouter(tags=["tasks"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CollectRequest(BaseModel):
    source_id: str
    trigger_type: str


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
    repo = TaskRepository(session)
    try:
        task = await repo.create(
            source_id=uuid.UUID(body.source_id),
            trigger_type=body.trigger_type,
        )
    except ValueError:
        return JSONResponse(status_code=404, content={"detail": "source not found"})

    serialized = _serialize_task(task)

    celery_instance = getattr(request.app.state, "celery_app", None)
    if celery_instance is not None:
        async_result = celery_instance.send_task(
            "run_pipeline",
            kwargs={
                "source_id": str(body.source_id),
                "trigger_type": body.trigger_type,
            },
        )
        serialized["task_id"] = async_result.id

    return serialized


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
