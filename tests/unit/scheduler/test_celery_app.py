"""Tests for T-083 AC-1 and AC-4: celery_app module-level instantiation and task registration."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# AC-1: module-level celery_app instantiated from settings
# ---------------------------------------------------------------------------


class TestCeleryAppModuleLevel:
    """AC-1: celery_app = Celery(...) at module level, broker/backend from settings."""

    def test_celery_app_module_exists(self) -> None:
        """AC-1: intellisource.scheduler.celery_app module must exist."""
        import importlib

        mod = importlib.import_module("intellisource.scheduler.celery_app")
        assert mod is not None

    def test_celery_app_attribute_exists(self) -> None:
        """AC-1: Module exports a module-level 'celery_app' name."""
        from intellisource.scheduler.celery_app import celery_app  # type: ignore[import-untyped]

        assert celery_app is not None

    def test_celery_app_is_celery_instance(self) -> None:
        """AC-1: celery_app is a Celery instance."""
        from celery import Celery

        from intellisource.scheduler.celery_app import celery_app  # type: ignore[import-untyped]

        assert isinstance(celery_app, Celery)

    def test_celery_app_main_name(self) -> None:
        """AC-1: Celery app name is 'intellisource'."""
        from intellisource.scheduler.celery_app import celery_app  # type: ignore[import-untyped]

        assert celery_app.main == "intellisource"

    def test_celery_app_broker_not_hardcoded_empty(self) -> None:
        """AC-1: broker URL is read from settings, not an empty or literal placeholder."""
        from intellisource.scheduler.celery_app import celery_app  # type: ignore[import-untyped]

        broker = celery_app.conf.broker_url
        assert broker is not None
        assert broker != ""
        assert "placeholder" not in str(broker).lower()

    def test_celery_app_result_backend_not_hardcoded_empty(self) -> None:
        """AC-1: result_backend URL is read from settings, not empty."""
        from intellisource.scheduler.celery_app import celery_app  # type: ignore[import-untyped]

        backend = celery_app.conf.result_backend
        assert backend is not None
        assert backend != ""


# ---------------------------------------------------------------------------
# AC-4: run_pipeline task registered and findable via celery_app.tasks
# ---------------------------------------------------------------------------


class TestRunPipelineTaskRegistration:
    """AC-4: run_pipeline task decorated with @celery_app.task and locatable."""

    def test_run_pipeline_task_registered(self) -> None:
        """AC-4: 'run_pipeline' task can be found in celery_app.tasks registry."""
        from intellisource.scheduler.celery_app import celery_app  # type: ignore[import-untyped]

        # Importing tasks module triggers decorator registration
        import intellisource.scheduler.tasks as _  # noqa: F401

        assert "run_pipeline" in celery_app.tasks, (
            "Expected 'run_pipeline' in celery_app.tasks after importing tasks module"
        )

    def test_run_pipeline_task_is_callable(self) -> None:
        """AC-4: The registered run_pipeline task is callable."""
        from intellisource.scheduler.celery_app import celery_app  # type: ignore[import-untyped]

        import intellisource.scheduler.tasks as _  # noqa: F401

        task = celery_app.tasks["run_pipeline"]
        assert callable(task) or hasattr(task, "run"), (
            "Registered task must be callable or have a .run method"
        )

    def test_run_pipeline_task_name_matches(self) -> None:
        """AC-4: The task's .name attribute equals 'run_pipeline'."""
        from intellisource.scheduler.celery_app import celery_app  # type: ignore[import-untyped]

        import intellisource.scheduler.tasks as _  # noqa: F401

        task = celery_app.tasks["run_pipeline"]
        assert task.name == "run_pipeline"
