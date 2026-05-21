"""Search API router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.deps import get_db_session
from intellisource.search.hybrid import HybridSearchEngine

router = APIRouter(tags=["search"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str
    search_mode: str | None = None
    tags: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None
    limit: int | None = None


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/search")
async def search(
    body: SearchRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    engine: Any = HybridSearchEngine(session)
    result: dict[str, Any] = await engine.search(
        query=body.query,
        mode=body.search_mode,
        tags=body.tags,
        date_from=body.date_from,
        date_to=body.date_to,
        limit=body.limit,
    )
    return result


@router.post("/search/chat")
async def chat_search(
    body: ChatRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    engine: Any = HybridSearchEngine(session)
    try:
        result: dict[str, Any] = await engine.chat(
            messages=[{"role": "user", "content": body.message}],
            session_id=body.session_id,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return result
