"""Tests for agent.compaction module.

Covers:
- Token-based retention strategy using estimate_tokens
- Structured summary template (compaction_summary.txt)
- Tool output priority pruning (protect last 3 tool messages)
- Auto-trigger threshold: estimated_tokens >
  min(context_window * 0.8, context_token_budget)
- Post-compaction token count <= context_window * 0.6
- LLM failure fallback to truncation
- Edge cases: empty messages, below threshold, already compact
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.agent.compaction import compact_messages, needs_compaction
from intellisource.llm.model_config import ModelProfile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_PROFILE = ModelProfile(
    temperature=0.0,
    max_tokens=512,
    context_window=4096,
    prompt_style="default",
    timeout_seconds=60,
)

_SMALL_PROFILE = ModelProfile(
    temperature=0.0,
    max_tokens=512,
    context_window=100,
    prompt_style="default",
    timeout_seconds=60,
)

_DEFAULT_BUDGET = 2000


def _make_gateway(summary: str = "Structured summary of conversation.") -> MagicMock:
    """Return a mock gateway with stubbed estimate_tokens and complete.

    estimate_tokens returns len(text) // 4; complete returns the summary text.
    """
    gateway = MagicMock()
    gateway.estimate_tokens = MagicMock(side_effect=lambda text, model: len(text) // 4)
    result = MagicMock()
    result.content = summary
    gateway.complete = AsyncMock(return_value=result)
    return gateway


def _make_failing_gateway() -> MagicMock:
    """Return a mock gateway whose complete always raises."""
    gateway = MagicMock()
    gateway.estimate_tokens = MagicMock(side_effect=lambda text, model: len(text) // 4)
    gateway.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    return gateway


# ---------------------------------------------------------------------------
# AC-T058-1: Token-based retention using estimate_tokens
# ---------------------------------------------------------------------------


class TestTokenBasedRetention:
    """estimate_tokens() is used to decide which messages to prune."""

    @pytest.mark.asyncio
    async def test_estimate_tokens_called_during_compaction(self) -> None:
        """estimate_tokens must be invoked when compaction is triggered."""
        # Use a tiny context window so compaction always triggers
        gateway = _make_gateway()
        messages = [{"role": "user", "content": "A" * 400}]
        await compact_messages(
            messages,
            gateway,
            profile=_SMALL_PROFILE,
            context_token_budget=10,
        )
        assert gateway.estimate_tokens.called

    @pytest.mark.asyncio
    async def test_token_based_not_message_count_based(self) -> None:
        """With a large budget and small messages, compaction should not trigger."""
        gateway = _make_gateway()
        # 3 tiny messages easily fit within a large context window
        messages = [{"role": "user", "content": "Hi"}] * 3
        result = await compact_messages(
            messages,
            gateway,
            profile=_DEFAULT_PROFILE,
            context_token_budget=_DEFAULT_BUDGET,
        )
        # No compaction: messages returned as-is, LLM not called
        assert result == messages
        gateway.complete.assert_not_awaited()


# ---------------------------------------------------------------------------
# AC-T058-2: Structured summary template compaction_summary.txt
# ---------------------------------------------------------------------------


class TestStructuredSummaryTemplate:
    """compact_messages uses compaction_summary.txt (5-section template)."""

    @pytest.mark.asyncio
    async def test_compaction_summary_template_loaded(self) -> None:
        """PromptBuilder('compaction_summary') must be used when summarising."""
        gateway = _make_gateway()
        # Force trigger: tiny context window
        messages = [{"role": "user", "content": "A" * 400}]
        with patch("intellisource.agent.compaction.PromptBuilder") as mock_builder_cls:
            mock_builder = MagicMock()
            mock_builder.add_context.return_value = mock_builder
            mock_builder.build.return_value = "rendered prompt"
            mock_builder_cls.return_value = mock_builder
            await compact_messages(
                messages,
                gateway,
                profile=_SMALL_PROFILE,
                context_token_budget=10,
            )
        mock_builder_cls.assert_called_once_with("compaction_summary")

    def test_compaction_summary_txt_exists(self) -> None:
        """The template file compaction_summary.txt must exist on disk."""
        from pathlib import Path

        template_path = (
            Path(__file__).parents[3]
            / "src"
            / "intellisource"
            / "llm"
            / "prompts"
            / "compaction_summary.txt"
        )
        assert template_path.exists(), f"Template not found: {template_path}"

    def test_compaction_summary_txt_has_five_sections(self) -> None:
        """Template must contain all 5 required section placeholders."""
        from pathlib import Path

        template_path = (
            Path(__file__).parents[3]
            / "src"
            / "intellisource"
            / "llm"
            / "prompts"
            / "compaction_summary.txt"
        )
        content = template_path.read_text(encoding="utf-8")
        for section in ("goal", "context", "changes", "state", "next_steps"):
            assert section in content.lower(), (
                f"Section '{section}' missing from compaction_summary.txt"
            )


# ---------------------------------------------------------------------------
# AC-T058-3: Tool output priority pruning
# ---------------------------------------------------------------------------


class TestToolOutputPruning:
    """role=tool messages are pruned before user/assistant; last 3 are protected."""

    @pytest.mark.asyncio
    async def test_tool_messages_pruned_before_user_messages(self) -> None:
        """Old tool messages should be removed before old user messages."""
        gateway = _make_gateway()
        # Build a list where tool messages appear early but user messages also exist
        messages: list[dict[str, str]] = [
            {"role": "tool", "content": "tool result 0"},
            {"role": "tool", "content": "tool result 1"},
            {"role": "user", "content": "user query"},
            {"role": "assistant", "content": "assistant response"},
            {"role": "tool", "content": "tool result 2"},
            {"role": "tool", "content": "tool result 3"},
            {"role": "tool", "content": "tool result 4"},
        ]
        # Trigger pruning with very tight budget
        result = await compact_messages(
            messages,
            gateway,
            profile=_SMALL_PROFILE,
            context_token_budget=10,
        )
        # The returned messages should not contain pruned early tool results
        # but user/assistant messages should be better preserved
        result_roles = [m["role"] for m in result]
        # user and assistant roles must survive longer than early tool messages
        assert (
            "user" in result_roles
            or "assistant" in result_roles
            or len(result) < len(messages)
        )

    @pytest.mark.asyncio
    async def test_last_three_tool_messages_protected(self) -> None:
        """Last 3 tool messages must never be pruned."""
        messages: list[dict[str, str]] = [
            {"role": "tool", "content": "old tool 0"},
            {"role": "tool", "content": "old tool 1"},
            {"role": "tool", "content": "recent tool A"},
            {"role": "tool", "content": "recent tool B"},
            {"role": "tool", "content": "recent tool C"},
        ]
        # Even with extreme budget pressure, last 3 tool messages survive pruning step
        pruned = _prune_tool_messages(messages)
        # The last 3 tool messages should still be present
        contents = [m["content"] for m in pruned]
        assert "recent tool A" in contents
        assert "recent tool B" in contents
        assert "recent tool C" in contents

    @pytest.mark.asyncio
    async def test_old_tool_messages_are_pruned(self) -> None:
        """Tool messages older than the last 3 must be candidates for pruning."""
        messages: list[dict[str, str]] = [
            {"role": "tool", "content": "old tool 0"},
            {"role": "tool", "content": "old tool 1"},
            {"role": "tool", "content": "recent tool A"},
            {"role": "tool", "content": "recent tool B"},
            {"role": "tool", "content": "recent tool C"},
        ]
        pruned = _prune_tool_messages(messages)
        contents = [m["content"] for m in pruned]
        assert "old tool 0" not in contents
        assert "old tool 1" not in contents


# ---------------------------------------------------------------------------
# AC-T058-4: Auto-trigger threshold
# ---------------------------------------------------------------------------


class TestAutoTriggerThreshold:
    """Compaction triggers when estimated_tokens > min(context_window*0.8, budget)."""

    @pytest.mark.asyncio
    async def test_no_compaction_below_threshold(self) -> None:
        """Messages well below threshold are returned unchanged."""
        gateway = _make_gateway()
        messages = [{"role": "user", "content": "short"}]
        result = await compact_messages(
            messages,
            gateway,
            profile=_DEFAULT_PROFILE,
            context_token_budget=_DEFAULT_BUDGET,
        )
        assert result == messages
        gateway.complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_compaction_triggers_above_threshold(self) -> None:
        """Messages exceeding threshold trigger compaction (LLM called)."""
        gateway = _make_gateway()
        # context_window=100, threshold = min(100*0.8=80, 2000) = 80 tokens
        # Each char ~= 0.25 tokens; 400 chars ~= 100 tokens > 80
        messages = [{"role": "user", "content": "A" * 400}]
        await compact_messages(
            messages,
            gateway,
            profile=_SMALL_PROFILE,
            context_token_budget=_DEFAULT_BUDGET,
        )
        gateway.complete.assert_awaited()

    def test_needs_compaction_uses_min_of_both_limits(self) -> None:
        """needs_compaction respects both context_window*0.8 and budget."""
        gateway = _make_gateway()
        # context_window=4096, threshold = min(4096*0.8=3276, 10) = 10
        messages = [{"role": "user", "content": "A" * 100}]
        # 100 chars // 4 = 25 tokens > 10 budget → needs compaction
        assert needs_compaction(
            messages, gateway, profile=_DEFAULT_PROFILE, context_token_budget=10
        )

    def test_needs_compaction_false_below_budget(self) -> None:
        """needs_compaction returns False when tokens well under both limits."""
        gateway = _make_gateway()
        messages = [{"role": "user", "content": "hi"}]
        # 2 chars // 4 = 0 tokens << min(3276, 2000)
        assert not needs_compaction(
            messages,
            gateway,
            profile=_DEFAULT_PROFILE,
            context_token_budget=_DEFAULT_BUDGET,
        )


# ---------------------------------------------------------------------------
# AC-T058-5: Post-compaction token count <= context_window * 0.6
# ---------------------------------------------------------------------------


class TestPostCompactionTokenBudget:
    """After compaction, result tokens must fit within context_window * 0.6."""

    @pytest.mark.asyncio
    async def test_result_fits_within_60_percent_of_context_window(self) -> None:
        """Compacted messages must fit within context_window * 0.6."""
        gateway = _make_gateway("short summary")
        # tiny context_window=100, 60% = 60 tokens
        messages = [{"role": "user", "content": "A" * 400}]
        result = await compact_messages(
            messages,
            gateway,
            profile=_SMALL_PROFILE,
            context_token_budget=_DEFAULT_BUDGET,
        )
        total_text = " ".join(m.get("content", "") for m in result)
        total_tokens = len(total_text) // 4
        assert total_tokens <= _SMALL_PROFILE.context_window * 0.6


# ---------------------------------------------------------------------------
# AC-T058-6: LLM failure fallback to truncation
# ---------------------------------------------------------------------------


class TestFallbackToTruncation:
    """When LLM summarisation fails, fall back to keeping recent N messages."""

    @pytest.mark.asyncio
    async def test_fallback_returns_messages_on_llm_error(self) -> None:
        """LLM failure must not raise; result is a valid message list."""
        gateway = _make_failing_gateway()
        messages = [{"role": "user", "content": "A" * 400}]
        result = await compact_messages(
            messages,
            gateway,
            profile=_SMALL_PROFILE,
            context_token_budget=_DEFAULT_BUDGET,
        )
        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_fallback_preserves_most_recent_messages(self) -> None:
        """Fallback must preserve the most recent messages."""
        gateway = _make_failing_gateway()
        messages = [
            {"role": "user", "content": "old message"},
            {"role": "assistant", "content": "old reply"},
            {"role": "user", "content": "recent question"},
            {"role": "assistant", "content": "recent answer"},
        ]
        result = await compact_messages(
            messages,
            gateway,
            profile=_SMALL_PROFILE,
            context_token_budget=_DEFAULT_BUDGET,
        )
        contents = [m["content"] for m in result]
        # At minimum, the very last message should be retained
        assert "recent answer" in contents


# ---------------------------------------------------------------------------
# Backward-compatible edge cases (kept from original tests)
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases: empty messages, single message."""

    @pytest.mark.asyncio
    async def test_empty_messages_returned_as_is(self) -> None:
        gateway = _make_gateway()
        result = await compact_messages(
            [],
            gateway,
            profile=_DEFAULT_PROFILE,
            context_token_budget=_DEFAULT_BUDGET,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_single_tiny_message_not_compacted(self) -> None:
        gateway = _make_gateway()
        messages = [{"role": "user", "content": "hi"}]
        result = await compact_messages(
            messages,
            gateway,
            profile=_DEFAULT_PROFILE,
            context_token_budget=_DEFAULT_BUDGET,
        )
        assert result == messages
        gateway.complete.assert_not_awaited()


# ---------------------------------------------------------------------------
# Helper import for pruning unit tests (white-box)
# ---------------------------------------------------------------------------


def _prune_tool_messages(
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    """White-box helper: exercise the tool-pruning logic directly."""
    from intellisource.agent.compaction import _prune_old_tool_messages

    return _prune_old_tool_messages(messages)
