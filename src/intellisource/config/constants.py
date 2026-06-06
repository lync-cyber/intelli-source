"""Shared constants for the configuration layer."""

from __future__ import annotations

from typing import Final, Literal

MAX_NAME_LENGTH: Final[int] = 100

RenderMode = Literal["code", "llm-assisted", "llm-freeform"]
RENDER_MODES: Final[tuple[RenderMode, ...]] = ("code", "llm-assisted", "llm-freeform")
DEFAULT_RENDER_MODE: Final[RenderMode] = "code"

#: Source.type → pipeline yaml name. Read by ``/tasks/collect`` send_task and
#: the Beat sync. Lives in the cross-cutting config layer so api and scheduler
#: resolve it without a reverse edge to the composition root.
SOURCE_TYPE_TO_PIPELINE: Final[dict[str, str]] = {
    "rss": "scheduled-collect",
    "api": "scheduled-collect",
    "web": "scheduled-collect",
}
