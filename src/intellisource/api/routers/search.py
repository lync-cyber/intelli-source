"""Search API router."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.agent.response_utils import extract_answer
from intellisource.api.chat_sessions import (
    compact_history,
    persist_turn,
    prepare_session,
)
from intellisource.api.deps import get_db_session
from intellisource.api.errors import error_json
from intellisource.api.schemas.search import (
    ChatSearchRequest,
    ChatSearchResponse,
    ChatSource,
)
from intellisource.observability.logging import get_logger
from intellisource.pipeline.definition_service import load_pipeline_config
from intellisource.search.hybrid import HybridSearchEngine, SearchResponse

logger = get_logger(__name__)

router = APIRouter(tags=["search"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str
    search_mode: Literal["keyword", "semantic", "hybrid"] = "hybrid"
    tags: list[str] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    limit: int = 10


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/search")
async def search(
    request: Request,
    body: SearchRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SearchResponse:
    llm_gateway = getattr(request.app.state, "llm_gateway", None)
    engine = HybridSearchEngine(session, llm_gateway=llm_gateway)
    return await engine.search(
        query=body.query,
        mode=body.search_mode,
        tags=body.tags,
        date_from=body.date_from,
        date_to=body.date_to,
        limit=body.limit,
    )


def _search_step_items(output: Any) -> list[Any]:
    """Extract search hit rows from a tool step output dict."""
    if not isinstance(output, dict):
        return []
    response = output.get("response")
    if isinstance(response, dict):
        return list(response.get("items") or [])
    items = output.get("contents") or output.get("items")
    if isinstance(items, list):
        return items
    return []


def _content_detail_row(output: Any) -> dict[str, Any] | None:
    """Extract the document dict from a get_content_detail step output."""
    if not isinstance(output, dict):
        return None
    content = output.get("content")
    return content if isinstance(content, dict) else None


def _extract_sources(flex_result: dict[str, Any]) -> list[ChatSource]:
    """Map search + get_content_detail steps to a deduped ChatSource list.

    The flexible loop may reach documents either by a ``search`` step or by a
    ``get_content_detail`` step (the LLM tool path is non-deterministic), so
    both are harvested and deduplicated by content_id.
    """
    sources: list[ChatSource] = []
    seen: set[str] = set()
    for step in flex_result.get("results", []):
        tool = step.get("tool")
        output = step.get("output", {})
        rows: list[Any] = []
        if tool == "search":
            rows = _search_step_items(output)
        elif tool == "get_content_detail":
            row = _content_detail_row(output)
            if row is not None:
                rows = [row]
        for item in rows:
            if not isinstance(item, dict):
                continue
            content_id = item.get("content_id") or item.get("id")
            dedup_key = str(content_id) if content_id is not None else None
            if dedup_key is not None:
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
            sources.append(
                ChatSource(
                    title=str(item.get("title", "")),
                    url=item.get("url") or item.get("source_url"),
                    content_id=content_id,
                )
            )
    return sources


@router.post("/search/chat", response_model=ChatSearchResponse)
async def chat_search(
    request: Request,
    body: ChatSearchRequest,
) -> Any:
    """Flexible-mode chat search via AgentRunner.run_flexible.

    AC-T100-4 persists a `ChatSession` row when ``session_id`` is supplied
    and an `app.state.db` is available: history `messages` are hydrated
    into the session dict passed to `run_flexible`, then the new
    user+assistant pair is written back before returning. When the DB
    is not configured (e.g. unit-test minimal app), persistence is
    silently skipped so the chat reply path stays usable.
    """
    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None:
        return error_json(503, "agent_runner not initialised")

    db_manager = getattr(request.app.state, "db", None)
    stored_session, session_uuid, session_payload = await _prepare_chat_session(
        request, db_manager, body
    )

    config = load_pipeline_config("instant-search")
    start = time.monotonic()
    flex_result: dict[str, Any] = await runner.run_flexible(
        config,
        user_message=body.message,
        session=session_payload,
        max_tokens_budget=body.max_tokens_budget,
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    answer = extract_answer(flex_result)

    steps_executed: int = int(flex_result.get("steps_executed", 0))
    task_chain_id: str = str(flex_result.get("task_chain_id", ""))

    response_session_uuid = await _persist_chat_turn_tx(
        db_manager,
        stored_session=stored_session,
        session_uuid=session_uuid,
        user_message=body.message,
        assistant_answer=answer,
    )

    resp = ChatSearchResponse(
        session_id=str(response_session_uuid),
        answer=answer,
        sources=_extract_sources(flex_result),
        query_time_ms=elapsed_ms,
        steps_executed=steps_executed,
        task_chain_id=task_chain_id,
    )
    return resp


@router.post("/search/chat/stream")
async def chat_search_stream(
    request: Request,
    body: ChatSearchRequest,
) -> StreamingResponse:
    """SSE streaming chat via AgentRunner.run_flexible_stream (RAG-aware).

    Event payloads (JSON object after ``data:``):
      - {"type": "step", "step": int, "action": "llm_call"|"tool_call",
         "tool": str|None, "duration_ms": float, "status": str}
      - {"type": "sources", "items": [{title, url, content_id}, ...]}
      - {"type": "token", "delta": str}
      - {"type": "done", "metadata": {...task_chain payload...}}
      - {"type": "error", "detail": str}
    """
    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None:
        return StreamingResponse(
            iter(
                [
                    "data: "
                    + json.dumps(
                        {"type": "error", "detail": "agent_runner not initialised"}
                    )
                    + "\n\n"
                ]
            ),
            status_code=503,
            media_type="text/event-stream",
        )

    db_manager = getattr(request.app.state, "db", None)
    stored_session, session_uuid, session_payload = await _prepare_chat_session(
        request, db_manager, body
    )

    config = load_pipeline_config("instant-search")

    async def event_gen() -> Any:
        final_answer = ""
        try:
            async for event in runner.run_flexible_stream(
                config,
                user_message=body.message,
                session=session_payload,
                max_tokens_budget=body.max_tokens_budget,
            ):
                if await request.is_disconnected():
                    break
                etype = event.get("type")
                if etype == "token":
                    final_answer += str(event.get("delta", ""))
                elif etype == "done":
                    # Persist the completed turn (same path as POST /search/chat)
                    # and surface the session token in the terminal event so the
                    # client can continue the conversation on the next request.
                    response_session_uuid = await _persist_chat_turn_tx(
                        db_manager,
                        stored_session=stored_session,
                        session_uuid=session_uuid,
                        user_message=body.message,
                        assistant_answer=final_answer,
                    )
                    metadata = dict(event.get("metadata") or {})
                    metadata["session_id"] = str(response_session_uuid)
                    event = {**event, "metadata": metadata}
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_gen(), media_type="text/event-stream")


async def _prepare_chat_session(
    request: Request,
    db_manager: Any,
    body: ChatSearchRequest,
) -> tuple[Any, uuid.UUID | None, dict[str, Any]]:
    """Load the stored ChatSession (if any) and build the run session payload.

    Thin request/body adapter over :func:`api.chat_sessions.prepare_session`,
    shared with ``/agent/chat``.
    """
    return await prepare_session(
        db_manager=db_manager,
        llm_gateway=getattr(request.app.state, "llm_gateway", None),
        session_id=body.session_id,
        base_session=body.session,
        max_tokens_budget=body.max_tokens_budget,
    )


async def _persist_chat_turn_tx(
    db_manager: Any,
    *,
    stored_session: Any,
    session_uuid: uuid.UUID | None,
    user_message: str,
    assistant_answer: str,
) -> uuid.UUID:
    """Persist one user+assistant turn; delegates to api.chat_sessions."""
    return await persist_turn(
        db_manager,
        stored_session=stored_session,
        session_uuid=session_uuid,
        user_message=user_message,
        assistant_answer=assistant_answer,
    )


async def _compact_history(
    request: Request,
    stored_session: Any,
    history_messages: list[dict[str, Any]],
    max_tokens_budget: int | None,
) -> list[dict[str, Any]]:
    """Compact stored chat history; delegates to api.chat_sessions."""
    return await compact_history(
        getattr(request.app.state, "llm_gateway", None),
        stored_session,
        history_messages,
        max_tokens_budget,
    )
