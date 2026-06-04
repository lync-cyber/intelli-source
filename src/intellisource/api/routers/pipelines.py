"""Pipelines API router: list / detail / run — thin shell over the service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.api.schemas.pipelines import (
    PipelineDetail,
    PipelineRunResponse,
    PipelineSummary,
)
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.observability.logging import get_logger
from intellisource.pipeline.definition_service import PipelineDefinitionService
from intellisource.scheduler.dispatch import send_task_with_trace

logger = get_logger(__name__)

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


def _get_service(
    session: AsyncSession = Depends(get_db_session),
) -> PipelineDefinitionService:
    return PipelineDefinitionService(session)


class PipelineRunRequest(BaseModel):
    """POST body for /pipelines/{name}/run."""

    params: dict[str, Any] | None = None


class PipelineWriteRequest(BaseModel):
    """Create/replace body for POST /pipelines (idempotent upsert by name)."""

    name: str
    mode: str = "flexible"
    steps: list[dict[str, Any]] = []
    max_steps: int = 50
    on_failure: str = "abort"
    tools_allowed: list[str] = []
    tools_denied: list[str] = []
    system_prompt: str | None = None
    max_tokens_budget: int | None = None
    agent_mode: str = "process"
    tool_permissions: dict[str, str] = {}


class PipelinePatchRequest(BaseModel):
    """Partial-update body for PATCH /pipelines/{name} (name is immutable)."""

    mode: str | None = None
    steps: list[dict[str, Any]] | None = None
    max_steps: int | None = None
    on_failure: str | None = None
    tools_allowed: list[str] | None = None
    tools_denied: list[str] | None = None
    system_prompt: str | None = None
    max_tokens_budget: int | None = None
    agent_mode: str | None = None
    tool_permissions: dict[str, str] | None = None


def _pipeline_to_dict(config: PipelineConfig) -> dict[str, Any]:
    return {
        "name": config.name,
        "mode": config.mode,
        "max_steps": config.max_steps,
        "on_failure": config.on_failure,
        "steps": config.steps,
        "tools_allowed": config.tools_allowed,
        "tools_denied": config.tools_denied,
        "system_prompt": config.system_prompt,
    }


@router.get("", response_model=list[PipelineSummary])
async def list_pipelines(
    service: PipelineDefinitionService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """Return a summary of every persisted pipeline definition."""
    return await service.list_summaries()


@router.get("/{name}", response_model=PipelineDetail)
async def get_pipeline(
    name: str,
    service: PipelineDefinitionService = Depends(_get_service),
) -> dict[str, Any]:
    """Return the parsed PipelineConfig for *name* or 404 if absent."""
    config = await service.get(name)
    if config is None:
        raise HTTPException(status_code=404, detail=f"pipeline '{name}' not found")
    return _pipeline_to_dict(config)


@router.post("/{name}/run", response_model=PipelineRunResponse)
async def run_pipeline(
    name: str,
    body: PipelineRunRequest,
    request: Request,
    service: PipelineDefinitionService = Depends(_get_service),
) -> dict[str, Any]:
    """Trigger a Celery `run_pipeline` task for the named pipeline.

    The pipeline must exist (DB-backed) before dispatch, so an unknown or
    path-traversal name is rejected with 404 and never reaches the broker.
    """
    if await service.get(name) is None:
        raise HTTPException(status_code=404, detail=f"pipeline '{name}' not found")

    celery_instance = getattr(request.app.state, "celery_app", None)
    if celery_instance is None:
        raise HTTPException(status_code=503, detail="celery_app not initialised")

    result = send_task_with_trace(
        "run_pipeline",
        kwargs={"pipeline_name": name, "params": body.params or {}},
        celery_instance=celery_instance,
    )
    return {"task_id": str(getattr(result, "id", result))}


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PipelineDetail)
async def create_pipeline(
    body: PipelineWriteRequest,
    service: PipelineDefinitionService = Depends(_get_service),
) -> dict[str, Any]:
    """Create or replace a pipeline definition (idempotent upsert by name)."""
    try:
        config = PipelineConfig.from_dict(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _pipeline_to_dict(await service.create(config))


@router.patch("/{name}", response_model=PipelineDetail)
async def update_pipeline(
    name: str,
    body: PipelinePatchRequest,
    service: PipelineDefinitionService = Depends(_get_service),
) -> dict[str, Any]:
    """Partial-update a pipeline definition; 404 if absent, 422 if invalid."""
    fields = body.model_dump(exclude_unset=True)
    try:
        updated = await service.update(name, fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"pipeline '{name}' not found")
    return _pipeline_to_dict(updated)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(
    name: str,
    service: PipelineDefinitionService = Depends(_get_service),
) -> Response:
    """Delete a pipeline definition; 404 if absent."""
    if not await service.delete(name):
        raise HTTPException(status_code=404, detail=f"pipeline '{name}' not found")
    return Response(status_code=204)
