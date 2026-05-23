"""Integration tests for AC-T100-4: /search/chat ChatSession persistence."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _flex_result() -> dict[str, Any]:
    return {
        "status": "success",
        "steps_executed": 2,
        "results": [
            {"tool": "summarize_for_user", "output": {"text": "回答内容 OK"}},
        ],
        "task_chain_id": "tc-test",
    }


def _make_app(*, db_session_mock: Any, existing_session: Any = None) -> FastAPI:
    from contextlib import asynccontextmanager

    from intellisource.api.routers.search import router as search_router

    app = FastAPI()
    app.include_router(search_router, prefix="/api/v1")

    runner = MagicMock()
    runner.run_flexible = AsyncMock(return_value=_flex_result())
    app.state.agent_runner = runner

    if existing_session is not None:
        db_session_mock.get = AsyncMock(return_value=existing_session)
    else:
        db_session_mock.get = AsyncMock(return_value=None)
    db_session_mock.commit = AsyncMock()
    db_session_mock.rollback = AsyncMock()

    @asynccontextmanager
    async def _session_cm() -> Any:
        yield db_session_mock

    db_manager = MagicMock()
    db_manager.get_session = lambda: _session_cm()
    app.state.db = db_manager

    return app


class TestChatSessionPersistence:
    """AC-T100-4: ChatSession row created / updated by /search/chat."""

    async def test_no_session_id_creates_new_chat_session(
        self, monkeypatch: Any
    ) -> None:
        from intellisource.storage.repositories import chat_session as cs_mod

        db_session = MagicMock()
        repo_create = AsyncMock()

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                self._session = session

            create = repo_create

            async def update_context(self, *args: Any, **kwargs: Any) -> None:
                raise AssertionError("update_context should not be called")

        monkeypatch.setattr(cs_mod, "ChatSessionRepository", _FakeRepo)

        app = _make_app(db_session_mock=db_session)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/search/chat",
                json={"message": "你好"},
            )

        assert resp.status_code == 200
        repo_create.assert_awaited_once()
        call_kwargs = repo_create.await_args.kwargs
        assert call_kwargs["channel"] == "api"
        messages = call_kwargs["context"]["messages"]
        assert messages[0] == {"role": "user", "content": "你好"}
        assert messages[1]["role"] == "assistant"

    async def test_existing_session_id_updates_context(self, monkeypatch: Any) -> None:
        from intellisource.storage.repositories import chat_session as cs_mod

        existing_id = uuid.uuid4()
        existing = SimpleNamespace(
            id=existing_id,
            context={
                "messages": [
                    {"role": "user", "content": "上一轮问题"},
                    {"role": "assistant", "content": "上一轮回答"},
                ]
            },
        )

        db_session = MagicMock()
        repo_update = AsyncMock()
        repo_create = AsyncMock()

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                self._session = session

            update_context = repo_update
            create = repo_create

        monkeypatch.setattr(cs_mod, "ChatSessionRepository", _FakeRepo)

        app = _make_app(db_session_mock=db_session, existing_session=existing)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/search/chat",
                json={"message": "新一轮", "session_id": str(existing_id)},
            )

        assert resp.status_code == 200
        repo_create.assert_not_awaited()
        repo_update.assert_awaited_once()
        called_id, called_context = repo_update.await_args.args
        assert called_id == existing_id
        history = called_context["messages"]
        # 2 old + 2 new = 4 turns
        assert len(history) == 4
        assert history[2] == {"role": "user", "content": "新一轮"}

    async def test_existing_session_history_hydrated_into_runner(
        self, monkeypatch: Any
    ) -> None:
        """run_flexible receives history messages in session payload."""
        from intellisource.storage.repositories import chat_session as cs_mod

        existing_id = uuid.uuid4()
        existing = SimpleNamespace(
            id=existing_id,
            context={
                "messages": [
                    {"role": "user", "content": "history-q"},
                    {"role": "assistant", "content": "history-a"},
                ]
            },
        )

        db_session = MagicMock()

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                self._session = session

            update_context = AsyncMock()
            create = AsyncMock()

        monkeypatch.setattr(cs_mod, "ChatSessionRepository", _FakeRepo)

        app = _make_app(db_session_mock=db_session, existing_session=existing)
        runner = app.state.agent_runner

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/v1/search/chat",
                json={"message": "新", "session_id": str(existing_id)},
            )

        passed_session = runner.run_flexible.await_args.kwargs["session"]
        assert passed_session.get("messages") == [
            {"role": "user", "content": "history-q"},
            {"role": "assistant", "content": "history-a"},
        ]

    async def test_persist_failure_does_not_break_response(
        self, monkeypatch: Any
    ) -> None:
        """ChatSession DB error must NOT prevent the chat reply from returning."""
        from intellisource.storage.repositories import chat_session as cs_mod

        db_session = MagicMock()

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                self._session = session

            create = AsyncMock()
            update_context = AsyncMock()

        monkeypatch.setattr(cs_mod, "ChatSessionRepository", _FakeRepo)

        app = _make_app(db_session_mock=db_session)
        # _make_app installs default commit/rollback mocks; override commit
        # to simulate a DB failure for this scenario.
        db_session.commit = AsyncMock(side_effect=RuntimeError("db down"))
        db_session.rollback = AsyncMock()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/search/chat",
                json={"message": "你好"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == "回答内容 OK"
        db_session.rollback.assert_awaited()
