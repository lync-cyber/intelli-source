"""Search API router."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.agent.response_utils import extract_answer
from intellisource.api.deps import get_db_session
from intellisource.api.schemas.search import (
    ChatSearchRequest,
    ChatSearchResponse,
    ChatSource,
)
from intellisource.observability.logging import get_logger
from intellisource.pipeline.definition_service import load_pipeline_config
from intellisource.search.chat_session import ChatSessionManager
from intellisource.search.hybrid import HybridSearchEngine, SearchResponse

logger = get_logger(__name__)

router = APIRouter(tags=["search"])

_CHAT_CHANNEL_API: str = "api"
_MAX_HISTORY_TURNS: int = 10
_CHAT_COMPACT_TOKEN_BUDGET: int = 6000


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
    body: SearchRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SearchResponse:
    engine = HybridSearchEngine(session)
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
        return JSONResponse(
            status_code=503,
            content={"detail": "agent_runner not initialised"},
        )

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

    Shared by ``/search/chat`` and ``/search/chat/stream`` so both replay the
    same compacted history. Returns ``(stored_session, session_uuid,
    session_payload)``; persistence is silently skipped (and an empty payload
    returned) when no DB is configured or no ``session_id`` is supplied.
    """
    stored_session: Any = None
    session_uuid: uuid.UUID | None = None
    session_payload = dict(body.session or {})

    if db_manager is not None and body.session_id:
        try:
            async with db_manager.get_session() as db_session:
                stored_session, session_uuid = await _load_chat_session(
                    db_session, body.session_id
                )
        except Exception:
            logger.exception("ChatSession lookup transaction failed")

    if stored_session is not None:
        history_messages = (stored_session.context or {}).get("messages")
        if isinstance(history_messages, list) and "messages" not in session_payload:
            compacted = await _compact_history(
                request, stored_session, history_messages, body.max_tokens_budget
            )
            session_payload["messages"] = compacted[-_MAX_HISTORY_TURNS:]

    return stored_session, session_uuid, session_payload


async def _persist_chat_turn_tx(
    db_manager: Any,
    *,
    stored_session: Any,
    session_uuid: uuid.UUID | None,
    user_message: str,
    assistant_answer: str,
) -> uuid.UUID:
    """Persist one user+assistant turn in its own DB transaction; return its id.

    Shared by both chat endpoints. When no DB is configured the turn is not
    written but a fresh session id is still returned, so the response always
    carries a usable session token. DB errors are logged, never raised.
    """
    response_session_uuid = session_uuid or uuid.uuid4()
    if db_manager is None:
        return response_session_uuid
    try:
        async with db_manager.get_session() as db_session:
            response_session_uuid = await _persist_chat_turn(
                db_session,
                existing=stored_session,
                session_id=response_session_uuid,
                user_message=user_message,
                assistant_answer=assistant_answer,
            )
    except Exception:
        logger.exception("ChatSession persist transaction failed")
    return response_session_uuid


async def _load_chat_session(
    db_session: AsyncSession, session_id: str | None
) -> tuple[Any, uuid.UUID | None]:
    """Return (ChatSession row or None, parsed UUID or None) for *session_id*."""
    if not session_id:
        return None, None
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        return None, None

    from intellisource.storage.repositories.chat_session import (
        ChatSessionRepository,
    )

    try:
        row = await ChatSessionRepository(db_session).get_by_id(session_uuid)
    except Exception:
        logger.exception("ChatSession lookup failed for session_id=%s", session_id)
        return None, session_uuid
    return row, session_uuid


async def _persist_chat_turn(
    db_session: AsyncSession,
    *,
    existing: Any,
    session_id: uuid.UUID,
    user_message: str,
    assistant_answer: str,
) -> uuid.UUID:
    """Append the new user+assistant turn to ChatSession.context.messages.

    Creates a new row when *existing* is None, using *session_id* as both
    the primary key and API channel_user_id so the response token can be
    used to load the same row on the next request. DB errors are logged
    but never raised so the chat reply still returns.
    """
    from intellisource.storage.repositories.chat_session import (
        ChatSessionRepository,
    )

    new_messages = [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": assistant_answer},
    ]
    repo = ChatSessionRepository(db_session)
    try:
        if existing is not None:
            context = dict(existing.context or {})
            history = list(context.get("messages") or [])
            history.extend(new_messages)
            context["messages"] = history[-(_MAX_HISTORY_TURNS * 2) :]
            await repo.update_context(existing.id, context)
            session_id = existing.id
        else:
            await repo.create(
                id=session_id,
                channel=_CHAT_CHANNEL_API,
                channel_user_id=str(session_id),
                context={"messages": new_messages},
            )
        await db_session.commit()
    except Exception:
        logger.exception("ChatSession persist failed; rolling back")
        try:
            await db_session.rollback()
        except Exception:
            logger.exception("ChatSession rollback also failed")
    return session_id


async def _compact_history(
    request: Request,
    stored_session: Any,
    history_messages: list[dict[str, Any]],
    max_tokens_budget: int | None,
) -> list[dict[str, Any]]:
    """Compact stored chat history via ChatSessionManager before replay.

    A history over the token budget is LLM-summarized (or truncated when no
    gateway is configured) instead of hard-sliced, so older context survives.
    Returns the (possibly compacted) message list; falls back to the raw history
    on any error.
    """
    budget = max_tokens_budget or _CHAT_COMPACT_TOKEN_BUDGET
    gateway = getattr(request.app.state, "llm_gateway", None)
    manager = ChatSessionManager(session=None, llm_gateway=gateway)
    try:
        await manager.maybe_compact(stored_session, max_tokens=budget)
    except Exception:
        logger.exception("chat history compaction failed; using raw history")
        return history_messages
    compacted = (stored_session.context or {}).get("messages")
    return compacted if isinstance(compacted, list) else history_messages
