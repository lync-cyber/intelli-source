"""Search API router."""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.agent.tools import load_pipeline_config
from intellisource.api.deps import get_db_session
from intellisource.api.schemas.search import (
    ChatSearchRequest,
    ChatSearchResponse,
    ChatSource,
)
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


def _extract_sources(flex_result: dict[str, Any]) -> list[ChatSource]:
    """Pull hybrid_search step output (if any) and map to ChatSource list."""
    for step in flex_result.get("results", []):
        if step.get("tool") != "hybrid_search":
            continue
        output = step.get("output", {})
        items = output.get("contents") or output.get("items") or []
        sources: list[ChatSource] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            sources.append(
                ChatSource(
                    title=str(item.get("title", "")),
                    url=item.get("url"),
                    content_id=item.get("content_id") or item.get("id"),
                )
            )
        return sources
    return []


@router.post("/search/chat")
async def chat_search(
    request: Request,
    body: ChatSearchRequest,
) -> Any:
    """Flexible-mode chat search via AgentRunner.run_flexible."""
    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "agent_runner not initialised"},
        )

    config = load_pipeline_config("instant-search")
    start = time.monotonic()
    flex_result: dict[str, Any] = await runner.run_flexible(
        config,
        user_message=body.message,
        session=body.session or {},
        max_tokens_budget=body.max_tokens_budget,
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    answer = ""
    for step in reversed(flex_result.get("results", [])):
        text = step.get("output", {}).get("text", "")
        if text:
            answer = str(text)
            break

    session_id = body.session_id or str(uuid.uuid4())
    steps_executed: int = int(flex_result.get("steps_executed", 0))
    task_chain_id: str = str(flex_result.get("task_chain_id", ""))

    resp = ChatSearchResponse(
        session_id=session_id,
        answer=answer,
        sources=_extract_sources(flex_result),
        query_time_ms=elapsed_ms,
        steps_executed=steps_executed,
        task_chain_id=task_chain_id,
    )
    return resp
