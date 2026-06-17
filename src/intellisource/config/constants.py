"""Shared constants for the configuration layer."""

from __future__ import annotations

from typing import Final, Literal

MAX_NAME_LENGTH: Final[int] = 100

VALID_FREQUENCIES: Final[frozenset[str]] = frozenset(
    {"realtime", "hourly", "daily", "weekly"}
)

#: Per-call deadlines for the flexible agent loop. Single-sourced here so the
#: PipelineConfig defaults and the executor module constants resolve to one value
#: and cannot drift apart.
DEFAULT_LLM_TIMEOUT_S: Final[float] = 120.0
DEFAULT_TOOL_TIMEOUT_S: Final[float] = 60.0

RenderMode = Literal["code", "llm-assisted", "llm-freeform"]
RENDER_MODES: Final[tuple[RenderMode, ...]] = ("code", "llm-assisted", "llm-freeform")

#: Source.type → pipeline yaml name. Read by ``/tasks/collect`` send_task and
#: the Beat sync. Lives in the cross-cutting config layer so api and scheduler
#: resolve it without a reverse edge to the composition root.
SOURCE_TYPE_TO_PIPELINE: Final[dict[str, str]] = {
    "rss": "scheduled-collect",
    "api": "scheduled-collect",
    "web": "scheduled-collect",
}
