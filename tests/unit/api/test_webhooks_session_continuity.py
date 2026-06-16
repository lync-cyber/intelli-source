"""CS webhook dispatch wires ChatSession continuity by channel+user (S-2)."""

from __future__ import annotations

import types
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

import intellisource.storage.repositories.chat_session as chat_repo_mod
from intellisource.api.routers.webhooks import _dispatch_chat_reply


class _Stub:
    def __init__(self, id_: str, context: dict[str, Any]) -> None:
        self.id = id_
        self.context = context


class _FakeGateway:
    """Faithful-shape gateway: estimate_tokens drives over-budget, complete
    returns a summary object with .content."""

    def __init__(self, summary: str) -> None:
        self._summary = summary
        self.complete_calls: list[str] = []

    def estimate_tokens(self, text: str, model: str) -> int:
        return max(len(str(text)) // 4, 1)

    async def complete(self, prompt: str) -> Any:
        self.complete_calls.append(prompt)
        return SimpleNamespace(content=self._summary)


def _over_budget_history() -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []
    for i in range(15):
        msgs.append({"role": "user", "content": f"问题{i} " + "x" * 3000})
        msgs.append({"role": "assistant", "content": f"回答{i} " + "y" * 3000})
    return msgs


def _make_fake_repo(existing: Any, calls: list[tuple[Any, ...]]) -> type:
    class _Repo:
        def __init__(self, _session: Any) -> None: ...

        async def find_by_channel_user(self, channel: str, uid: str) -> Any:
            calls.append(("find", channel, uid))
            return existing

        async def update_context(self, id_: Any, context: dict[str, Any]) -> Any:
            calls.append(("update", id_, context))
            return None

        async def create(
            self, channel: str, channel_user_id: str, context: dict[str, Any]
        ) -> Any:
            calls.append(("create", channel, channel_user_id, context))
            return _Stub("new-id", context)

    return _Repo


class _FakeDB:
    @asynccontextmanager
    async def get_session(self) -> Any:
        yield None


class _FakeRunner:
    def __init__(self) -> None:
        self.captured_session: Any = None

    async def run_flexible(
        self, config: Any, *, user_message: str, session: Any
    ) -> dict[str, Any]:
        self.captured_session = session
        return {"final_answer": f"answer-for-{user_message}"}


class _FakeMessenger:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, *, openid: str, content: str) -> None:
        self.sent.append((openid, content))


def _app(db: Any, gateway: Any = None) -> Any:
    return types.SimpleNamespace(
        state=types.SimpleNamespace(db=db, llm_gateway=gateway)
    )


@pytest.mark.asyncio
async def test_dispatch_resumes_existing_channel_user_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    existing = _Stub("sid-1", {"messages": prior})
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        chat_repo_mod, "ChatSessionRepository", _make_fake_repo(existing, calls)
    )

    runner, messenger = _FakeRunner(), _FakeMessenger()
    await _dispatch_chat_reply(
        _app(_FakeDB()),
        runner,
        messenger,
        channel="wework",
        openid="u1",
        user_text="more",
    )

    assert ("find", "wework", "u1") in calls
    assert runner.captured_session["messages"] == prior
    assert messenger.sent == [("u1", "answer-for-more")]
    update = next(c for c in calls if c[0] == "update")
    assert update[1] == "sid-1"
    assert update[2]["messages"][-2:] == [
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "answer-for-more"},
    ]


@pytest.mark.asyncio
async def test_dispatch_creates_session_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        chat_repo_mod, "ChatSessionRepository", _make_fake_repo(None, calls)
    )

    runner, messenger = _FakeRunner(), _FakeMessenger()
    await _dispatch_chat_reply(
        _app(_FakeDB()),
        runner,
        messenger,
        channel="wechat",
        openid="new",
        user_text="hello",
    )

    assert runner.captured_session == {}
    assert messenger.sent == [("new", "answer-for-hello")]
    create = next(c for c in calls if c[0] == "create")
    assert create[1:3] == ("wechat", "new")
    assert create[3]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "answer-for-hello"},
    ]


@pytest.mark.asyncio
async def test_dispatch_persists_token_aware_summary_over_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An over-budget CS history is summarised (token-aware) before persistence
    instead of hard-sliced, so early multi-turn context survives as a summary."""
    prior = _over_budget_history()
    existing = _Stub("sid-cs", {"messages": prior})
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        chat_repo_mod, "ChatSessionRepository", _make_fake_repo(existing, calls)
    )

    gateway = _FakeGateway(summary="CS 历史结构化摘要")
    runner, messenger = _FakeRunner(), _FakeMessenger()
    await _dispatch_chat_reply(
        _app(_FakeDB(), gateway=gateway),
        runner,
        messenger,
        channel="wework",
        openid="u-big",
        user_text="新问题",
    )

    update = next(c for c in calls if c[0] == "update")
    persisted = update[2]["messages"]
    # Early turns survive as a structured summary, not silently truncated.
    assert any(
        m.get("role") == "system" and m.get("content") == "CS 历史结构化摘要"
        for m in persisted
    ), "over-budget CS history must be summarised before persistence"
    # The just-appended newest turn is retained.
    assert any(m.get("content") == "answer-for-新问题" for m in persisted)
    assert gateway.complete_calls, "LLM summariser must run for an over-budget history"
