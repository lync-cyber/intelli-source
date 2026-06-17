"""Tests for worker log formatter injects trace_id contextvar.

Covers the TraceIdFormatter behavior used by stdlib `logging.getLogger(...)`
calls in worker / api processes after setup_logging() is called at boot.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
import structlog

from intellisource.observability.logging import (
    TraceIdFormatter,
    setup_logging,
)
from intellisource.observability.trace_context import (
    reset_trace_id,
    set_trace_id,
)


@pytest.fixture(autouse=True)
def _clean_trace_id() -> None:
    """Ensure trace_id contextvar is clean between tests."""
    token = set_trace_id("")
    try:
        yield
    finally:
        try:
            reset_trace_id(token)
        except (ValueError, LookupError):
            pass


def _make_record(message: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(
        name="test.module",
        level=level,
        pathname=__file__,
        lineno=10,
        msg=message,
        args=None,
        exc_info=None,
    )


class TestTraceIdFormatter:
    """stdlib Formatter that prepends trace_id from contextvar."""

    def test_includes_trace_id_when_set(self) -> None:
        formatter = TraceIdFormatter()
        set_trace_id("trace-abc-123")
        record = _make_record("hello world")
        line = formatter.format(record)
        assert "trace_id=trace-abc-123" in line
        assert "hello world" in line

    def test_falls_back_to_dash_when_unset(self) -> None:
        formatter = TraceIdFormatter()
        record = _make_record("plain message")
        line = formatter.format(record)
        assert "trace_id=-" in line

    def test_json_message_passthrough(self) -> None:
        formatter = TraceIdFormatter()
        set_trace_id("trace-json")
        json_msg = '{"event":"foo","level":"info","trace_id":"trace-json"}'
        record = _make_record(json_msg)
        line = formatter.format(record)
        assert line == json_msg
        assert json.loads(line) == {
            "event": "foo",
            "level": "info",
            "trace_id": "trace-json",
        }

    def test_json_with_leading_or_trailing_whitespace_passthrough(self) -> None:
        formatter = TraceIdFormatter()
        msg = '  {"event":"bar"}\n'
        record = _make_record(msg)
        out = formatter.format(record)
        assert out == msg

    def test_format_includes_levelname_and_logger_name(self) -> None:
        formatter = TraceIdFormatter()
        set_trace_id("t-1")
        record = _make_record("hi", level=logging.WARNING)
        line = formatter.format(record)
        assert "WARNING" in line
        assert "test.module" in line


class TestSetupLoggingInstallsFormatter:
    """setup_logging() must install TraceIdFormatter on the stdlib handler."""

    def test_handler_uses_trace_id_formatter(self) -> None:
        stream = io.StringIO()
        setup_logging(stream=stream)
        root = logging.getLogger()
        assert len(root.handlers) >= 1
        handler = root.handlers[0]
        assert isinstance(handler.formatter, TraceIdFormatter)

    def test_stdlib_log_emits_trace_id(self) -> None:
        stream = io.StringIO()
        setup_logging(stream=stream)
        set_trace_id("trace-stdlib-emit")
        logger = logging.getLogger("intellisource.b040_test")
        logger.info("worker-side stdlib log")

        out = stream.getvalue()
        assert "trace_id=trace-stdlib-emit" in out
        assert "worker-side stdlib log" in out

    def test_structlog_json_output_unwrapped(self) -> None:
        """Structlog JSON Lines must remain pure JSON (parseable)."""
        from intellisource.observability.logging import get_logger

        stream = io.StringIO()
        setup_logging(stream=stream)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id="trace-struct-json")
        try:
            log = get_logger("test")
            log.info("struct-msg")
        finally:
            structlog.contextvars.unbind_contextvars("trace_id")

        out = stream.getvalue().strip()
        last_line = [ln for ln in out.splitlines() if ln.strip()][-1]
        parsed = json.loads(last_line)
        assert parsed.get("trace_id") == "trace-struct-json"


class TestSignalsBindStructlogContextvars:
    """signals._on_task_prerun / _on_task_postrun bind+unbind structlog ctxvars."""

    def test_prerun_binds_structlog_trace_id(self) -> None:
        from intellisource.scheduler import signals as sig_mod

        class _Req:
            headers: dict[str, str] = {"trace_id": "trace-sig-prerun"}

        class _Sender:
            request = _Req()

        structlog.contextvars.clear_contextvars()
        sender = _Sender()
        sig_mod._on_task_prerun(sender=sender, task_id="t1")
        try:
            ctx = structlog.contextvars.get_contextvars()
            assert ctx.get("trace_id") == "trace-sig-prerun"
        finally:
            sig_mod._on_task_postrun(sender=sender, task_id="t1", state="SUCCESS")

    def test_postrun_unbinds_structlog_trace_id(self) -> None:
        from intellisource.scheduler import signals as sig_mod

        class _Req:
            headers: dict[str, str] = {"trace_id": "trace-sig-postrun"}

        class _Sender:
            request = _Req()

        structlog.contextvars.clear_contextvars()
        sender = _Sender()
        sig_mod._on_task_prerun(sender=sender, task_id="t2")
        sig_mod._on_task_postrun(sender=sender, task_id="t2", state="SUCCESS")
        ctx = structlog.contextvars.get_contextvars()
        assert "trace_id" not in ctx

    def test_prerun_with_no_header_binds_dash(self) -> None:
        from intellisource.scheduler import signals as sig_mod

        class _Req:
            headers: dict[str, str] = {}

        class _Sender:
            request = _Req()

        structlog.contextvars.clear_contextvars()
        sender = _Sender()
        sig_mod._on_task_prerun(sender=sender, task_id="t3")
        try:
            ctx = structlog.contextvars.get_contextvars()
            assert ctx.get("trace_id") == "-"
        finally:
            sig_mod._on_task_postrun(sender=sender, task_id="t3", state="SUCCESS")
