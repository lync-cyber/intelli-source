"""Tests for T-006: Observability module -- structured logging.

Covers:
  AC-057: Log output contains structured fields: task_id, processing_stage, duration_ms
  AC-059: TracingMiddleware emits per-request trace_id, injected into log context
  AC-T006-1: Log format is JSON Lines with timestamp, level, message, extra fields
  AC-T006-2: Log level configurable via IS_LOG_LEVEL environment variable
"""

from __future__ import annotations

import io
import json
import os
from unittest.mock import patch

import pytest

# ===========================================================================
# AC-T006-1: Log format is JSON Lines with timestamp, level, message, extra
# ===========================================================================


class TestLogFormatJsonLines:
    """AC-T006-1: Logs are emitted as JSON Lines containing required fields."""

    def test_import_setup_logging(self) -> None:
        """setup_logging must be importable from observability.logging."""
        from intellisource.observability.logging import setup_logging

        assert callable(setup_logging)

    def test_import_get_logger(self) -> None:
        """get_logger must be importable from observability.logging."""
        from intellisource.observability.logging import get_logger

        assert callable(get_logger)

    def test_log_output_is_valid_json(self) -> None:
        """Each log line must be a valid JSON object (JSON Lines format)."""
        from intellisource.observability.logging import get_logger, setup_logging

        stream = io.StringIO()
        setup_logging(stream=stream)
        logger = get_logger("test")
        logger.info("hello")

        output = stream.getvalue().strip()
        assert output, "No log output captured"
        # Each non-empty line must parse as JSON
        for line in output.splitlines():
            if line.strip():
                parsed = json.loads(line)
                assert isinstance(parsed, dict)

    def test_log_contains_timestamp(self) -> None:
        """Every log entry must include a 'timestamp' field."""
        from intellisource.observability.logging import get_logger, setup_logging

        stream = io.StringIO()
        setup_logging(stream=stream)
        logger = get_logger("test")
        logger.info("ts-check")

        output = stream.getvalue().strip()
        assert output, "No log output captured"
        entry = json.loads(output.splitlines()[-1])
        assert "timestamp" in entry, f"Missing 'timestamp' in log entry: {entry}"

    def test_log_contains_level(self) -> None:
        """Every log entry must include a 'level' field."""
        from intellisource.observability.logging import get_logger, setup_logging

        stream = io.StringIO()
        setup_logging(stream=stream)
        logger = get_logger("test")
        logger.warning("level-check")

        output = stream.getvalue().strip()
        assert output, "No log output captured"
        entry = json.loads(output.splitlines()[-1])
        assert "level" in entry, f"Missing 'level' in log entry: {entry}"
        assert entry["level"].upper() == "WARNING"

    def test_log_contains_message(self) -> None:
        """Every log entry must include a 'message' (or 'event') field."""
        from intellisource.observability.logging import get_logger, setup_logging

        stream = io.StringIO()
        setup_logging(stream=stream)
        logger = get_logger("test")
        logger.info("msg-check")

        output = stream.getvalue().strip()
        assert output, "No log output captured"
        entry = json.loads(output.splitlines()[-1])
        # structlog may use 'event' instead of 'message'; accept either
        has_message = "message" in entry or "event" in entry
        assert has_message, f"Missing 'message'/'event' in log entry: {entry}"

    def test_log_contains_extra_fields(self) -> None:
        """Extra fields passed via bind/context must appear in the JSON output."""
        from intellisource.observability.logging import get_logger, setup_logging

        stream = io.StringIO()
        setup_logging(stream=stream)
        logger = get_logger("test")
        bound = logger.bind(request_id="abc-123")
        bound.info("extra-check")

        output = stream.getvalue().strip()
        assert output, "No log output captured"
        entry = json.loads(output.splitlines()[-1])
        assert entry.get("request_id") == "abc-123", (
            f"Extra field 'request_id' not found or incorrect in: {entry}"
        )


# ===========================================================================
# AC-T006-2: Log level configurable via IS_LOG_LEVEL environment variable
# ===========================================================================


