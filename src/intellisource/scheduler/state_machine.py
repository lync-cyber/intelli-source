"""Task transition validation and scheduler management for IntelliSource."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from intellisource.core.errors import ErrorCategory, IntelliSourceError

VALID_ACTIONS: set[str] = {
    "start",
    "complete",
    "fail",
    "pause",
    "resume",
    "cancel",
    "timeout",
    "retry",
}

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
    ("failed", "retry"): "pending",
}


class InvalidTransitionError(IntelliSourceError):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            category=ErrorCategory.UNRECOVERABLE,
            recovery_hint="",
        )


def resolve_transition(current_state: str, action: str) -> str:
    """Return the target state for applying *action* in *current_state*.

    Raises InvalidTransitionError when *action* is unknown or the
    (current_state, action) pair has no defined transition. Stateless so
    callers holding the authoritative state elsewhere (e.g. a DB row) can
    validate a transition directly.
    """
    if action not in VALID_ACTIONS:
        raise InvalidTransitionError(f"Unknown action '{action}'")
    key = (current_state, action)
    if key not in _TRANSITIONS:
        msg = f"Invalid transition: cannot apply '{action}' in state '{current_state}'"
        raise InvalidTransitionError(msg)
    return _TRANSITIONS[key]


class SchedulerStateBackend(ABC):
    """Abstract backend for SchedulerManager schedule persistence."""

    @abstractmethod
    def get(self, name: str) -> dict[str, Any] | None:
        """Return schedule dict by name, or None if not found."""
        ...

    @abstractmethod
    def set(self, name: str, schedule: dict[str, Any]) -> None:
        """Persist a schedule entry."""
        ...

    @abstractmethod
    def delete(self, name: str) -> None:
        """Remove a schedule entry. Raises KeyError if not found."""
        ...

    @abstractmethod
    def all(self) -> list[dict[str, Any]]:
        """Return all schedule entries."""
        ...

    @abstractmethod
    def exists(self, name: str) -> bool:
        """Return True if a schedule with the given name exists."""
        ...


class InMemoryStateBackend(SchedulerStateBackend):
    """In-process dict-backed schedule storage."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    def get(self, name: str) -> dict[str, Any] | None:
        return self._data.get(name)

    def set(self, name: str, schedule: dict[str, Any]) -> None:
        self._data[name] = schedule

    def delete(self, name: str) -> None:
        if name not in self._data:
            raise KeyError(name)
        del self._data[name]

    def all(self) -> list[dict[str, Any]]:
        return list(self._data.values())

    def exists(self, name: str) -> bool:
        return name in self._data


class SchedulerManager:
    """Manages Celery Beat schedule registration and removal."""

    def __init__(self, backend: SchedulerStateBackend | None = None) -> None:
        self._backend: SchedulerStateBackend = (
            backend if backend is not None else InMemoryStateBackend()
        )
        # Keep internal dict view for fast schedule writes;
        # backend is the persistence layer.
        self._schedules: dict[str, dict[str, Any]] = {}

    def register_schedule(
        self,
        name: str,
        cron_expr: str,
        pipeline_name: str,
        params: dict[str, Any],
    ) -> None:
        """Register a scheduled task. Raises ValueError on duplicate."""
        if name in self._schedules or self._backend.exists(name):
            msg = f"Schedule '{name}' already exists"
            raise ValueError(msg)
        entry = {
            "name": name,
            "cron_expr": cron_expr,
            "pipeline_name": pipeline_name,
            "params": params,
        }
        self._schedules[name] = entry
        self._backend.set(name, entry)

    def list_schedules(self) -> list[dict[str, Any]]:
        """Return all registered schedules as a list of dicts."""
        return list(self._schedules.values())
