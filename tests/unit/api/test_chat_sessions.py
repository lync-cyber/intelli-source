"""Shared ChatSession persistence used by /search/chat and /agent/chat.

Locks the cross-endpoint multi-turn memory contract: history hydration into the
run payload and best-effort write-back, independent of any one router.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator

import pytest

import intellisource.storage.repositories.chat_session as chat_repo_mod
from intellisource.api import chat_sessions


class _FakeSession:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _FakeDB:
    def get_session(self) -> Any:
        @asynccontextmanager
        async def _cm() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        return _cm()


@pytest.mark.asyncio
async def test_prepare_session_without_db_returns_base_payload() -> None:
    base = {"messages": [{"role": "user", "content": "prev"}]}
    stored, session_uuid, payload = await chat_sessions.prepare_session(
        db_manager=None,
        llm_gateway=None,
        session_id=None,
        base_session=base,
        max_tokens_budget=None,
    )
    assert stored is None
    assert session_uuid is None
    assert payload == base


@pytest.mark.asyncio
async def test_persist_turn_without_db_returns_fresh_uuid() -> None:
    sid = await chat_sessions.persist_turn(
        None,
        stored_session=None,
        session_uuid=None,
        user_message="hi",
        assistant_answer="ok",
    )
    assert uuid.UUID(str(sid))


@pytest.mark.asyncio
async def test_persist_turn_creates_new_row(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, Any]] = []

    class _Repo:
        def __init__(self, _session: Any) -> None: ...

        async def create(self, **kwargs: Any) -> None:
            created.append(kwargs)

    monkeypatch.setattr(chat_repo_mod, "ChatSessionRepository", _Repo)

    sid = uuid.uuid4()
    out = await chat_sessions.persist_turn(
        _FakeDB(),
        stored_session=None,
        session_uuid=sid,
        user_message="建信源 hn",
        assistant_answer="已创建",
    )

    assert out == sid
    assert created and created[0]["id"] == sid
    # the first turn seeds both the user and assistant messages
    assert [m["role"] for m in created[0]["context"]["messages"]] == [
        "user",
        "assistant",
    ]


@pytest.mark.asyncio
async def test_prepare_session_hydrates_stored_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = [
        {"role": "user", "content": "上一轮问题"},
        {"role": "assistant", "content": "上一轮回答"},
    ]
    row = SimpleNamespace(id=uuid.uuid4(), context={"messages": history})

    class _Repo:
        def __init__(self, _session: Any) -> None: ...

        async def get_by_id(self, _sid: uuid.UUID) -> Any:
            return row

    monkeypatch.setattr(chat_repo_mod, "ChatSessionRepository", _Repo)

    stored, session_uuid, payload = await chat_sessions.prepare_session(
        db_manager=_FakeDB(),
        llm_gateway=None,
        session_id=str(row.id),
        base_session=None,
        max_tokens_budget=None,
    )

    assert stored is row
    assert session_uuid == row.id
    # prior turns are replayed into the run payload the agent loop consumes
    assert payload["messages"] == history