class TestLogLevelConfiguration:
    """AC-T006-2: IS_LOG_LEVEL environment variable controls minimum log level."""

    def test_default_log_level_is_info(self) -> None:
        """When IS_LOG_LEVEL is unset, default log level should be INFO.
        DEBUG messages should be suppressed."""
        from intellisource.observability.logging import get_logger, setup_logging

        with patch.dict(os.environ, {}, clear=False):
            # Ensure IS_LOG_LEVEL is not set
            os.environ.pop("IS_LOG_LEVEL", None)
            stream = io.StringIO()
            setup_logging(stream=stream)
            logger = get_logger("test")
            logger.debug("should-not-appear")
            logger.info("should-appear")

        output = stream.getvalue().strip()
        lines = [ln for ln in output.splitlines() if ln.strip()]
        # At least the INFO line should be present
        assert len(lines) >= 1, "Expected at least one log line for INFO"
        # Verify no DEBUG line leaked through
        for line in lines:
            entry = json.loads(line)
            msg = entry.get("message", entry.get("event", ""))
            assert msg != "should-not-appear", (
                "DEBUG message appeared when default level should be INFO"
            )

    def test_log_level_set_to_debug(self) -> None:
        """Setting IS_LOG_LEVEL=DEBUG should allow DEBUG messages through."""
        from intellisource.observability.logging import get_logger, setup_logging

        with patch.dict(os.environ, {"IS_LOG_LEVEL": "DEBUG"}):
            stream = io.StringIO()
            setup_logging(stream=stream)
            logger = get_logger("test")
            logger.debug("debug-msg")

        output = stream.getvalue().strip()
        assert output, "No log output; DEBUG message should have appeared"
        found_debug = False
        for line in output.splitlines():
            if line.strip():
                entry = json.loads(line)
                msg = entry.get("message", entry.get("event", ""))
                if msg == "debug-msg":
                    found_debug = True
        assert found_debug, "DEBUG message not found when IS_LOG_LEVEL=DEBUG"

    def test_log_level_set_to_warning(self) -> None:
        """Setting IS_LOG_LEVEL=WARNING should suppress INFO messages."""
        from intellisource.observability.logging import get_logger, setup_logging

        with patch.dict(os.environ, {"IS_LOG_LEVEL": "WARNING"}):
            stream = io.StringIO()
            setup_logging(stream=stream)
            logger = get_logger("test")
            logger.info("info-suppressed")
            logger.warning("warn-visible")

        output = stream.getvalue().strip()
        for line in output.splitlines():
            if line.strip():
                entry = json.loads(line)
                msg = entry.get("message", entry.get("event", ""))
                assert msg != "info-suppressed", (
                    "INFO message appeared when IS_LOG_LEVEL=WARNING"
                )


# ===========================================================================
# AC-057: Structured fields -- task_id, processing_stage, duration_ms
# ===========================================================================


class TestStructuredLogFields:
    """AC-057: Log output contains task_id, processing_stage, duration_ms."""

    def test_task_id_in_log_output(self) -> None:
        """Binding task_id to logger must include it in JSON output."""
        from intellisource.observability.logging import get_logger, setup_logging

        stream = io.StringIO()
        setup_logging(stream=stream)
        logger = get_logger("worker")
        logger.bind(task_id="task-001").info("processing")

        output = stream.getvalue().strip()
        assert output, "No log output captured"
        entry = json.loads(output.splitlines()[-1])
        assert entry.get("task_id") == "task-001", (
            f"task_id not found in log entry: {entry}"
        )

    def test_processing_stage_in_log_output(self) -> None:
        """Binding processing_stage to logger must include it in JSON output."""
        from intellisource.observability.logging import get_logger, setup_logging

        stream = io.StringIO()
        setup_logging(stream=stream)
        logger = get_logger("pipeline")
        logger.bind(processing_stage="extraction").info("stage log")

        output = stream.getvalue().strip()
        assert output, "No log output captured"
        entry = json.loads(output.splitlines()[-1])
        assert entry.get("processing_stage") == "extraction", (
            f"processing_stage not found in log entry: {entry}"
        )

    def test_duration_ms_in_log_output(self) -> None:
        """Binding duration_ms to logger must include it in JSON output."""
        from intellisource.observability.logging import get_logger, setup_logging

        stream = io.StringIO()
        setup_logging(stream=stream)
        logger = get_logger("pipeline")
        logger.bind(duration_ms=123.45).info("completed")

        output = stream.getvalue().strip()
        assert output, "No log output captured"
        entry = json.loads(output.splitlines()[-1])
        assert "duration_ms" in entry, f"duration_ms not found in log entry: {entry}"
        assert entry["duration_ms"] == 123.45

    def test_all_structured_fields_combined(self) -> None:
        """All three structured fields can coexist in a single log entry."""
        from intellisource.observability.logging import get_logger, setup_logging

        stream = io.StringIO()
        setup_logging(stream=stream)
        logger = get_logger("worker")
        logger.bind(
            task_id="task-002",
            processing_stage="summarization",
            duration_ms=456,
        ).info("done")

        output = stream.getvalue().strip()
        assert output, "No log output captured"
        entry = json.loads(output.splitlines()[-1])
        assert entry.get("task_id") == "task-002"
        assert entry.get("processing_stage") == "summarization"
        assert entry.get("duration_ms") == 456


