"""Integration tests for AC-4, AC-5, AC-7 (T-096).

AC-4: _process_execute fetches RawContent via session_factory, builds a
PipelineContext, calls pipeline_engine.execute() synchronously, and returns
{"status": "ok", "tool": "process", "results": [{...}]}.

AC-5: ContentRepository.get_raw_by_id(raw_id: UUID) -> RawContent | None exists
and returns the correct row.

AC-7: Given a RawContent fixture with HTML body, calling _process_execute with
full ToolDeps returns status="ok" and results[0]["body_text"] is non-empty
(HTMLParser has run).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.agent.deps import ToolDeps
from intellisource.core.processor import PipelineContext
from intellisource.pipeline.engine import PipelineEngine
from intellisource.pipeline.processors.parser import HTMLParser
from intellisource.storage.models import RawContent, Source

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_source(session: AsyncSession) -> Source:
    """Insert and flush a minimal Source row."""
    source = Source(
        id=uuid.uuid4(),
        name=f"test-source-{uuid.uuid4().hex[:8]}",
        type="rss",
        url="https://example.com/feed",
        tags=[],
        status="active",
        schedule_interval=3600,
        schedule_adaptive=False,
    )
    session.add(source)
    await session.flush()
    return source


async def _make_raw_content(
    session: AsyncSession,
    source: Source,
    *,
    body_html: str = "<p>Hello <b>world</b></p>",
    title: str = "Test article",
) -> RawContent:
    """Insert and flush a RawContent row with HTML body."""
    raw = RawContent(
        id=uuid.uuid4(),
        source_id=source.id,
        title=title,
        body_html=body_html,
        source_url=f"https://example.com/{uuid.uuid4().hex}",
        fingerprint=uuid.uuid4().hex,
        raw_metadata={},
    )
    session.add(raw)
    await session.flush()
    return raw


# ---------------------------------------------------------------------------
# AC-5: ContentRepository.get_raw_by_id
# ---------------------------------------------------------------------------


class TestContentRepositoryGetRawById:
    """AC-5: ContentRepository.get_raw_by_id(raw_id: UUID) -> RawContent | None."""

    @pytest.mark.asyncio
    async def test_get_raw_by_id_returns_correct_row(
        self, pg_session: AsyncSession
    ) -> None:
        """get_raw_by_id must return the RawContent with the given UUID."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        source = await _make_source(pg_session)
        raw = await _make_raw_content(pg_session, source, body_html="<p>Test</p>")

        repo = ContentRepository(session=pg_session)
        result = await repo.get_raw_by_id(raw.id)

        assert result is not None, (
            f"get_raw_by_id({raw.id}) must return a RawContent row, got None"
        )
        assert result.id == raw.id, (
            f"Returned RawContent.id {result.id} does not match requested {raw.id}"
        )

    @pytest.mark.asyncio
    async def test_get_raw_by_id_returns_none_for_missing_id(
        self, pg_session: AsyncSession
    ) -> None:
        """get_raw_by_id must return None for a UUID that does not exist."""
        from intellisource.storage.repositories.content import (  # noqa: PLC0415
            ContentRepository,
        )

        repo = ContentRepository(session=pg_session)
        result = await repo.get_raw_by_id(uuid.uuid4())

        assert result is None, "get_raw_by_id with a non-existent UUID must return None"


# ---------------------------------------------------------------------------
# AC-4 / AC-7: _process_execute contract
# ---------------------------------------------------------------------------


