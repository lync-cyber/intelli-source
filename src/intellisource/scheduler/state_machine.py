"""Task state machine and scheduler management for IntelliSource.

Implements TaskStateMachine (AC-038, AC-T028-1/2/3) and
SchedulerManager (AC-T028-4, AC-039).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from intellisource.core.errors import ErrorCategory, IntelliSourceError

VALID_STATES: set[str] = {
    "pending",
    "running",
    "success",
    "failed",
    "paused",
    "cancelled",
}

VALID_ACTIONS: set[str] = {
    "start",
    "complete",
    "fail",
    "pause",
    "resume",
    "cancel",
    "timeout",
}

SUPPORTED_TRIGGER_MODES: set[str] = {"scheduled", "manual", "message"}

DEFAULT_TIMEOUT_SECONDS: int = 3600

# Transition table: (current_state, action) -> next_state
_TRANSITIONS: dict[tuple[str, str], str] = {
    ("pending", "start"): "running",
    ("running", "complete"): "success",
    ("running", "fail"): "failed",
    ("running", "pause"): "paused",
    ("running", "timeout"): "failed",
    ("paused", "resume"): "running",
    ("pending", "cancel"): "cancelled",
    ("running", "cancel"): "cancelled",
    ("paused", "cancel"): "cancelled",
}


class InvalidTransitionError(IntelliSourceError):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            category=ErrorCategory.UNRECOVERABLE,
            recovery_hint="",
        )


class TaskStateMachine:
    """Manages task state transitions."""

    def __init__(
        self,
        timeout_seconds: int | float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._states: dict[str, str] = {}

    def get_state(self, task_id: str) -> str:
        """Return current state of a task, defaulting to 'pending'."""
        return self._states.get(task_id, "pending")

    def transition(self, task_id: str, action: str) -> dict:
        """Execute a state transition and return metadata dict."""
        if action not in VALID_ACTIONS:
            msg = f"Unknown action '{action}'"
            raise InvalidTransitionError(msg)

        current = self.get_state(task_id)
        key = (current, action)

        if key not in _TRANSITIONS:
            msg = f"Invalid transition: cannot apply '{action}' in state '{current}'"
            raise InvalidTransitionError(msg)

        new_state = _TRANSITIONS[key]
        self._states[task_id] = new_state

        result: dict = {
            "from_state": current,
            "to_state": new_state,
        }

        if action == "pause":
            result["paused_at"] = datetime.now(tz=timezone.utc).isoformat()
            result["revoked_subtasks"] = []
        elif action == "resume":
            result["resumed_at"] = datetime.now(tz=timezone.utc).isoformat()
        elif action == "timeout":
            result["reason"] = f"Task exceeded timeout of {self.timeout_seconds}s"

        return result


class SchedulerManager:
    """Manages Celery Beat schedule registration and removal."""

    def __init__(self) -> None:
        self._schedules: dict[str, dict] = {}

    def register_schedule(
        self,
        name: str,
        cron_expr: str,
        pipeline_name: str,
        params: dict,
    ) -> None:
        """Register a scheduled task. Raises ValueError on duplicate."""
        if name in self._schedules:
            msg = f"Schedule '{name}' already exists"
            raise ValueError(msg)
        self._schedules[name] = {
            "name": name,
            "cron_expr": cron_expr,
            "pipeline_name": pipeline_name,
            "params": params,
        }

    def remove_schedule(self, name: str) -> None:
        """Remove a schedule by name. Raises KeyError if not found."""
        if name not in self._schedules:
            raise KeyError(name)
        del self._schedules[name]

    def list_schedules(self) -> list[dict]:
        """Return all registered schedules as a list of dicts."""
        return list(self._schedules.values())

    def trigger_manual(
        self,
        pipeline_name: str,
        params: dict,
    ) -> dict:
        """Trigger a manual pipeline execution."""
        return {
            "task_id": str(uuid.uuid4()),
            "pipeline_name": pipeline_name,
            "params": params,
            "execution_mode": "manual",
        }
