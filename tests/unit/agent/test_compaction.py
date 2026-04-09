"""Tests for agent.compaction module.

Covers:
- compact_messages() normal path: LLM summarization of old messages
- compact_messages() fallback: truncation when LLM fails
- Edge cases: empty messages, all-recent messages
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.agent.compaction import compact_messages

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gateway() -> AsyncMock:
    """Create a mock LLM gateway that returns a summary string."""
    gateway = AsyncMock()
    result = MagicMock()
    result.content = "Summary: users discussed project deadlines and task assignments."
    gateway.complete = AsyncMock(return_value=result)
    return gateway


@pytest.fixture
def mock_gateway_failing() -> AsyncMock:
    """Create a mock LLM gateway that always raises."""
    gateway = AsyncMock()
    gateway.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    return gateway


@pytest.fixture
def sample_messages() -> list[dict[str, str]]:
    """A conversation with enough messages to trigger compaction."""
    return [{"role": "user", "content": f"Message {i}"} for i in range(20)]


# ---------------------------------------------------------------------------
# Tests: normal path
# ---------------------------------------------------------------------------


class TestCompactMessagesNormalPath:
    """LLM summarization produces a system summary + recent messages."""

    @pytest.mark.asyncio
    async def test_returns_system_summary_plus_recent(
        self, mock_gateway: AsyncMock, sample_messages: list[dict[str, str]]
    ) -> None:
        result = await compact_messages(sample_messages, mock_gateway, max_tokens=500)

        assert len(result) >= 2
        assert result[0]["role"] == "system"
        assert "Summary" in result[0]["content"]

    @pytest.mark.asyncio
    async def test_llm_gateway_called(
        self, mock_gateway: AsyncMock, sample_messages: list[dict[str, str]]
    ) -> None:
        await compact_messages(sample_messages, mock_gateway, max_tokens=500)

        mock_gateway.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recent_messages_preserved(
        self, mock_gateway: AsyncMock, sample_messages: list[dict[str, str]]
    ) -> None:
        result = await compact_messages(sample_messages, mock_gateway, max_tokens=500)

        # Last message should be preserved as-is
        assert result[-1]["content"] == sample_messages[-1]["content"]


# ---------------------------------------------------------------------------
# Tests: fallback path
# ---------------------------------------------------------------------------


class TestCompactMessagesFallback:
    """When LLM fails, falls back to truncation-based summary."""

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(
        self, mock_gateway_failing: AsyncMock, sample_messages: list[dict[str, str]]
    ) -> None:
        result = await compact_messages(
            sample_messages, mock_gateway_failing, max_tokens=500
        )

        assert len(result) >= 2
        assert result[0]["role"] == "system"
        assert "Summary of previous conversation" in result[0]["content"]


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestCompactMessagesEdgeCases:
    """Edge cases: too few messages, empty list."""

    @pytest.mark.asyncio
    async def test_few_messages_returned_as_is(self, mock_gateway: AsyncMock) -> None:
        short = [{"role": "user", "content": "Hello"}]
        result = await compact_messages(short, mock_gateway, max_tokens=500)

        assert result == short
        mock_gateway.complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_messages(self, mock_gateway: AsyncMock) -> None:
        result = await compact_messages([], mock_gateway, max_tokens=500)

        assert result == []
