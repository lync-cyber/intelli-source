"""Subscription CRUD API router."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.storage.repositories.subscription import SubscriptionRepository

router = APIRouter(tags=["subscriptions"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SubscriptionCreateRequest(BaseModel):
    name: str
    channel: str
    channel_config: dict[str, Any] | None = None
    match_rules: dict[str, Any] | None = None


class SubscriptionUpdateRequest(BaseModel):
    name: str | None = None
    channel: str | None = None
    channel_config: dict[str, Any] | None = None
    match_rules: dict[str, Any] | None = None
    status: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_subscription(obj: Any) -> dict[str, Any]:
    """Convert a Subscription ORM object to a JSON-serializable dict."""
    return {
        "id": str(obj.id),
        "name": obj.name,
        "source_id": str(obj.source_id) if obj.source_id else None,
        "channel": obj.channel,
        "channel_config": obj.channel_config,
        "match_rules": obj.match_rules,
        "frequency": obj.frequency,
        "status": obj.status,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/subscriptions")
async def list_subscriptions(
    limit: int = 20,
    cursor: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    limit = min(limit, 100)
    repo = SubscriptionRepository(session)
    result = await repo.list(limit=limit, cursor=cursor)
    items = [_serialize_subscription(s) for s in result["items"]]
    return {
        "items": items,
        "next_cursor": result["next_cursor"],
        "has_more": result["has_more"],
    }


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
async def create_subscription(
    body: SubscriptionCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    repo = SubscriptionRepository(session)
    created = await repo.create(
        name=body.name,
        channel=body.channel,
        channel_config=body.channel_config or {},
        match_rules=body.match_rules or {},
    )
    return _serialize_subscription(created)


@router.patch("/subscriptions/{id}")
async def update_subscription(
    id: uuid.UUID,
    body: SubscriptionUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    repo = SubscriptionRepository(session)
    fields = body.model_dump(exclude_unset=True)
    updated = await repo.update(id, **fields)
    if updated is None:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return _serialize_subscription(updated)


@router.delete("/subscriptions/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    repo = SubscriptionRepository(session)
    deleted = await repo.delete(id)
    if not deleted:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return Response(status_code=204)
