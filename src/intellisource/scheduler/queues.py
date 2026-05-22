"""Queue name constants shared by celery_app and tasks modules."""

from __future__ import annotations

PRIORITY_QUEUES: dict[str, str] = {
    "low": "queue.priority.low",
    "normal": "queue.priority.normal",
    "high": "queue.priority.high",
}

TRIGGER_TYPE_QUEUES: dict[str, str] = {
    "scheduled": "queue.trigger.scheduled",
    "manual": "queue.trigger.manual",
}
