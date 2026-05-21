"""Tests for CeleryTasks scheduler module (T-027).

Covers:
- AC-034: Celery task triggers AgentRunner pipeline execution,
          single-step failure supports independent retry.
- AC-035: Scheduled and manual tasks processed via independent
          queues in parallel.
- AC-T027-1: CeleryTasks.run_pipeline(pipeline_name, params) loads
             pipeline config and invokes AgentRunner.
- AC-T027-2: Single-step failure records error to
             CollectTask.error_message.
- AC-T027-3: Task chain execution state persisted to TaskChain table
             (E-008) with pipeline_name and execution_mode.
- AC-T027-4: Supports low/normal/high three-tier priority queues.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _import_tasks():
    """Lazy import of the tasks module under test.

    Raises ``ModuleNotFoundError`` (or ``ImportError``) when the
    implementation does not yet exist -- which is the expected RED
    state.
    """
    import intellisource.scheduler.tasks as mod

    return mod


def _make_celery_tasks(agent_runner, pipeline_config):
    """Instantiate CeleryTasks with mocked dependencies (no session_factory)."""
    mod = _import_tasks()
    return mod.CeleryTasks(
        agent_runner=agent_runner,
        pipeline_config=pipeline_config,
    )


def _make_celery_tasks_with_session_factory(
    agent_runner, pipeline_config, session_factory
):
    """Instantiate CeleryTasks with a session_factory for persistence tests."""
    mod = _import_tasks()
    return mod.CeleryTasks(
        agent_runner=agent_runner,
        pipeline_config=pipeline_config,
        session_factory=session_factory,
    )


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture()
def mock_agent_runner():
    """Provide a mock AgentRunner that records calls."""
    runner = MagicMock()
    runner.execute = AsyncMock(return_value={"status": "success"})
    return runner


@pytest.fixture()
def mock_pipeline_config():
    """Provide a mock PipelineConfig with sample pipeline data."""
    config = MagicMock()
    config.load.return_value = {
        "name": "news_collect",
        "steps": [
            {"name": "fetch", "processor": "rss_collector"},
            {"name": "parse", "processor": "html_parser"},
        ],
        "execution_mode": "strict",
    }
    return config


@pytest.fixture()
def celery_tasks(mock_agent_runner, mock_pipeline_config):
    """Provide a CeleryTasks instance with mocked deps."""
    return _make_celery_tasks(mock_agent_runner, mock_pipeline_config)


# ===================================================================
# AC-T027-1: CeleryTasks.run_pipeline loads config and calls
#             AgentRunner
# ===================================================================


class TestRunPipeline:
    """AC-T027-1: run_pipeline(pipeline_name, params) loads
    pipeline config and invokes AgentRunner."""

    def test_run_pipeline_loads_config(self, celery_tasks, mock_pipeline_config):
        """run_pipeline should load the named pipeline config."""
        celery_tasks.run_pipeline("news_collect", params={"source_id": "src-1"})
        mock_pipeline_config.load.assert_called_once_with("news_collect")

    def test_run_pipeline_invokes_agent_runner(self, celery_tasks, mock_agent_runner):
        """run_pipeline should invoke AgentRunner.execute with
        the loaded pipeline config."""
        celery_tasks.run_pipeline("news_collect", params={"source_id": "src-1"})
        mock_agent_runner.execute.assert_called_once()

    def test_run_pipeline_passes_params_to_runner(
        self, celery_tasks, mock_agent_runner
    ):
        """run_pipeline should forward params to AgentRunner."""
        params = {"source_id": "src-1", "max_items": 100}
        celery_tasks.run_pipeline("news_collect", params=params)
        call_kwargs = mock_agent_runner.execute.call_args
        assert params == call_kwargs[1].get(
            "params",
            call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None,
        )

    def test_run_pipeline_returns_result(self, celery_tasks):
        """run_pipeline should return execution result from
        AgentRunner."""
        result = celery_tasks.run_pipeline("news_collect", params={})
        assert result is not None
        assert result["status"] == "success"


# ===================================================================
# AC-034: Celery task triggers AgentRunner; single-step failure
#         supports independent retry
# ===================================================================


class TestSingleStepRetry:
    """AC-034: Single-step failure can be retried independently."""

    def test_single_step_failure_does_not_abort_pipeline(
        self, celery_tasks, mock_agent_runner
    ):
        """When one step fails the pipeline should not entirely
        abort -- the failure is isolated to that step."""
        mock_agent_runner.execute = AsyncMock(
            side_effect=[
                RuntimeError("fetch step failed"),
                {"status": "success"},
            ]
        )
        result = celery_tasks.run_pipeline("news_collect", params={})
        assert result is not None

    def test_failed_step_is_retried_up_to_max(self, celery_tasks, mock_agent_runner):
        """A failed step should be retried up to 3 times with
        exponential backoff (arch 5.3)."""
        mock_agent_runner.execute = AsyncMock(
            side_effect=RuntimeError("transient error")
        )
        with pytest.raises(RuntimeError):
            celery_tasks.run_pipeline("news_collect", params={})
        # 1 initial + 3 retries = 4 calls
        assert mock_agent_runner.execute.call_count == 4

    def test_retry_backoff_constants(self):
        """Retry constants should match arch 5.3 spec."""
        mod = _import_tasks()
        assert mod.MAX_RETRIES == 3
        assert mod.RETRY_BACKOFF_BASE == 1


# ===================================================================
# AC-T027-2: Single-step failure records error to
#             CollectTask.error_message
# ===================================================================


class TestErrorRecording:
    """AC-T027-2: Step failure records error_message on
    CollectTask."""

    def test_step_failure_records_error_message(self, celery_tasks, mock_agent_runner):
        """When a step fails the error should be recorded in
        CollectTask.error_message."""
        mock_agent_runner.execute = AsyncMock(
            side_effect=RuntimeError("parse step timeout")
        )
        with patch("intellisource.scheduler.tasks.TaskRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            try:
                celery_tasks.run_pipeline(
                    "news_collect",
                    params={"task_id": "t-1"},
                )
            except RuntimeError:
                pass

            mock_repo.update.assert_called()
            update_call = mock_repo.update.call_args
            assert "error_message" in str(update_call)

    def test_error_message_contains_failure_detail(
        self, celery_tasks, mock_agent_runner
    ):
        """The recorded error_message should contain enough
        detail to identify the failure."""
        error_msg = "Connection refused to rss.example.com"
        mock_agent_runner.execute = AsyncMock(side_effect=RuntimeError(error_msg))
        with patch("intellisource.scheduler.tasks.TaskRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            try:
                celery_tasks.run_pipeline(
                    "news_collect",
                    params={"task_id": "t-1"},
                )
            except RuntimeError:
                pass

            calls = mock_repo.update.call_args_list
            error_recorded = any(error_msg in str(c) for c in calls)
            assert error_recorded, (
                f"Expected '{error_msg}' in update calls, got: {calls}"
            )


# ===================================================================
# AC-T027-3: Task chain execution persisted to TaskChain table
# ===================================================================


class TestTaskChainPersistence:
    """AC-T027-3: Execution state persisted to TaskChain (E-008)."""

    def _make_tasks_with_mock_repo(self, mock_agent_runner, mock_pipeline_config):
        """Build CeleryTasks with session_factory DI + patched TaskChainRepository."""
        mock_repo = AsyncMock()

        mock_session = AsyncMock()
        mock_session.close = AsyncMock()

        async def fake_session_factory():
            return mock_session

        with patch(
            "intellisource.scheduler.tasks.TaskChainRepository",
            return_value=mock_repo,
        ):
            tasks = _make_celery_tasks_with_session_factory(
                mock_agent_runner,
                mock_pipeline_config,
                fake_session_factory,
            )
            return tasks, mock_repo, fake_session_factory

    def test_run_pipeline_creates_task_chain_record(
        self, mock_agent_runner, mock_pipeline_config
    ):
        """run_pipeline should create a TaskChain record before execution starts."""
        mock_repo = AsyncMock()
        mock_session = AsyncMock()
        mock_session.close = AsyncMock()

        async def fake_session_factory():
            return mock_session

        with patch(
            "intellisource.scheduler.tasks.TaskChainRepository",
            return_value=mock_repo,
        ):
            tasks = _make_celery_tasks_with_session_factory(
                mock_agent_runner, mock_pipeline_config, fake_session_factory
            )
            tasks.run_pipeline("news_collect", params={})

        mock_repo.create.assert_called_once()

    def test_task_chain_contains_pipeline_name(
        self, mock_agent_runner, mock_pipeline_config
    ):
        """TaskChain passed to create() must carry pipeline_name."""
        from intellisource.storage.models import TaskChain

        mock_repo = AsyncMock()
        mock_session = AsyncMock()
        mock_session.close = AsyncMock()

        async def fake_session_factory():
            return mock_session

        with patch(
            "intellisource.scheduler.tasks.TaskChainRepository",
            return_value=mock_repo,
        ):
            tasks = _make_celery_tasks_with_session_factory(
                mock_agent_runner, mock_pipeline_config, fake_session_factory
            )
            tasks.run_pipeline("news_collect", params={})

        call_args = mock_repo.create.call_args
        chain_arg = call_args.args[0]
        assert isinstance(chain_arg, TaskChain), (
            f"create() must receive a TaskChain instance, got {type(chain_arg)}"
        )
        assert chain_arg.pipeline_name == "news_collect"

    def test_task_chain_contains_execution_mode(
        self, mock_agent_runner, mock_pipeline_config
    ):
        """TaskChain passed to create() must carry execution_mode from config."""
        from intellisource.storage.models import TaskChain

        mock_repo = AsyncMock()
        mock_session = AsyncMock()
        mock_session.close = AsyncMock()

        async def fake_session_factory():
            return mock_session

        with patch(
            "intellisource.scheduler.tasks.TaskChainRepository",
            return_value=mock_repo,
        ):
            tasks = _make_celery_tasks_with_session_factory(
                mock_agent_runner, mock_pipeline_config, fake_session_factory
            )
            tasks.run_pipeline("news_collect", params={})

        call_args = mock_repo.create.call_args
        chain_arg = call_args.args[0]
        assert isinstance(chain_arg, TaskChain), (
            f"create() must receive a TaskChain instance, got {type(chain_arg)}"
        )
        assert chain_arg.execution_mode == "strict"

    def test_task_chain_status_updated_on_completion(
        self, mock_agent_runner, mock_pipeline_config
    ):
        """update_status() should be called with 'success' on successful completion."""
        import uuid

        mock_repo = AsyncMock()
        persisted_id = uuid.uuid4()

        # Simulate create() setting the id on the TaskChain object
        async def fake_create(task_chain):
            task_chain.id = persisted_id
            return task_chain

        mock_repo.create = AsyncMock(side_effect=fake_create)

        mock_session = AsyncMock()
        mock_session.close = AsyncMock()

        async def fake_session_factory():
            return mock_session

        with patch(
            "intellisource.scheduler.tasks.TaskChainRepository",
            return_value=mock_repo,
        ):
            tasks = _make_celery_tasks_with_session_factory(
                mock_agent_runner, mock_pipeline_config, fake_session_factory
            )
            tasks.run_pipeline("news_collect", params={})

        update_calls = mock_repo.update_status.call_args_list
        assert any("success" in str(c) for c in update_calls), (
            f"Expected update_status(..., 'success') call, got: {update_calls}"
        )

    def test_task_chain_status_updated_on_failure(
        self, mock_agent_runner, mock_pipeline_config
    ):
        """update_status() should be called with 'failed' when pipeline fails."""
        import uuid

        mock_agent_runner.execute = AsyncMock(side_effect=RuntimeError("fatal error"))

        mock_repo = AsyncMock()
        persisted_id = uuid.uuid4()

        async def fake_create(task_chain):
            task_chain.id = persisted_id
            return task_chain

        mock_repo.create = AsyncMock(side_effect=fake_create)

        mock_session = AsyncMock()
        mock_session.close = AsyncMock()

        async def fake_session_factory():
            return mock_session

        with patch(
            "intellisource.scheduler.tasks.TaskChainRepository",
            return_value=mock_repo,
        ):
            tasks = _make_celery_tasks_with_session_factory(
                mock_agent_runner, mock_pipeline_config, fake_session_factory
            )
            try:
                tasks.run_pipeline("news_collect", params={})
            except RuntimeError:
                pass

        update_calls = mock_repo.update_status.call_args_list
        assert any("failed" in str(c) for c in update_calls), (
            f"Expected update_status(..., 'failed') call, got: {update_calls}"
        )


# ===================================================================
# AC-T027-4: Supports low/normal/high priority queues
# ===================================================================


class TestPriorityQueues:
    """AC-T027-4: Three-tier priority queue support."""

    def test_priority_queues_constant_defined(self):
        """PRIORITY_QUEUES should define three queue names."""
        mod = _import_tasks()
        assert len(mod.PRIORITY_QUEUES) == 3

    def test_priority_queues_contains_low(self):
        """PRIORITY_QUEUES should include 'low'."""
        mod = _import_tasks()
        assert "low" in mod.PRIORITY_QUEUES

    def test_priority_queues_contains_normal(self):
        """PRIORITY_QUEUES should include 'normal'."""
        mod = _import_tasks()
        assert "normal" in mod.PRIORITY_QUEUES

    def test_priority_queues_contains_high(self):
        """PRIORITY_QUEUES should include 'high'."""
        mod = _import_tasks()
        assert "high" in mod.PRIORITY_QUEUES

    def test_priority_routes_to_different_queues(self):
        """Different priorities should map to different queues."""
        mod = _import_tasks()
        high_q = mod.get_queue_for_priority("high")
        low_q = mod.get_queue_for_priority("low")
        assert high_q != low_q

    def test_default_priority_is_normal(self):
        """Normal priority should resolve to a valid queue."""
        mod = _import_tasks()
        queue = mod.get_queue_for_priority("normal")
        assert queue is not None


# ===================================================================
# AC-035: Scheduled vs manual tasks use independent queues
# ===================================================================


class TestIndependentQueues:
    """AC-035: Scheduled and manual tasks processed via
    independent queues in parallel."""

    def test_scheduled_queue_differs_from_manual(self):
        """Scheduled and manual trigger types should map to
        different queue names."""
        mod = _import_tasks()
        scheduled_q = mod.get_queue_for_trigger_type("scheduled")
        manual_q = mod.get_queue_for_trigger_type("manual")
        assert scheduled_q != manual_q

    def test_scheduled_queue_is_defined(self):
        """A dedicated queue for scheduled tasks should exist."""
        mod = _import_tasks()
        assert "scheduled" in mod.TRIGGER_TYPE_QUEUES

    def test_manual_queue_is_defined(self):
        """A dedicated queue for manual tasks should exist."""
        mod = _import_tasks()
        assert "manual" in mod.TRIGGER_TYPE_QUEUES

    def test_trigger_type_scheduled_returns_queue(self):
        """get_queue_for_trigger_type('scheduled') should return
        a non-empty queue name."""
        mod = _import_tasks()
        queue = mod.get_queue_for_trigger_type("scheduled")
        assert queue is not None
        assert len(queue) > 0


# ===================================================================
# Edge cases and boundary conditions
# ===================================================================


class TestEdgeCases:
    """Boundary conditions implied by the acceptance criteria."""

    def test_run_pipeline_with_empty_params(self, celery_tasks):
        """run_pipeline should handle empty params dict."""
        result = celery_tasks.run_pipeline("news_collect", params={})
        assert result is not None

    def test_run_pipeline_unknown_pipeline_raises(
        self, celery_tasks, mock_pipeline_config
    ):
        """run_pipeline with non-existent pipeline name should
        raise an appropriate error."""
        from intellisource.core.errors import (
            IntelliSourceError,
        )

        mock_pipeline_config.load.side_effect = IntelliSourceError(
            "Pipeline 'nonexistent' not found",
            category=mock_pipeline_config,
        )
        with pytest.raises(IntelliSourceError):
            celery_tasks.run_pipeline("nonexistent", params={})

    def test_invalid_priority_raises_value_error(self):
        """An invalid priority value should raise ValueError."""
        mod = _import_tasks()
        with pytest.raises(ValueError):
            mod.get_queue_for_priority("critical")
