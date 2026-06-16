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


class _FakeGateway:
    """Faithful-shape LLM gateway: complete() returns an object with .content;
    estimate_tokens() returns a controllable integer to drive over-budget."""

    def __init__(self, summary: str) -> None:
        self._summary = summary
        self.complete_calls: list[str] = []

    def estimate_tokens(self, text: str, model: str) -> int:
        return max(len(str(text)) // 4, 1)

    async def complete(self, prompt: str) -> Any:
        self.complete_calls.append(prompt)
        return SimpleNamespace(content=self._summary)


def _over_budget_history() -> list[dict[str, Any]]:
    # 30 turns of long content; the total (~30 * 3000 chars ≈ 22500 tokens at
    # 4 chars/token) exceeds the synthetic profile's recent-keep window
    # (context_window 0.6) so the summarise + truncate branch genuinely bounds
    # the result rather than keeping every message.
    msgs: list[dict[str, Any]] = []
    for i in range(15):
        msgs.append({"role": "user", "content": f"问题{i} " + "x" * 3000})
        msgs.append({"role": "assistant", "content": f"回答{i} " + "y" * 3000})
    return msgs


@pytest.mark.asyncio
async def test_bounded_history_summarizes_over_budget_history() -> None:
    history = _over_budget_history()
    gateway = _FakeGateway(summary="第1轮到第N轮的结构化摘要")

    # budget large enough for the summary plus at least the latest turn (each
    # message ~750 tokens), so the recent-keep window actually retains it.
    bounded = await chat_sessions._bounded_history(history, gateway, budget=2000)

    # Early context survives as a structured summary message, not silently dropped.
    assert any(
        m.get("role") == "system" and m.get("content") == "第1轮到第N轮的结构化摘要"
        for m in bounded
    ), "summary message must be present so early context survives compaction"
    # The result is token-bounded, not the fixed 20-message slice — the input
    # is 30 messages; a summary+recent window must be strictly smaller.
    assert len(bounded) < len(history)
    # Most recent turn is retained verbatim alongside the summary.
    assert any(m.get("content", "").startswith("回答14") for m in bounded)


@pytest.mark.asyncio
async def test_bounded_history_result_fits_within_budget() -> None:
    """The compacted history must estimate at or below the passed budget, so a
    second turn does not immediately re-trigger LLM summarisation every round."""
    history = _over_budget_history()
    gateway = _FakeGateway(summary="结构化摘要")
    budget = 6000

    bounded = await chat_sessions._bounded_history(history, gateway, budget=budget)

    assert chat_sessions._estimate_tokens(bounded) <= budget, (
        "compacted result must fit within budget; otherwise it stays over "
        "threshold and re-triggers compaction on the very next turn"
    )


@pytest.mark.asyncio
async def test_bounded_history_no_immediate_retrigger_after_small_append() -> None:
    """After compaction, appending one short turn must stay under budget so the
    next _bounded_history call does not invoke the LLM again."""
    history = _over_budget_history()
    gateway = _FakeGateway(summary="摘要")
    budget = 6000

    first = await chat_sessions._bounded_history(history, gateway, budget=budget)
    first_calls = len(gateway.complete_calls)

    # Append a small turn (well within budget) and bound again.
    appended = first + [
        {"role": "user", "content": "短问题"},
        {"role": "assistant", "content": "短回答"},
    ]
    second = await chat_sessions._bounded_history(appended, gateway, budget=budget)

    # No new LLM summary call: the appended history is still under budget.
    assert len(gateway.complete_calls) == first_calls
    assert second == appended


@pytest.mark.asyncio
async def test_bounded_history_passes_through_when_under_budget() -> None:
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
    ]
    gateway = _FakeGateway(summary="unused")

    bounded = await chat_sessions._bounded_history(history, gateway, budget=6000)

    assert bounded == history
    assert gateway.complete_calls == []  # under budget → no LLM call


