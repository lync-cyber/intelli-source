"""Tests for PipelineLoopObserver — the agent-loop event sink."""

from __future__ import annotations

from typing import Any

from intellisource.agent.observer import LoopObserver, PipelineLoopObserver


class _SpyLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def pipeline_start(self, **kw: Any) -> None:
        self.calls.append(("pipeline_start", kw))

    async def tool_call(self, **kw: Any) -> None:
        self.calls.append(("tool_call", kw))

    async def llm_call(self, **kw: Any) -> None:
        self.calls.append(("llm_call", kw))

    async def pipeline_error(self, **kw: Any) -> None:
        self.calls.append(("pipeline_error", kw))


async def test_none_logger_is_silent_no_op() -> None:
    """A None logger makes every event a no-op so the loop still drives."""
    obs = PipelineLoopObserver(None)
    await obs.pipeline_start("p", "c", "flexible")
    await obs.tool_call("p", "c", "search", 1.0, "success")
    await obs.llm_call("p", "c", "m", 1, 2, 3.0)
    await obs.pipeline_error("p", "c", "boom")


async def test_delegates_to_logger_with_task_chain_id() -> None:
    spy = _SpyLogger()
    obs = PipelineLoopObserver(spy)  # type: ignore[arg-type]
    await obs.pipeline_start("p", "chain-1", "flexible")
    await obs.llm_call("p", "chain-1", "deepseek/x", 10, 20, 5.0)

    assert [c[0] for c in spy.calls] == ["pipeline_start", "llm_call"]
    assert spy.calls[0][1] == {
        "pipeline_name": "p",
        "task_chain_id": "chain-1",
        "mode": "flexible",
    }
    assert spy.calls[1][1]["model"] == "deepseek/x"
    assert spy.calls[1][1]["task_chain_id"] == "chain-1"


async def test_tool_call_status_normalized_to_success_or_error() -> None:
    spy = _SpyLogger()
    obs = PipelineLoopObserver(spy)  # type: ignore[arg-type]
    await obs.tool_call("p", "c", "search", 1.0, "weird-status")
    await obs.tool_call("p", "c", "search", 1.0, "error", error="boom")

    assert spy.calls[0][1]["status"] == "success"  # any non-"error" → success
    assert spy.calls[1][1]["status"] == "error"
    assert spy.calls[1][1]["error"] == "boom"


def test_observer_satisfies_protocol() -> None:
    assert isinstance(PipelineLoopObserver(), LoopObserver)
