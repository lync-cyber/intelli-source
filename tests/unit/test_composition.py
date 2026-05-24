"""T-095 RED: unit tests for intellisource.composition module.

Covers AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-9.
All tests in this file are expected to FAIL until the implementation exists.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# AC-1: composition module is importable and exports all 7 builder functions
# ---------------------------------------------------------------------------


class TestCompositionModuleImportable:
    """AC-1: src/intellisource/composition.py exists and exports 7 functions."""

    def test_module_importable(self) -> None:
        """composition module can be imported without error."""
        import importlib

        mod = importlib.import_module("intellisource.composition")
        assert mod is not None

    def test_build_llm_gateway_exists(self) -> None:
        """AC-1: composition exports build_llm_gateway."""
        from intellisource.composition import build_llm_gateway  # type: ignore[import]

        assert callable(build_llm_gateway)

    def test_build_pipeline_loader_exists(self) -> None:
        """AC-1: composition exports build_pipeline_loader."""
        from intellisource.composition import (
            build_pipeline_loader,  # type: ignore[import]
        )

        assert callable(build_pipeline_loader)

    def test_build_collector_registry_exists(self) -> None:
        """AC-1: composition exports build_collector_registry."""
        from intellisource.composition import (
            build_collector_registry,  # type: ignore[import]
        )

        assert callable(build_collector_registry)

    def test_build_distributor_facade_exists(self) -> None:
        """AC-1: composition exports build_distributor_facade."""
        from intellisource.composition import (
            build_distributor_facade,  # type: ignore[import]
        )

        assert callable(build_distributor_facade)

    def test_build_search_engine_factory_exists(self) -> None:
        """AC-1: composition exports build_search_engine_factory."""
        from intellisource.composition import (
            build_search_engine_factory,  # type: ignore[import]
        )

        assert callable(build_search_engine_factory)

    def test_build_worker_composition_exists(self) -> None:
        """AC-1: composition exports build_worker_composition."""
        from intellisource.composition import (
            build_worker_composition,  # type: ignore[import]
        )

        assert callable(build_worker_composition)

    def test_build_api_composition_exists(self) -> None:
        """AC-1: composition exports build_api_composition."""
        from intellisource.composition import (
            build_api_composition,  # type: ignore[import]
        )

        assert callable(build_api_composition)


# ---------------------------------------------------------------------------
# AC-2: PipelineLoader class with load(name) -> PipelineConfig
# ---------------------------------------------------------------------------


class TestPipelineLoader:
    """AC-2: composition.PipelineLoader.load(name) delegates to load_pipeline_config."""

    def test_pipeline_loader_class_exists(self) -> None:
        """AC-2: composition module exports PipelineLoader class."""
        from intellisource.composition import PipelineLoader  # type: ignore[import]

        assert isinstance(PipelineLoader, type)

    def test_pipeline_loader_has_load_method(self) -> None:
        """AC-2: PipelineLoader instance has a load() method."""
        from intellisource.composition import PipelineLoader  # type: ignore[import]

        loader = PipelineLoader()
        assert hasattr(loader, "load")
        assert callable(loader.load)

    def test_pipeline_loader_load_delegates_to_load_pipeline_config(self) -> None:
        """AC-2: PipelineLoader.load(name) calls load_pipeline_config(name).

        composition.py imports `load_pipeline_config` from agent.tools at
        module load time, so the patch target must be the composition
        namespace binding — patching agent.tools.load_pipeline_config after
        import has no effect on the bound reference.
        """
        from intellisource.agent.pipeline import PipelineConfig
        from intellisource.composition import PipelineLoader  # type: ignore[import]

        mock_config = MagicMock(spec=PipelineConfig)
        with patch(
            "intellisource.composition.load_pipeline_config",
            return_value=mock_config,
        ) as mock_fn:
            loader = PipelineLoader()
            result = loader.load("scheduled-collect")

        mock_fn.assert_called_once_with("scheduled-collect")
        assert result is mock_config

    def test_pipeline_loader_load_returns_pipeline_config(self) -> None:
        """AC-2: PipelineLoader.load('scheduled-collect') returns a PipelineConfig."""
        from intellisource.agent.pipeline import PipelineConfig
        from intellisource.composition import PipelineLoader  # type: ignore[import]

        loader = PipelineLoader()
        result = loader.load("scheduled-collect")

        assert isinstance(result, PipelineConfig), (
            f"Expected PipelineConfig, got {type(result)}"
        )

    def test_build_pipeline_loader_returns_pipeline_loader_instance(self) -> None:
        """AC-2: build_pipeline_loader() returns a PipelineLoader instance."""
        from intellisource.composition import (  # type: ignore[import]
            PipelineLoader,
            build_pipeline_loader,
        )

        loader = build_pipeline_loader()
        assert isinstance(loader, PipelineLoader)


# ---------------------------------------------------------------------------
# AC-3: WorkerComposition dataclass with required fields
# ---------------------------------------------------------------------------


class TestWorkerComposition:
    """AC-3: WorkerComposition dataclass has the five required fields."""

    def test_worker_composition_class_exists(self) -> None:
        """AC-3: composition module exports WorkerComposition class."""
        from intellisource.composition import WorkerComposition  # type: ignore[import]

        assert isinstance(WorkerComposition, type)

    def test_worker_composition_has_agent_runner_field(self) -> None:
        """AC-3: WorkerComposition dataclass has agent_runner field."""
        import dataclasses

        from intellisource.composition import WorkerComposition  # type: ignore[import]

        field_names = {f.name for f in dataclasses.fields(WorkerComposition)}
        assert "agent_runner" in field_names, (
            f"WorkerComposition missing 'agent_runner' field; found: {field_names}"
        )

    def test_worker_composition_has_pipeline_loader_field(self) -> None:
        """AC-3: WorkerComposition dataclass has pipeline_loader field."""
        import dataclasses

        from intellisource.composition import WorkerComposition  # type: ignore[import]

        field_names = {f.name for f in dataclasses.fields(WorkerComposition)}
        assert "pipeline_loader" in field_names, (
            f"WorkerComposition missing 'pipeline_loader' field; found: {field_names}"
        )

    def test_worker_composition_has_collector_registry_field(self) -> None:
        """AC-3: WorkerComposition dataclass has collector_registry field."""
        import dataclasses

        from intellisource.composition import WorkerComposition  # type: ignore[import]

        field_names = {f.name for f in dataclasses.fields(WorkerComposition)}
        assert "collector_registry" in field_names, (
            "WorkerComposition missing 'collector_registry' field; "
            f"found: {field_names}"
        )

    def test_worker_composition_has_distributor_field(self) -> None:
        """AC-3: WorkerComposition dataclass has distributor field."""
        import dataclasses

        from intellisource.composition import WorkerComposition  # type: ignore[import]

        field_names = {f.name for f in dataclasses.fields(WorkerComposition)}
        assert "distributor" in field_names, (
            f"WorkerComposition missing 'distributor' field; found: {field_names}"
        )

    def test_worker_composition_has_session_factory_field(self) -> None:
        """AC-3: WorkerComposition dataclass has session_factory field."""
        import dataclasses

        from intellisource.composition import WorkerComposition  # type: ignore[import]

        field_names = {f.name for f in dataclasses.fields(WorkerComposition)}
        assert "session_factory" in field_names, (
            f"WorkerComposition missing 'session_factory' field; found: {field_names}"
        )

    def test_build_worker_composition_returns_worker_composition(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-3: build_worker_composition(...) returns a WorkerComposition instance."""
        monkeypatch.setenv("IS_REDIS_URL", "redis://localhost:6379/0")

        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from intellisource.composition import (  # type: ignore[import]
            WorkerComposition,
            build_worker_composition,
        )

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            factory = async_sessionmaker(
                bind=engine, class_=AsyncSession, expire_on_commit=False
            )
            mock_redis = MagicMock()

            result = build_worker_composition(
                session_factory=factory,
                redis_client=mock_redis,
            )
            assert isinstance(result, WorkerComposition), (
                f"Expected WorkerComposition, got {type(result)}"
            )
        finally:
            import asyncio  # noqa: PLC0415

            asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# AC-4: build_agent_runner enforces keyword-only args — None raises TypeError/ValueError
