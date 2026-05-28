"""Sources API router — HTTP shell over SourceConfigService."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.config.loader import ConfigLoader
from intellisource.config.models import SourceConfig
from intellisource.source.service import SourceConfigService

router = APIRouter(tags=["sources"])


class SourcePatchRequest(BaseModel):
    """Partial-update body — every field optional; mirrors SourceConfig + status."""

    name: str | None = None
    type: str | None = None
    url: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    schedule_interval: int | None = None
    schedule_adaptive: bool | None = None
    proxy: str | None = None
    rate_limit_qps: float | None = None
    rate_limit_concurrency: int | None = None
    metadata: dict[str, Any] | None = None


def _serialize_source(s: Any) -> dict[str, Any]:
    """ORM → JSON-friendly dict."""
    return {
        "id": str(s.id),
        "name": s.name,
        "type": s.type,
        "url": s.url,
        "tags": s.tags,
        "status": s.status,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "schedule_interval": s.schedule_interval,
        "schedule_adaptive": s.schedule_adaptive,
        "proxy": s.proxy,
        "rate_limit_qps": s.rate_limit_qps,
        "rate_limit_concurrency": s.rate_limit_concurrency,
        "metadata": s.metadata_,
        "last_collected_at": s.last_collected_at,
        "next_collect_at": s.next_collect_at,
        "error_count": s.error_count,
        "avg_update_interval": s.avg_update_interval,
        "http_etag": s.http_etag,
        "http_last_modified": s.http_last_modified,
        "config_version": s.config_version,
    }


def _get_service(
    session: AsyncSession = Depends(get_db_session),
) -> SourceConfigService:
    return SourceConfigService(session)


@router.get("/sources")
async def list_sources(
    type: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
    service: SourceConfigService = Depends(_get_service),
) -> dict[str, Any]:
    limit = min(limit, 100)
    result = await service.list_paginated(
        limit=limit, cursor=cursor, type=type, status=status, tag=tag
    )
    return {
        "items": [_serialize_source(s) for s in result["items"]],
        "next_cursor": result["next_cursor"],
        "has_more": result["has_more"],
    }


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def create_source(
    body: SourceConfig,
    service: SourceConfigService = Depends(_get_service),
) -> dict[str, Any]:
    """Idempotent upsert by name."""
    return _serialize_source(await service.create(body))


@router.patch("/sources/{id}")
async def update_source(
    id: uuid.UUID,
    body: SourcePatchRequest,
    service: SourceConfigService = Depends(_get_service),
) -> Any:
    fields = body.model_dump(exclude_unset=True)
    updated = await service.patch(id, fields)
    if updated is None:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return _serialize_source(updated)


@router.delete("/sources/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    id: uuid.UUID,
    service: SourceConfigService = Depends(_get_service),
) -> Response:
    deleted = await service.delete(id)
    if not deleted:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return Response(status_code=204)


@router.post("/sources/reload")
async def reload_sources(
    service: SourceConfigService = Depends(_get_service),
) -> dict[str, Any]:
    """Load yaml from disk → service.bulk_sync_with_version → record snapshot."""
    loader = ConfigLoader()
    try:
        configs = loader.load_source_configs()
    except Exception as exc:
        return {"loaded_count": 0, "errors": [{"file": "(scan)", "error": str(exc)}]}

    try:
        return await service.bulk_sync_with_version(configs)
    except Exception as exc:
        return {
            "loaded_count": 0,
            "errors": [{"file": "(sync)", "error": str(exc)}],
        }


@router.post("/sources/config/rollback/{version}")
async def rollback_source_config(
    version: str,
    service: SourceConfigService = Depends(_get_service),
) -> dict[str, Any]:
    """Restore sources from snapshot identified by `version` label."""
    try:
        return await service.rollback_to_version(version)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})  # type: ignore[return-value]
