"""TypedDict contracts for agent tool results.

``ToolResult`` is the universal envelope every execute function returns
(``status`` + ``tool``); concrete payload keys vary per tool and per outcome
(ok / degraded / error), so the envelope stays open rather than a closed
per-tool schema. ``ProcessItemResult`` is the homogeneous per-item shape inside
the ``process`` tool's always-list ``results`` field — the chained payload that
``merge_step_output`` and ``AgentRunner.run_batch`` read to thread
``content_id`` / ``raw_content_id`` between collect → process → distribute.
"""

from __future__ import annotations

from typing import TypedDict


class ToolResult(TypedDict):
    """Universal envelope shared by every agent tool execute result."""

    status: str
    tool: str


class ProcessItemResult(TypedDict, total=False):
    """One entry in the ``process`` tool's ``results`` list.

    Success entries carry the rendered fields plus ``content_id`` /
    ``raw_content_id``; skipped entries carry ``status`` + ``reason``.
    """

    status: str
    reason: str
    content_id: str
    raw_content_id: str
    title: str | None
    body_text: str | None
    body_html: str | None
    fingerprint: str | None
