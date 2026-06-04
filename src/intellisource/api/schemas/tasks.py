"""Response schemas for the tasks router."""

from __future__ import annotations

from datetime import datetime

from intellisource.api.schemas.common import APIModel


class TaskItem(APIModel):
    """A single collect task row (mirrors `_serialize_task`)."""

    id: str
    source_id: str
    task_chain_id: str | None = None
    status: str
    priority: str
    trigger_type: str | None = None
    items_collected: int | None = None
    error_message: str | None = None
    retry_count: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


class TaskListResponse(APIModel):
    """Cursor-paginated task list."""

    items: list[TaskItem]
    next_cursor: str | None = None
    has_more: bool


class TaskBrief(APIModel):
    """Compact task descriptor returned by the collect trigger."""

    id: str
    type: str
    status: str
    created_at: datetime | None = None


class TaskTriggerResponse(APIModel):
    """Result of POST /tasks/collect."""

    task_chain_id: str
    tasks: list[TaskBrief]
    message: str
