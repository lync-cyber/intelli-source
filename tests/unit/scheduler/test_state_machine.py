"""Tests for resolve_transition and SchedulerManager (T-028).

Covers:
- AC-T028-4: SchedulerManager manages Celery Beat schedule registration
  and removal.
- Stateless resolve_transition validation for DB-backed callers
  (PATCH /tasks/{id} action wiring).
"""

from __future__ import annotations

import pytest


def _import_state_machine():
    """Lazy import of the state_machine module under test."""
    import intellisource.scheduler.state_machine as mod

    return mod


def _make_scheduler_manager(**kwargs):
    """Instantiate SchedulerManager with optional overrides."""
    mod = _import_state_machine()
    return mod.SchedulerManager(**kwargs)


class TestTransitionConstants:
    """Module-level constants backing resolve_transition."""

    def test_valid_actions_enumerated(self):
        """The module should expose VALID_ACTIONS with all 8 actions."""
        mod = _import_state_machine()
        expected = {
            "start",
            "complete",
            "fail",
            "pause",
            "resume",
            "cancel",
            "timeout",
            "retry",
        }
        assert set(mod.VALID_ACTIONS) == expected

    def test_invalid_transition_error_inherits_base(self):
        """InvalidTransitionError should inherit IntelliSourceError."""
        mod = _import_state_machine()
        from intellisource.core.errors import IntelliSourceError

        assert issubclass(mod.InvalidTransitionError, IntelliSourceError)


class TestResolveTransition:
    """Stateless resolve_transition mirrors the table the state machine uses."""

    def test_pause_from_running(self):
        mod = _import_state_machine()
        assert mod.resolve_transition("running", "pause") == "paused"

    def test_resume_from_paused(self):
        mod = _import_state_machine()
        assert mod.resolve_transition("paused", "resume") == "running"

    def test_cancel_from_pending(self):
        mod = _import_state_machine()
        assert mod.resolve_transition("pending", "cancel") == "cancelled"

    def test_cancel_from_running(self):
        mod = _import_state_machine()
        assert mod.resolve_transition("running", "cancel") == "cancelled"

    def test_cancel_from_paused(self):
        mod = _import_state_machine()
        assert mod.resolve_transition("paused", "cancel") == "cancelled"

    def test_pause_from_pending_raises(self):
        mod = _import_state_machine()
        with pytest.raises(mod.InvalidTransitionError):
            mod.resolve_transition("pending", "pause")

    def test_resume_from_running_raises(self):
        mod = _import_state_machine()
        with pytest.raises(mod.InvalidTransitionError):
            mod.resolve_transition("running", "resume")

    def test_cancel_from_terminal_raises(self):
        mod = _import_state_machine()
        with pytest.raises(mod.InvalidTransitionError):
            mod.resolve_transition("success", "cancel")

    def test_unknown_action_raises(self):
        mod = _import_state_machine()
        with pytest.raises(mod.InvalidTransitionError):
            mod.resolve_transition("running", "explode")


class TestSchedulerManagerRegistration:
    """AC-T028-4: SchedulerManager registers and removes Celery Beat
    scheduled tasks."""

    def test_register_schedule(self):
        """register_schedule should add a new scheduled task."""
        mgr = _make_scheduler_manager()
        mgr.register_schedule(
            name="daily_news",
            cron_expr="0 8 * * *",
            pipeline_name="news_collect",
            params={"source": "rss"},
        )
        schedules = mgr.list_schedules()
        names = [s["name"] for s in schedules]
        assert "daily_news" in names

    def test_register_schedule_with_cron_expr(self):
        """Registered schedule should store the cron expression."""
        mgr = _make_scheduler_manager()
        mgr.register_schedule(
            name="hourly_check",
            cron_expr="0 * * * *",
            pipeline_name="check_pipeline",
            params={},
        )
        schedules = mgr.list_schedules()
        entry = next(s for s in schedules if s["name"] == "hourly_check")
        assert entry["cron_expr"] == "0 * * * *"

    def test_list_schedules_empty_initially(self):
        """list_schedules should return empty list when no schedules
        are registered."""
        mgr = _make_scheduler_manager()
        schedules = mgr.list_schedules()
        assert schedules == []

    def test_duplicate_schedule_name_raises(self):
        """Registering a schedule with a duplicate name should raise
        ValueError."""
        mgr = _make_scheduler_manager()
        mgr.register_schedule(
            name="daily_news",
            cron_expr="0 8 * * *",
            pipeline_name="news_collect",
            params={},
        )
        with pytest.raises(ValueError):
            mgr.register_schedule(
                name="daily_news",
                cron_expr="0 9 * * *",
                pipeline_name="other_pipeline",
                params={},
            )
