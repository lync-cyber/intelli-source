"""Clusters listing API router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.storage.repositories.cluster import ClusterRepository

router = APIRouter(tags=["clusters"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_cluster(obj: Any) -> dict[str, Any]:
    """Serialize ContentCluster to API-016 response dict.

    Planned for migration to api/schemas/clusters.py (Pydantic) in a future sprint.
    """
    latest_digest = (
        max(obj.digests, key=lambda d: d.created_at, default=None)
        if obj.digests
        else None
    )
    digest_summary: str | None = (
        latest_digest.summary if latest_digest is not None else None
    )
    return {
        "id": str(obj.id),
        "topic": obj.topic,
        "tags": obj.tags,
        "content_count": obj.content_count,
        "digest": digest_summary,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/clusters")
async def list_clusters(
    tag: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    repo = ClusterRepository(session)
    try:
        result = await repo.list_clusters(
            tag=tag,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            cursor=cursor,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid cursor")
    items = [_serialize_cluster(c) for c in result["items"]]
    return {
        "items": items,
        "next_cursor": result["next_cursor"],
        "has_more": result["has_more"],
    }
