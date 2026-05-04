"""Search API router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
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
        search_mode=body.search_mode,
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
) -> dict[str, Any]:
    engine: Any = HybridSearchEngine(session)
    result: dict[str, Any] = await engine.chat(
        message=body.message,
        session_id=body.session_id,
    )
    return result
