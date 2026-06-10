"""Tests for compact_agent_messages — pairing-safe agent history compaction.

Unlike compact_messages (plain chat history), this must keep every assistant
tool_calls message bound to its tool responses: the result is validated against
the agent loop's own history invariant (_validate_history).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from intellisource.agent.executors.flexible import _validate_history
from intellisource.llm.compaction import compact_agent_messages
from intellisource.llm.model_config import ModelProfile


class _FakeGateway:
    """Faithful-shape gateway stub: 1 token per char + a summarizing complete()."""

    def __init__(self, summary: str = "SUMMARY") -> None:
        self._summary = summary
        self.complete_calls = 0

    def estimate_tokens(self, text: str, model: str) -> int:
        return len(str(text))

    async def complete(self, prompt: str) -> Any:
        self.complete_calls += 1
        return SimpleNamespace(content=self._summary)


def _profile() -> ModelProfile:
    return ModelProfile(temperature=0.0, max_tokens=50, context_window=100)


def _tool_call(call_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "t", "arguments": "{}"},
    }


async def test_under_threshold_returns_unchanged() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]
    gw = _FakeGateway()
    out = await compact_agent_messages(
        messages, gw, _profile(), context_token_budget=1000, model="m"
    )
    assert out == messages
    assert gw.complete_calls == 0


async def test_over_threshold_summarizes_and_preserves_pairing() -> None:
    big = "x" * 30
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": big},
        {"role": "assistant", "content": "", "tool_calls": [_tool_call("a")]},
        {"role": "tool", "content": big, "tool_call_id": "a"},
        {"role": "assistant", "content": big},
        {"role": "user", "content": big},
        {"role": "assistant", "content": "", "tool_calls": [_tool_call("b")]},
        {"role": "tool", "content": big, "tool_call_id": "b"},
        {"role": "assistant", "content": "final"},
    ]
    gw = _FakeGateway(summary="SUMMARY")
    out = await compact_agent_messages(
        messages, gw, _profile(), protect_last_n=3, context_token_budget=80, model="m"
    )

    assert _validate_history(out) == []
    assert len(out) < len(messages)
    assert out[0] == {"role": "system", "content": "sys"}
    assert any(m["role"] == "system" and m["content"] == "SUMMARY" for m in out[1:])
    assert out[-1] == {"role": "assistant", "content": "final"}
    assert gw.complete_calls == 1


async def test_cut_snaps_back_to_avoid_splitting_tool_chain() -> None:
    big = "y" * 30
    messages = [
        {"role": "user", "content": big},
        {"role": "assistant", "content": "", "tool_calls": [_tool_call("a")]},
        {"role": "tool", "content": big, "tool_call_id": "a"},
        {"role": "assistant", "content": big},
        {"role": "assistant", "content": "", "tool_calls": [_tool_call("b")]},
        {"role": "tool", "content": big, "tool_call_id": "b"},
        {"role": "assistant", "content": "done"},
    ]
    gw = _FakeGateway()
    # protect_last_n=2 targets the bare tool message for "b"; the cut must snap
    # back to the assistant that opened "b" so the chain is never split.
    out = await compact_agent_messages(
        messages, gw, _profile(), protect_last_n=2, context_token_budget=80, model="m"
    )

    assert _validate_history(out) == []
    assert len(out) < len(messages)
    non_system = [m for m in out if m["role"] != "system"]
    assert non_system[0]["role"] != "tool"


async def test_compress_if_needed_triggers_at_absolute_budget_not_half_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """compress_if_needed must fire on a history far below 50 % of a 1M window.

    A ~52k-token agent history sits under DeepSeek's 500k half-window but well
    over the agent compaction budget, so it must be summarised rather than
    passed through untouched — otherwise the compaction hook is inert for the
    only model the project ships with.
    """
    from intellisource.llm.gateway import LLMGateway

    gw = LLMGateway()
    monkeypatch.setattr(gw, "estimate_tokens", lambda text, model: len(str(text)))

    async def _fake_complete(prompt: str) -> Any:
        return SimpleNamespace(content="SUMMARY")

    monkeypatch.setattr(gw, "complete", _fake_complete)

    # >protect_last_n(20) turns so the head is actually summarisable, each ~2100
    # "tokens" → ~52k total: above the agent budget, below the 500k half-window.
    messages: list[dict[str, Any]] = [{"role": "system", "content": "sys"}]
    for i in range(25):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": "x" * 2100})

    out = await gw.compress_if_needed(messages)

    assert _validate_history(out) == []
    assert len(out) < len(messages)
    assert any(m.get("content") == "SUMMARY" for m in out)


class _NoScanGateway(_FakeGateway):
    """estimate_tokens raises so a stray full-history scan is caught at assertion."""

    def estimate_tokens(self, text: str, model: str) -> int:
        raise AssertionError("estimate_tokens called despite precomputed_total")


async def test_precomputed_total_below_threshold_skips_token_scan() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "x" * 30},
    ]
    gw = _NoScanGateway()
    out = await compact_agent_messages(
        messages,
        gw,
        _profile(),
        context_token_budget=80,
        model="m",
        precomputed_total=10,
    )
    assert out == messages
    assert gw.complete_calls == 0


async def test_precomputed_total_above_threshold_triggers_compaction() -> None:
    big = "x" * 30
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": big},
        {"role": "assistant", "content": "", "tool_calls": [_tool_call("a")]},
        {"role": "tool", "content": big, "tool_call_id": "a"},
        {"role": "assistant", "content": big},
        {"role": "user", "content": big},
        {"role": "assistant", "content": "final"},
    ]
    gw = _NoScanGateway(summary="SUMMARY")
    out = await compact_agent_messages(
        messages,
        gw,
        _profile(),
        protect_last_n=3,
        context_token_budget=80,
        model="m",
        precomputed_total=10_000,
    )
    assert _validate_history(out) == []
    assert len(out) < len(messages)
    assert gw.complete_calls == 1


async def test_estimate_history_tokens_sums_per_message_estimates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intellisource.llm.gateway import LLMGateway

    gw = LLMGateway()
    monkeypatch.setattr(gw, "estimate_tokens", lambda text, model: len(str(text)))
    messages = [
        {"role": "system", "content": "abc"},
        {"role": "user", "content": "de"},
        {"role": "assistant", "content": ""},
    ]

    assert gw.estimate_history_tokens(messages) == 5


async def test_summary_failure_keeps_valid_tail() -> None:
    class _BoomGateway(_FakeGateway):
        async def complete(self, prompt: str) -> Any:
            raise RuntimeError("summary upstream down")

    big = "z" * 30
    messages = [
        {"role": "user", "content": big},
        {"role": "assistant", "content": "", "tool_calls": [_tool_call("a")]},
        {"role": "tool", "content": big, "tool_call_id": "a"},
        {"role": "assistant", "content": big},
        {"role": "user", "content": big},
        {"role": "assistant", "content": "done"},
    ]
    gw = _BoomGateway()
    out = await compact_agent_messages(
        messages, gw, _profile(), protect_last_n=2, context_token_budget=80, model="m"
    )

    assert _validate_history(out) == []
    assert len(out) < len(messages)
