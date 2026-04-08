"""Tests for TaskStateMachine and SchedulerManager (T-028).

Covers:
- AC-038: State machine supports pending/running/success/failed/paused/
          cancelled state transitions.
- AC-039: Supports Celery Beat scheduled, manual trigger, and message
          trigger modes.
- AC-T028-1: pause operation suspends running task chain (revoke
             pending subtasks).
- AC-T028-2: resume operation resumes execution from paused point.
- AC-T028-3: Task timeout (configurable) automatically marks as failed.
- AC-T028-4: SchedulerManager manages Celery Beat schedule
             registration and removal.
"""

from __future__ import annotations

import pytest

# ===================================================================
# Lazy imports (RED pattern -- expected to fail with ImportError)
# ===================================================================


def _import_state_machine():
    """Lazy import of the state_machine module under test.

    Raises ``ModuleNotFoundError`` (or ``ImportError``) when the
    implementation does not yet exist -- which is the expected RED
    state.
    """
    import intellisource.scheduler.state_machine as mod

    return mod


def _make_state_machine(**kwargs):
    """Instantiate TaskStateMachine with optional overrides."""
    mod = _import_state_machine()
    return mod.TaskStateMachine(**kwargs)


def _make_scheduler_manager(**kwargs):
    """Instantiate SchedulerManager with optional overrides."""
    mod = _import_state_machine()
    return mod.SchedulerManager(**kwargs)


# ===================================================================
# AC-038: State machine supports all defined state transitions
# ===================================================================


class TestTaskStateMachineTransitions:
    """AC-038: pending/running/success/failed/paused/cancelled
    state transitions."""

    def test_initial_state_is_pending(self):
        """A newly created task should start in 'pending' state."""
        sm = _make_state_machine()
        state = sm.get_state("task-1")
        assert state == "pending"

    def test_start_transitions_pending_to_running(self):
        """Action 'start' should transition pending -> running."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        assert sm.get_state("task-1") == "running"

    def test_complete_transitions_running_to_success(self):
        """Action 'complete' should transition running -> success."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "complete")
        assert sm.get_state("task-1") == "success"

    def test_fail_transitions_running_to_failed(self):
        """Action 'fail' should transition running -> failed."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "fail")
        assert sm.get_state("task-1") == "failed"

    def test_pause_transitions_running_to_paused(self):
        """Action 'pause' should transition running -> paused."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "pause")
        assert sm.get_state("task-1") == "paused"

    def test_resume_transitions_paused_to_running(self):
        """Action 'resume' should transition paused -> running."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "pause")
        sm.transition("task-1", "resume")
        assert sm.get_state("task-1") == "running"

    def test_cancel_from_pending(self):
        """Action 'cancel' should transition pending -> cancelled."""
        sm = _make_state_machine()
        sm.transition("task-1", "cancel")
        assert sm.get_state("task-1") == "cancelled"

    def test_cancel_from_running(self):
        """Action 'cancel' should transition running -> cancelled."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "cancel")
        assert sm.get_state("task-1") == "cancelled"

    def test_cancel_from_paused(self):
        """Action 'cancel' should transition paused -> cancelled."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "pause")
        sm.transition("task-1", "cancel")
        assert sm.get_state("task-1") == "cancelled"

    def test_timeout_transitions_running_to_failed(self):
        """Action 'timeout' should transition running -> failed."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "timeout")
        assert sm.get_state("task-1") == "failed"

    def test_valid_states_enumerated(self):
        """The module should expose VALID_STATES with all 6 states."""
        mod = _import_state_machine()
        expected = {"pending", "running", "success", "failed", "paused", "cancelled"}
        assert set(mod.VALID_STATES) == expected

    def test_valid_actions_enumerated(self):
        """The module should expose VALID_ACTIONS with all 7 actions."""
        mod = _import_state_machine()
        expected = {
            "start",
            "complete",
            "fail",
            "pause",
            "resume",
            "cancel",
            "timeout",
        }
        assert set(mod.VALID_ACTIONS) == expected


# ===================================================================
# AC-038 (boundary): Invalid transitions raise InvalidTransitionError
# ===================================================================


