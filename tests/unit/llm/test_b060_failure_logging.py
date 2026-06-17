"""Failed LLM calls must be persisted to llm_call_logs.

These tests pin the contract that ``_unified_call_with_retry`` emits a failure
record with a non-empty ``error_message`` for every terminal failure mode:
retry-exhausted failures, timeouts, and circuit-open rejections.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from tenacity import wait_none

from intellisource.llm.circuit_breaker import CircuitOpenError
from intellisource.llm.cost_tracker import CostTracker, LLMCallRecord
from intellisource.llm.gateway import LLMGateway
from intellisource.storage.models import LLMCallLog


def _make_gateway(**kwargs: object) -> LLMGateway:
    return LLMGateway(**kwargs)  # type: ignore[arg-type]


def _logged_records(tracker: AsyncMock) -> list[LLMCallRecord]:
    """Return every LLMCallRecord passed to ``cost_tracker.log_call``."""
    return [call.args[0] for call in tracker.log_call.await_args_list]


# ===========================================================================
# DTO + persistence: error_message field
# ===========================================================================


class TestErrorMessageField:
    """LLMCallRecord carries error_message and CostTracker persists it."""

    def test_record_accepts_error_message(self) -> None:
        record = LLMCallRecord(
            model="gpt-4o-mini",
            provider="openai",
            call_type="complete",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            input_length=0,
            output_length=0,
            status="error",
            error_message="boom",
        )
        assert record.error_message == "boom"

    def test_record_error_message_defaults_none(self) -> None:
        record = LLMCallRecord(
            model="m",
            provider="p",
            call_type="complete",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            input_length=1,
            output_length=1,
            status="success",
        )
        assert record.error_message is None

    @pytest.mark.asyncio
    async def test_log_call_persists_error_message(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        tracker = CostTracker(session=session)
        record = LLMCallRecord(
            model="gpt-4o-mini",
            provider="openai",
            call_type="complete",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            input_length=0,
            output_length=0,
            status="error",
            error_message="upstream exploded",
        )

        await tracker.log_call(record)

        orm_obj = session.add.call_args[0][0]
        assert isinstance(orm_obj, LLMCallLog)
        assert orm_obj.error_message == "upstream exploded"


# ===========================================================================
# Failure-path emission in _unified_call_with_retry
# ===========================================================================


class TestFailureLogging:
    """_unified_call_with_retry emits a failure record on every terminal failure."""

    @pytest.mark.asyncio
    async def test_unrecoverable_failure_emits_error_record(self) -> None:
        tracker = AsyncMock()
        tracker.log_call = AsyncMock()
        gw = _make_gateway(_retry_wait=wait_none(), cost_tracker=tracker)

        class _FakeBadRequestError(Exception):
            pass

        _FakeBadRequestError.__name__ = "BadRequestError"

        async def _bad() -> object:
            raise _FakeBadRequestError("invalid api key")

        with pytest.raises(_FakeBadRequestError):
            await gw._unified_call_with_retry(
                _bad,
                model="gpt-4o-mini",
                call_type="complete",
                enable_circuit_breaker=False,
            )

        records = _logged_records(tracker)
        failures = [r for r in records if r.status == "error"]
        assert len(failures) == 1, f"expected one error record, got {records}"
        assert failures[0].error_message, "error_message must be non-empty"
        assert "invalid api key" in failures[0].error_message
        assert failures[0].call_type == "complete"
        assert failures[0].model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_circuit_open_emits_circuit_open_record(self) -> None:
        tracker = AsyncMock()
        tracker.log_call = AsyncMock()
        mock_cb = AsyncMock()
        mock_cb.allow_request = AsyncMock(return_value=False)
        gw = _make_gateway(cost_tracker=tracker, circuit_breaker=mock_cb)

        async def _never_called() -> object:  # pragma: no cover
            raise AssertionError("call_fn must not run when circuit is OPEN")

        with pytest.raises(CircuitOpenError):
            await gw._unified_call_with_retry(
                _never_called,
                model="gpt-4o-mini",
                call_type="chat",
                enable_circuit_breaker=True,
            )

        records = _logged_records(tracker)
        assert [r.status for r in records] == ["circuit_open"]
        assert records[0].error_message, "circuit_open record needs error_message"

    @pytest.mark.asyncio
    async def test_timeout_classified_as_timeout_status(self) -> None:
        tracker = AsyncMock()
        tracker.log_call = AsyncMock()
        gw = _make_gateway(_retry_wait=wait_none(), cost_tracker=tracker)

        class _FakeTimeoutError(Exception):
            pass

        _FakeTimeoutError.__name__ = "Timeout"

        async def _slow() -> object:
            raise _FakeTimeoutError("deadline exceeded")

        with pytest.raises(_FakeTimeoutError):
            await gw._unified_call_with_retry(
                _slow,
                model="gpt-4o-mini",
                call_type="complete",
                enable_circuit_breaker=False,
            )

        records = _logged_records(tracker)
        terminal = [r for r in records if r.status in ("error", "timeout")]
        assert len(terminal) == 1
        assert terminal[0].status == "timeout"
        assert terminal[0].error_message

    @pytest.mark.asyncio
    async def test_success_emits_no_failure_record(self) -> None:
        tracker = AsyncMock()
        tracker.log_call = AsyncMock()
        gw = _make_gateway(cost_tracker=tracker)
        resp = MagicMock()

        async def _ok() -> object:
            return resp

        result = await gw._unified_call_with_retry(
            _ok,
            model="gpt-4o-mini",
            call_type="complete",
            enable_circuit_breaker=False,
        )

        assert result is resp
        failure_statuses = {"error", "timeout", "circuit_open"}
        assert not [
            r for r in _logged_records(tracker) if r.status in failure_statuses
        ], "success path must not emit any failure record"