class TestProcessExecuteRealPipeline:
    """AC-4 / AC-7: _process_execute fetches RawContent and runs HTMLParser."""

    @pytest.mark.asyncio
    async def test_process_execute_returns_ok_status(
        self, pg_session: AsyncSession
    ) -> None:
        """AC-4: _process_execute returns status=ok envelope."""
        from intellisource.agent.tools import _process_execute  # noqa: PLC0415

        source = await _make_source(pg_session)
        raw = await _make_raw_content(
            pg_session, source, body_html="<p>Hello world</p>"
        )

        engine = PipelineEngine(processors=[HTMLParser()])
        session_factory = _make_session_factory_from_session(pg_session)

        tool_deps = ToolDeps(
            session_factory=session_factory,
            llm_gateway=None,
            pipeline_engine=engine,
            search_engine_factory=None,
            collector_registry=None,
            distributor=None,
        )

        result = await _process_execute(content_id=str(raw.id), tool_deps=tool_deps)

        assert result.get("status") == "ok", (
            f"_process_execute must return status='ok', got {result.get('status')!r}. "
            f"Full result: {result}"
        )
        assert result.get("tool") == "process", (
            f"_process_execute must return tool='process', got {result.get('tool')!r}"
        )

    @pytest.mark.asyncio
    async def test_process_execute_body_text_non_empty_after_html_parser(
        self, pg_session: AsyncSession
    ) -> None:
        """AC-7: After _process_execute, result['body_text'] must be non-empty
        (confirms HTMLParser ran on the body_html stored in RawContent)."""
        from intellisource.agent.tools import _process_execute  # noqa: PLC0415

        source = await _make_source(pg_session)
        raw = await _make_raw_content(
            pg_session,
            source,
            body_html="<h1>Breaking News</h1><p>AI model surpasses expectations.</p>",
            title="Breaking News",
        )

        engine = PipelineEngine(processors=[HTMLParser()])
        session_factory = _make_session_factory_from_session(pg_session)

        tool_deps = ToolDeps(
            session_factory=session_factory,
            llm_gateway=None,
            pipeline_engine=engine,
            search_engine_factory=None,
            collector_registry=None,
            distributor=None,
        )

        result = await _process_execute(content_id=str(raw.id), tool_deps=tool_deps)

        assert result.get("status") == "ok", (
            f"Expected status='ok', got {result.get('status')!r}"
        )
        results = result.get("results", [])
        inner = results[0] if results else {}
        body_text = inner.get("body_text") if isinstance(inner, dict) else None
        assert body_text, (
            "AC-7: result['body_text'] must be non-empty after HTMLParser runs. "
            f"Full result: {result}"
        )

    @pytest.mark.asyncio
    async def test_process_execute_calls_pipeline_engine_synchronously(
        self, pg_session: AsyncSession
    ) -> None:
        """AC-4: pipeline_engine.execute() must be called synchronously (not awaited).

        If the implementation incorrectly awaits execute(), the synchronous
        PipelineEngine.execute() will return a coroutine object rather than a
        PipelineContext — catching TypeError or an unawaited-coroutine warning
        is the signal.
        """
        from intellisource.agent.tools import _process_execute  # noqa: PLC0415

        source = await _make_source(pg_session)
        raw = await _make_raw_content(pg_session, source, body_html="<p>sync test</p>")

        call_log: list[str] = []

        class _TrackingEngine:
            """Fake synchronous engine that records how it was called."""

            def execute(self, ctx: PipelineContext) -> PipelineContext:
                call_log.append("sync_execute")
                ctx.set("body_text", "sync-processed")
                return ctx

        session_factory = _make_session_factory_from_session(pg_session)

        tool_deps = ToolDeps(
            session_factory=session_factory,
            llm_gateway=None,
            pipeline_engine=_TrackingEngine(),
            search_engine_factory=None,
            collector_registry=None,
            distributor=None,
        )

        result = await _process_execute(content_id=str(raw.id), tool_deps=tool_deps)

        assert "sync_execute" in call_log, (
            "AC-4: pipeline_engine.execute() must be called (synchronously). "
            f"call_log={call_log}, result={result}"
        )
        assert result.get("status") == "ok", (
            f"_process_execute must return status='ok', got {result!r}"
        )

    @pytest.mark.asyncio
    async def test_process_execute_loads_raw_content_from_db(
        self, pg_session: AsyncSession
    ) -> None:
        """AC-4: _process_execute must fetch the RawContent row by content_id UUID
        and set body_html on the PipelineContext before calling execute()."""
        from intellisource.agent.tools import _process_execute  # noqa: PLC0415

        source = await _make_source(pg_session)
        html_body = "<p>Unique content marker 42</p>"
        raw = await _make_raw_content(pg_session, source, body_html=html_body)

        observed_ctx_html: list[Any] = []

        class _CapturingEngine:
            def execute(self, ctx: PipelineContext) -> PipelineContext:
                observed_ctx_html.append(ctx.get("body_html"))
                ctx.set("body_text", "captured")
                return ctx

        session_factory = _make_session_factory_from_session(pg_session)

        tool_deps = ToolDeps(
            session_factory=session_factory,
            llm_gateway=None,
            pipeline_engine=_CapturingEngine(),
            search_engine_factory=None,
            collector_registry=None,
            distributor=None,
        )

        await _process_execute(content_id=str(raw.id), tool_deps=tool_deps)

        assert observed_ctx_html, (
            "AC-4: pipeline_engine.execute() must have been called"
        )
        assert observed_ctx_html[0] == html_body, (
            f"AC-4: PipelineContext.body_html must be set from RawContent.body_html. "
            f"Expected {html_body!r}, got {observed_ctx_html[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_process_execute_result_contains_content_id(
        self, pg_session: AsyncSession
    ) -> None:
        """AC-4: result dict must expose processed content_id distinct from raw id."""
        from intellisource.agent.tools import _process_execute  # noqa: PLC0415

        source = await _make_source(pg_session)
        raw = await _make_raw_content(pg_session, source, body_html="<p>id test</p>")

        engine = PipelineEngine(processors=[HTMLParser()])
        session_factory = _make_session_factory_from_session(pg_session)

        tool_deps = ToolDeps(
            session_factory=session_factory,
            llm_gateway=None,
            pipeline_engine=engine,
            search_engine_factory=None,
            collector_registry=None,
            distributor=None,
        )

        result = await _process_execute(content_id=str(raw.id), tool_deps=tool_deps)

        results = result.get("results", [])
        inner = results[0] if results else {}
        assert isinstance(inner, dict), (
            f"result['result'] must be a dict, got {type(inner)}"
        )
        assert inner.get("raw_content_id") == str(raw.id)
        assert inner.get("content_id") != str(raw.id), (
            "process must return ProcessedContent.id as content_id, not RawContent.id"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory_from_session(
    session: AsyncSession,
) -> Any:
    """Return a callable session_factory that yields the provided session
    as a synchronous context manager (matching the ToolDeps protocol)."""

    class _FakeContextManager:
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *_: Any) -> None:
            pass

    def _factory() -> _FakeContextManager:
        return _FakeContextManager()

    return _factory
