"""Source CRUD API router."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.config.loader import ConfigLoader, ConfigVersionManager
from intellisource.config.validator import ConfigValidator
from intellisource.storage.repositories.source import SourceRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sources"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SourceCreateRequest(BaseModel):
    name: str
    type: str
    url: str
    tags: list[str] | None = None
    schedule: dict[str, Any] | None = None
    proxy: str | None = None
    rate_limit: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class SourceUpdateRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    url: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    schedule: dict[str, Any] | None = None
    proxy: str | None = None
    rate_limit: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class ReloadRequest(BaseModel):
    config_name: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FIELD_MAP: dict[str, str] = {
    "schedule": "schedule_interval",
    "rate_limit": "rate_limit_qps",
    "metadata": "metadata_",
}


def _payload_to_orm_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    """Remap public API field names to ORM column names."""
    return {_FIELD_MAP.get(k, k): v for k, v in payload.items()}


def _serialize_source(source: Any) -> dict[str, Any]:
    """Convert a Source ORM object to a JSON-serializable dict."""
    return {
        "id": str(source.id),
        "name": source.name,
        "type": source.type,
        "url": source.url,
        "tags": source.tags,
        "status": source.status,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
        "schedule_interval": source.schedule_interval,
        "schedule_adaptive": source.schedule_adaptive,
        "proxy": source.proxy,
        "rate_limit_qps": source.rate_limit_qps,
        "rate_limit_concurrency": source.rate_limit_concurrency,
        "metadata": source.metadata_,
        "last_collected_at": source.last_collected_at,
        "next_collect_at": source.next_collect_at,
        "error_count": source.error_count,
        "avg_update_interval": source.avg_update_interval,
        "http_etag": source.http_etag,
        "http_last_modified": source.http_last_modified,
        "config_version": source.config_version,
    }


async def reload_source_configs(
    session: AsyncSession,
    *,
    config_name: str | None = None,
) -> dict[str, Any]:
    """Load all source configs from disk, validate, bulk-upsert, and record version."""
    from intellisource.config.models import SourceConfig

    loader = ConfigLoader()
    validator = ConfigValidator()
    repo = SourceRepository(session)
    version_manager = ConfigVersionManager(
        table_name="config_versions",
        config_cls=SourceConfig,
    )

    try:
        configs = loader.load_source_configs()
    except Exception as exc:
        return {"loaded_count": 0, "errors": [{"file": "(scan)", "error": str(exc)}]}

    validated: list[Any] = []
    errors: list[dict[str, Any]] = []
    for cfg in configs:
        try:
            validated.append(validator.validate(cfg))
        except Exception as exc:
            errors.append({"error": str(exc)})

    if validated:
        await repo.bulk_upsert(validated)

    version_label: str = ""
    try:
        version_label = await version_manager.record_version_async(
            validated, session=session, author=None
        )
    except Exception:
        logger.warning("reload: version snapshot recording failed", exc_info=True)

    return {"loaded_count": len(validated), "errors": errors, "version": version_label}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/sources")
async def list_sources(
    type: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    limit = min(limit, 100)
    repo = SourceRepository(session)
    result = await repo.list(
        type=type, status=status, tag=tag, limit=limit, cursor=cursor
    )
    items = [_serialize_source(s) for s in result["items"]]
    return {
        "items": items,
        "next_cursor": result["next_cursor"],
        "has_more": result["has_more"],
    }


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def create_source(
    body: SourceCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    repo = SourceRepository(session)
    raw: dict[str, Any] = {}
    if body.schedule is not None:
        raw["schedule"] = body.schedule
    if body.proxy is not None:
        raw["proxy"] = body.proxy
    if body.rate_limit is not None:
        raw["rate_limit"] = body.rate_limit
    if body.metadata is not None:
        raw["metadata"] = body.metadata
    kwargs = _payload_to_orm_kwargs(raw)
    try:
        created = await repo.create(
            name=body.name,
            type=body.type,
            url=body.url,
            tags=body.tags or [],
            **kwargs,
        )
    except IntegrityError:
        return JSONResponse(status_code=409, content={"detail": "conflict"})  # type: ignore[return-value]
    return _serialize_source(created)


@router.patch("/sources/{id}")
async def update_source(
    id: uuid.UUID,
    body: SourceUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    repo = SourceRepository(session)
    fields = _payload_to_orm_kwargs(body.model_dump(exclude_unset=True))
    updated = await repo.update(id, **fields)
    if updated is None:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return _serialize_source(updated)


@router.delete("/sources/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    repo = SourceRepository(session)
    deleted = await repo.delete(id)
    if not deleted:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return Response(status_code=204)


@router.post("/sources/reload")
async def reload_sources(
    body: ReloadRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        result = await reload_source_configs(session, config_name=body.config_name)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})  # type: ignore[return-value]
    return result


@router.post("/sources/config/rollback/{version}")
async def rollback_source_config(
    version: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Rollback source configuration to a previously recorded version."""
    from typing import cast

    from intellisource.config.models import SourceConfig

    manager = ConfigVersionManager(
        table_name="config_versions",
        config_cls=SourceConfig,
    )
    try:
        configs = cast(
            list[SourceConfig],
            await manager.rollback_by_label(version, session=session),
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})  # type: ignore[return-value]
    repo = SourceRepository(session)
    await repo.bulk_sync_from_configs(list(configs))
    return {
        "rolled_back_to": version,
        "config_count": len(configs),
        "source_names": [c.name for c in configs],
    }
