"""/search/chat history compaction wiring (api.chat_sessions.compact_history)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from intellisource.api.routers.search import _compact_history


def _request(gateway: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(llm_gateway=gateway))
    )


def _over_budget_messages() -> list[dict[str, str]]:
    # > CHAT_COMPACT_TOKEN_BUDGET (6000 tokens ≈ 24000 chars) to cross threshold.
    return [{"role": "user", "content": "x" * 600} for _ in range(50)]


@pytest.mark.asyncio
async def test_compact_history_compacts_when_over_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = SimpleNamespace(context={"messages": _over_budget_messages()})

    async def fake_compact(messages: Any, **kwargs: Any) -> list[dict[str, str]]:
        return [{"role": "system", "content": "summary"}]

    monkeypatch.setattr(
        "intellisource.api.chat_sessions.compact_messages_for_chat", fake_compact
    )
    out = await _compact_history(_request(), stored, stored.context["messages"], None)
    assert out == [{"role": "system", "content": "summary"}]


@pytest.mark.asyncio
async def test_compact_history_skips_when_under_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = [{"role": "user", "content": "hi"}]
    stored = SimpleNamespace(context={"messages": raw})
    calls: list[Any] = []

    async def fake_compact(messages: Any, **kwargs: Any) -> list[dict[str, str]]:
        calls.append(messages)
        return [{"role": "system", "content": "summary"}]

    monkeypatch.setattr(
        "intellisource.api.chat_sessions.compact_messages_for_chat", fake_compact
    )
    out = await _compact_history(_request(), stored, raw, None)
    assert out == raw
    assert calls == []  # under budget → helper never invoked


@pytest.mark.asyncio
async def test_compact_history_falls_back_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _over_budget_messages()
    stored = SimpleNamespace(context={"messages": raw})

    async def boom(messages: Any, **kwargs: Any) -> list[dict[str, str]]:
        raise RuntimeError("compaction unavailable")

    monkeypatch.setattr(
        "intellisource.api.chat_sessions.compact_messages_for_chat", boom
    )
    out = await _compact_history(_request(), stored, raw, None)
    assert out == raw
