"""Unit tests for push_optimizer.optimize_for_push (F-010)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from intellisource.distributor.push_optimizer import optimize_for_push
from intellisource.llm.gateway import LLMResult


def _make_content(
    title: str = "Original title", body: str = "Body text."
) -> SimpleNamespace:
    return SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        title=title,
        body_text=body,
        summary=None,
        tags=[],
        source_url="https://example.com/a",
    )


def _make_llm(response_json: str) -> AsyncMock:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=LLMResult(content=response_json))
    return llm


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


@pytest.mark.asyncio
async def test_valid_json_with_correct_schema_uses_optimization() -> None:
    content = _make_content(title="Old title", body="Old body text.")
    sub = SimpleNamespace(name="Tech feed")
    llm = _make_llm('{"title": "Optimized title", "summary": "Optimized summary"}')

    push_view = await optimize_for_push(content, sub, llm)

    assert push_view.title == "Optimized title"
    assert push_view.summary == "Optimized summary"


@pytest.mark.asyncio
async def test_hallucinated_key_falls_back_to_original() -> None:
    content = _make_content(title="Real title", body="Real body text for testing.")
    sub = SimpleNamespace(name="sub")
    # LLM returns wrong keys (headline/body instead of title/summary)
    llm = _make_llm('{"headline": "Hallucinated title", "body": "Hallucinated body"}')

    push_view = await optimize_for_push(content, sub, llm)

    assert push_view.title == "Real title"
    assert "Real body" in push_view.summary or push_view.summary != "Hallucinated body"


@pytest.mark.asyncio
async def test_missing_required_field_falls_back() -> None:
    content = _make_content(title="Fallback title", body="Fallback body text here.")
    sub = SimpleNamespace(name="sub")
    # LLM returns only title, missing required summary field
    llm = _make_llm('{"title": "Partial title"}')

    push_view = await optimize_for_push(content, sub, llm)

    assert push_view.title == "Fallback title"


@pytest.mark.asyncio
async def test_field_length_exceeds_max_falls_back() -> None:
    content = _make_content(title="Short title", body="Body text for length test.")
    sub = SimpleNamespace(name="sub")
    # title exceeds max_length=200
    long_title = "A" * 201
    llm = _make_llm(f'{{"title": "{long_title}", "summary": "ok summary"}}')

    push_view = await optimize_for_push(content, sub, llm)

    assert push_view.title == "Short title"


@pytest.mark.asyncio
async def test_invalid_json_falls_back() -> None:
    content = _make_content(title="Original title", body="Original body text.")
    sub = SimpleNamespace(name="sub")
    llm = _make_llm("not valid json at all {{{")

    push_view = await optimize_for_push(content, sub, llm)

    assert push_view.title == "Original title"
