"""Content listing API router."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.api.schemas.contents import (
    BackfillEmbeddingsResponse,
    ContentListResponse,
)
from intellisource.scheduler.dispatch import (
    BrokerUnavailableError,
    send_task_with_trace,
)
from intellisource.storage.repositories.content import ContentRepository

router = APIRouter(tags=["contents"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_content(obj: Any) -> dict[str, Any]:
    """Convert a Content ORM object to a JSON-serializable dict."""
    return {
        "id": str(obj.id),
        "title": obj.title,
        "summary": obj.summary,
        "tags": obj.tags,
        "source_name": obj.source_name,
        "published_at": obj.published_at,
        "body_text": obj.body_text,
        "source_url": obj.source_url,
        "processing_status": obj.processing_status,
        "raw_content_id": str(obj.raw_content_id) if obj.raw_content_id else None,
        "created_at": obj.created_at,
        "cluster_id": str(obj.cluster_id) if obj.cluster_id else None,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/content/backfill-embeddings",
    status_code=202,
    response_model=BackfillEmbeddingsResponse,
)
async def backfill_embeddings(request: Request) -> BackfillEmbeddingsResponse:
    """Dispatch the backfill-embeddings Celery task and return 202 Accepted."""
    celery_instance = getattr(request.app.state, "celery_app", None)
    if celery_instance is None:
        raise HTTPException(status_code=503, detail="celery_app not initialised")
    try:
        result = send_task_with_trace(
            "backfill_embeddings",
            celery_instance=celery_instance,
        )
    except BrokerUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail=f"broker unavailable: {exc}"
        ) from exc
    return BackfillEmbeddingsResponse(status="accepted", task_id=str(result.id))


@router.get("/contents", response_model=ContentListResponse)
async def list_contents(
    tag: str | None = None,
    source_id: uuid.UUID | None = None,
    cluster_id: uuid.UUID | None = None,
    limit: int = 20,
    cursor: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    limit = min(limit, 100)
    repo = ContentRepository(session)
    result = await repo.list(
        tag=tag,
        source_id=source_id,
        cluster_id=cluster_id,
        limit=limit,
        cursor=cursor,
    )
    items = [_serialize_content(c) for c in result["items"]]
    return {
        "items": items,
        "next_cursor": result["next_cursor"],
        "has_more": result["has_more"],
    }
