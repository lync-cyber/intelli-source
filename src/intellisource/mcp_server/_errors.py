"""Shared error shapes + id parsing for the MCP tool modules.

The MCP tools return plain JSON-able dicts; an error is signalled by an
``{"error": <code>, ...}`` envelope rather than an exception. These helpers
keep that envelope's shape consistent across every tool module.
"""

from __future__ import annotations

import uuid
from typing import Any


def invalid_input(reason: str) -> dict[str, str]:
    """Build the ``invalid_input`` error envelope."""
    return {"error": "invalid_input", "reason": reason}


def not_found(**ctx: Any) -> dict[str, Any]:
    """Build the ``not_found`` error envelope, echoing the looked-up id(s)."""
    return {"error": "not_found", **ctx}


def parse_uuid(value: str, field: str) -> uuid.UUID | dict[str, str]:
    """Parse *value* as a UUID, or return an ``invalid_input`` envelope.

    Returning the error dict (rather than raising) lets callers narrow with
    ``isinstance(result, dict)`` and forward it straight to the MCP client.
    """
    try:
        return uuid.UUID(value)
    except ValueError:
        return invalid_input(f"bad {field}: {value!r}")