class TestInvalidTransitions:
    """Invalid state transitions should raise InvalidTransitionError."""

    def test_invalid_transition_error_inherits_base(self):
        """InvalidTransitionError should inherit IntelliSourceError."""
        mod = _import_state_machine()
        from intellisource.core.errors import IntelliSourceError

        assert issubclass(mod.InvalidTransitionError, IntelliSourceError)

    def test_complete_from_pending_raises(self):
        """Cannot 'complete' a task that is still 'pending'."""
        mod = _import_state_machine()
        sm = _make_state_machine()
        with pytest.raises(mod.InvalidTransitionError):
            sm.transition("task-1", "complete")

    def test_start_from_running_raises(self):
        """Cannot 'start' a task that is already 'running'."""
        mod = _import_state_machine()
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        with pytest.raises(mod.InvalidTransitionError):
            sm.transition("task-1", "start")

    def test_resume_from_running_raises(self):
        """Cannot 'resume' a task that is already 'running'."""
        mod = _import_state_machine()
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        with pytest.raises(mod.InvalidTransitionError):
            sm.transition("task-1", "resume")

    def test_pause_from_pending_raises(self):
        """Cannot 'pause' a task that is 'pending'."""
        mod = _import_state_machine()
        sm = _make_state_machine()
        with pytest.raises(mod.InvalidTransitionError):
            sm.transition("task-1", "pause")

    def test_start_from_success_raises(self):
        """Cannot 'start' a task that has already 'success'."""
        mod = _import_state_machine()
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "complete")
        with pytest.raises(mod.InvalidTransitionError):
            sm.transition("task-1", "start")

    def test_start_from_failed_raises(self):
        """Cannot 'start' a task that has already 'failed'."""
        mod = _import_state_machine()
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "fail")
        with pytest.raises(mod.InvalidTransitionError):
            sm.transition("task-1", "start")

    def test_cancel_from_success_raises(self):
        """Cannot 'cancel' a task that is in terminal 'success'."""
        mod = _import_state_machine()
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "complete")
        with pytest.raises(mod.InvalidTransitionError):
            sm.transition("task-1", "cancel")

    def test_cancel_from_cancelled_raises(self):
        """Cannot 'cancel' a task that is already 'cancelled'."""
        mod = _import_state_machine()
        sm = _make_state_machine()
        sm.transition("task-1", "cancel")
        with pytest.raises(mod.InvalidTransitionError):
            sm.transition("task-1", "cancel")

    def test_unknown_action_raises(self):
        """An action not in VALID_ACTIONS should raise
        InvalidTransitionError."""
        mod = _import_state_machine()
        sm = _make_state_machine()
        with pytest.raises(mod.InvalidTransitionError):
            sm.transition("task-1", "explode")


# ===================================================================
# AC-T028-1: pause revokes pending subtasks
# ===================================================================


class TestPauseOperation:
    """AC-T028-1: pause suspends running task chain and revokes
    pending subtasks."""

    def test_pause_revokes_pending_subtasks(self):
        """When a running task is paused, any pending subtasks
        should be revoked."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        result = sm.transition("task-1", "pause")
        # The transition result should indicate subtasks were revoked
        assert result is not None
        assert result.get("revoked_subtasks") is not None

    def test_pause_records_paused_at_timestamp(self):
        """Pausing a task should record a paused_at timestamp."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        result = sm.transition("task-1", "pause")
        assert "paused_at" in result


# ===================================================================
# AC-T028-2: resume from paused point
# ===================================================================


class TestResumeOperation:
    """AC-T028-2: resume operation restores execution from
    paused point."""

    def test_resume_restores_running_state(self):
        """After resume, the task state should be 'running'."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "pause")
        sm.transition("task-1", "resume")
        assert sm.get_state("task-1") == "running"

    def test_resume_records_resumed_at_timestamp(self):
        """Resuming a task should record a resumed_at timestamp."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "pause")
        result = sm.transition("task-1", "resume")
        assert "resumed_at" in result

    def test_resume_from_non_paused_raises(self):
        """Cannot resume a task that is not in 'paused' state."""
        mod = _import_state_machine()
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        with pytest.raises(mod.InvalidTransitionError):
            sm.transition("task-1", "resume")


# ===================================================================
# AC-T028-3: Task timeout auto-marks as failed
# ===================================================================


class TestTaskTimeout:
    """AC-T028-3: Configurable timeout automatically marks task
    as failed."""

    def test_timeout_marks_task_as_failed(self):
        """A running task that times out should become 'failed'."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "timeout")
        assert sm.get_state("task-1") == "failed"

    def test_default_timeout_value(self):
        """TaskStateMachine should define a DEFAULT_TIMEOUT_SECONDS."""
        mod = _import_state_machine()
        assert hasattr(mod, "DEFAULT_TIMEOUT_SECONDS")
        assert isinstance(mod.DEFAULT_TIMEOUT_SECONDS, (int, float))
        assert mod.DEFAULT_TIMEOUT_SECONDS > 0

    def test_custom_timeout_configurable(self):
        """TaskStateMachine should accept a custom timeout_seconds."""
        sm = _make_state_machine(timeout_seconds=120)
        assert sm.timeout_seconds == 120

    def test_timeout_result_includes_reason(self):
        """Timeout transition result should include a timeout reason."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        result = sm.transition("task-1", "timeout")
        assert "reason" in result
        assert "timeout" in result["reason"].lower()


