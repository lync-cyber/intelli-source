"""Subscription API router — HTTP shell over SubscriptionService."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.config.subscription_loader import SubscriptionConfigLoader
from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.config.subscription_validator import SubscriptionValidationError
from intellisource.subscription.service import SubscriptionService

router = APIRouter(tags=["subscriptions"])


# ---------------------------------------------------------------------------
# Request models — Layer 1 alignment: API uses SubscriptionConfig directly
# for create; patch uses an all-Optional variant for partial updates.
# ---------------------------------------------------------------------------


class SubscriptionPatchRequest(BaseModel):
    """Partial-update body: every field optional; mirrors SubscriptionConfig."""

    name: str | None = None
    channel: str | None = None
    channel_config: dict[str, Any] | None = None
    match_rules: dict[str, Any] | None = None
    frequency: str | None = None
    quiet_hours: dict[str, Any] | None = None
    timezone: str | None = None
    discipline_tags: list[str] | None = None
    status: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize(obj: Any) -> dict[str, Any]:
    """ORM → JSON-friendly dict."""
    return {
        "id": str(obj.id),
        "name": obj.name,
        "source_id": str(obj.source_id) if obj.source_id else None,
        "channel": obj.channel,
        "channel_config": obj.channel_config,
        "match_rules": obj.match_rules,
        "frequency": obj.frequency,
        "quiet_hours": obj.quiet_hours,
        "timezone": obj.timezone,
        "discipline_tags": list(obj.discipline_tags),
        "status": obj.status,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


def _get_service(
    session: AsyncSession = Depends(get_db_session),
) -> SubscriptionService:
    return SubscriptionService(session)


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("/subscriptions")
async def list_subscriptions(
    limit: int = 20,
    cursor: str | None = None,
    service: SubscriptionService = Depends(_get_service),
) -> dict[str, Any]:
    limit = min(limit, 100)
    result = await service.list_paginated(limit=limit, cursor=cursor)
    return {
        "items": [_serialize(s) for s in result["items"]],
        "next_cursor": result["next_cursor"],
        "has_more": result["has_more"],
    }


@router.get("/subscriptions/config/versions")
async def list_subscription_versions(
    limit: int = 20,
    service: SubscriptionService = Depends(_get_service),
) -> dict[str, Any]:
    """List recorded subscription config version snapshots (newest first)."""
    limit = min(limit, 100)
    return {"versions": await service.list_versions(limit=limit)}


@router.get("/subscriptions/config/diff")
async def diff_subscription_config(
    service: SubscriptionService = Depends(_get_service),
) -> dict[str, Any]:
    """Diff the yaml SSOT against current DB state (what a reload would change)."""
    loader = SubscriptionConfigLoader()
    try:
        configs = loader.load_subscription_configs()
    except Exception as exc:
        return JSONResponse(  # type: ignore[return-value]
            status_code=400, content={"detail": f"failed to load yaml: {exc}"}
        )
    return await service.diff_with_yaml(configs)


@router.get("/subscriptions/{id}")
async def get_subscription(
    id: uuid.UUID,
    service: SubscriptionService = Depends(_get_service),
) -> Any:
    obj = await service.get(id)
    if obj is None:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return _serialize(obj)


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
async def create_subscription(
    body: SubscriptionConfig,
    service: SubscriptionService = Depends(_get_service),
) -> Any:
    try:
        created = await service.create(body)
    except SubscriptionValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return _serialize(created)


@router.patch("/subscriptions/{id}")
async def update_subscription(
    id: uuid.UUID,
    body: SubscriptionPatchRequest,
    service: SubscriptionService = Depends(_get_service),
) -> Any:
    fields = body.model_dump(exclude_unset=True)
    updated = await service.patch(id, fields)
    if updated is None:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return _serialize(updated)


@router.delete("/subscriptions/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    id: uuid.UUID,
    service: SubscriptionService = Depends(_get_service),
) -> Response:
    deleted = await service.delete(id)
    if not deleted:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Bulk / versioning endpoints (yaml-driven flow)
# ---------------------------------------------------------------------------


@router.post("/subscriptions/reload")
async def reload_subscriptions(
    service: SubscriptionService = Depends(_get_service),
) -> dict[str, Any]:
    """Load yaml from disk → service.bulk_sync_with_version → record snapshot."""
    loader = SubscriptionConfigLoader()
    try:
        configs = loader.load_subscription_configs()
    except Exception as exc:
        return {"loaded_count": 0, "errors": [{"file": "(scan)", "error": str(exc)}]}

    try:
        result = await service.bulk_sync_with_version(configs)
    except Exception as exc:
        return {
            "loaded_count": 0,
            "errors": [{"file": "(sync)", "error": str(exc)}],
        }
    return result


@router.post("/subscriptions/config/rollback/{version}")
async def rollback_subscription_config(
    version: str,
    service: SubscriptionService = Depends(_get_service),
) -> dict[str, Any]:
    """Restore subscriptions from snapshot identified by `version` label."""
    try:
        return await service.rollback_to_version(version)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})  # type: ignore[return-value]
