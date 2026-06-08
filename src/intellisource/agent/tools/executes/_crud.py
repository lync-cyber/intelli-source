"""Shared envelope + input-validation helpers for management CRUD tools."""

from __future__ import annotations

import functools
import uuid as _uuid
from typing import Any, Callable, Coroutine, TypeVar

from intellisource.agent.deps import ToolDeps
from intellisource.agent.tools.executes._deps import resolve_factories
from intellisource.agent.tools.results import tool_error
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")
ExecuteFn = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


class _ToolInputError(Exception):
    """Raised inside a CRUD body for caller-input faults → ``code=invalid_input``."""


def _crud(tool: str, factory_attr: str) -> Callable[[ExecuteFn], ExecuteFn]:
    """Wrap a CRUD body with the not_wired guard + invalid_input/error envelope.

    The decorated body receives ``(factory, session_factory, **kwargs)`` already
    resolved from ``tool_deps`` and **opens its own session**, so input
    validation can short-circuit before any DB/service call. A body signals a
    caller-input fault by raising ``_ToolInputError`` (mapped to
    ``code=invalid_input``); any other exception is logged and returned as
    ``code=error``. Returned dicts (including ``not_found`` errors and ``tool_ok``
    payloads) pass through untouched.
    """

    def deco(fn: ExecuteFn) -> ExecuteFn:
        @functools.wraps(fn)
        async def wrapper(
            tool_deps: ToolDeps | None = None, **kwargs: Any
        ) -> dict[str, Any]:
            factory, session_factory = resolve_factories(tool_deps, factory_attr)
            if factory is None or session_factory is None:
                return tool_error(tool, "tool_deps not injected", code="not_wired")
            try:
                return await fn(factory, session_factory, **kwargs)
            except _ToolInputError as exc:
                return tool_error(tool, str(exc), code="invalid_input")
            except Exception as exc:  # noqa: BLE001 — uniform tool error envelope
                logger.warning("%s failed: %s", tool, exc)
                return tool_error(tool, str(exc), code="error")

        return wrapper

    return deco


def _validated(build: Callable[[], T]) -> T:
    """Run *build* (a config constructor); map any failure to invalid_input."""
    try:
        return build()
    except _ToolInputError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _ToolInputError(str(exc)) from exc


def _parse_uuid(value: Any, field: str) -> _uuid.UUID:
    """Parse a UUID or raise invalid_input preserving the original message shape."""
    try:
        return _uuid.UUID(str(value))
    except ValueError as exc:
        raise _ToolInputError(f"invalid {field}: {value!r}") from exc
