"""AC-10: worker_init_handler + run_pipeline does not crash.

Simulates Celery worker bootstrap (worker_init_handler) under production-like
config and invokes the registered run_pipeline task — must not raise
AttributeError or TypeError. The wired path:
- worker_init_handler calls build_worker_composition(...) to assemble ToolDeps
- build_celery_tasks receives a real PipelineLoader (not None)
- CeleryTasks.run_pipeline uses config.mode / config.steps attribute access
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def isolate_celery_tasks_singleton() -> Any:
    """Reset the module-level _celery_tasks singleton between tests.

    boot.py keeps a module-level _celery_tasks; without reset, prior tests
    can leak state into this one.
    """
    import intellisource.scheduler.boot as boot_mod

    original = boot_mod._celery_tasks
    boot_mod._celery_tasks = None
    yield
    boot_mod._celery_tasks = original


@pytest.fixture
def env_for_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("IS_REDIS_URL", "redis://localhost:6379/0")


# ---------------------------------------------------------------------------
# AC-10: worker_init_handler + run_pipeline production path does not crash
# ---------------------------------------------------------------------------


def test_worker_init_handler_assembles_complete_tool_deps(env_for_worker: None) -> None:
    """AC-10: After worker_init_handler runs, the cached AgentRunner's
    tool_deps has session_factory and llm_gateway non-None (production wire-up).

    Current main: get_agent_runner() returns silently-built runner with all-None
    ToolDeps → this assertion fails.
    """
    # Patch external IO (Redis client creation) but keep composition assembly real.
    with (
        patch(
            "intellisource.scheduler.boot._build_redis_client",
            return_value=MagicMock(),
        ),
    ):
        # Reload boot to clear any module-level cache picked up before patches.
        # Reset agent factory singleton
        import intellisource.scheduler.boot as boot_mod
        from intellisource.agent.runner import get_agent_runner_holder

        get_agent_runner_holder().reset()

        # Trigger the handler (Celery normally fires this via signal).
        boot_mod.worker_init_handler(sender=object())

    # get_agent_runner returns a runner with non-None deps.
    import intellisource.agent.factory as factory_mod
    from intellisource.llm.gateway import LLMGateway

    runner = factory_mod.get_agent_runner()
    assert runner is not None
    assert runner._tool_deps is not None, (
        "AC-10: AgentRunner.tool_deps must not be None"
    )
    assert callable(runner._tool_deps.session_factory), (
        "AC-10: tool_deps.session_factory must be a callable wired by "
        "build_worker_composition"
    )
    assert isinstance(runner._tool_deps.llm_gateway, LLMGateway), (
        "AC-10: tool_deps.llm_gateway must be an LLMGateway wired by "
        "build_worker_composition"
    )


def test_run_pipeline_does_not_raise_attribute_error(
    env_for_worker: None,
) -> None:
    """AC-10: After worker_init_handler runs, _celery_tasks_instance.run_pipeline(
    "scheduled-collect", {...}) does NOT raise AttributeError or TypeError.

    Production failure on main:
      AttributeError: 'NoneType' object has no attribute 'load'
      (from tasks.py:150 self._pipeline_config.load(...))
      or
      AttributeError: 'PipelineConfig' object has no attribute 'get'
      (from tasks.py:152 config.get("execution_mode", "strict"))
    """
    with (
        patch(
            "intellisource.scheduler.boot._build_redis_client",
            return_value=MagicMock(),
        ),
    ):
        import intellisource.scheduler.boot as boot_mod
        from intellisource.agent.runner import get_agent_runner_holder

        get_agent_runner_holder().reset()

        boot_mod.worker_init_handler(sender=object())

    from intellisource.scheduler.celery_app import celery_app
    from intellisource.scheduler.tasks import CeleryTasks

    _instance = getattr(celery_app, "_celery_tasks_instance", None)
    assert isinstance(_instance, CeleryTasks), (
        "AC-10: celery_app._celery_tasks_instance must be a CeleryTasks set by "
        "worker_init_handler"
    )

    # Stub AgentRunner.execute so we don't need a full pipeline runtime here.
    # The point of AC-10 is the wiring chain — config.load + property access —
    # not the actual collection logic.
    if _instance._agent_runner is not None:
        _instance._agent_runner.execute = MagicMock(
            return_value={"status": "ok", "results": []}
        )

    # Disable idempotency/fingerprint guards (they need real Redis).
    _instance._idempotency_guard = None
    _instance._fingerprint_checker = None
    _instance._session_factory = None  # short-circuit chain DB writes
    _instance._content_repository = None

    try:
        result = _instance.run_pipeline(
            "scheduled-collect", {"task_id": "test-001", "fingerprint": ""}
        )
    except AttributeError as exc:
        pytest.fail(
            f"AC-10: run_pipeline raised AttributeError on production path: {exc!r}. "
            f"This is the crash in pipeline_loader / config "
            f"attribute access not yet wired."
        )
    except TypeError as exc:
        pytest.fail(
            f"AC-10: run_pipeline raised TypeError on production path: {exc!r}. "
            f"This is the crash in pipeline_engine.execute "
            f"contract mismatch or similar."
        )

    assert isinstance(result, dict), (
        f"AC-10: run_pipeline must return a dict result; got {type(result)}"
    )
