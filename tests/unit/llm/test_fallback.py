"""Tests for FallbackManager degradation logic.

Covers:
- AC-030: Fallback switch time < 500ms
- AC-T020-3: FallbackManager maintains degradation mapping table
- AC-T020-4: Fallback events recorded to LLMCallLog (status=fallback)
"""

from __future__ import annotations

import time
from typing import Any, Callable
from unittest.mock import AsyncMock

import pytest

from intellisource.llm.fallback import FallbackManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_FALLBACK_REGISTRY: dict[str, Callable[..., Any]] = {
    "structured_extraction": lambda text: {"entities": []},
    "semantic_dedup": lambda text: {"fingerprint": hash(text)},
    "cluster_analysis": lambda texts: {"clusters": []},
    "summary_generation": lambda text: text[:200],
    "tagging": lambda text: ["default"],
    "content_reranking": lambda items: items,
    "intro_generation": lambda _: "",
    "context_compression": lambda turns: turns[-3:] if len(turns) > 3 else turns,
}


@pytest.fixture
def fallback_registry() -> dict[str, Callable[..., Any]]:
    """Return a sample fallback function registry."""
    return dict(_SAMPLE_FALLBACK_REGISTRY)


@pytest.fixture
def mock_call_log() -> AsyncMock:
    """Return a mock LLMCallLog writer."""
    log = AsyncMock()
    log.record.return_value = None
    return log


@pytest.fixture
def manager(
    fallback_registry: dict[str, Callable[..., Any]],
    mock_call_log: AsyncMock,
) -> FallbackManager:
    """Return a FallbackManager with sample registry and mock log."""
    return FallbackManager(
        fallback_registry=fallback_registry,
        call_log=mock_call_log,
    )


# ===================================================================
# AC-030: Fallback switch time < 500ms
# ===================================================================


