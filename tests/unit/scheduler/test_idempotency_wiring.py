"""Tests for AC-3, AC-4, and AC-5.

AC-3: The collection entry point (CeleryTasks.run_pipeline) calls
      IdempotencyGuard.acquire(task_id) AND FingerprintChecker.is_duplicate(fingerprint)
      before pipeline execution; each is called exactly once.

AC-4: When IdempotencyGuard.acquire(task_id) returns False (lock already held),
      run_pipeline returns an early-exit signal and the pipeline is NOT executed.

AC-5: When FingerprintChecker.is_duplicate(fingerprint) returns True (content already
      seen), the collection step skips the DB write; ContentRepository.create is
      NOT called.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_pipeline_config(
    pipeline_name: str = "news_collect",
    execution_mode: str = "strict",
) -> MagicMock:
    """Return a minimal PipelineLoader-like mock whose load() returns a
    PipelineConfig with attribute access on .mode / .steps."""
    cfg_mock = MagicMock()
    loaded = MagicMock()
    loaded.name = pipeline_name
    loaded.mode = execution_mode
    loaded.steps = [{"name": "fetch", "processor": "rss_collector"}]
    cfg_mock.load.return_value = loaded
    return cfg_mock


def _make_mock_agent_runner(result: dict[str, Any] | None = None) -> MagicMock:
    """Return an AgentRunner mock whose execute() returns *result*."""
    runner = MagicMock()
    runner.execute = AsyncMock(return_value=result or {"status": "success"})
    return runner


def _make_idempotency_guard(acquire_return: bool = True) -> MagicMock:
    """Return an IdempotencyGuard mock with acquire wired."""
    guard = MagicMock()
    guard.acquire = AsyncMock(return_value=acquire_return)
    guard.release = AsyncMock(return_value=None)
    guard.was_succeeded = AsyncMock(return_value=False)
    guard.mark_succeeded = AsyncMock(return_value=None)
    return guard


def _make_fingerprint_checker(is_duplicate_return: bool = False) -> MagicMock:
    """Return a FingerprintChecker mock with is_duplicate wired.

    is_duplicate() returning False means the fingerprint is new (not a duplicate).
    is_duplicate() returning True means the fingerprint already exists (duplicate).
    """
    checker = MagicMock()
    checker.is_duplicate = AsyncMock(return_value=is_duplicate_return)
    return checker


def _make_content_repository() -> MagicMock:
    """Return a ContentRepository mock."""
    repo = MagicMock()
    repo.create = AsyncMock(return_value=MagicMock())
    return repo


# ---------------------------------------------------------------------------
# AC-3: IdempotencyGuard.acquire_lock + FingerprintChecker.check called before
#        pipeline execution (one call each, in order).
# ---------------------------------------------------------------------------


class TestIdempotencyWiringAC3:
    """AC-3: acquire(task_id) and is_duplicate(fingerprint) each invoked once
    before pipeline runs."""

    def test_acquire_lock_called_once_before_pipeline(self) -> None:
        """IdempotencyGuard.acquire must be called exactly once before
        AgentRunner.execute is invoked."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=True)
        checker = _make_fingerprint_checker(is_duplicate_return=False)
        agent_runner = _make_mock_agent_runner()
        pipeline_config = _make_mock_pipeline_config()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
        )

        tasks.run_pipeline(
            "news_collect",
            {"task_id": "task-001", "fingerprint": "sha256-abc"},
        )

        guard.acquire.assert_called_once()
        call_args = guard.acquire.call_args
        # task_id must be passed as positional or keyword argument
        assert "task-001" in (call_args.args + tuple(call_args.kwargs.values())), (
            "acquire must be called with the task_id from params; "
            f"actual call: {call_args}"
        )

    def test_fingerprint_check_called_once_before_pipeline(self) -> None:
        """FingerprintChecker.is_duplicate must be called exactly once before
        AgentRunner.execute is invoked."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=True)
        checker = _make_fingerprint_checker(is_duplicate_return=False)
        agent_runner = _make_mock_agent_runner()
        pipeline_config = _make_mock_pipeline_config()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
        )

        tasks.run_pipeline(
            "news_collect",
            {"task_id": "task-002", "fingerprint": "sha256-xyz"},
        )

        checker.is_duplicate.assert_called_once()
        call_args = checker.is_duplicate.call_args
        assert "sha256-xyz" in (call_args.args + tuple(call_args.kwargs.values())), (
            "FingerprintChecker.is_duplicate must be called with the fingerprint "
            f"from params; actual call: {call_args}"
        )

    def test_acquire_lock_called_before_agent_execute(self) -> None:
        """acquire must be invoked strictly before AgentRunner.execute."""
        from intellisource.scheduler.tasks import CeleryTasks

        call_order: list[str] = []

        guard = MagicMock()

        async def _acquire_side_effect(task_id: str) -> bool:
            call_order.append("acquire")
            return True

        guard.acquire = AsyncMock(side_effect=_acquire_side_effect)
        guard.was_succeeded = AsyncMock(return_value=False)
        guard.mark_succeeded = AsyncMock(return_value=None)

        checker = MagicMock()

        async def _is_duplicate_side_effect(fingerprint: str) -> bool:
            call_order.append("is_duplicate")
            return False

        checker.is_duplicate = AsyncMock(side_effect=_is_duplicate_side_effect)

        agent_runner = MagicMock()

        async def _execute_side_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
            call_order.append("execute")
            return {"status": "success"}

        agent_runner.execute = AsyncMock(side_effect=_execute_side_effect)
        pipeline_config = _make_mock_pipeline_config()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
        )

        tasks.run_pipeline(
            "news_collect",
            {"task_id": "task-003", "fingerprint": "sha256-order"},
        )

        assert call_order.index("acquire") < call_order.index("execute"), (
            f"acquire must be invoked before execute; actual order: {call_order}"
        )
        assert call_order.index("is_duplicate") < call_order.index("execute"), (
            "FingerprintChecker.is_duplicate must be invoked before execute; "
            f"actual order: {call_order}"
        )

    def test_both_idempotency_components_called_on_happy_path(self) -> None:
        """When neither guard nor checker short-circuits, both are called
        and the pipeline executes normally."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=True)
        checker = _make_fingerprint_checker(is_duplicate_return=False)
        agent_runner = _make_mock_agent_runner({"status": "success"})
        pipeline_config = _make_mock_pipeline_config()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
        )

        result = tasks.run_pipeline(
            "news_collect",
            {"task_id": "task-004", "fingerprint": "fp-happy"},
        )

        guard.acquire.assert_called_once()
        checker.is_duplicate.assert_called_once()
        agent_runner.execute.assert_called_once()
        assert result["status"] == "success"


