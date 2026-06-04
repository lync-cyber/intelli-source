"""Agent control-plane chat router.

Exposes the management-capable ``admin-agent`` pipeline over HTTP so a user can
manage sources / subscriptions / templates / pipelines and trigger runs through
natural language. The endpoints drive ``AgentRunner.run_flexible`` (a real LLM
tool-calling loop) and return the synthesized answer plus a compact trace of
which tools the agent invoked.

Multi-turn memory is server-side: a ``session_id`` round-trips the conversation
through the shared ``ChatSession`` store (same as ``/search/chat``).

Write actions gated at ``confirm`` permission (e.g. ``distribute``) are not
executed on first proposal — the response carries a signed ``confirm_token``
describing the pending calls. The client shows them to the user and, on
approval, replays the token on the next turn; the runner then executes exactly
those approved calls (human-in-the-loop).

A whitelist guards the write-capable agent: only known internal pipeline names
are accepted, so a caller can never point the endpoint at an arbitrary or
path-traversal config.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from intellisource.agent.response_utils import extract_answer
from intellisource.api.chat_sessions import persist_turn, prepare_session
from intellisource.api.confirm_token import mint_confirm_token, parse_confirm_token
from intellisource.api.errors import error_json
from intellisource.observability.logging import get_logger
from intellisource.pipeline.definition_service import load_pipeline_config

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

# Internal pipelines reachable via conversational chat. ``admin-agent`` carries
# the full management toolset; ``instant-search`` is the read-only RAG agent.
_ALLOWED_PIPELINES: frozenset[str] = frozenset({"admin-agent", "instant-search"})


class AgentChatRequest(BaseModel):
    """POST body for /agent/chat and /agent/chat/stream."""

    message: str
    pipeline: str = "admin-agent"
    session: dict[str, Any] | None = None
    session_id: str | None = None
    confirm_token: str | None = None
    max_tokens_budget: int | None = None


class AgentChatResponse(BaseModel):
    """Response for /agent/chat.

    ``tools_used`` is the compact ordered list of tool names; ``results`` is the
    full per-step tool trace (tool + output/error) for callers that need to
    inspect what each tool returned. ``confirm_token`` is present when one or
    more confirm-gated tools are awaiting approval: replay it on the next turn
    (with the user's confirmation) to execute the ``pending_confirmations``.
    """

    answer: str
    pipeline: str
    steps_executed: int
    task_chain_id: str
    session_id: str
    tools_used: list[str]
    results: list[dict[str, Any]] = []
    confirm_token: str | None = None
    pending_confirmations: list[dict[str, Any]] = []


def _tools_used(flex_result: dict[str, Any]) -> list[str]:
    """Project the agent's tool-call trace to an ordered list of tool names."""
    names: list[str] = []
    for step in flex_result.get("results", []):
        if isinstance(step, dict) and "tool" in step:
            names.append(str(step["tool"]))
    return names


def _pending_confirmations(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract the {tool, args} of confirm-gated calls awaiting approval."""
    return [
        {"tool": str(step.get("tool")), "args": step.get("args") or {}}
        for step in results
        if step.get("status") == "pending_confirmation"
    ]


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(request: Request, body: AgentChatRequest) -> Any:
    """Run a conversational agent turn against a whitelisted internal pipeline."""
    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None:
        return error_json(503, "agent_runner not initialised")
    if body.pipeline not in _ALLOWED_PIPELINES:
        return error_json(400, f"unknown agent pipeline: {body.pipeline!r}")

    db_manager = getattr(request.app.state, "db", None)
    llm_gateway = getattr(request.app.state, "llm_gateway", None)
    stored_session, session_uuid, session_payload = await prepare_session(
        db_manager=db_manager,
        llm_gateway=llm_gateway,
        session_id=body.session_id,
        base_session=body.session,
        max_tokens_budget=body.max_tokens_budget,
    )
    approved_calls = parse_confirm_token(body.confirm_token)

    config = load_pipeline_config(body.pipeline)
    flex_result: dict[str, Any] = await runner.run_flexible(
        config,
        user_message=body.message,
        session=session_payload,
        max_tokens_budget=body.max_tokens_budget,
        approved_calls=approved_calls,
    )

    answer = extract_answer(flex_result)
    results = [
        step for step in flex_result.get("results", []) if isinstance(step, dict)
    ]
    pending = _pending_confirmations(results)
    confirm_token = mint_confirm_token(pending) if pending else None

    response_session_uuid = await persist_turn(
        db_manager,
        stored_session=stored_session,
        session_uuid=session_uuid,
        user_message=body.message,
        assistant_answer=answer,
    )

    return AgentChatResponse(
        answer=answer,
        pipeline=body.pipeline,
        steps_executed=int(flex_result.get("steps_executed", 0)),
        task_chain_id=str(flex_result.get("task_chain_id", "")),
        session_id=str(response_session_uuid),
        tools_used=_tools_used(flex_result),
        results=results,
        confirm_token=confirm_token,
        pending_confirmations=pending,
    )


def _sse_error(detail: str, status_code: int) -> StreamingResponse:
    """Return a one-shot SSE error event with the given HTTP status."""
    return StreamingResponse(
        iter([f"data: {json.dumps({'type': 'error', 'detail': detail})}\n\n"]),
        status_code=status_code,
        media_type="text/event-stream",
    )


@router.post("/chat/stream")
async def agent_chat_stream(request: Request, body: AgentChatRequest) -> Any:
    """SSE streaming counterpart to /agent/chat.

    Event payloads mirror /search/chat/stream (step / token / done / error).
    The terminal ``done`` event's ``metadata`` carries ``session_id`` and, when
    confirm-gated calls remain, ``confirm_token`` + ``pending_confirmations``.
    """
    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None:
        return _sse_error("agent_runner not initialised", 503)
    if body.pipeline not in _ALLOWED_PIPELINES:
        return _sse_error(f"unknown agent pipeline: {body.pipeline!r}", 400)

    db_manager = getattr(request.app.state, "db", None)
    llm_gateway = getattr(request.app.state, "llm_gateway", None)
    stored_session, session_uuid, session_payload = await prepare_session(
        db_manager=db_manager,
        llm_gateway=llm_gateway,
        session_id=body.session_id,
        base_session=body.session,
        max_tokens_budget=body.max_tokens_budget,
    )
    approved_calls = parse_confirm_token(body.confirm_token)
    config = load_pipeline_config(body.pipeline)

    async def event_gen() -> Any:
        final_answer = ""
        try:
            async for event in runner.run_flexible_stream(
                config,
                user_message=body.message,
                session=session_payload,
                max_tokens_budget=body.max_tokens_budget,
                approved_calls=approved_calls,
            ):
                if await request.is_disconnected():
                    break
                etype = event.get("type")
                if etype == "token":
                    final_answer += str(event.get("delta", ""))
                elif etype == "done":
                    metadata = dict(event.get("metadata") or {})
                    results = [
                        s for s in metadata.get("results", []) if isinstance(s, dict)
                    ]
                    pending = _pending_confirmations(results)
                    response_session_uuid = await persist_turn(
                        db_manager,
                        stored_session=stored_session,
                        session_uuid=session_uuid,
                        user_message=body.message,
                        assistant_answer=final_answer,
                    )
                    metadata["session_id"] = str(response_session_uuid)
                    if pending:
                        metadata["confirm_token"] = mint_confirm_token(pending)
                        metadata["pending_confirmations"] = pending
                    event = {**event, "metadata": metadata}
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_gen(), media_type="text/event-stream")