# ---------------------------------------------------------------------------


class TestBuildAgentRunnerKeywordOnly:
    """AC-4: build_agent_runner requires all 5 kwargs; None values rejected.

    The legacy signature was build_agent_runner(session_factory, llm_gateway, *,
    pipeline_config=None) and silently accepted None for session_factory and
    llm_gateway. After T-095 the signature is keyword-only with 5 required
    non-None args. Tests verify the "silent None acceptance" is gone.
    """

    def test_build_agent_runner_rejects_none_session_factory(self) -> None:
        """AC-4: build_agent_runner with None args raises TypeError/ValueError.

        Current behaviour: silently accepts None (test FAILS = correct RED state).
        After fix: raises TypeError (type annotation enforcement) or ValueError.
        """
        from intellisource.agent.factory import build_agent_runner

        # The new signature requires session_factory, llm_gateway,
        # collector_registry, distributor, search_engine_factory as keyword-only
        # non-None args. We call with only the two old args to confirm the new
        # signature enforcement.
        with pytest.raises((TypeError, ValueError)):
            # After implementation: missing collector_registry/distributor/
            # search_engine_factory are required kwargs → TypeError; passing
            # None → ValueError. For the RED test we verify all-None old-style
            # args raise.
            result = build_agent_runner(
                session_factory=None,
                llm_gateway=None,
            )
            # If the above call succeeds (current behavior), check that the runner
            # carries None in its tool_deps — which should NOT happen after fix.
            # Force a failure to mark this as RED:
            assert result._tool_deps.session_factory is not None, (
                "AC-4 RED: build_agent_runner currently accepts session_factory=None; "
                "after fix this must raise"
            )

    def test_build_agent_runner_requires_collector_registry_kwarg(self) -> None:
        """AC-4: build_agent_runner missing collector_registry raises TypeError."""
        from intellisource.agent.factory import build_agent_runner

        # After fix, collector_registry is a required kwarg.
        # Currently the param does not exist → TypeError for unknown kwarg.
        # After fix: TypeError for missing required kwarg.
        # Either way we expect TypeError, so this test is green in both states —
        # UNLESS we distinguish: call with only new-style args minus collector_registry.
        # The RED signal comes from test_build_agent_runner_rejects_none_session_factory
        # and test_build_agent_runner_all_required_kwargs_must_be_provided below.
        with pytest.raises(TypeError):
            build_agent_runner(  # type: ignore[call-arg]
                session_factory=MagicMock(),
                llm_gateway=MagicMock(),
                distributor=MagicMock(),
                search_engine_factory=MagicMock(),
                # collector_registry intentionally omitted
            )

    def test_build_agent_runner_all_required_kwargs_must_be_provided(self) -> None:
        """AC-4: omitting any of the three new kwargs raises TypeError."""
        from intellisource.agent.factory import build_agent_runner

        with pytest.raises(TypeError):
            build_agent_runner(  # type: ignore[call-arg]
                session_factory=MagicMock(),
                llm_gateway=MagicMock(),
                # collector_registry, distributor, search_engine_factory omitted
            )

    def test_build_agent_runner_tool_deps_wires_collector_registry(self) -> None:
        """AC-4: ToolDeps.collector_registry is set from the kwarg (not hardcoded None).

        Current code: ToolDeps(collector_registry=None, distributor=None) — always None.
        After fix: ToolDeps.collector_registry = the passed collector_registry.
        """
        from intellisource.agent.factory import build_agent_runner

        mock_collector_registry = MagicMock()
        mock_distributor = MagicMock()
        mock_search_engine_factory = MagicMock()

        runner = build_agent_runner(
            session_factory=MagicMock(),
            llm_gateway=MagicMock(),
            collector_registry=mock_collector_registry,
            distributor=mock_distributor,
            search_engine_factory=mock_search_engine_factory,
        )
        assert runner._tool_deps is not None
        assert runner._tool_deps.collector_registry is mock_collector_registry, (
            "AC-4: ToolDeps.collector_registry must be the passed value, "
            "not hardcoded None"
        )

    def test_build_agent_runner_tool_deps_wires_distributor(self) -> None:
        """AC-4: ToolDeps.distributor is set from the kwarg (not hardcoded None)."""
        from intellisource.agent.factory import build_agent_runner

        mock_distributor = MagicMock()

        runner = build_agent_runner(
            session_factory=MagicMock(),
            llm_gateway=MagicMock(),
            collector_registry=MagicMock(),
            distributor=mock_distributor,
            search_engine_factory=MagicMock(),
        )
        assert runner._tool_deps is not None
        assert runner._tool_deps.distributor is mock_distributor, (
            "AC-4: ToolDeps.distributor must be the passed value, not hardcoded None"
        )