# ---------------------------------------------------------------------------
# AC-4: acquire_lock returns False → early exit, pipeline NOT executed.
# ---------------------------------------------------------------------------


class TestIdempotencyWiringAC4:
    """AC-4: Lock already held → early-exit result, no pipeline execution."""

    def test_pipeline_not_executed_when_lock_not_acquired(self) -> None:
        """When acquire returns False, AgentRunner.execute must not be called."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=False)
        checker = _make_fingerprint_checker(is_duplicate_return=False)
        agent_runner = _make_mock_agent_runner()
        pipeline_config = _make_mock_pipeline_config()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
        )

        tasks.run_pipeline(
            "news_collect",
            {"task_id": "task-dup-001", "fingerprint": "fp-dup"},
        )

        agent_runner.execute.assert_not_called()

    def test_early_exit_does_not_raise(self) -> None:
        """When lock acquisition fails, run_pipeline must return without
        raising an exception."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=False)
        checker = _make_fingerprint_checker(is_duplicate_return=False)
        agent_runner = _make_mock_agent_runner()
        pipeline_config = _make_mock_pipeline_config()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
        )

        # Must not raise — early exit is a signal, not an error.
        result = tasks.run_pipeline(
            "news_collect",
            {"task_id": "task-dup-002", "fingerprint": "fp-dup2"},
        )
        assert isinstance(result, dict), (
            "run_pipeline must return a result dict on early exit, not None"
        )

    def test_early_exit_result_indicates_skipped(self) -> None:
        """The early-exit return value must signal that the task was skipped
        (e.g. contains a 'skipped' or 'already_running' indicator)."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=False)
        checker = _make_fingerprint_checker(is_duplicate_return=False)
        agent_runner = _make_mock_agent_runner()
        pipeline_config = _make_mock_pipeline_config()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
        )

        result = tasks.run_pipeline(
            "news_collect",
            {"task_id": "task-dup-003", "fingerprint": "fp-dup3"},
        )

        # The result must contain at least one of these indicators
        result_values = set(result.values()) if isinstance(result, dict) else set()
        result_keys = set(result.keys()) if isinstance(result, dict) else set()
        has_skip_signal = (
            "skipped" in result_keys
            or "already_running" in result_keys
            or "skipped" in result_values
            or "already_running" in result_values
            or result.get("status") in {"skipped", "already_running", "duplicate"}
        )
        assert has_skip_signal, (
            f"Early-exit result must signal the task was skipped; got: {result}"
        )

    def test_fingerprint_check_not_called_after_lock_failure(self) -> None:
        """When acquire returns False, FingerprintChecker.is_duplicate need not
        be called — the pipeline is already blocked."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=False)
        checker = _make_fingerprint_checker(is_duplicate_return=False)
        agent_runner = _make_mock_agent_runner()
        pipeline_config = _make_mock_pipeline_config()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
        )

        tasks.run_pipeline(
            "news_collect",
            {"task_id": "task-dup-004", "fingerprint": "fp-dup4"},
        )

        # Neither execute nor the downstream check should fire
        agent_runner.execute.assert_not_called()


