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

from types import SimpleNamespace
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
    """Provide a mock PipelineLoader whose load() returns a PipelineConfig-like
    object (attribute access on .mode / .steps, per T-095 contract)."""
    config = MagicMock()
    loaded = MagicMock()
    loaded.name = "news_collect"
    loaded.mode = "strict"
    loaded.steps = [
        {"name": "fetch", "processor": "rss_collector"},
        {"name": "parse", "processor": "html_parser"},
    ]
    config.load.return_value = loaded
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
        assert isinstance(result, dict)

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
    """AC-T027-2: Step failure propagates as a raised exception."""

    def test_step_failure_propagates_exception(self, celery_tasks, mock_agent_runner):
        """When all retries are exhausted, run_pipeline must re-raise
        the last exception."""
        mock_agent_runner.execute = AsyncMock(
            side_effect=RuntimeError("parse step timeout")
        )
        with pytest.raises(RuntimeError, match="parse step timeout"):
            celery_tasks.run_pipeline(
                "news_collect",
                params={"task_id": "t-1"},
            )

    def test_error_message_preserved_in_raised_exception(
        self, celery_tasks, mock_agent_runner
    ):
        """The raised exception must preserve the original error message."""
        error_msg = "Connection refused to rss.example.com"
        mock_agent_runner.execute = AsyncMock(side_effect=RuntimeError(error_msg))
        with pytest.raises(RuntimeError, match=error_msg):
            celery_tasks.run_pipeline(
                "news_collect",
                params={"task_id": "t-1"},
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
        """create() must carry pipeline_name in its kwargs."""
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

        assert mock_repo.create.call_args.kwargs["pipeline_name"] == "news_collect"

    def test_task_chain_contains_execution_mode(
        self, mock_agent_runner, mock_pipeline_config
    ):
        """create() must carry execution_mode from config in its kwargs."""
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

        assert mock_repo.create.call_args.kwargs["execution_mode"] == "strict"

    def test_task_chain_status_updated_on_completion(
        self, mock_agent_runner, mock_pipeline_config
    ):
        """update_status() should be called with 'success' on successful completion."""
        import uuid

        mock_repo = AsyncMock()
        persisted_id = uuid.uuid4()

        async def fake_create(**kwargs):
            return SimpleNamespace(id=kwargs.get("id") or persisted_id)

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

        async def fake_create(**kwargs):
            return SimpleNamespace(id=kwargs.get("id") or persisted_id)

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

    def test_explicit_task_chain_id_is_persisted_as_row_id(
        self, mock_agent_runner, mock_pipeline_config
    ):
        """params['task_chain_id'] becomes the persisted TaskChain id.

        Closes the trigger -> get_task_status loop: the worker writes the run
        under the same id the dispatch layer (api / agent / mcp) returned.
        """
        import uuid

        chain_id = str(uuid.uuid4())
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)  # row does not pre-exist

        async def fake_create(**kwargs):
            return SimpleNamespace(id=kwargs.get("id") or uuid.uuid4())

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
            tasks.run_pipeline("news_collect", params={"task_chain_id": chain_id})

        assert str(mock_repo.create.call_args.kwargs["id"]) == chain_id
        # completion status is written against that same id
        update_calls = mock_repo.update_status.call_args_list
        assert any(chain_id in str(c) and "success" in str(c) for c in update_calls)

    def test_explicit_task_chain_id_already_owned_does_not_hijack_parent(
        self, mock_agent_runner, mock_pipeline_config
    ):
        """When the id is already owned (collect batch parent) a separate child
        row is created — the worker must not adopt the parent id or overwrite
        the parent's status."""
        import uuid

        parent_id = str(uuid.uuid4())
        existing = SimpleNamespace(id=uuid.UUID(parent_id))
        child_id = uuid.uuid4()

        async def fake_create(**kwargs):
            # parent id is already owned, so the child INSERT carries no id and
            # the repo assigns a fresh one.
            return SimpleNamespace(id=kwargs.get("id") or child_id)

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=existing)
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
            tasks.run_pipeline("news_collect", params={"task_chain_id": parent_id})

        # a separate child row was inserted without adopting the parent id
        assert "id" not in mock_repo.create.call_args.kwargs
        # the parent's status is never touched by this child run
        update_calls = mock_repo.update_status.call_args_list
        assert not any(parent_id in str(c) for c in update_calls)
        assert any(
            str(child_id) in str(c) and "success" in str(c) for c in update_calls
        )

    def test_malformed_task_chain_id_falls_back_to_generated(
        self, mock_agent_runner, mock_pipeline_config
    ):
        """A non-UUID task_chain_id is ignored; the worker generates its own."""
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
            tasks.run_pipeline("news_collect", params={"task_chain_id": "not-a-uuid"})

        # falls back to the generate-fresh path: create called, get-or-create not
        mock_repo.create.assert_called_once()
        mock_repo.get.assert_not_called()


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
        assert queue in mod.PRIORITY_QUEUES.values()


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
        assert result["status"] == "success"

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


# ===================================================================
# C1-B: worker writes CollectTask lifecycle status keyed by
#       params['task_id'] (makes pause/cancel reachable) + resume
#       force-unlock
# ===================================================================


