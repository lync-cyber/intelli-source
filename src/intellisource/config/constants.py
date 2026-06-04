"""Shared constants for the configuration layer."""

from __future__ import annotations

from typing import Final, Literal

MAX_NAME_LENGTH: Final[int] = 100

RenderMode = Literal["code", "llm-assisted", "llm-freeform"]
RENDER_MODES: Final[tuple[RenderMode, ...]] = ("code", "llm-assisted", "llm-freeform")
DEFAULT_RENDER_MODE: Final[RenderMode] = "code"