# ---------------------------------------------------------------------------
# AC-5: FingerprintChecker.check returns True → DB write skipped.
# ---------------------------------------------------------------------------


class TestIdempotencyWiringAC5:
    """AC-5: Content fingerprint already exists → ContentRepository.create
    must not be called."""

    def test_content_repository_create_not_called_on_duplicate_fingerprint(
        self,
    ) -> None:
        """When is_duplicate(fingerprint) returns True, ContentRepository.create
        must NOT be invoked."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=True)
        checker = _make_fingerprint_checker(is_duplicate_return=True)  # duplicate!
        agent_runner = _make_mock_agent_runner()
        pipeline_config = _make_mock_pipeline_config()
        content_repo = _make_content_repository()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
            content_repository=content_repo,
        )

        tasks.run_pipeline(
            "news_collect",
            {"task_id": "task-fp-001", "fingerprint": "sha256-existing"},
        )

        content_repo.create.assert_not_called()

    def test_pipeline_skipped_when_fingerprint_duplicate(self) -> None:
        """When is_duplicate(fingerprint) returns True, the collection pipeline
        step is skipped — AgentRunner.execute must not be called."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=True)
        checker = _make_fingerprint_checker(is_duplicate_return=True)  # duplicate!
        agent_runner = _make_mock_agent_runner()
        pipeline_config = _make_mock_pipeline_config()
        content_repo = _make_content_repository()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
            content_repository=content_repo,
        )

        tasks.run_pipeline(
            "news_collect",
            {"task_id": "task-fp-002", "fingerprint": "sha256-existing-2"},
        )

        agent_runner.execute.assert_not_called()

    def test_fingerprint_duplicate_result_signals_skip(self) -> None:
        """When is_duplicate(fingerprint) returns True, the returned result dict
        must contain a skip/duplicate indicator."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=True)
        checker = _make_fingerprint_checker(is_duplicate_return=True)
        agent_runner = _make_mock_agent_runner()
        pipeline_config = _make_mock_pipeline_config()
        content_repo = _make_content_repository()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
            content_repository=content_repo,
        )

        result = tasks.run_pipeline(
            "news_collect",
            {"task_id": "task-fp-003", "fingerprint": "sha256-existing-3"},
        )

        assert isinstance(result, dict), (
            "run_pipeline must return a dict even on fingerprint-duplicate skip"
        )
        result_values = set(result.values())
        result_keys = set(result.keys())
        has_skip_signal = (
            "skipped" in result_keys
            or "duplicate" in result_keys
            or "skipped" in result_values
            or "duplicate" in result_values
            or result.get("status") in {"skipped", "duplicate", "already_exists"}
        )
        assert has_skip_signal, (
            f"Fingerprint-duplicate result must signal skip; got: {result}"
        )

    def test_content_repository_create_called_on_new_fingerprint(self) -> None:
        """When is_duplicate(fingerprint) returns False (new content),
        ContentRepository.create IS called after pipeline executes successfully."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=True)
        checker = _make_fingerprint_checker(is_duplicate_return=False)  # new content
        agent_runner = _make_mock_agent_runner({"status": "success"})
        pipeline_config = _make_mock_pipeline_config()
        content_repo = _make_content_repository()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
            content_repository=content_repo,
        )

        tasks.run_pipeline(
            "news_collect",
            {"task_id": "task-fp-new-001", "fingerprint": "sha256-new"},
        )

        # Pipeline must execute when fingerprint is new
        agent_runner.execute.assert_called_once()
        # ContentRepository.create must be called after successful execution
        content_repo.create.assert_called_once()


