"""Integration tests for Celery worker wiring via scheduler.boot (T-075).

Covers AC-T075-1, AC-T075-2, and AC-T075-4:
- AC-T075-1: worker_init creates an independent async session_factory from
  IS_DATABASE_URL without touching FastAPI app.state.db.
- AC-T075-2: build_celery_tasks registers run_pipeline as a Celery task and
  returns a CeleryTasks instance with _session_factory wired.
- AC-T075-4: end-to-end run_pipeline call with mock session_factory reaches
  repo.create exactly once and the TaskChain carries the correct trigger_type
  and pipeline_name.
"""

from __future__ import annotations

import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

# ---------------------------------------------------------------------------
# AC-T075-1
# ---------------------------------------------------------------------------


class TestInitWorkerSessionFactory:
    """init_worker_session_factory() creates an independent session_factory."""

    def test_init_worker_session_factory_returns_async_sessionmaker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling init_worker_session_factory() with IS_DATABASE_URL set returns
        an async_sessionmaker instance without importing intellisource.main."""
        monkeypatch.setenv("IS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        # Importing boot must NOT import intellisource.main
        from intellisource.scheduler import boot  # noqa: PLC0415

        factory = boot.init_worker_session_factory()

        assert isinstance(factory, async_sessionmaker), (
            f"Expected async_sessionmaker, got {type(factory)}"
        )

    def test_init_worker_session_factory_does_not_import_main(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """boot.init_worker_session_factory() must not call create_app or access
        app.state.db — verified by ensuring intellisource.main is never invoked."""
        monkeypatch.setenv("IS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        # Remove any previously cached import of scheduler.boot to force re-import
        sys.modules.pop("intellisource.scheduler.boot", None)

        with patch.dict(sys.modules, {"intellisource.main": None}):
            # If boot.py imports from intellisource.main the None sentinel will
            # raise AttributeError/ImportError — that would make the test fail with
            # an explanatory error instead of a silent green.
            from intellisource.scheduler import boot as fresh_boot  # noqa: PLC0415

            fresh_boot.init_worker_session_factory()
            # If we reach here, main was not imported in the call path.


# ---------------------------------------------------------------------------
# AC-T075-2
# ---------------------------------------------------------------------------


class TestBuildCeleryTasks:
    """build_celery_tasks() registers run_pipeline and wires session_factory."""

    def test_build_celery_tasks_returns_celery_tasks_with_session_factory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """build_celery_tasks(...) returns a CeleryTasks instance whose
        _session_factory attribute is not None."""
        monkeypatch.setenv("IS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("IS_REDIS_URL", "redis://localhost:6379/0")

        from intellisource.scheduler import boot  # noqa: PLC0415
        from intellisource.scheduler.tasks import CeleryTasks  # noqa: PLC0415

        mock_agent_runner = MagicMock()
        mock_pipeline_config = MagicMock()
        factory = boot.init_worker_session_factory()

        mock_redis = MagicMock()
        with patch(
            "intellisource.scheduler.boot._build_redis_client", return_value=mock_redis
        ):
            tasks = boot.build_celery_tasks(
                mock_agent_runner, mock_pipeline_config, factory
            )

        assert isinstance(tasks, CeleryTasks), (
            f"Expected CeleryTasks instance, got {type(tasks)}"
        )
        assert tasks._session_factory is not None, (
            "CeleryTasks._session_factory must be set after build_celery_tasks()"
        )
        assert tasks._idempotency_guard is not None, (
            "CeleryTasks._idempotency_guard must be non-None after build_celery_tasks()"
        )
        assert tasks._fingerprint_checker is not None, (
            "CeleryTasks._fingerprint_checker must be non-None "
            "after build_celery_tasks()"
        )
        assert tasks._content_repository is not None, (
            "CeleryTasks._content_repository must be non-None "
            "after build_celery_tasks()"
        )
        import asyncio  # noqa: PLC0415

        factory_callable = tasks._session_factory
        assert callable(factory_callable), "_session_factory must be callable"
        assert asyncio.iscoroutinefunction(factory_callable), (
            "_session_factory must be an async coroutine function "
            "(returns an awaitable that yields AsyncSession)"
        )

    def test_build_celery_tasks_registers_run_pipeline_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The module-level celery_app registers 'run_pipeline' as a task."""
        monkeypatch.setenv("IS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        # Importing tasks registers run_pipeline on the module-level celery_app.
        import intellisource.scheduler.tasks  # noqa: PLC0415, F401
        from intellisource.scheduler.celery_app import celery_app  # noqa: PLC0415

        registered_names = list(celery_app.tasks.keys())
        assert any("run_pipeline" in key for key in registered_names), (
            f"Expected a task with 'run_pipeline' in its name, got: {registered_names}"
        )


# ---------------------------------------------------------------------------
# AC-T075-1 (signal handler variant)
# ---------------------------------------------------------------------------


class TestWorkerInitSignalHandler:
    """worker_init_handler() wires the CeleryTasks singleton when called."""

    def test_worker_init_signal_wires_celery_tasks_singleton(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After worker_init_handler() is invoked get_celery_tasks() returns a
        non-None CeleryTasks instance."""
        import importlib  # noqa: PLC0415

        monkeypatch.setenv("IS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("IS_REDIS_URL", "redis://localhost:6379/0")

        # Force a clean module state so _celery_tasks singleton starts at None.
        sys.modules.pop("intellisource.scheduler.boot", None)
        import intellisource.scheduler.boot as boot_mod  # noqa: PLC0415

        importlib.reload(boot_mod)

        from intellisource.scheduler.tasks import CeleryTasks  # noqa: PLC0415

        mock_runner = MagicMock()
        mock_factory = MagicMock()
        mock_redis = MagicMock()
        mock_tasks = MagicMock(spec=CeleryTasks)

        with (
            patch(
                "intellisource.scheduler.boot.init_worker_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "intellisource.scheduler.boot.build_celery_tasks",
                return_value=mock_tasks,
            ),
            patch(
                "intellisource.agent.factory.get_agent_runner",
                return_value=mock_runner,
            ),
            patch(
                "intellisource.scheduler.boot._build_redis_client",
                return_value=mock_redis,
            ),
        ):
            boot_mod.worker_init_handler(sender=object())

        result = boot_mod.get_celery_tasks()
        assert result is not None, (
            "get_celery_tasks() must return a non-None value after "
            "worker_init_handler() has been called"
        )
        assert isinstance(result, CeleryTasks), (
            f"Expected CeleryTasks instance, got {type(result)}"
        )


# ---------------------------------------------------------------------------
# AC-T075-4: end-to-end run_pipeline with mock session_factory
# ---------------------------------------------------------------------------


class TestRunPipelineEndToEndWithSessionFactory:
    """run_pipeline reaches repo.create with correct TaskChain fields."""

    def test_run_pipeline_end_to_end_repo_create_called_once(
        self,
    ) -> None:
        """With a mock session_factory injected, run_pipeline('manual-collect', {})
        calls repo.create exactly once."""
        from intellisource.scheduler.tasks import CeleryTasks  # noqa: PLC0415
        from intellisource.storage.models import TaskChain  # noqa: PLC0415

        mock_repo = AsyncMock()

        # repo.create returns the TaskChain back (mirrors real implementation)
        async def _fake_create(chain: TaskChain) -> TaskChain:
            chain.id = uuid.uuid4()
            return chain

        mock_repo.create = AsyncMock(side_effect=_fake_create)

        mock_session = AsyncMock()
        mock_session.close = AsyncMock()

        async def mock_session_factory() -> AsyncMock:
            return mock_session

        mock_agent_runner = MagicMock()
        mock_agent_runner.execute = AsyncMock(return_value={"status": "success"})

        mock_pipeline_config = MagicMock()
        mock_pipeline_config.load.return_value = {
            "name": "manual-collect",
            "steps": [{"name": "fetch", "processor": "rss_collector"}],
            "execution_mode": "strict",
        }

        with patch(
            "intellisource.scheduler.tasks.TaskChainRepository",
            return_value=mock_repo,
        ):
            tasks = CeleryTasks(
                agent_runner=mock_agent_runner,
                pipeline_config=mock_pipeline_config,
                session_factory=mock_session_factory,
            )
            tasks.run_pipeline("manual-collect", {"trigger_type": "manual"})

        assert mock_repo.create.await_count == 1, (
            f"repo.create must be awaited exactly once, "
            f"got {mock_repo.create.await_count}"
        )

    def test_run_pipeline_task_chain_has_correct_trigger_type_and_pipeline_name(
        self,
    ) -> None:
        """The TaskChain passed to repo.create carries the trigger_type from
        params and the pipeline_name passed to run_pipeline."""
        from intellisource.scheduler.tasks import CeleryTasks  # noqa: PLC0415
        from intellisource.storage.models import TaskChain  # noqa: PLC0415

        captured_chains: list[TaskChain] = []
        mock_repo = AsyncMock()

        async def _capture_create(chain: TaskChain) -> TaskChain:
            captured_chains.append(chain)
            chain.id = uuid.uuid4()
            return chain

        mock_repo.create = AsyncMock(side_effect=_capture_create)

        mock_session = AsyncMock()
        mock_session.close = AsyncMock()

        async def mock_session_factory() -> AsyncMock:
            return mock_session

        mock_agent_runner = MagicMock()
        mock_agent_runner.execute = AsyncMock(return_value={"status": "success"})

        mock_pipeline_config = MagicMock()
        mock_pipeline_config.load.return_value = {
            "name": "manual-collect",
            "steps": [],
            "execution_mode": "strict",
        }

        with patch(
            "intellisource.scheduler.tasks.TaskChainRepository",
            return_value=mock_repo,
        ):
            tasks = CeleryTasks(
                agent_runner=mock_agent_runner,
                pipeline_config=mock_pipeline_config,
                session_factory=mock_session_factory,
            )
            tasks.run_pipeline("manual-collect", {"trigger_type": "manual"})

        assert len(captured_chains) == 1
        chain = captured_chains[0]
        assert chain.pipeline_name == "manual-collect", (
            f"Expected pipeline_name='manual-collect', got '{chain.pipeline_name}'"
        )
        assert chain.trigger_type == "manual", (
            f"Expected trigger_type='manual', got '{chain.trigger_type}'"
        )


# ---------------------------------------------------------------------------
# N-003: worker_init_handler cold-start without mocking build_celery_tasks
# ---------------------------------------------------------------------------


class TestWorkerInitHandlerRealBuild:
    """N-003: worker_init_handler() cold-start must not raise AttributeError
    and must wire all four singleton components when build_celery_tasks is not
    mocked."""

    def test_worker_init_handler_runs_real_build_celery_tasks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """worker_init_handler() with only external I/O mocked (Redis client +
        agent_runner) must complete without AttributeError and wire all singleton
        components via the real build_celery_tasks path.

        N-003 refproof: if boot.py R-001 wiring is reverted this test fails
        because get_celery_tasks() returns None (setattr not called) or
        build_celery_tasks raises AttributeError on a missing component.
        """
        import importlib  # noqa: PLC0415

        monkeypatch.setenv("IS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("IS_REDIS_URL", "redis://localhost:6379/0")

        # Force a clean module state so _celery_tasks singleton starts as None.
        sys.modules.pop("intellisource.scheduler.boot", None)
        import intellisource.scheduler.boot as boot_mod  # noqa: PLC0415

        importlib.reload(boot_mod)

        # Build a real sqlite-backed session factory (no DB tables needed —
        # we only assert the adapter is wired, not that it executes queries).
        from sqlalchemy.ext.asyncio import (  # noqa: PLC0415
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        real_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

        mock_runner = MagicMock()

        # Mock Redis client with async-compatible methods so IdempotencyGuard
        # construction succeeds without a real Redis connection.
        mock_redis = MagicMock()

        with (
            patch(
                "intellisource.scheduler.boot.init_worker_session_factory",
                return_value=real_factory,
            ),
            patch(
                "intellisource.scheduler.boot._build_redis_client",
                return_value=mock_redis,
            ),
            patch(
                "intellisource.agent.factory.get_agent_runner",
                return_value=mock_runner,
            ),
        ):
            # build_celery_tasks is NOT mocked — real assembly path runs.
            boot_mod.worker_init_handler(sender=object())

        tasks = boot_mod.get_celery_tasks()

        assert tasks is not None, (
            "get_celery_tasks() must return non-None after worker_init_handler()"
        )
        assert tasks._idempotency_guard is not None, (
            "worker_init_handler must wire _idempotency_guard via build_celery_tasks"
        )
        assert tasks._fingerprint_checker is not None, (
            "worker_init_handler must wire _fingerprint_checker via build_celery_tasks"
        )
        assert tasks._content_repository is not None, (
            "worker_init_handler must wire _content_repository via build_celery_tasks"
        )
