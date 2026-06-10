"""Tests for run_with_model_failover — the shared chat/complete/stream sweep.

Each model owns its own transient retries, so reaching the next candidate means
the current one is genuinely unavailable; an UNRECOVERABLE error stops early.
"""

from __future__ import annotations

import asyncio

import pytest

from intellisource.core.errors import ErrorCategory, LLMError
from intellisource.llm.gateway._routing import run_with_model_failover


async def test_first_model_success_returns_its_result() -> None:
    async def call_one(model: str) -> str:
        return f"ok:{model}"

    result, model = await run_with_model_failover(["a", "b"], call_one)
    assert result == "ok:a"
    assert model == "a"


async def test_transient_failure_falls_over_to_next_model() -> None:
    seen: list[str] = []
    failed: list[tuple[str, str]] = []

    async def call_one(model: str) -> str:
        seen.append(model)
        if model == "a":
            raise RuntimeError("a down")  # RECOVERABLE_DEGRADED → keep going
        return f"ok:{model}"

    result, model = await run_with_model_failover(
        ["a", "b"],
        call_one,
        on_failure=lambda m, e: failed.append((m, str(e))),
    )
    assert result == "ok:b"
    assert model == "b"
    assert seen == ["a", "b"]
    assert failed == [("a", "a down")]


async def test_unrecoverable_error_stops_before_next_model() -> None:
    seen: list[str] = []

    async def call_one(model: str) -> str:
        seen.append(model)
        raise LLMError("bad request", category=ErrorCategory.UNRECOVERABLE)

    with pytest.raises(LLMError, match="bad request"):
        await run_with_model_failover(["a", "b"], call_one)
    assert seen == ["a"], "an UNRECOVERABLE error fails identically on every model"


async def test_all_models_fail_reraises_last_exception() -> None:
    async def call_one(model: str) -> str:
        raise RuntimeError(f"{model} down")

    with pytest.raises(RuntimeError, match="b down"):
        await run_with_model_failover(["a", "b"], call_one)


async def test_cancellation_propagates_without_failover() -> None:
    seen: list[str] = []

    async def call_one(model: str) -> str:
        seen.append(model)
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_with_model_failover(["a", "b"], call_one)
    assert seen == ["a"], "cancellation must propagate, never fall over"


async def test_empty_model_list_raises() -> None:
    async def call_one(model: str) -> str:
        return "never"

    with pytest.raises(LLMError):
        await run_with_model_failover([], call_one)