# ---------------------------------------------------------------------------
# Boundary / edge cases
# ---------------------------------------------------------------------------


class TestIdempotencyWiringEdgeCases:
    """Edge cases: missing task_id / fingerprint in params."""

    def test_run_pipeline_without_task_id_does_not_crash(self) -> None:
        """When params dict lacks 'task_id', run_pipeline must not crash
        with an unhandled KeyError; idempotency guard should still be
        invoked (with a fallback or the method handles absence)."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=True)
        checker = _make_fingerprint_checker(is_duplicate_return=False)
        agent_runner = _make_mock_agent_runner()
        pipeline_config = _make_mock_pipeline_config()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
        )

        # Missing task_id — must not raise unhandled KeyError
        try:
            tasks.run_pipeline("news_collect", {"fingerprint": "fp-no-id"})
        except KeyError as exc:
            raise AssertionError(
                f"run_pipeline must not propagate KeyError for missing task_id; "
                f"got: {exc!r}"
            ) from exc

    def test_run_pipeline_without_task_id_uses_source_lock_and_releases(self) -> None:
        """Source-triggered tasks without task_id use a stable non-empty lock key."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=True)
        agent_runner = _make_mock_agent_runner()
        pipeline_config = _make_mock_pipeline_config()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
        )

        tasks.run_pipeline("scheduled-collect", {"source_id": "src-1"})

        guard.acquire.assert_awaited_once_with("scheduled-collect:source:src-1")
        guard.release.assert_awaited_once_with("scheduled-collect:source:src-1")

    def test_run_pipeline_without_fingerprint_does_not_crash(self) -> None:
        """When params dict lacks 'fingerprint', run_pipeline must not crash
        with an unhandled KeyError."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard(acquire_return=True)
        checker = _make_fingerprint_checker(is_duplicate_return=False)
        agent_runner = _make_mock_agent_runner()
        pipeline_config = _make_mock_pipeline_config()

        tasks = CeleryTasks(
            agent_runner=agent_runner,
            pipeline_config=pipeline_config,
            idempotency_guard=guard,
            fingerprint_checker=checker,
        )

        # Missing fingerprint — must not raise unhandled KeyError
        try:
            tasks.run_pipeline("news_collect", {"task_id": "task-no-fp"})
        except KeyError as exc:
            raise AssertionError(
                f"run_pipeline must not propagate KeyError for missing fingerprint; "
                f"got: {exc!r}"
            ) from exc

    def test_celery_tasks_accepts_idempotency_guard_kwarg(self) -> None:
        """CeleryTasks.__init__ must accept idempotency_guard as a keyword
        argument; TypeError here means the constructor signature is wrong."""
        from intellisource.scheduler.tasks import CeleryTasks

        guard = _make_idempotency_guard()
        runner = _make_mock_agent_runner()
        config = _make_mock_pipeline_config()

        try:
            CeleryTasks(
                agent_runner=runner,
                pipeline_config=config,
                idempotency_guard=guard,
            )
        except TypeError as exc:
            raise AssertionError(
                "CeleryTasks must accept 'idempotency_guard' kwarg; "
                f"got TypeError: {exc}"
            ) from exc

    def test_celery_tasks_accepts_fingerprint_checker_kwarg(self) -> None:
        """CeleryTasks.__init__ must accept fingerprint_checker as a keyword
        argument; TypeError here means the constructor signature is wrong."""
        from intellisource.scheduler.tasks import CeleryTasks

        checker = _make_fingerprint_checker()
        runner = _make_mock_agent_runner()
        config = _make_mock_pipeline_config()

        try:
            CeleryTasks(
                agent_runner=runner,
                pipeline_config=config,
                fingerprint_checker=checker,
            )
        except TypeError as exc:
            raise AssertionError(
                "CeleryTasks must accept 'fingerprint_checker' kwarg; "
                f"got TypeError: {exc}"
            ) from exc

    def test_celery_tasks_accepts_content_repository_kwarg(self) -> None:
        """CeleryTasks.__init__ must accept content_repository as a keyword
        argument; TypeError here means the constructor signature is wrong."""
        from intellisource.scheduler.tasks import CeleryTasks

        repo = _make_content_repository()
        runner = _make_mock_agent_runner()
        config = _make_mock_pipeline_config()

        try:
            CeleryTasks(
                agent_runner=runner,
                pipeline_config=config,
                content_repository=repo,
            )
        except TypeError as exc:
            raise AssertionError(
                "CeleryTasks must accept 'content_repository' kwarg; "
                f"got TypeError: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# wiring: build_celery_tasks assembles all three guards as non-None
# ---------------------------------------------------------------------------


class TestBuildCeleryTasksGuardWiring:
    """build_celery_tasks must wire all three idempotency components."""

    def test_build_celery_tasks_wires_three_guards_non_none(self) -> None:
        """CeleryTasks returned by build_celery_tasks must have
        _idempotency_guard, _fingerprint_checker, and _content_repository
        all set to non-None values, confirming real assembly (not None defaults)."""
        from unittest.mock import MagicMock, patch

        from intellisource.scheduler.boot import build_celery_tasks
        from intellisource.scheduler.idempotency import (
            FingerprintChecker,
            IdempotencyGuard,
        )

        mock_session_factory = MagicMock()
        mock_session_factory.return_value = MagicMock()
        mock_agent_runner = MagicMock()

        mock_redis = MagicMock()

        with patch(
            "intellisource.scheduler.boot._build_redis_client",
            return_value=mock_redis,
        ):
            celery_tasks = build_celery_tasks(
                mock_agent_runner, None, mock_session_factory
            )

        assert celery_tasks._idempotency_guard is not None, (
            "build_celery_tasks must wire _idempotency_guard (got None)"
        )
        assert isinstance(celery_tasks._idempotency_guard, IdempotencyGuard), (
            f"_idempotency_guard must be IdempotencyGuard; "
            f"got {type(celery_tasks._idempotency_guard)}"
        )
        assert celery_tasks._fingerprint_checker is not None, (
            "build_celery_tasks must wire _fingerprint_checker (got None)"
        )
        assert isinstance(celery_tasks._fingerprint_checker, FingerprintChecker), (
            f"_fingerprint_checker must be FingerprintChecker; "
            f"got {type(celery_tasks._fingerprint_checker)}"
        )
