"""Tests for _llm_complete_execute real LLMGateway invocation via ToolDeps.

Covers T-087 AC-4:
- _llm_complete_execute must call LLMGateway.complete() or LLMGateway.chat()
  through the ToolDeps-injected gateway instance (not return a placeholder).
- The call must be made exactly once per invocation.
- The returned result must not be the old placeholder {"status": "ok", ...}.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helper: build a minimal ToolDeps mock matching the shared design contract.
# ToolDeps lives in intellisource.agent.deps (or intellisource.agent.factory),
# and exposes at minimum: llm_gateway.
# ---------------------------------------------------------------------------


def _make_tool_deps(llm_gateway: Any) -> Any:
    """Construct a ToolDeps-like container with a mock llm_gateway field."""
    from intellisource.agent.deps import ToolDeps  # type: ignore[import]

    return ToolDeps(
        session_factory=MagicMock(),
        llm_gateway=llm_gateway,
        pipeline_engine=MagicMock(),
        search_engine=MagicMock(),
        collector_registry=MagicMock(),
        distributor=MagicMock(),
    )


# ---------------------------------------------------------------------------
# AC-4: _llm_complete_execute calls LLMGateway.complete() or .chat()
# ---------------------------------------------------------------------------


class TestLLMCompleteExecuteCallsGateway:
    """AC-4: _llm_complete_execute invokes LLMGateway, not a placeholder."""

    @pytest.mark.asyncio
    async def test_llm_complete_calls_gateway_complete(self) -> None:
        """_llm_complete_execute must call gateway.complete() once."""
        from intellisource.agent.tools import (
            _llm_complete_execute,  # type: ignore[import]
        )
        from intellisource.llm.gateway import LLMResult  # type: ignore[import]

        mock_gateway = AsyncMock()
        mock_gateway.complete = AsyncMock(
            return_value=LLMResult(content="result text", metadata={})
        )
        mock_gateway.chat = AsyncMock(
            return_value=LLMResult(content="result text", metadata={})
        )

        deps = _make_tool_deps(mock_gateway)

        await _llm_complete_execute(
            call_type="summarize",
            prompt_vars={"text": "some content"},
            tool_deps=deps,
        )

        total_calls = mock_gateway.complete.call_count + mock_gateway.chat.call_count
        assert total_calls >= 1, (
            "_llm_complete_execute must call LLMGateway.complete() or .chat() "
            f"at least once; found {total_calls} total calls"
        )

    @pytest.mark.asyncio
    async def test_llm_complete_calls_gateway_exactly_once(self) -> None:
        """_llm_complete_execute must call the gateway exactly once per invocation."""
        from intellisource.agent.tools import (
            _llm_complete_execute,  # type: ignore[import]
        )
        from intellisource.llm.gateway import LLMResult  # type: ignore[import]

        mock_gateway = AsyncMock()
        mock_gateway.complete = AsyncMock(
            return_value=LLMResult(content="summary", metadata={})
        )
        mock_gateway.chat = AsyncMock(
            return_value=LLMResult(content="summary", metadata={})
        )

        deps = _make_tool_deps(mock_gateway)

        await _llm_complete_execute(
            call_type="extract",
            prompt_vars={"body": "text body"},
            tool_deps=deps,
        )

        total_calls = mock_gateway.complete.call_count + mock_gateway.chat.call_count
        assert total_calls == 1, (
            f"Expected exactly 1 LLMGateway call, got {total_calls}"
        )

    @pytest.mark.asyncio
    async def test_llm_complete_result_not_placeholder(self) -> None:
        """Result must not be the old placeholder {status: ok, tool: llm_complete}."""
        from intellisource.agent.tools import (
            _llm_complete_execute,  # type: ignore[import]
        )
        from intellisource.llm.gateway import LLMResult  # type: ignore[import]

        mock_gateway = AsyncMock()
        mock_gateway.complete = AsyncMock(
            return_value=LLMResult(content="actual LLM output", metadata={})
        )
        mock_gateway.chat = AsyncMock(
            return_value=LLMResult(content="actual LLM output", metadata={})
        )

        deps = _make_tool_deps(mock_gateway)

        result = await _llm_complete_execute(
            call_type="summarize",
            prompt_vars={"text": "some content"},
            tool_deps=deps,
        )

        is_old_placeholder = (
            isinstance(result, dict)
            and result.get("status") == "ok"
            and result.get("tool") == "llm_complete"
            and "content" not in result
        )
        assert not is_old_placeholder, (
            "_llm_complete_execute must not return the old placeholder dict; "
            f"got: {result}"
        )

    @pytest.mark.asyncio
    async def test_llm_complete_gateway_receives_prompt_vars(self) -> None:
        """The LLMGateway call must include content derived from prompt_vars."""
        from intellisource.agent.tools import (
            _llm_complete_execute,  # type: ignore[import]
        )
        from intellisource.llm.gateway import LLMResult  # type: ignore[import]

        mock_gateway = AsyncMock()
        mock_gateway.complete = AsyncMock(
            return_value=LLMResult(content="extracted data", metadata={})
        )
        mock_gateway.chat = AsyncMock(
            return_value=LLMResult(content="extracted data", metadata={})
        )

        deps = _make_tool_deps(mock_gateway)

        prompt_text = "this is the target content for extraction"
        await _llm_complete_execute(
            call_type="extract",
            prompt_vars={"text": prompt_text},
            tool_deps=deps,
        )

        total_calls = mock_gateway.complete.call_count + mock_gateway.chat.call_count
        assert total_calls >= 1, (
            "Expected LLMGateway to be called with prompt_vars content"
        )

        if mock_gateway.complete.call_count > 0:
            call_args = mock_gateway.complete.call_args
            all_args_str = str(call_args)
        else:
            call_args = mock_gateway.chat.call_args
            all_args_str = str(call_args)

        assert prompt_text in all_args_str or "extract" in all_args_str, (
            "LLMGateway call arguments must include prompt content or call_type; "
            f"call args: {all_args_str}"
        )


# ---------------------------------------------------------------------------
# AC-4: ToolDeps class exists and has llm_gateway field
# ---------------------------------------------------------------------------


class TestToolDepsContract:
    """ToolDeps must exist and carry the llm_gateway field."""

    def test_tool_deps_importable(self) -> None:
        """ToolDeps must be importable from intellisource.agent.deps."""
        from intellisource.agent.deps import ToolDeps  # type: ignore[import]

        assert ToolDeps is not None

    def test_tool_deps_has_llm_gateway_field(self) -> None:
        """ToolDeps must expose a llm_gateway attribute."""
        from intellisource.agent.deps import ToolDeps  # type: ignore[import]

        mock_gw = MagicMock()
        deps = ToolDeps(
            session_factory=MagicMock(),
            llm_gateway=mock_gw,
            pipeline_engine=MagicMock(),
            search_engine=MagicMock(),
            collector_registry=MagicMock(),
            distributor=MagicMock(),
        )
        assert deps.llm_gateway is mock_gw

    def test_tool_deps_has_required_fields(self) -> None:
        """ToolDeps must expose all fields from the shared design contract."""
        from intellisource.agent.deps import ToolDeps  # type: ignore[import]

        deps = ToolDeps(
            session_factory=MagicMock(),
            llm_gateway=MagicMock(),
            pipeline_engine=MagicMock(),
            search_engine=MagicMock(),
            collector_registry=MagicMock(),
            distributor=MagicMock(),
        )
        assert hasattr(deps, "session_factory")
        assert hasattr(deps, "llm_gateway")
        assert hasattr(deps, "pipeline_engine")
        assert hasattr(deps, "search_engine")
        assert hasattr(deps, "collector_registry")
        assert hasattr(deps, "distributor")
