"""Inc5 P2-4: /search/chat history compaction wiring via ChatSessionManager."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from intellisource.api.routers.search import _compact_history
from intellisource.search.chat_session import ChatSessionManager


def _request(gateway: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(llm_gateway=gateway))
    )


@pytest.mark.asyncio
async def test_compact_history_returns_manager_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = SimpleNamespace(context={"messages": [{"role": "user", "content": "hi"}]})

    async def fake_maybe_compact(self: Any, session_row: Any, max_tokens: int) -> None:
        session_row.context["messages"] = [{"role": "system", "content": "summary"}]

    monkeypatch.setattr(ChatSessionManager, "maybe_compact", fake_maybe_compact)
    out = await _compact_history(_request(), stored, stored.context["messages"], None)
    assert out == [{"role": "system", "content": "summary"}]


@pytest.mark.asyncio
async def test_compact_history_falls_back_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = [{"role": "user", "content": "hi"}]
    stored = SimpleNamespace(context={"messages": raw})

    async def boom(self: Any, session_row: Any, max_tokens: int) -> None:
        raise RuntimeError("compaction unavailable")

    monkeypatch.setattr(ChatSessionManager, "maybe_compact", boom)
    out = await _compact_history(_request(), stored, raw, None)
    assert out == raw
