"""Shared helper for the management CRUD tool package."""

from __future__ import annotations

from typing import Any


def _pick(kwargs: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Project the subset of *kwargs* whose keys appear in *fields*."""
    return {k: kwargs[k] for k in fields if k in kwargs}
