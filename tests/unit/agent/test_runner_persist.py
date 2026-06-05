"""Tests for TaskChainPersister.persist parameterization (T-075 AC-T075-3).

AgentRunner delegates persistence to ``self._persister`` (TaskChainPersister).
Verifies that:
- persist accepts trigger_type and execution_mode keyword parameters and
  forwards them to the TaskChain it constructs.
- run_strict drives persist with execution_mode="strict".
- run_flexible drives persist with execution_mode="flexible".
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.agent.runner import AgentRunner
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.llm.gateway import LLMResult

# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_runner() -> AgentRunner:
    registry = MagicMock()
    registry.list_tools.return_value = []
    registry.get.return_value = None
    return AgentRunner(tool_registry=registry, llm_gateway=None)


def _make_mock_repo() -> AsyncMock:
    """Create a TaskChainRepository mock that captures create() kwargs."""
    mock_repo = AsyncMock()

    async def _fake_create(**kwargs: Any) -> Any:
        chain = MagicMock()
        chain.id = kwargs.get("id") or uuid.uuid4()
        return chain

    mock_repo.create = AsyncMock(side_effect=_fake_create)
    return mock_repo


def _strict_config(**overrides: Any) -> PipelineConfig:
    base: dict[str, Any] = {
        "name": "test-strict",
        "mode": "strict",
        "steps": [],
        "max_steps": 5,
        "on_failure": "abort",
    }
    base.update(overrides)
    return PipelineConfig.from_dict(base)


def _flexible_config(**overrides: Any) -> PipelineConfig:
    base: dict[str, Any] = {
        "name": "test-flexible",
        "mode": "flexible",
        "steps": [],
        "max_steps": 3,
        "on_failure": "skip",
        "tools_allowed": [],
        "tools_denied": [],
    }
    base.update(overrides)
    return PipelineConfig.from_dict(base)


# ---------------------------------------------------------------------------
# AC-T075-3: _persist default parameter values
# ---------------------------------------------------------------------------


class TestPersistDefaultParameters:
    """_persist uses 'manual' / 'strict' defaults when caller omits them."""

    async def test_persist_uses_default_trigger_type_and_execution_mode(
        self,
    ) -> None:
        """_persist(repo=mock_repo) with no explicit trigger_type/execution_mode
        must store trigger_type='manual' and execution_mode='strict' on the
        TaskChain passed to repo.create()."""
        runner = _make_runner()
        mock_repo = _make_mock_repo()

        await runner._persister.persist(
            status="success",
            steps_executed=0,
            results=[],
            pipeline_name="default-test",
            repo=mock_repo,
        )

        mock_repo.create.assert_awaited_once()
        kwargs = mock_repo.create.call_args.kwargs
        assert kwargs["trigger_type"] == "manual", (
            f"Expected trigger_type='manual', got '{kwargs['trigger_type']}'"
        )
        assert kwargs["execution_mode"] == "strict", (
            f"Expected execution_mode='strict', got '{kwargs['execution_mode']}'"
        )


# ---------------------------------------------------------------------------
# AC-T075-3: _persist explicit parameter values
# ---------------------------------------------------------------------------


class TestPersistExplicitParameters:
    """_persist forwards caller-supplied trigger_type / execution_mode."""

    async def test_persist_accepts_explicit_trigger_type_and_execution_mode(
        self,
    ) -> None:
        """When trigger_type='scheduled' and execution_mode='flexible' are
        explicitly passed, repo.create must receive a TaskChain with those
        exact field values."""
        runner = _make_runner()
        mock_repo = _make_mock_repo()

        await runner._persister.persist(
            status="success",
            steps_executed=2,
            results=[],
            pipeline_name="explicit-test",
            trigger_type="scheduled",
            execution_mode="flexible",
            repo=mock_repo,
        )

        mock_repo.create.assert_awaited_once()
        kwargs = mock_repo.create.call_args.kwargs
        assert kwargs["trigger_type"] == "scheduled", (
            f"Expected trigger_type='scheduled', got '{kwargs['trigger_type']}'"
        )
        assert kwargs["execution_mode"] == "flexible", (
            f"Expected execution_mode='flexible', got '{kwargs['execution_mode']}'"
        )


# ---------------------------------------------------------------------------
# AC-T075-3: run_strict passes execution_mode="strict"
# ---------------------------------------------------------------------------


class TestRunStrictPassesExecutionMode:
    """run_strict calls _persist with execution_mode='strict'."""

    async def test_run_strict_passes_execution_mode_strict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After run_strict completes, the _persist spy must have been called
        with execution_mode='strict' in its keyword arguments."""
        runner = _make_runner()
        config = _strict_config()

        captured_kwargs: list[dict[str, Any]] = []

        original_persist = runner._persister.persist

        async def _spy_persist(**kwargs: Any) -> dict[str, Any]:
            captured_kwargs.append(dict(kwargs))
            return await original_persist(**kwargs)

        monkeypatch.setattr(runner._persister, "persist", _spy_persist)

        await runner.run_strict(config, params={})

        assert len(captured_kwargs) >= 1, "_persist was not called by run_strict"
        last_call = captured_kwargs[-1]
        assert last_call.get("execution_mode") == "strict", (
            f"run_strict must call _persist with execution_mode='strict', "
            f"got execution_mode={last_call.get('execution_mode')!r}"
        )


# ---------------------------------------------------------------------------
# AC-T075-3: run_flexible passes execution_mode="flexible"
# ---------------------------------------------------------------------------


class TestRunFlexiblePassesExecutionMode:
    """run_flexible calls _persist with execution_mode='flexible'."""

    async def test_run_flexible_passes_execution_mode_flexible(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After run_flexible completes, the _persist spy must have been called
        with execution_mode='flexible' in its keyword arguments."""
        llm_gateway = AsyncMock()
        llm_gateway.chat.return_value = LLMResult(
            content="done",
            metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
        )

        registry = MagicMock()
        registry.list_tools.return_value = []
        registry.get.return_value = None

        runner = AgentRunner(tool_registry=registry, llm_gateway=llm_gateway)
        config = _flexible_config()

        captured_kwargs: list[dict[str, Any]] = []

        original_persist = runner._persister.persist

        async def _spy_persist(**kwargs: Any) -> dict[str, Any]:
            captured_kwargs.append(dict(kwargs))
            return await original_persist(**kwargs)

        monkeypatch.setattr(runner._persister, "persist", _spy_persist)

        await runner.run_flexible(config, user_message="test", session={})

        assert len(captured_kwargs) >= 1, "_persist was not called by run_flexible"
        last_call = captured_kwargs[-1]
        assert last_call.get("execution_mode") == "flexible", (
            f"run_flexible must call _persist with execution_mode='flexible', "
            f"got execution_mode={last_call.get('execution_mode')!r}"
        )
