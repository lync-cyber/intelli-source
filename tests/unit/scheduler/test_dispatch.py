"""Tests for send_task_with_trace — unified Celery dispatch facade."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from intellisource.observability.trace_context import (
    TRACE_HEADER_KEY,
    reset_trace_id,
    set_trace_id,
)


@pytest.fixture(autouse=True)
def _clear_trace_id():
    """Reset trace_id contextvar to empty string before and after each test."""
    token = set_trace_id("")
    yield
    reset_trace_id(token)


class TestSendTaskWithTraceInjectsTraceId:
    """send_task_with_trace must inject trace_id into Celery message headers."""

    def test_injects_active_trace_id_into_headers(self) -> None:
        token = set_trace_id("test-trace-abc")
        try:
            mock_result = MagicMock()
            with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
                mock_celery.send_task.return_value = mock_result
                from intellisource.scheduler.dispatch import send_task_with_trace

                send_task_with_trace("run_pipeline", args=[1, 2])

            call_kwargs: dict[str, Any] = mock_celery.send_task.call_args.kwargs
            assert call_kwargs["headers"][TRACE_HEADER_KEY] == "test-trace-abc"
        finally:
            reset_trace_id(token)

    def test_fallback_when_trace_id_not_set(self) -> None:
        """When contextvar is empty, headers must still contain a trace_id key."""
        with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
            mock_celery.send_task.return_value = MagicMock()
            from intellisource.scheduler.dispatch import send_task_with_trace

            send_task_with_trace("run_pipeline")

        call_kwargs: dict[str, Any] = mock_celery.send_task.call_args.kwargs
        # Fallback must be a non-empty string (uuid or "unknown") — not blank
        fallback = call_kwargs["headers"][TRACE_HEADER_KEY]
        assert isinstance(fallback, str) and len(fallback) > 0

    def test_transparent_passthrough_of_celery_options(self) -> None:
        """args / kwargs / queue / countdown must be forwarded unchanged."""
        token = set_trace_id("tid-passthrough")
        try:
            with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
                mock_celery.send_task.return_value = MagicMock()
                from intellisource.scheduler.dispatch import send_task_with_trace

                send_task_with_trace(
                    "run_pipeline",
                    args=(10, 20),
                    kwargs={"a": 1},
                    queue="high",
                    countdown=5,
                )

            _, call_kwargs = mock_celery.send_task.call_args
            assert call_kwargs["args"] == (10, 20)
            assert call_kwargs["kwargs"] == {"a": 1}
            assert call_kwargs["queue"] == "high"
            assert call_kwargs["countdown"] == 5
        finally:
            reset_trace_id(token)

    def test_returns_celery_async_result(self) -> None:
        """Return value must be whatever celery_app.send_task returns."""
        mock_result = MagicMock(id="celery-task-id-123")
        with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
            mock_celery.send_task.return_value = mock_result
            from intellisource.scheduler.dispatch import send_task_with_trace

            result = send_task_with_trace("run_pipeline")

        assert result is mock_result

    def test_caller_provided_headers_are_preserved(self) -> None:
        """Caller-supplied headers must be merged; trace_id wins on conflict."""
        token = set_trace_id("ctx-trace")
        try:
            with patch("intellisource.scheduler.dispatch.celery_app") as mock_celery:
                mock_celery.send_task.return_value = MagicMock()
                from intellisource.scheduler.dispatch import send_task_with_trace

                send_task_with_trace(
                    "run_pipeline",
                    headers={"custom_key": "custom_val"},
                )

            call_kwargs: dict[str, Any] = mock_celery.send_task.call_args.kwargs
            assert call_kwargs["headers"]["custom_key"] == "custom_val"
            assert call_kwargs["headers"][TRACE_HEADER_KEY] == "ctx-trace"
        finally:
            reset_trace_id(token)