# ===================================================================
# AC-T028-4: SchedulerManager manages Celery Beat schedules
# ===================================================================


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

    def test_remove_schedule(self):
        """remove_schedule should remove the named schedule."""
        mgr = _make_scheduler_manager()
        mgr.register_schedule(
            name="to_remove",
            cron_expr="0 0 * * *",
            pipeline_name="cleanup",
            params={},
        )
        mgr.remove_schedule("to_remove")
        schedules = mgr.list_schedules()
        names = [s["name"] for s in schedules]
        assert "to_remove" not in names

    def test_remove_nonexistent_schedule_raises(self):
        """Removing a schedule that does not exist should raise
        an error."""
        mgr = _make_scheduler_manager()
        with pytest.raises(KeyError):
            mgr.remove_schedule("nonexistent_schedule")

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


# ===================================================================
# AC-039: Three trigger modes (scheduled, manual, message)
# ===================================================================


class TestTriggerModes:
    """AC-039: Supports Celery Beat scheduled, manual trigger, and
    message trigger modes."""

    def test_trigger_manual(self):
        """trigger_manual should create and return a task execution."""
        mgr = _make_scheduler_manager()
        result = mgr.trigger_manual(
            pipeline_name="news_collect",
            params={"source_id": "src-1"},
        )
        assert result is not None
        assert "task_id" in result

    def test_trigger_manual_sets_mode(self):
        """Manual trigger should set execution_mode to 'manual'."""
        mgr = _make_scheduler_manager()
        result = mgr.trigger_manual(
            pipeline_name="news_collect",
            params={},
        )
        assert result["execution_mode"] == "manual"

    def test_supported_trigger_modes(self):
        """Module should define SUPPORTED_TRIGGER_MODES with three
        modes."""
        mod = _import_state_machine()
        expected = {"scheduled", "manual", "message"}
        assert set(mod.SUPPORTED_TRIGGER_MODES) == expected

    def test_trigger_manual_with_empty_params(self):
        """trigger_manual should handle empty params dict."""
        mgr = _make_scheduler_manager()
        result = mgr.trigger_manual(pipeline_name="test_pipeline", params={})
        assert result is not None


# ===================================================================
# Edge cases and boundary conditions
# ===================================================================


class TestStateMachineEdgeCases:
    """Boundary conditions for state machine and scheduler."""

    def test_get_state_unknown_task_returns_pending(self):
        """Getting state of an unregistered task should default
        to 'pending'."""
        sm = _make_state_machine()
        assert sm.get_state("unknown-task") == "pending"

    def test_multiple_tasks_independent_states(self):
        """Different task IDs should maintain independent states."""
        sm = _make_state_machine()
        sm.transition("task-a", "start")
        sm.transition("task-b", "start")
        sm.transition("task-b", "complete")
        assert sm.get_state("task-a") == "running"
        assert sm.get_state("task-b") == "success"

    def test_transition_returns_dict(self):
        """transition() should return a dict with transition metadata."""
        sm = _make_state_machine()
        result = sm.transition("task-1", "start")
        assert isinstance(result, dict)
        assert "from_state" in result
        assert "to_state" in result

    def test_transition_result_from_to_states(self):
        """The transition result should contain correct from/to
        states."""
        sm = _make_state_machine()
        result = sm.transition("task-1", "start")
        assert result["from_state"] == "pending"
        assert result["to_state"] == "running"

    def test_full_lifecycle_pending_to_success(self):
        """A complete happy-path lifecycle:
        pending -> running -> success."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "complete")
        assert sm.get_state("task-1") == "success"

    def test_full_lifecycle_with_pause_resume(self):
        """Lifecycle with pause/resume:
        pending -> running -> paused -> running -> success."""
        sm = _make_state_machine()
        sm.transition("task-1", "start")
        sm.transition("task-1", "pause")
        sm.transition("task-1", "resume")
        sm.transition("task-1", "complete")
        assert sm.get_state("task-1") == "success"