# ---------------------------------------------------------------------------
# AC-5: get_agent_runner() raises RuntimeError when not initialised
# ---------------------------------------------------------------------------


class TestGetAgentRunnerRaisesWhenNotInitialised:
    """AC-5: get_agent_runner() raises RuntimeError when _agent_runner is None."""

    def test_get_agent_runner_raises_runtime_error_when_not_initialised(self) -> None:
        """AC-5: get_agent_runner() raises RuntimeError with correct message."""

        import intellisource.agent.factory as factory_mod
        from intellisource.composition import get_agent_runner_holder

        holder = get_agent_runner_holder()
        original = holder._runner
        holder.reset()
        try:
            with pytest.raises(RuntimeError, match="AgentRunner not initialised"):
                factory_mod.get_agent_runner()
        finally:
            holder._runner = original

    def test_get_agent_runner_error_message_mentions_build_function(self) -> None:
        """AC-5: RuntimeError message names the required build function."""
        import intellisource.agent.factory as factory_mod
        from intellisource.composition import get_agent_runner_holder

        holder = get_agent_runner_holder()
        original = holder._runner
        holder.reset()
        try:
            with pytest.raises(RuntimeError) as exc_info:
                factory_mod.get_agent_runner()
            assert "build_worker_composition" in str(
                exc_info.value
            ) or "build_api_composition" in str(exc_info.value), (
                f"Error message must mention build_worker_composition or "
                f"build_api_composition; got: {exc_info.value}"
            )
        finally:
            holder._runner = original


