"""Agent control-plane chat router.

Exposes the management-capable ``admin-agent`` pipeline over HTTP so a user can
manage sources / subscriptions / pipelines and trigger runs through natural
language. The endpoint drives ``AgentRunner.run_flexible`` (a real LLM
tool-calling loop) and returns the synthesized answer plus a compact trace of
which tools the agent invoked.

A whitelist guards the write-capable agent: only known internal pipeline names
are accepted, so a caller can never point the endpoint at an arbitrary or
path-traversal config.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from intellisource.agent.response_utils import extract_answer
from intellisource.observability.logging import get_logger
from intellisource.pipeline.definition_service import load_pipeline_config

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

# Internal pipelines reachable via conversational chat. ``admin-agent`` carries
# the full management toolset; ``instant-search`` is the read-only RAG agent.
_ALLOWED_PIPELINES: frozenset[str] = frozenset({"admin-agent", "instant-search"})


class AgentChatRequest(BaseModel):
    """POST body for /agent/chat."""

    message: str
    pipeline: str = "admin-agent"
    session: dict[str, Any] | None = None
    max_tokens_budget: int | None = None


class AgentChatResponse(BaseModel):
    """Response for /agent/chat.

    ``tools_used`` is the compact ordered list of tool names; ``results`` is the
    full per-step tool trace (tool + output/error) for callers that need to
    inspect what each tool returned, not just which tools ran.
    """

    answer: str
    pipeline: str
    steps_executed: int
    task_chain_id: str
    tools_used: list[str]
    results: list[dict[str, Any]] = []


def _tools_used(flex_result: dict[str, Any]) -> list[str]:
    """Project the agent's tool-call trace to an ordered list of tool names."""
    names: list[str] = []
    for step in flex_result.get("results", []):
        if isinstance(step, dict) and "tool" in step:
            names.append(str(step["tool"]))
    return names


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(request: Request, body: AgentChatRequest) -> Any:
    """Run a conversational agent turn against a whitelisted internal pipeline."""
    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "agent_runner not initialised"},
        )
    if body.pipeline not in _ALLOWED_PIPELINES:
        return JSONResponse(
            status_code=400,
            content={"detail": f"unknown agent pipeline: {body.pipeline!r}"},
        )

    config = load_pipeline_config(body.pipeline)
    flex_result: dict[str, Any] = await runner.run_flexible(
        config,
        user_message=body.message,
        session=dict(body.session or {}),
        max_tokens_budget=body.max_tokens_budget,
    )

    raw_results = flex_result.get("results", [])
    results = [step for step in raw_results if isinstance(step, dict)]

    return AgentChatResponse(
        answer=extract_answer(flex_result),
        pipeline=body.pipeline,
        steps_executed=int(flex_result.get("steps_executed", 0)),
        task_chain_id=str(flex_result.get("task_chain_id", "")),
        tools_used=_tools_used(flex_result),
        results=results,
    )