# ===========================================================================
# AC-059: TracingMiddleware generates trace_id and injects into log context
# ===========================================================================


class TestTracingMiddlewareLogIntegration:
    """AC-059: TracingMiddleware generates unique trace_id per request
    and injects it into structlog context."""

    def test_import_tracing_middleware(self) -> None:
        """TracingMiddleware must be importable from observability.tracing."""
        from intellisource.observability.tracing import TracingMiddleware

        assert isinstance(TracingMiddleware, type)

    @pytest.mark.asyncio
    async def test_trace_id_injected_into_log_context(self) -> None:
        """TracingMiddleware must inject a trace_id into the structlog context
        so that logs emitted during request handling contain the trace_id."""
        from intellisource.observability.logging import get_logger, setup_logging
        from intellisource.observability.tracing import TracingMiddleware

        stream = io.StringIO()
        setup_logging(stream=stream)

        # Minimal ASGI app that logs a message
        async def app(scope: dict, receive: object, send: object) -> None:
            logger = get_logger("app")
            logger.info("request-handled")

        middleware = TracingMiddleware(app)

        # Simulate a minimal HTTP request through the middleware
        scope = {"type": "http", "method": "GET", "path": "/test"}

        async def receive() -> dict:
            return {"type": "http.request", "body": b""}

        sent_events: list[dict] = []

        async def send(event: dict) -> None:
            sent_events.append(event)

        await middleware(scope, receive, send)

        output = stream.getvalue().strip()
        assert output, "No log output during middleware handling"
        entry = json.loads(output.splitlines()[-1])
        assert "trace_id" in entry, f"trace_id not injected into log context: {entry}"
        assert isinstance(entry["trace_id"], str)
        assert len(entry["trace_id"]) > 0

    @pytest.mark.asyncio
    async def test_trace_id_is_unique_per_request(self) -> None:
        """Each request through TracingMiddleware must get a unique trace_id."""
        from intellisource.observability.logging import get_logger, setup_logging
        from intellisource.observability.tracing import TracingMiddleware

        stream = io.StringIO()
        setup_logging(stream=stream)

        async def app(scope: dict, receive: object, send: object) -> None:
            logger = get_logger("app")
            logger.info("handled")

        middleware = TracingMiddleware(app)
        scope = {"type": "http", "method": "GET", "path": "/test"}

        async def receive() -> dict:
            return {"type": "http.request", "body": b""}

        async def send(event: dict) -> None:
            pass

        # Two requests
        await middleware(scope, receive, send)
        await middleware(scope, receive, send)

        output = stream.getvalue().strip()
        lines = [ln for ln in output.splitlines() if ln.strip()]
        assert len(lines) >= 2, "Expected at least 2 log lines for 2 requests"

        trace_ids = []
        for line in lines:
            entry = json.loads(line)
            if "trace_id" in entry:
                trace_ids.append(entry["trace_id"])

        assert len(trace_ids) >= 2, "Expected trace_id in at least 2 log entries"
        assert trace_ids[0] != trace_ids[1], (
            f"trace_id should be unique per request, got same: {trace_ids[0]}"
        )
