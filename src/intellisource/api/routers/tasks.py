"""Task management API router."""

from __future__ import annotations

import json
import uuid
from typing import Any

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.api.errors import error_json
from intellisource.api.schemas.tasks import (
    TaskChainDetail,
    TaskItem,
    TaskListResponse,
    TaskTriggerResponse,
)
from intellisource.composition import SOURCE_TYPE_TO_PIPELINE
from intellisource.observability.logging import get_logger
from intellisource.scheduler.dispatch import (
    BrokerUnavailableError,
    send_task_with_trace,
)
from intellisource.scheduler.queues import PRIORITY_QUEUES
from intellisource.storage.repositories.source import SourceRepository
from intellisource.storage.repositories.task import TaskRepository
from intellisource.storage.repositories.task_chain import TaskChainRepository

logger = get_logger(__name__)

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
    callers who need them follow `task_chain_id` and query /tasks/chains/{id}
    rather than expecting them inlined here (they are not columns on CollectTask).
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


def _serialize_task_chain(chain: Any) -> dict[str, Any]:
    """Convert a TaskChain ORM object to a JSON-serializable dict."""
    return {
        "id": str(chain.id),
        "pipeline_name": chain.pipeline_name,
        "status": chain.status,
        "trigger_type": chain.trigger_type,
        "execution_mode": chain.execution_mode,
        "total_steps": chain.total_steps,
        "completed_steps": chain.completed_steps,
        "current_step": chain.current_step,
        "error_message": chain.error_message,
        "started_at": chain.started_at,
        "finished_at": chain.finished_at,
        "created_at": chain.created_at,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/tasks", response_model=TaskListResponse)
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


@router.post("/tasks/collect", status_code=202, response_model=TaskTriggerResponse)
async def trigger_collect(
    request: Request,
    body: CollectRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    source_repo = SourceRepository(session)
    task_repo = TaskRepository(session)
    priority = body.priority

    if priority not in _VALID_PRIORITIES:
        allowed = sorted(_VALID_PRIORITIES)
        return error_json(
            400, f"invalid priority {priority!r}; must be one of {allowed}"
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
            return error_json(400, f"invalid source_ids: {invalid}")
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
        try:
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
        except BrokerUnavailableError as exc:
            # Broker unreachable — raising here rolls back the just-created
            # task_chain + task rows (get_db_session rolls back on exception)
            # so we don't leave orphan pending rows that were never dispatched.
            raise HTTPException(
                status_code=503,
                detail="task broker unavailable; collect not dispatched",
            ) from exc

    return {
        "task_chain_id": task_chain_id,
        "tasks": [_task_brief(t) for t in tasks],
        "message": f"已创建 {len(tasks)} 个采集任务",
    }


@router.get("/tasks/chains/{id}", response_model=TaskChainDetail)
async def get_task_chain(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    """Return the parent TaskChain for *id* or 404 if absent."""
    repo = TaskChainRepository(session)
    chain = await repo.get(str(id))
    if chain is None:
        return error_json(404, "not found")
    return _serialize_task_chain(chain)


def _celery_result_jsonable(value: Any) -> Any:
    """Return *value* if JSON-encodable, else its ``str`` form.

    A task result can be an arbitrary Python object (or a raised exception);
    coerce anything the JSON encoder cannot handle so the endpoint never 500s
    on an exotic payload.
    """
    try:
        json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)
    return value


@router.get("/tasks/celery/{task_id}")
async def get_celery_task(task_id: str, request: Request) -> Any:
    """Resolve a Celery task id to its broker-side state and result.

    ``task_id`` is the id returned by a pipeline-run dispatch (``run_pipeline`` /
    ``trigger_pipeline`` / ``POST /pipelines/{name}/run``), distinct from the
    ``task_chain_id`` used by ``/tasks/chains/{id}``. Wraps
    ``celery.result.AsyncResult`` so a caller holding only the Celery id can poll
    state (PENDING/STARTED/SUCCESS/FAILURE) and fetch the result when ready.
    """
    celery_instance = getattr(request.app.state, "celery_app", None)
    if celery_instance is None:
        return error_json(503, "celery_app not initialised")
    try:
        async_result = AsyncResult(task_id, app=celery_instance)
        state = async_result.state
        ready = async_result.ready()
        payload: dict[str, Any] = {
            "task_id": task_id,
            "state": state,
            "ready": ready,
        }
        if ready:
            successful = async_result.successful()
            payload["successful"] = successful
            if successful:
                payload["result"] = _celery_result_jsonable(async_result.result)
            else:
                payload["error"] = str(async_result.result)
    except Exception as exc:
        logger.warning("celery AsyncResult lookup failed for %s: %s", task_id, exc)
        return error_json(503, f"result backend unavailable: {exc}")
    return payload


@router.get("/tasks/{id}", response_model=TaskItem)
async def get_task(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    repo = TaskRepository(session)
    task = await repo.get_by_id(id)
    if task is None:
        return error_json(404, "not found")
    return _serialize_task(task)


@router.patch("/tasks/{id}", response_model=TaskItem)
async def update_task(
    id: uuid.UUID,
    body: TaskUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    repo = TaskRepository(session)
    fields = body.model_dump(exclude_unset=True)
    updated = await repo.update(id, **fields)
    if updated is None:
        return error_json(404, "not found")
    return _serialize_task(updated)
