"""Tests for T-092 AC-1 and AC-2.

AC-1: celery_app.conf contains task_routes and task_queues; run_pipeline routing
      config is non-empty and refers to at least one queue from PRIORITY_QUEUES /
      TRIGGER_TYPE_QUEUES.

AC-2: worker_process_init signal handler (worker_init_handler) does not accept
      agent_runner / pipeline_config as required keyword arguments; it obtains them
      from agent.factory.get_agent_runner() lazy singleton instead.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# AC-1: task_routes and task_queues present in celery_app.conf
# ---------------------------------------------------------------------------


class TestCeleryTaskRoutes:
    """AC-1: celery_app.conf has task_routes and task_queues configured."""

    def test_task_routes_key_present_in_conf(self) -> None:
        """celery_app.conf must expose a non-None task_routes mapping."""
        from intellisource.scheduler.celery_app import celery_app

        routes = celery_app.conf.task_routes
        assert routes is not None, "celery_app.conf.task_routes must be set (not None)"

    def test_task_routes_is_non_empty(self) -> None:
        """task_routes mapping must have at least one entry."""
        from intellisource.scheduler.celery_app import celery_app

        routes = celery_app.conf.task_routes
        assert len(routes) > 0, (
            "celery_app.conf.task_routes must be non-empty; "
            "expected at least one task routing rule"
        )

    def test_task_routes_contains_run_pipeline(self) -> None:
        """task_routes must include a routing rule for the run_pipeline task."""
        from intellisource.scheduler.celery_app import celery_app

        routes = celery_app.conf.task_routes
        # Accept either the short name 'run_pipeline' or the fully-qualified name
        route_keys = set(routes.keys()) if isinstance(routes, dict) else set()
        has_run_pipeline = any("run_pipeline" in key for key in route_keys)
        assert has_run_pipeline, (
            f"task_routes must contain a rule for 'run_pipeline'; "
            f"current keys: {route_keys}"
        )

    def test_run_pipeline_route_specifies_a_queue(self) -> None:
        """The run_pipeline routing entry must specify a 'queue' value."""
        from intellisource.scheduler.celery_app import celery_app

        routes = celery_app.conf.task_routes
        if not isinstance(routes, dict):
            raise AssertionError("task_routes must be a dict")

        run_pipeline_config: dict[str, Any] | None = None
        for key, value in routes.items():
            if "run_pipeline" in key:
                run_pipeline_config = value
                break

        assert run_pipeline_config is not None, (
            "No routing entry found for run_pipeline"
        )
        assert "queue" in run_pipeline_config, (
            "run_pipeline routing entry must have a 'queue' key; "
            f"got: {run_pipeline_config}"
        )
        assert run_pipeline_config["queue"], (
            "run_pipeline routing entry 'queue' must be a non-empty string"
        )

    def test_task_queues_key_present_in_conf(self) -> None:
        """celery_app.conf must expose a non-None task_queues sequence."""
        from intellisource.scheduler.celery_app import celery_app

        queues = celery_app.conf.task_queues
        assert queues is not None, "celery_app.conf.task_queues must be set (not None)"

    def test_task_queues_is_non_empty(self) -> None:
        """task_queues sequence must have at least one Queue definition."""
        from intellisource.scheduler.celery_app import celery_app

        queues = celery_app.conf.task_queues
        assert len(queues) > 0, (
            "celery_app.conf.task_queues must define at least one Queue; "
            "expected entries for PRIORITY_QUEUES and TRIGGER_TYPE_QUEUES"
        )

    def test_task_queues_include_priority_queue_names(self) -> None:
        """task_queues must define queues for all names in PRIORITY_QUEUES."""
        import intellisource.scheduler.tasks as tasks_mod
        from intellisource.scheduler.celery_app import celery_app

        queues = celery_app.conf.task_queues
        queue_names = {q.name if hasattr(q, "name") else str(q) for q in queues}

        for _priority_key, queue_name in tasks_mod.PRIORITY_QUEUES.items():
            assert queue_name in queue_names, (
                f"task_queues must include queue '{queue_name}' "
                f"(from PRIORITY_QUEUES); found: {queue_names}"
            )

    def test_task_queues_include_trigger_type_queue_names(self) -> None:
        """task_queues must define queues for all names in TRIGGER_TYPE_QUEUES."""
        import intellisource.scheduler.tasks as tasks_mod
        from intellisource.scheduler.celery_app import celery_app

        queues = celery_app.conf.task_queues
        queue_names = {q.name if hasattr(q, "name") else str(q) for q in queues}

        for _trigger_key, queue_name in tasks_mod.TRIGGER_TYPE_QUEUES.items():
            assert queue_name in queue_names, (
                f"task_queues must include queue '{queue_name}' "
                f"(from TRIGGER_TYPE_QUEUES); found: {queue_names}"
            )


# ---------------------------------------------------------------------------
# AC-2: worker_init_handler does not require agent_runner / pipeline_config kwargs
# ---------------------------------------------------------------------------


class TestWorkerInitHandlerSignature:
    """AC-2: worker_init_handler obtains agent_runner from get_agent_runner()
    singleton; calling it with no kwargs (or only framework kwargs) must not
    raise TypeError."""

    @pytest.fixture(autouse=True)
    def _reset_celery_tasks_singleton(self) -> Any:
        """Reset boot._celery_tasks before each test so the idempotency guard
        in worker_init_handler does not short-circuit the assembly path under
        test."""
        import intellisource.scheduler.boot as boot_mod

        original = boot_mod._celery_tasks
        boot_mod._celery_tasks = None
        yield
        boot_mod._celery_tasks = original

    def test_handler_callable_with_no_kwargs(self) -> None:
        """Calling worker_init_handler() with no kwargs must not raise TypeError.

        Patching get_agent_runner and init_worker_session_factory to avoid
        real DB/Redis side-effects; TypeError would fire before any patch takes
        effect if the signature still requires agent_runner as a keyword argument.
        """
        from intellisource.scheduler.boot import worker_init_handler

        mock_runner = MagicMock()
        mock_factory = MagicMock()
        mock_tasks = MagicMock()
        mock_composition = MagicMock()
        mock_composition.agent_runner = mock_runner
        mock_composition.pipeline_loader = MagicMock()

        with (
            patch(
                "intellisource.scheduler.boot.init_worker_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "intellisource.scheduler.boot._build_redis_client",
                return_value=MagicMock(),
            ),
            patch(
                "intellisource.scheduler.boot.build_worker_composition",
                return_value=mock_composition,
            ),
            patch(
                "intellisource.scheduler.boot.build_celery_tasks",
                return_value=mock_tasks,
            ),
        ):
            # Must NOT raise TypeError — no required positional / keyword args
            worker_init_handler()

    def test_handler_callable_with_sender_kwarg_only(self) -> None:
        """Celery passes 'sender' as a kwarg; the handler must accept it
        without TypeError."""
        from intellisource.scheduler.boot import worker_init_handler

        mock_runner = MagicMock()
        mock_factory = MagicMock()
        mock_tasks = MagicMock()
        mock_composition = MagicMock()
        mock_composition.agent_runner = mock_runner
        mock_composition.pipeline_loader = MagicMock()

        with (
            patch(
                "intellisource.scheduler.boot.init_worker_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "intellisource.scheduler.boot._build_redis_client",
                return_value=MagicMock(),
            ),
            patch(
                "intellisource.scheduler.boot.build_worker_composition",
                return_value=mock_composition,
            ),
            patch(
                "intellisource.scheduler.boot.build_celery_tasks",
                return_value=mock_tasks,
            ),
        ):
            worker_init_handler(sender=object())

    def test_handler_uses_build_worker_composition(self) -> None:
        """worker_init_handler must call build_worker_composition() to obtain
        the runner + pipeline_loader rather than requiring them as kwargs.

        Updated by T-095: legacy assertion targeted get_agent_runner();
        composition root now flows through build_worker_composition.
        """
        from intellisource.scheduler.boot import worker_init_handler

        mock_runner = MagicMock()
        mock_factory = MagicMock()
        mock_tasks = MagicMock()
        mock_composition = MagicMock()
        mock_composition.agent_runner = mock_runner
        mock_composition.pipeline_loader = MagicMock()

        with (
            patch(
                "intellisource.scheduler.boot.init_worker_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "intellisource.scheduler.boot._build_redis_client",
                return_value=MagicMock(),
            ),
            patch(
                "intellisource.scheduler.boot.build_worker_composition",
                return_value=mock_composition,
            ) as mock_build_composition,
            patch(
                "intellisource.scheduler.boot.build_celery_tasks",
                return_value=mock_tasks,
            ),
        ):
            worker_init_handler()

        mock_build_composition.assert_called_once()

    def test_handler_does_not_require_agent_runner_kwarg(self) -> None:
        """worker_init_handler must accept no kwargs and assemble its own deps.

        Updated by T-095: the legacy assertion required get_agent_runner() to
        be called; composition now flows through build_worker_composition.
        """
        from intellisource.scheduler.boot import worker_init_handler

        mock_runner = MagicMock()
        mock_factory = MagicMock()
        mock_tasks = MagicMock()
        mock_composition = MagicMock()
        mock_composition.agent_runner = mock_runner
        mock_composition.pipeline_loader = MagicMock()

        with (
            patch(
                "intellisource.scheduler.boot.init_worker_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "intellisource.scheduler.boot._build_redis_client",
                return_value=MagicMock(),
            ),
            patch(
                "intellisource.scheduler.boot.build_worker_composition",
                return_value=mock_composition,
            ) as mock_build_composition,
            patch(
                "intellisource.scheduler.boot.build_celery_tasks",
                return_value=mock_tasks,
            ),
        ):
            worker_init_handler()

        mock_build_composition.assert_called_once()


class TestGetAgentRunnerSingletonExists:
    """AC-2 prerequisite: agent.factory must expose get_agent_runner()."""

    def test_get_agent_runner_function_exists(self) -> None:
        """intellisource.agent.factory must expose a get_agent_runner callable."""
        import intellisource.agent.factory as factory_mod

        assert hasattr(factory_mod, "get_agent_runner"), (
            "agent.factory must export get_agent_runner() for the boot handler"
        )
        assert callable(factory_mod.get_agent_runner), (
            "get_agent_runner must be a callable (lazy singleton function)"
        )

    def test_get_agent_runner_returns_without_args(self) -> None:
        """get_agent_runner() must accept zero positional arguments.

        Updated by T-095: legacy behaviour was a silent fallback constructing
        a None-wired runner. The function now raises RuntimeError when no
        composition root has installed an instance — which is still a
        zero-arg signature; we just guard TypeError specifically.
        """
        import intellisource.agent.factory as factory_mod
        from intellisource.composition import get_agent_runner_holder

        holder = get_agent_runner_holder()
        original = holder._runner
        holder.reset()
        try:
            try:
                factory_mod.get_agent_runner()
            except TypeError as exc:
                raise AssertionError(
                    f"get_agent_runner() raised TypeError — "
                    f"must accept zero arguments: {exc}"
                ) from exc
            except RuntimeError:
                # Expected when no composition root has installed an instance.
                pass
        finally:
            holder._runner = original


# ---------------------------------------------------------------------------
# R-001: worker_process_init signal does not raise AttributeError
# ---------------------------------------------------------------------------


class TestWorkerInitSignalNoAttributeError:
    """R-001: worker_init_handler uses the module-level celery_app singleton,
    not a kwarg, so it must never raise AttributeError on signal dispatch."""

    @pytest.fixture(autouse=True)
    def _reset_celery_tasks_singleton(self) -> Any:
        import intellisource.scheduler.boot as boot_mod

        original = boot_mod._celery_tasks
        boot_mod._celery_tasks = None
        yield
        boot_mod._celery_tasks = original

    def test_worker_init_signal_does_not_raise_attribute_error(self) -> None:
        """Simulates Celery dispatching worker_process_init with no celery_app kwarg.

        Patches IdempotencyGuard, FingerprintChecker, and the Redis client builder
        so no real infrastructure is needed; verifies that worker_init_handler
        completes without AttributeError (the 'NoneType has no attribute task' failure
        that occurs when celery_app is taken from a missing kwarg).
        """
        from unittest.mock import MagicMock, patch

        from intellisource.scheduler.boot import worker_init_handler
        from intellisource.scheduler.idempotency import (
            FingerprintChecker,
            IdempotencyGuard,
        )

        mock_runner = MagicMock()
        mock_factory = MagicMock()
        mock_tasks = MagicMock()
        mock_tasks._idempotency_guard = MagicMock(spec=IdempotencyGuard)
        mock_tasks._fingerprint_checker = MagicMock(spec=FingerprintChecker)
        mock_composition = MagicMock()
        mock_composition.agent_runner = mock_runner
        mock_composition.pipeline_loader = MagicMock()

        with (
            patch(
                "intellisource.scheduler.boot.init_worker_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "intellisource.scheduler.boot._build_redis_client",
                return_value=MagicMock(),
            ),
            patch(
                "intellisource.scheduler.boot.build_worker_composition",
                return_value=mock_composition,
            ),
            patch(
                "intellisource.scheduler.boot.build_celery_tasks",
                return_value=mock_tasks,
            ),
        ):
            # Celery dispatches worker_process_init with sender kwarg only.
            # Must NOT raise AttributeError.
            try:
                worker_init_handler(sender=object())
            except AttributeError as exc:
                raise AssertionError(
                    f"worker_init_handler raised AttributeError — "
                    f"celery_app singleton not wired correctly: {exc}"
                ) from exc