# ---------------------------------------------------------------------------
# AC-6: worker_init_handler passes non-None pipeline_loader to build_celery_tasks
# ---------------------------------------------------------------------------


class TestWorkerInitHandlerPipelineLoader:
    """AC-6: worker_init_handler passes a PipelineLoader (not None) as arg #2."""

    def test_build_celery_tasks_second_arg_is_not_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6: build_celery_tasks gets non-None pipeline_config from boot."""
        import importlib

        monkeypatch.setenv("IS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("IS_REDIS_URL", "redis://localhost:6379/0")

        sys.modules.pop("intellisource.scheduler.boot", None)
        import intellisource.scheduler.boot as boot_mod

        importlib.reload(boot_mod)

        captured_pipeline_config: list[Any] = []

        original_build_celery_tasks = boot_mod.build_celery_tasks

        def _spy_build_celery_tasks(
            agent_runner: Any, pipeline_config: Any, session_factory: Any
        ) -> Any:
            captured_pipeline_config.append(pipeline_config)
            return original_build_celery_tasks(
                agent_runner, pipeline_config, session_factory
            )

        mock_runner = MagicMock()
        mock_redis = MagicMock()
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            real_factory = async_sessionmaker(
                bind=engine, class_=AsyncSession, expire_on_commit=False
            )

            with (
                patch.object(
                    boot_mod, "build_celery_tasks", side_effect=_spy_build_celery_tasks
                ),
                patch.object(
                    boot_mod,
                    "init_worker_session_factory",
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
                boot_mod.worker_init_handler(sender=object())

            assert len(captured_pipeline_config) == 1, (
                "build_celery_tasks must have been called exactly once"
            )
            assert captured_pipeline_config[0] is not None, (
                "AC-6: pipeline_config (2nd arg to build_celery_tasks) must not be "
                "None; got None — boot.py still passes None"
            )
        finally:
            import asyncio  # noqa: PLC0415

            asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# AC-7: run_pipeline does not AttributeError with real PipelineLoader
# ---------------------------------------------------------------------------


class TestRunPipelineNoAttributeError:
    """AC-7: CeleryTasks.run_pipeline survives wiring with a real PipelineLoader."""

    def test_run_pipeline_with_real_pipeline_loader_no_attribute_error(self) -> None:
        """AC-7: run_pipeline('scheduled-collect', {...}) does not AttributeError.

        Current code raises 'NoneType' object has no attribute 'load' (when
        pipeline_config is None) or AttributeError on config.get() (since
        PipelineConfig has no .get()). After fix: config.mode and config.steps
        are accessed as dataclass properties.
        """
        from intellisource.composition import PipelineLoader  # type: ignore[import]
        from intellisource.scheduler.tasks import CeleryTasks

        loader = PipelineLoader()
        mock_runner = MagicMock()
        mock_runner.execute.return_value = {"status": "ok"}

        tasks = CeleryTasks(
            agent_runner=mock_runner,
            pipeline_config=loader,
            session_factory=None,
        )

        # Must not raise AttributeError or TypeError — these are the wiring
        # crashes (None.load / .get on dataclass) that AC-7 guards against.
        # Other exceptions (RuntimeError from missing redis, asyncio etc.) are
        # acceptable because they're not symptoms of the wire-up bug.
        try:
            tasks.run_pipeline(
                "scheduled-collect",
                {"task_id": "test-001", "fingerprint": ""},
            )
        except (AttributeError, TypeError) as exc:
            pytest.fail(
                f"AC-7: run_pipeline raised {type(exc).__name__} — "
                f"pipeline_loader / PipelineConfig wiring still broken: {exc}"
            )
        except (RuntimeError, ConnectionError):
            # Acceptable — these are external dependency failures, not wiring.
            pass

    def test_run_pipeline_accesses_config_mode_as_attribute(self) -> None:
        """AC-7: tasks.py reads config.mode (attribute), not config.get(...)."""
        from intellisource.composition import PipelineLoader  # type: ignore[import]

        loader = PipelineLoader()
        config = loader.load("scheduled-collect")

        # Verify config.mode is accessible as an attribute (not .get())
        assert hasattr(config, "mode"), "PipelineConfig must have .mode property"
        assert config.mode in ("strict", "flexible", "batch"), (
            f"config.mode must be a valid mode, got: {config.mode}"
        )

    def test_run_pipeline_accesses_config_steps_as_attribute(self) -> None:
        """AC-7: tasks.py uses config.steps (attribute), not config.get('steps')."""
        from intellisource.composition import PipelineLoader  # type: ignore[import]

        loader = PipelineLoader()
        config = loader.load("scheduled-collect")

        assert hasattr(config, "steps"), "PipelineConfig must have .steps property"
        assert isinstance(config.steps, list), (
            f"config.steps must be a list, got {type(config.steps)}"
        )


# ---------------------------------------------------------------------------
# AC-9: main.py no longer defines init_celery / shutdown_celery
# ---------------------------------------------------------------------------


class TestMainNoInitCelery:
    """AC-9: main.py does not define init_celery() or shutdown_celery()."""

    def test_main_has_no_init_celery(self) -> None:
        """AC-9: intellisource.main does not have init_celery attribute."""
        import intellisource.main as main_mod

        assert not hasattr(main_mod, "init_celery"), (
            "AC-9: main.init_celery still exists; it must be deleted"
        )

    def test_main_has_no_shutdown_celery(self) -> None:
        """AC-9: intellisource.main does not have shutdown_celery attribute."""
        import intellisource.main as main_mod

        assert not hasattr(main_mod, "shutdown_celery"), (
            "AC-9: main.shutdown_celery still exists; it must be deleted"
        )


# ---------------------------------------------------------------------------
# r2 R-003: CompositionError / CompositionNotInitialisedError hierarchy
# ---------------------------------------------------------------------------


class TestCompositionErrorHierarchy:
    """r2 R-003: composition raises IntelliSourceError-rooted exceptions.

    Multiple inheritance keeps backward compat with `pytest.raises(ValueError)`
    / `pytest.raises(RuntimeError)` from existing AC-4 / AC-5 tests.
    """

    def test_composition_error_inherits_intellisource_error(self) -> None:
        from intellisource.composition import CompositionError
        from intellisource.core.errors import IntelliSourceError

        assert issubclass(CompositionError, IntelliSourceError)
        assert issubclass(CompositionError, ValueError)

    def test_composition_error_has_unrecoverable_category(self) -> None:
        from intellisource.composition import CompositionError
        from intellisource.core.errors import ErrorCategory

        exc = CompositionError("test")
        assert exc.category is ErrorCategory.UNRECOVERABLE

    def test_composition_not_initialised_error_inherits_intellisource_error(
        self,
    ) -> None:
        from intellisource.composition import CompositionNotInitialisedError
        from intellisource.core.errors import IntelliSourceError

        assert issubclass(CompositionNotInitialisedError, IntelliSourceError)
        assert issubclass(CompositionNotInitialisedError, RuntimeError)

    def test_build_agent_runner_raises_composition_error_on_none(self) -> None:
        from intellisource.agent.factory import build_agent_runner
        from intellisource.composition import CompositionError

        with pytest.raises(CompositionError):
            build_agent_runner(
                session_factory=None,
                llm_gateway=MagicMock(),
                collector_registry=MagicMock(),
                distributor=MagicMock(),
                search_engine_factory=MagicMock(),
            )

    def test_get_agent_runner_raises_composition_not_initialised(self) -> None:
        from intellisource.agent.factory import get_agent_runner
        from intellisource.composition import (
            CompositionNotInitialisedError,
            get_agent_runner_holder,
        )

        holder = get_agent_runner_holder()
        original = holder._runner
        holder.reset()
        try:
            with pytest.raises(CompositionNotInitialisedError):
                get_agent_runner()
        finally:
            holder._runner = original


# ---------------------------------------------------------------------------
# r2 R-004: AgentRunnerHolder API
# ---------------------------------------------------------------------------


class TestAgentRunnerHolder:
    """r2 R-004: composition.AgentRunnerHolder replaces module-level
    `agent_factory._agent_runner` mutation."""

    def test_holder_singleton(self) -> None:
        """get_agent_runner_holder() returns the same instance every call."""
        from intellisource.composition import get_agent_runner_holder

        assert get_agent_runner_holder() is get_agent_runner_holder()

    def test_holder_install_and_get_round_trip(self) -> None:
        from intellisource.composition import get_agent_runner_holder

        holder = get_agent_runner_holder()
        original = holder._runner
        sentinel = MagicMock(name="runner-sentinel")
        holder.install(sentinel)
        try:
            assert holder.get() is sentinel
            assert holder.installed is True
        finally:
            holder._runner = original

    def test_holder_reset_clears_runner(self) -> None:
        from intellisource.composition import (
            CompositionNotInitialisedError,
            get_agent_runner_holder,
        )

        holder = get_agent_runner_holder()
        original = holder._runner
        holder.install(MagicMock())
        try:
            holder.reset()
            assert holder.installed is False
            with pytest.raises(CompositionNotInitialisedError):
                holder.get()
        finally:
            holder._runner = original

    def test_factory_no_longer_owns_module_singleton(self) -> None:
        """factory.py must no longer keep an `_agent_runner` module attribute."""
        import intellisource.agent.factory as factory_mod

        assert not hasattr(factory_mod, "_agent_runner"), (
            "r2 R-004: factory._agent_runner module state must be removed; "
            "singleton lives in composition.AgentRunnerHolder"
        )


# ---------------------------------------------------------------------------
# r2 R-002: worker_init_handler is idempotent
# ---------------------------------------------------------------------------


class TestWorkerInitHandlerIdempotent:
    """r2 R-002: worker_init_handler must short-circuit on second invocation."""

    def test_second_invocation_does_not_rebuild(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import intellisource.scheduler.boot as boot_mod

        original = boot_mod._celery_tasks
        boot_mod._celery_tasks = None

        from unittest.mock import patch

        call_count = {"build_composition": 0}

        def _count_build_composition(*args: Any, **kwargs: Any) -> Any:
            call_count["build_composition"] += 1
            mock_composition = MagicMock()
            mock_composition.agent_runner = MagicMock()
            mock_composition.pipeline_loader = MagicMock()
            return mock_composition

        try:
            with (
                patch(
                    "intellisource.scheduler.boot.init_worker_session_factory",
                    return_value=MagicMock(),
                ),
                patch(
                    "intellisource.scheduler.boot._build_redis_client",
                    return_value=MagicMock(),
                ),
                patch(
                    "intellisource.scheduler.boot.build_worker_composition",
                    side_effect=_count_build_composition,
                ),
                patch(
                    "intellisource.scheduler.boot.build_celery_tasks",
                    return_value=MagicMock(),
                ),
            ):
                boot_mod.worker_init_handler()
                boot_mod.worker_init_handler()  # second call
                boot_mod.worker_init_handler()  # third call

            assert call_count["build_composition"] == 1, (
                f"r2 R-002: build_worker_composition called "
                f"{call_count['build_composition']} times across 3 invocations; "
                f"expected idempotent guard to keep it at 1"
            )
        finally:
            boot_mod._celery_tasks = original


# ---------------------------------------------------------------------------
# r2 R-006: tasks.py rejects legacy flat kwargs
# ---------------------------------------------------------------------------


class TestRunPipelineRejectsLegacyFlatKwargs:
    """r2 R-006: worker-side `run_pipeline` task must reject kwargs lacking
    a top-level 'params' key (the legacy flat shape AC-8 banned at the API)."""

    def test_run_pipeline_raises_when_params_missing(self) -> None:
        from intellisource.scheduler.tasks import _run_pipeline_body

        with pytest.raises(RuntimeError, match="legacy flat-kwargs shape"):
            # Simulate Celery dispatching with the legacy flat shape.
            _run_pipeline_body(
                pipeline_name="scheduled-collect",
                source_id="00000000-0000-0000-0000-000000000001",
                task_id="legacy-task-id",
            )

    def test_run_pipeline_accepts_new_contract(self) -> None:
        from intellisource.scheduler.celery_app import celery_app
        from intellisource.scheduler.tasks import _run_pipeline_body

        # Wire a stub _celery_tasks_instance so the task body doesn't blow up.
        stub_instance = MagicMock()
        stub_instance.run_pipeline.return_value = {"status": "ok"}
        original = getattr(celery_app, "_celery_tasks_instance", None)
        celery_app._celery_tasks_instance = stub_instance  # type: ignore[attr-defined]
        try:
            result = _run_pipeline_body(
                pipeline_name="scheduled-collect",
                params={"task_id": "T-1", "source_id": "S-1"},
            )
            assert result == {"status": "ok"}
            stub_instance.run_pipeline.assert_called_once_with(
                "scheduled-collect", {"task_id": "T-1", "source_id": "S-1"}
            )
        finally:
            if original is None:
                if hasattr(celery_app, "_celery_tasks_instance"):
                    delattr(celery_app, "_celery_tasks_instance")
            else:
                celery_app._celery_tasks_instance = original  # type: ignore[attr-defined]
