"""Canonical structured result shape for agent tool execute functions.

Management / CRUD tools return ``{"status": "ok" | "error", "tool", ...}`` so the
agent loop and downstream consumers branch on outcome uniformly. ``tool_error``
carries a machine-readable ``code`` plus a human ``reason``.
"""

from __future__ import annotations

from typing import Any


def tool_ok(tool: str, **data: Any) -> dict[str, Any]:
    """Build a success result for *tool* with arbitrary payload fields."""
    return {"status": "ok", "tool": tool, **data}


def tool_error(
    tool: str, reason: str, *, code: str = "error", **data: Any
) -> dict[str, Any]:
    """Build an error result with a machine code and a human-readable reason."""
    return {"status": "error", "tool": tool, "code": code, "reason": reason, **data}
