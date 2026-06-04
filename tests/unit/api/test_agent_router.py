"""P0-1: POST /api/v1/agent/chat — admin-agent conversational control plane.

The endpoint loads the management-capable ``admin-agent`` pipeline (full
CRUD + collect/process/distribute + run/status tools) and drives it through
``AgentRunner.run_flexible`` so a user can manage sources / subscriptions /
pipelines and trigger runs via natural language. A pipeline whitelist guards
the write-capable agent against arbitrary config injection.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.confirm_token import mint_confirm_token
from intellisource.api.routers.agent import router as agent_router


class _StubRunner:
    """Records run_flexible invocations and returns a canned result dict."""

    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def run_flexible(
        self,
        config: Any,
        user_message: str,
        session: dict[str, Any],
        *,
        max_tokens_budget: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "config_name": config.name,
                "user_message": user_message,
                "session": session,
                "max_tokens_budget": max_tokens_budget,
            }
        )
        return self._result


def _make_app(runner: Any | None) -> FastAPI:
    app = FastAPI()
    app.include_router(agent_router, prefix="/api/v1")
    app.state.agent_runner = runner
    return app


async def _post(app: FastAPI, payload: dict[str, Any]) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/api/v1/agent/chat", json=payload)


@pytest.mark.asyncio
async def test_agent_chat_runs_admin_agent_and_summarizes() -> None:
    runner = _StubRunner(
        {
            "final_answer": "已创建信源 hn。",
            "steps_executed": 2,
            "task_chain_id": "chain-1",
            "results": [
                {"tool": "list_sources", "output": {"status": "ok"}},
                {"tool": "create_source", "output": {"status": "ok"}},
            ],
        }
    )
    app = _make_app(runner)

    resp = await _post(app, {"message": "添加 hn 信源"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "已创建信源 hn。"
    assert body["pipeline"] == "admin-agent"
    assert body["steps_executed"] == 2
    assert body["task_chain_id"] == "chain-1"
    # tools_used reflects, in order, which tools the agent actually invoked
    assert body["tools_used"] == ["list_sources", "create_source"]
    # results carries the full per-step trace (tool + output), not just names,
    # so a caller can inspect what each tool returned
    assert body["results"] == [
        {"tool": "list_sources", "output": {"status": "ok"}},
        {"tool": "create_source", "output": {"status": "ok"}},
    ]
    # the endpoint must drive the management-capable admin-agent config, not a
    # read-only search config
    assert runner.calls[0]["config_name"] == "admin-agent"
    assert runner.calls[0]["user_message"] == "添加 hn 信源"


@pytest.mark.asyncio
async def test_agent_chat_503_when_runner_absent() -> None:
    app = _make_app(None)

    resp = await _post(app, {"message": "hi"})

    assert resp.status_code == 503
    assert "agent_runner" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_agent_chat_rejects_unknown_pipeline() -> None:
    runner = _StubRunner({"final_answer": "x"})
    app = _make_app(runner)

    resp = await _post(app, {"message": "hi", "pipeline": "../../etc/passwd"})

    assert resp.status_code == 400
    # an unknown pipeline name must never reach the runner
    assert runner.calls == []


@pytest.mark.asyncio
async def test_agent_chat_allows_instant_search_pipeline() -> None:
    runner = _StubRunner(
        {
            "final_answer": "搜索结果",
            "steps_executed": 1,
            "task_chain_id": "c2",
            "results": [],
        }
    )
    app = _make_app(runner)

    resp = await _post(app, {"message": "查 AI", "pipeline": "instant-search"})

    assert resp.status_code == 200
    assert runner.calls[0]["config_name"] == "instant-search"
    assert resp.json()["pipeline"] == "instant-search"


@pytest.mark.asyncio
async def test_agent_chat_forwards_session_and_budget() -> None:
    runner = _StubRunner(
        {
            "final_answer": "ok",
            "steps_executed": 1,
            "task_chain_id": "c3",
            "results": [],
        }
    )
    app = _make_app(runner)
    session = {"messages": [{"role": "user", "content": "上一轮"}]}

    resp = await _post(
        app,
        {"message": "下一轮", "session": session, "max_tokens_budget": 1234},
    )

    assert resp.status_code == 200
    assert runner.calls[0]["session"] == session
    assert runner.calls[0]["max_tokens_budget"] == 1234


@pytest.mark.asyncio
async def test_agent_chat_falls_back_to_step_output_when_no_final_answer() -> None:
    runner = _StubRunner(
        {
            "steps_executed": 1,
            "task_chain_id": "c4",
            "results": [
                {"tool": "search", "output": {"summary": "三条结果"}},
            ],
        }
    )
    app = _make_app(runner)

    resp = await _post(app, {"message": "查", "pipeline": "instant-search"})

    assert resp.status_code == 200
    # extract_answer falls back to the last step's summary text
    assert resp.json()["answer"] == "三条结果"


# ---------------------------------------------------------------------------
# P1.1: server-side session memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_chat_returns_session_id() -> None:
    """The response always carries a usable session token (even without a DB)."""
    runner = _StubRunner(
        {"final_answer": "ok", "steps_executed": 1, "task_chain_id": "c", "results": []}
    )
    app = _make_app(runner)

    resp = await _post(app, {"message": "hi"})

    assert resp.status_code == 200
    # a parseable session id is returned so the client can continue the thread
    assert uuid.UUID(resp.json()["session_id"])


# ---------------------------------------------------------------------------
# P1.2: confirm-token human-in-the-loop
# ---------------------------------------------------------------------------


class _CapturingRunner:
    """Records run_flexible kwargs (esp. approved_calls) and returns a result."""

    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.approved_calls: Any = "unset"

    async def run_flexible(
        self, config: Any, user_message: str, session: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        self.approved_calls = kwargs.get("approved_calls")
        return self._result


@pytest.mark.asyncio
async def test_agent_chat_mints_confirm_token_for_pending() -> None:
    runner = _CapturingRunner(
        {
            "final_answer": "将向订阅 s1 推送 c1，确认？",
            "steps_executed": 1,
            "task_chain_id": "c",
            "results": [
                {
                    "tool": "distribute",
                    "status": "pending_confirmation",
                    "args": {"content_id": "c1", "subscription_id": "s1"},
                    "tool_call_id": "tc-1",
                }
            ],
        }
    )
    app = _make_app(runner)

    resp = await _post(app, {"message": "把 c1 推给 s1"})

    body = resp.json()
    assert resp.status_code == 200
    # a confirm token + the pending action are surfaced for the user to approve
    assert body["confirm_token"]
    assert body["pending_confirmations"] == [
        {"tool": "distribute", "args": {"content_id": "c1", "subscription_id": "s1"}}
    ]


@pytest.mark.asyncio
async def test_agent_chat_forwards_confirm_token_as_approved_calls() -> None:
    runner = _CapturingRunner(
        {
            "final_answer": "已推送",
            "steps_executed": 1,
            "task_chain_id": "c",
            "results": [],
        }
    )
    app = _make_app(runner)
    token = mint_confirm_token([{"tool": "distribute", "args": {"content_id": "c1"}}])

    resp = await _post(app, {"message": "确认", "confirm_token": token})

    assert resp.status_code == 200
    # the approved calls recovered from the token reach the runner verbatim
    assert runner.approved_calls == [
        {"tool": "distribute", "args": {"content_id": "c1"}}
    ]
    # nothing left pending after approval
    assert resp.json()["confirm_token"] is None


@pytest.mark.asyncio
async def test_agent_chat_no_confirm_token_when_nothing_pending() -> None:
    runner = _CapturingRunner(
        {
            "final_answer": "已创建",
            "steps_executed": 1,
            "task_chain_id": "c",
            "results": [{"tool": "create_source", "output": {"status": "ok"}}],
        }
    )
    app = _make_app(runner)

    resp = await _post(app, {"message": "建信源"})

    body = resp.json()
    assert body["confirm_token"] is None
    assert body["pending_confirmations"] == []
    # approved_calls is None when no confirm_token is supplied
    assert runner.approved_calls is None


# ---------------------------------------------------------------------------
# P1.3: SSE streaming endpoint
# ---------------------------------------------------------------------------


class _StreamRunner:
    """Yields a fixed SSE event sequence from run_flexible_stream."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.approved_calls: Any = "unset"

    async def run_flexible_stream(
        self, config: Any, user_message: str, session: dict[str, Any], **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        self.approved_calls = kwargs.get("approved_calls")
        for event in self._events:
            yield event


def _parse_sse(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_agent_chat_stream_done_carries_session_and_confirm_token() -> None:
    runner = _StreamRunner(
        [
            {"type": "token", "delta": "将推送 c1，确认？"},
            {
                "type": "done",
                "metadata": {
                    "task_chain_id": "c",
                    "results": [
                        {
                            "tool": "distribute",
                            "status": "pending_confirmation",
                            "args": {"content_id": "c1"},
                        }
                    ],
                },
            },
        ]
    )
    app = _make_app(runner)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/agent/chat/stream", json={"message": "推 c1"})

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    done = next(e for e in events if e["type"] == "done")
    meta = done["metadata"]
    assert uuid.UUID(meta["session_id"])
    assert meta["confirm_token"]
    assert meta["pending_confirmations"] == [
        {"tool": "distribute", "args": {"content_id": "c1"}}
    ]


@pytest.mark.asyncio
async def test_agent_chat_stream_503_when_runner_absent() -> None:
    app = _make_app(None)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/agent/chat/stream", json={"message": "hi"})

    assert resp.status_code == 503
    events = _parse_sse(resp.text)
    assert events[0]["type"] == "error"
