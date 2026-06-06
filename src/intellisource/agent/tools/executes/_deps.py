"""Shared dependency-wiring helper for agent tool execute functions."""

from __future__ import annotations

from typing import Any

from intellisource.agent.deps import ToolDeps


def resolve_factories(tool_deps: ToolDeps | None, factory_attr: str) -> tuple[Any, Any]:
    """Return ``(service_factory, session_factory)`` resolved from *tool_deps*.

    Yields ``(None, None)`` when *tool_deps* is unset or a factory attribute is
    absent, letting callers degrade gracefully instead of raising.
    """
    if tool_deps is None:
        return None, None
    return (
        getattr(tool_deps, factory_attr, None),
        getattr(tool_deps, "session_factory", None),
    )