@pytest.mark.asyncio
async def test_bounded_history_degrades_without_gateway() -> None:
    history = _over_budget_history()

    bounded = await chat_sessions._bounded_history(history, None, budget=300)

    # No gateway → char-budget truncation; bounded and non-raising.
    assert isinstance(bounded, list)
    assert 0 < len(bounded) < len(history)


@pytest.mark.asyncio
async def test_compact_history_does_not_mutate_stored_context() -> None:
    """compact_history must be pure: it returns the compacted list but leaves
    stored_session.context untouched, so the persist path still reads the raw
    DB history (no read-side/write-side double compaction)."""
    original = _over_budget_history()
    stored = SimpleNamespace(context={"messages": list(original)})
    gateway = _FakeGateway(summary="读取端摘要")

    compacted = await chat_sessions.compact_history(
        gateway, stored, original, max_tokens_budget=2000
    )

    # Returned value is compacted (summary present, strictly shorter)...
    assert any(
        m.get("role") == "system" and m.get("content") == "读取端摘要"
        for m in compacted
    )
    assert len(compacted) < len(original)
    # ...but the detached stored object is left exactly as loaded from the DB.
    assert stored.context["messages"] == original


class _StatefulRepo:
    """Captures the context dicts persisted via create()/update_context().

    Capture lists are per-instance, so concurrent or reordered tests never share
    state. Tests read the captured calls through ``_capturing_repo_factory``.
    """

    def __init__(self, _session: Any) -> None:
        self.created: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> None:
        self.created.append(kwargs)

    async def update_context(self, id: uuid.UUID, context: dict[str, Any]) -> None:  # noqa: A002
        self.updated.append({"id": id, "context": context})


def _capturing_repo_factory() -> tuple[Any, list[_StatefulRepo]]:
    """Return (factory, instances) — every repo the code builds is appended."""
    instances: list[_StatefulRepo] = []

    def _factory(session: Any) -> _StatefulRepo:
        repo = _StatefulRepo(session)
        instances.append(repo)
        return repo

    return _factory, instances


@pytest.mark.asyncio
async def test_persist_turn_writes_summary_into_stored_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The summary produced for an over-budget history is actually persisted
    (written via update_context), not discarded after the request."""
    factory, repos = _capturing_repo_factory()
    monkeypatch.setattr(chat_repo_mod, "ChatSessionRepository", factory)

    existing = SimpleNamespace(
        id=uuid.uuid4(), context={"messages": _over_budget_history()}
    )
    gateway = _FakeGateway(summary="持久化的历史摘要")

    out = await chat_sessions.persist_turn(
        _FakeDB(),
        stored_session=existing,
        session_uuid=existing.id,
        user_message="新一轮问题",
        assistant_answer="新一轮回答",
        llm_gateway=gateway,
        max_tokens_budget=2000,
    )

    assert out == existing.id
    updated = [u for repo in repos for u in repo.updated]
    assert updated, "update_context must be called for an existing row"
    persisted = updated[-1]["context"]["messages"]
    # The persisted history contains the structured summary — proving it was
    # written to the DB, not just used for this request's replay payload.
    assert any(
        m.get("role") == "system" and m.get("content") == "持久化的历史摘要"
        for m in persisted
    )
    # And the just-appended newest turn survives in the persisted window.
    assert any(m.get("content") == "新一轮回答" for m in persisted)


@pytest.mark.asyncio
async def test_persist_turn_without_gateway_still_persists_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gateway=None must not raise and must still write a bounded history."""
    factory, repos = _capturing_repo_factory()
    monkeypatch.setattr(chat_repo_mod, "ChatSessionRepository", factory)

    existing = SimpleNamespace(
        id=uuid.uuid4(), context={"messages": _over_budget_history()}
    )

    out = await chat_sessions.persist_turn(
        _FakeDB(),
        stored_session=existing,
        session_uuid=existing.id,
        user_message="问",
        assistant_answer="答",
        llm_gateway=None,
        max_tokens_budget=2000,
    )

    assert out == existing.id
    updated = [u for repo in repos for u in repo.updated]
    assert updated
    persisted = updated[-1]["context"]["messages"]
    assert 0 < len(persisted) < len(existing.context["messages"]) + 2
