"""Structured logging configuration using structlog.

Provides JSON Lines output with timestamp, level, message, and extra fields.
Log level is configurable via IS_LOG_LEVEL environment variable (default: INFO).
"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

import structlog

from intellisource.core.settings import get_settings


class TraceIdFormatter(logging.Formatter):
    """Formatter that prepends ``trace_id=<id>`` to non-JSON log lines.

    Reads the trace_id from
    :func:`intellisource.observability.trace_context.current_trace_id` at
    format time. Structlog-rendered lines that already serialize to JSON
    pass through unchanged so the JSON Lines consumer contract stays intact
    (the JSON object already carries ``trace_id`` via ``merge_contextvars``).
    """

    _BASE_FORMAT = (
        "[%(asctime)s] %(levelname)s %(name)s trace_id=%(trace_id)s %(message)s"
    )

    def __init__(self) -> None:
        super().__init__(fmt=self._BASE_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        from intellisource.observability.trace_context import (  # noqa: PLC0415
            current_trace_id,
        )

        record.trace_id = current_trace_id() or "-"
        message = record.getMessage()
        stripped = message.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return message
        return super().format(record)


def setup_logging(stream: TextIO | None = None) -> None:
    """Initialize structlog with JSON Lines output.

    Args:
        stream: Output stream for log lines. Defaults to sys.stderr.
    """
    if stream is None:
        stream = sys.stderr

    log_level_name = get_settings().log_level.upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    handler = logging.StreamHandler(stream)
    handler.setLevel(log_level)
    handler.setFormatter(TraceIdFormatter())
    root_logger.addHandler(handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(key="timestamp"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound with the given module name.

    Args:
        name: Logger name (typically module name).

    Returns:
        A structlog BoundLogger instance.
    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]