class TestFallbackSwitchTime:
    """Verify degradation switching completes within 500ms."""

    async def test_fallback_execution_under_500ms(
        self, manager: FallbackManager
    ) -> None:
        """AC-030: Time from fault detection to fallback execution < 500ms."""
        start = time.monotonic()
        result = await manager.execute_fallback(
            task_type="structured_extraction",
            input_data="Some text to extract from",
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        assert elapsed_ms < 500, (
            f"Fallback switch took {elapsed_ms:.1f}ms, exceeds 500ms limit"
        )
        # Also verify the fallback actually returned the degraded payload
        assert result == {"entities": []}

    async def test_fallback_switch_time_with_log_recording(
        self, manager: FallbackManager, mock_call_log: AsyncMock
    ) -> None:
        """Fallback + log recording combined should still be < 500ms."""
        start = time.monotonic()
        await manager.execute_fallback(
            task_type="summary_generation",
            input_data="A long article text " * 50,
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        assert elapsed_ms < 500

    async def test_fallback_for_tagging_under_500ms(
        self, manager: FallbackManager
    ) -> None:
        """Tagging fallback (keyword matching) should be fast."""
        start = time.monotonic()
        result = await manager.execute_fallback(
            task_type="tagging",
            input_data="Python programming tutorial",
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        assert elapsed_ms < 500
        assert isinstance(result, list)


# ===================================================================
# AC-T020-3: FallbackManager maintains degradation mapping table
# ===================================================================


class TestFallbackMappingTable:
    """Verify FallbackManager maintains and uses the degradation mapping."""

    def test_manager_has_fallback_registry(self, manager: FallbackManager) -> None:
        """Manager must expose its fallback registry."""
        registry = manager.fallback_registry
        assert isinstance(registry, dict)
        assert len(registry) > 0

    def test_registry_contains_structured_extraction(
        self, manager: FallbackManager
    ) -> None:
        """Registry must have structured_extraction -> rule engine + regex."""
        assert "structured_extraction" in manager.fallback_registry

    def test_registry_contains_semantic_dedup(self, manager: FallbackManager) -> None:
        """Registry must have semantic_dedup -> content fingerprint + SimHash."""
        assert "semantic_dedup" in manager.fallback_registry

    def test_registry_contains_cluster_analysis(self, manager: FallbackManager) -> None:
        """Registry must have cluster_analysis -> TF-IDF + cosine similarity."""
        assert "cluster_analysis" in manager.fallback_registry

    def test_registry_contains_summary_generation(
        self, manager: FallbackManager
    ) -> None:
        """Registry must have summary_generation -> truncation summary."""
        assert "summary_generation" in manager.fallback_registry

    def test_registry_contains_tagging(self, manager: FallbackManager) -> None:
        """Registry must have tagging -> keyword matching + predefined tags."""
        assert "tagging" in manager.fallback_registry

    def test_registry_contains_content_reranking(
        self, manager: FallbackManager
    ) -> None:
        """Registry must have content_reranking -> default time ordering."""
        assert "content_reranking" in manager.fallback_registry

    def test_registry_contains_intro_generation(self, manager: FallbackManager) -> None:
        """Registry must have intro_generation -> no intro."""
        assert "intro_generation" in manager.fallback_registry

    def test_registry_contains_context_compression(
        self, manager: FallbackManager
    ) -> None:
        """Registry must have context_compression -> truncate oldest turns."""
        assert "context_compression" in manager.fallback_registry

    async def test_execute_fallback_calls_correct_function(
        self, manager: FallbackManager
    ) -> None:
        """execute_fallback should dispatch to the matching registry entry."""
        result = await manager.execute_fallback(
            task_type="summary_generation",
            input_data="First sentence. Second sentence. Third sentence.",
        )
        # The truncation fallback returns text[:200]
        assert isinstance(result, str)
        assert len(result) <= 200

    async def test_execute_fallback_unknown_task_raises(
        self, manager: FallbackManager
    ) -> None:
        """Requesting fallback for unregistered task should raise an error."""
        with pytest.raises((KeyError, ValueError)):
            await manager.execute_fallback(
                task_type="nonexistent_task",
                input_data="data",
            )

    def test_register_new_fallback(self, manager: FallbackManager) -> None:
        """It should be possible to register additional fallback functions."""

        def custom_fn(x):
            return x

        manager.register_fallback("custom_task", custom_fn)
        assert "custom_task" in manager.fallback_registry


# ===================================================================
# AC-T020-4: Fallback events recorded to LLMCallLog (status=fallback)
# ===================================================================


class TestFallbackEventLogging:
    """Verify fallback events are recorded with status=fallback."""

    async def test_fallback_records_to_call_log(
        self, manager: FallbackManager, mock_call_log: AsyncMock
    ) -> None:
        """execute_fallback must write an entry to LLMCallLog."""
        await manager.execute_fallback(
            task_type="tagging",
            input_data="test input",
        )
        mock_call_log.record.assert_called_once()

    async def test_log_entry_has_fallback_status(
        self, manager: FallbackManager, mock_call_log: AsyncMock
    ) -> None:
        """The log entry must have status='fallback'."""
        await manager.execute_fallback(
            task_type="structured_extraction",
            input_data="test input",
        )
        call_kwargs = mock_call_log.record.call_args
        # Check that 'status' is passed as 'fallback' either in kwargs or positional
        all_args = str(call_kwargs)
        assert "fallback" in all_args, (
            f"Expected status='fallback' in log record call, got: {call_kwargs}"
        )

    async def test_log_entry_contains_task_type(
        self, manager: FallbackManager, mock_call_log: AsyncMock
    ) -> None:
        """The log entry should reference the task_type that was degraded."""
        await manager.execute_fallback(
            task_type="semantic_dedup",
            input_data="duplicate check text",
        )
        call_kwargs = mock_call_log.record.call_args
        all_args = str(call_kwargs)
        assert "semantic_dedup" in all_args, (
            f"Expected task_type in log record, got: {call_kwargs}"
        )

    async def test_multiple_fallbacks_log_separately(
        self, manager: FallbackManager, mock_call_log: AsyncMock
    ) -> None:
        """Each fallback invocation should produce its own log entry."""
        await manager.execute_fallback(task_type="tagging", input_data="text1")
        await manager.execute_fallback(
            task_type="summary_generation", input_data="text2"
        )
        assert mock_call_log.record.call_count == 2


# ===================================================================
# Edge cases and boundary conditions
# ===================================================================


class TestFallbackEdgeCases:
    """Boundary conditions for FallbackManager."""

    async def test_fallback_with_empty_input(self, manager: FallbackManager) -> None:
        """Fallback should handle empty string input without error."""
        result = await manager.execute_fallback(
            task_type="summary_generation",
            input_data="",
        )
        assert result == ""

    async def test_fallback_with_none_input_raises(
        self, manager: FallbackManager
    ) -> None:
        """Fallback should raise on None input."""
        with pytest.raises((TypeError, ValueError)):
            await manager.execute_fallback(
                task_type="tagging",
                input_data=None,
            )

    def test_empty_registry_init(self, mock_call_log: AsyncMock) -> None:
        """FallbackManager can be created with an empty registry."""
        mgr = FallbackManager(
            fallback_registry={},
            call_log=mock_call_log,
        )
        assert len(mgr.fallback_registry) == 0

    async def test_context_compression_truncates_oldest(
        self, manager: FallbackManager
    ) -> None:
        """Context compression fallback should truncate oldest turns."""
        turns = ["turn1", "turn2", "turn3", "turn4", "turn5"]
        result = await manager.execute_fallback(
            task_type="context_compression",
            input_data=turns,
        )
        # Should keep only the most recent turns
        assert isinstance(result, list)
        assert len(result) <= len(turns)