class TestCollectTaskLifecycle:
    """run_pipeline advances CollectTask.status pending → running → success/
    failed via params['task_id'], guarded so it only steps from the expected
    prior state. Non-UUID lock keys leave the table untouched."""

    def _patches(self, task_obj):
        """Return (chain_patch, task_patch, task_repo, session_factory)."""
        import uuid as _uuid

        chain_repo = AsyncMock()

        async def fake_create(**kwargs):
            return SimpleNamespace(id=kwargs.get("id") or _uuid.uuid4())

        chain_repo.create = AsyncMock(side_effect=fake_create)

        task_repo = AsyncMock()
        task_repo.get_by_id = AsyncMock(return_value=task_obj)

        async def fake_update(_uid, **fields):
            for key, value in fields.items():
                setattr(task_obj, key, value)
            return task_obj

        task_repo.update = AsyncMock(side_effect=fake_update)

        mock_session = AsyncMock()
        mock_session.close = AsyncMock()

        async def fake_session_factory():
            return mock_session

        chain_patch = patch(
            "intellisource.scheduler.tasks.TaskChainRepository",
            return_value=chain_repo,
        )
        task_patch = patch(
            "intellisource.scheduler.tasks.TaskRepository",
            return_value=task_repo,
        )
        return chain_patch, task_patch, task_repo, fake_session_factory

    def test_marks_running_then_success(
        self, mock_agent_runner, mock_pipeline_config
    ):
        import uuid

        task_id = uuid.uuid4()
        task_obj = SimpleNamespace(status="pending")
        chain_p, task_p, task_repo, factory = self._patches(task_obj)

        with chain_p, task_p:
            tasks = _make_celery_tasks_with_session_factory(
                mock_agent_runner, mock_pipeline_config, factory
            )
            tasks.run_pipeline("news_collect", params={"task_id": str(task_id)})

        statuses = [c.kwargs.get("status") for c in task_repo.update.call_args_list]
        assert statuses == ["running", "success"]
        assert task_obj.status == "success"

    def test_marks_failed_with_error_message(
        self, mock_agent_runner, mock_pipeline_config
    ):
        import uuid

        mock_agent_runner.execute = AsyncMock(side_effect=RuntimeError("boom"))
        task_id = uuid.uuid4()
        task_obj = SimpleNamespace(status="pending")
        chain_p, task_p, task_repo, factory = self._patches(task_obj)

        with chain_p, task_p:
            tasks = _make_celery_tasks_with_session_factory(
                mock_agent_runner, mock_pipeline_config, factory
            )
            with pytest.raises(RuntimeError, match="boom"):
                tasks.run_pipeline("news_collect", params={"task_id": str(task_id)})

        statuses = [c.kwargs.get("status") for c in task_repo.update.call_args_list]
        assert statuses == ["running", "failed"]
        assert task_obj.status == "failed"
        failed_call = task_repo.update.call_args_list[-1]
        assert "boom" in str(failed_call.kwargs.get("error_message"))

    def test_non_uuid_task_id_skips_status_write(
        self, mock_agent_runner, mock_pipeline_config
    ):
        task_obj = SimpleNamespace(status="pending")
        chain_p, task_p, task_repo, factory = self._patches(task_obj)

        with chain_p, task_p:
            tasks = _make_celery_tasks_with_session_factory(
                mock_agent_runner, mock_pipeline_config, factory
            )
            tasks.run_pipeline("news_collect", params={"task_id": "lock-key:src"})

        task_repo.update.assert_not_called()

    def test_running_guard_skips_when_already_cancelled(
        self, mock_agent_runner, mock_pipeline_config
    ):
        """A row the API already moved to 'cancelled' is not flipped to running."""
        import uuid

        task_id = uuid.uuid4()
        task_obj = SimpleNamespace(status="cancelled")
        chain_p, task_p, task_repo, factory = self._patches(task_obj)

        with chain_p, task_p:
            tasks = _make_celery_tasks_with_session_factory(
                mock_agent_runner, mock_pipeline_config, factory
            )
            tasks.run_pipeline("news_collect", params={"task_id": str(task_id)})

        task_repo.update.assert_not_called()
        assert task_obj.status == "cancelled"

    def test_force_param_releases_stale_lock_before_acquire(
        self, mock_agent_runner, mock_pipeline_config
    ):
        guard = MagicMock()
        guard.acquire = AsyncMock(return_value=True)
        guard.release = AsyncMock()
        mod = _import_tasks()
        tasks = mod.CeleryTasks(
            agent_runner=mock_agent_runner,
            pipeline_config=mock_pipeline_config,
            idempotency_guard=guard,
        )

        tasks.run_pipeline(
            "news_collect", params={"task_id": "t-1", "force": True}
        )

        # force-clear before acquire + finally release == 2 release calls
        assert guard.release.await_count == 2

    def test_no_force_releases_lock_once(
        self, mock_agent_runner, mock_pipeline_config
    ):
        guard = MagicMock()
        guard.acquire = AsyncMock(return_value=True)
        guard.release = AsyncMock()
        mod = _import_tasks()
        tasks = mod.CeleryTasks(
            agent_runner=mock_agent_runner,
            pipeline_config=mock_pipeline_config,
            idempotency_guard=guard,
        )

        tasks.run_pipeline("news_collect", params={"task_id": "t-1"})

        assert guard.release.await_count == 1
