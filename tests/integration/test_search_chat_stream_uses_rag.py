"""Integration tests for /search/chat/stream (B-001).

Verifies the stream endpoint:
- Routes through app.state.agent_runner.run_flexible_stream (NOT
  llm_gateway.stream_complete directly — that was the pre-B-001 behaviour
  that bypassed RAG).
- Returns 503 when agent_runner is unset.
- Emits the documented SSE event shape (step / sources / token / done).
- Echoes back the user message into run_flexible_stream.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(agent_runner: Any = None) -> FastAPI:
    from intellisource.api.routers.search import router as search_router

    app = FastAPI()
    app.include_router(search_router, prefix="/api/v1")
    if agent_runner is not None:
        app.state.agent_runner = agent_runner
    return app


async def _async_iter(events: list[dict[str, Any]]) -> Any:
    for ev in events:
        yield ev


def _make_streaming_runner(events: list[dict[str, Any]]) -> MagicMock:
    runner = MagicMock()
    runner.run_flexible_stream = MagicMock(return_value=_async_iter(events))
    return runner


def _parse_sse_payloads(body: str) -> list[dict[str, Any]]:
    """Parse `data: {...json...}\n\n` stream into a list of dicts."""
    out: list[dict[str, Any]] = []
    for chunk in body.split("\n\n"):
        line = chunk.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload:
            continue
        out.append(json.loads(payload))
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSearchChatStreamRoutesThroughRunner:
    """B-001: stream endpoint must call runner.run_flexible_stream, not gateway."""

    @pytest.mark.asyncio
    async def test_returns_503_when_agent_runner_missing(self) -> None:
        app = _make_app(agent_runner=None)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/search/chat/stream", json={"message": "x"}
            )
        assert resp.status_code == 503
        payloads = _parse_sse_payloads(resp.text)
        assert payloads and payloads[0]["type"] == "error"

    @pytest.mark.asyncio
    async def test_calls_run_flexible_stream_with_user_message(self) -> None:
        runner = _make_streaming_runner(
            [
                {"type": "token", "delta": "ok"},
                {"type": "done", "metadata": {"task_chain_id": "tc-1"}},
            ]
        )
        app = _make_app(agent_runner=runner)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/search/chat/stream",
                json={"message": "找最近的 RAG 论文"},
            )

        assert resp.status_code == 200
        runner.run_flexible_stream.assert_called_once()
        kwargs = runner.run_flexible_stream.call_args.kwargs
        assert kwargs["user_message"] == "找最近的 RAG 论文"

    @pytest.mark.asyncio
    async def test_emits_documented_event_shape(self) -> None:
        runner = _make_streaming_runner(
            [
                {
                    "type": "step",
                    "step": 1,
                    "action": "llm_call",
                    "tool": None,
                    "duration_ms": 12.3,
                    "status": "success",
                },
                {
                    "type": "step",
                    "step": 1,
                    "action": "tool_call",
                    "tool": "search",
                    "duration_ms": 8.0,
                    "status": "success",
                },
                {
                    "type": "sources",
                    "items": [{"title": "Doc", "url": "http://x", "content_id": "c1"}],
                },
                {"type": "token", "delta": "Hello"},
                {"type": "token", "delta": " world"},
                {"type": "done", "metadata": {"task_chain_id": "tc-2"}},
            ]
        )
        app = _make_app(agent_runner=runner)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/search/chat/stream",
                json={"message": "find ai"},
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        payloads = _parse_sse_payloads(resp.text)
        types = [p["type"] for p in payloads]
        assert types == ["step", "step", "sources", "token", "token", "done"]
        assert payloads[2]["items"][0]["content_id"] == "c1"
        assert payloads[3]["delta"] == "Hello"
        assert payloads[-1]["metadata"]["task_chain_id"] == "tc-2"
