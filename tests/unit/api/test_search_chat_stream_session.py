"""P3: /search/chat/stream now persists the conversation turn.

The streaming endpoint previously dropped the session entirely (no history
replay, no write-back, no session token in the response), unlike POST
/search/chat. It now shares ``_prepare_chat_session`` / ``_persist_chat_turn_tx``
with the sync endpoint: the accumulated answer is persisted on the terminal
``done`` event and the session id is surfaced in that event's metadata.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.routers.search import router as search_router


@pytest.fixture()
def stream_app() -> FastAPI:
    app = FastAPI()
    app.include_router(search_router, prefix="/api/v1")
    return app


def _runner_yielding(events: list[dict[str, Any]]) -> MagicMock:
    async def _stream(
        config: Any,
        *,
        user_message: str,
        session: dict[str, Any],
        max_tokens_budget: int | None = None,
        **_: Any,
    ) -> Any:
        for ev in events:
            yield ev

    runner = MagicMock()
    runner.run_flexible_stream = _stream
    return runner


def _sse_events(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in text.split("\n\n"):
        line = block.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[len("data:") :].strip()))
    return out


@pytest.mark.asyncio
async def test_stream_persists_turn_and_emits_session_id(
    stream_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream_app.state.agent_runner = _runner_yielding(
        [
            {"type": "token", "delta": "Hello "},
            {"type": "token", "delta": "world"},
            {"type": "done", "metadata": {"task_chain_id": "tc-1"}},
        ]
    )
    stream_app.state.db = MagicMock()  # presence; persistence is stubbed below

    captured: dict[str, Any] = {}
    fixed_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    async def _fake_persist(
        request: Any,
        db_manager: Any,
        body: Any,
        *,
        stored_session: Any,
        session_uuid: Any,
        user_message: str,
        assistant_answer: str,
    ) -> uuid.UUID:
        captured.update(user_message=user_message, assistant_answer=assistant_answer)
        return fixed_id

    monkeypatch.setattr(
        "intellisource.api.routers.search._persist_chat_turn_tx", _fake_persist
    )

    async with AsyncClient(
        transport=ASGITransport(app=stream_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/search/chat/stream", json={"message": "hi there"}
        )

    assert resp.status_code == 200
    # The full assistant answer is accumulated from token deltas and persisted.
    assert captured["assistant_answer"] == "Hello world"
    assert captured["user_message"] == "hi there"

    events = _sse_events(resp.text)
    done = next(e for e in events if e.get("type") == "done")
    assert done["metadata"]["session_id"] == str(fixed_id)
    # Original metadata is preserved alongside the injected session id.
    assert done["metadata"]["task_chain_id"] == "tc-1"


@pytest.mark.asyncio
async def test_stream_emits_session_id_without_db(stream_app: FastAPI) -> None:
    """With no DB the turn is not written, but a session token is still returned."""
    stream_app.state.agent_runner = _runner_yielding(
        [
            {"type": "token", "delta": "ok"},
            {"type": "done", "metadata": {}},
        ]
    )
    stream_app.state.db = None

    async with AsyncClient(
        transport=ASGITransport(app=stream_app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/search/chat/stream", json={"message": "hi"})

    events = _sse_events(resp.text)
    done = next(e for e in events if e.get("type") == "done")
    # A parseable UUID was minted and surfaced even though nothing was persisted.
    assert uuid.UUID(done["metadata"]["session_id"])


@pytest.mark.asyncio
async def test_stream_503_when_runner_missing(stream_app: FastAPI) -> None:
    stream_app.state.agent_runner = None
    async with AsyncClient(
        transport=ASGITransport(app=stream_app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/search/chat/stream", json={"message": "hi"})
    assert resp.status_code == 503
