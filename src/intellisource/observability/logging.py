"""Structured logging configuration using structlog.

Provides JSON Lines output with timestamp, level, message, and extra fields.
Log level is configurable via IS_LOG_LEVEL environment variable (default: INFO).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TextIO

import structlog


def setup_logging(stream: TextIO | None = None) -> None:
    """Initialize structlog with JSON Lines output.

    Args:
        stream: Output stream for log lines. Defaults to sys.stderr.
    """
    if stream is None:
        stream = sys.stderr

    log_level_name = os.environ.get("IS_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    # Configure stdlib logging to use the desired stream and level
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # Remove existing handlers to avoid duplicates on repeated calls
    root_logger.handlers.clear()

    handler = logging.StreamHandler(stream)
    handler.setLevel(log_level)
    root_logger.addHandler(handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
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


# NOTE: Most business modules in src/intellisource/ still use
# `logging.getLogger(__name__)` directly (arch requires structlog).
# Migration is tracked as a backlog item; blockers are mypy --strict
# type incompatibilities between logging.Logger and
# structlog.stdlib.BoundLogger when loggers are passed as parameters.
