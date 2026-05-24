"""Unit tests for push_optimizer.optimize_for_push (F-010)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from intellisource.distributor.push_optimizer import optimize_for_push
from intellisource.llm.gateway import LLMResult


@pytest.mark.asyncio
async def test_optimize_uses_llm_json_when_available() -> None:
    content = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        title="Original title that is fairly long",
        body_text="First sentence. Second sentence. Third sentence.",
        summary=None,
        tags=[],
        source_url="https://example.com/a",
    )
    sub = SimpleNamespace(name="AI digest")
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value=LLMResult(
            content='{"title": "LLM title", "summary": "LLM summary line"}'
        )
    )

    push_view = await optimize_for_push(content, sub, llm)

    assert push_view.title == "LLM title"
    assert push_view.summary == "LLM summary line"
    assert push_view.id == content.id
    llm.complete.assert_awaited_once()
    assert llm.complete.call_args.kwargs["task_type"] == "push_optimize"


@pytest.mark.asyncio
async def test_optimize_degrades_to_truncated_on_llm_failure() -> None:
    content = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        title="Short",
        body_text="Alpha. Beta. Gamma.",
        summary=None,
    )
    sub = SimpleNamespace(name="sub")
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=RuntimeError("provider down"))

    push_view = await optimize_for_push(content, sub, llm)

    assert push_view.title == "Short"
    assert "Alpha" in push_view.summary
