"""Integration tests for AC-6 and AC-8 (T-096).

AC-6: _RawContentResultRepo.create(result) persists status="processed" and
processed_at=utcnow() back to the RawContent row when result contains
a content_id. Must not raise; must return result (caller contract stable).

AC-8: CeleryTasks.run_pipeline("content-process", {"content_id": ...}) ends
with RawContent.status == "processed" and RawContent.processed_at non-None
in the database.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.storage.models import RawContent, Source

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _make_source(session: AsyncSession) -> Source:
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
    body_html: str = "<p>Hello world</p>",
) -> RawContent:
    raw = RawContent(
        id=uuid.uuid4(),
        source_id=source.id,
        title="Test",
        body_html=body_html,
        source_url=f"https://example.com/{uuid.uuid4().hex}",
        fingerprint=uuid.uuid4().hex,
        raw_metadata={},
    )
    session.add(raw)
    await session.flush()
    return raw


# ---------------------------------------------------------------------------
# AC-6: _RawContentResultRepo.create()
# ---------------------------------------------------------------------------


class TestRawContentResultRepoCreate:
    """AC-6: _RawContentResultRepo.create(result) persists RawContent fields."""

    @pytest.mark.asyncio
    async def test_create_updates_status_to_processed(
        self, pg_session: AsyncSession
    ) -> None:
        """AC-6: After create(result), RawContent.status must equal 'processed'."""
        from intellisource.scheduler.boot import (  # noqa: PLC0415
            _RawContentResultRepo,
        )

        source = await _make_source(pg_session)
        raw = await _make_raw_content(pg_session, source)

        # Build a real session_factory backed by the same DB as pg_session.
        # _RawContentResultRepo opens its own session, so we give it the
        # pg_session's connection engine via a thin async_sessionmaker wrapper.
        session_factory = _sessionmaker_from_session(pg_session)

        repo = _RawContentResultRepo(session_factory=session_factory)

        result_payload = {
            "status": "ok",
            "content_id": str(raw.id),
            "body_text": "Hello world",
        }

        returned = await repo.create(result_payload)

        # Verify return value is unchanged (caller contract stable, AC-6).
        assert returned is result_payload, (
            "AC-6: create() must return the original result dict unchanged"
        )

        # Refresh and verify DB state.
        await pg_session.refresh(raw)

        # RawContent.status must exist and equal "processed" — if the attribute
        # is missing on the model (pre-GREEN), this raises AttributeError which
        # counts as a meaningful FAIL (implementation not yet done).
        assert raw.status == "processed", (  # type: ignore[attr-defined]
            f"AC-6: RawContent.status must be 'processed' after create(), "
            f"got {raw.status!r}"  # type: ignore[attr-defined]
        )

    @pytest.mark.asyncio
    async def test_create_sets_processed_at_non_none(
        self, pg_session: AsyncSession
    ) -> None:
        """AC-6: After create(result), RawContent.processed_at must be non-None."""
        from intellisource.scheduler.boot import (  # noqa: PLC0415
            _RawContentResultRepo,
        )

        source = await _make_source(pg_session)
        raw = await _make_raw_content(pg_session, source)

        session_factory = _sessionmaker_from_session(pg_session)
        repo = _RawContentResultRepo(session_factory=session_factory)

        await repo.create({"status": "ok", "content_id": str(raw.id)})
        await pg_session.refresh(raw)

        assert raw.processed_at is not None, (  # type: ignore[attr-defined]
            "AC-6: RawContent.processed_at must be set (non-None) after create()"
        )

    @pytest.mark.asyncio
    async def test_create_returns_result_when_no_content_id(
        self, pg_session: AsyncSession
    ) -> None:
        """AC-6: create() does not raise and returns result when content_id absent."""
        from intellisource.scheduler.boot import (  # noqa: PLC0415
            _RawContentResultRepo,
        )

        session_factory = _sessionmaker_from_session(pg_session)
        repo = _RawContentResultRepo(session_factory=session_factory)

        payload: dict[str, Any] = {"status": "ok", "something": "else"}
        returned = await repo.create(payload)

        assert returned is payload, (
            "AC-6: create() must return the result unchanged when content_id is absent"
        )

    @pytest.mark.asyncio
    async def test_create_does_not_raise_on_non_dict_result(
        self, pg_session: AsyncSession
    ) -> None:
        """AC-6: create() must not raise even when result is not a dict."""
        from intellisource.scheduler.boot import (  # noqa: PLC0415
            _RawContentResultRepo,
        )

        session_factory = _sessionmaker_from_session(pg_session)
        repo = _RawContentResultRepo(session_factory=session_factory)

        non_dict_result = "plain-string-result"
        returned = await repo.create(non_dict_result)

        assert returned == non_dict_result, (
            "AC-6: create() must return result unchanged for non-dict inputs"
        )


# ---------------------------------------------------------------------------
# AC-8: run_pipeline end-to-end → RawContent.status updated
# ---------------------------------------------------------------------------


class TestRunPipelinePersistsProcessedStatus:
    """AC-8: CeleryTasks.run_pipeline updates RawContent.status in the DB."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason=(
            "B-048: CeleryTasks.run_pipeline is sync — internally uses "
            "_run_sync(asyncio.run, ...) which spins a ThreadPoolExecutor + "
            "new event loop. pg_session is bound to the pytest-asyncio outer "
            "loop, so the inner thread hits 'cannot perform operation: another "
            "operation is in progress'. Real worker uses worker_session_factory "
            "+ NullPool (B-037 path); pytest fixture lacks that wiring."
        ),
        strict=False,
    )
    async def test_run_pipeline_marks_raw_content_as_processed(
        self, pg_session: AsyncSession
    ) -> None:
        """AC-8: After run_pipeline('content-process', {'content_id': <uuid>}),
        RawContent.status == 'processed' and processed_at is non-None in the DB."""
        from intellisource.scheduler.boot import (  # noqa: PLC0415
            _RawContentResultRepo,
        )
        from intellisource.scheduler.tasks import CeleryTasks  # noqa: PLC0415

        source = await _make_source(pg_session)
        raw = await _make_raw_content(
            pg_session, source, body_html="<p>Pipeline test</p>"
        )
        content_id = str(raw.id)

        session_factory = _sessionmaker_from_session(pg_session)

        # Real content repo backed by pg_session
        content_repo = _RawContentResultRepo(session_factory=session_factory)

        # Mock AgentRunner.execute — returns a result dict with content_id
        mock_runner = MagicMock()
        mock_runner.execute = AsyncMock(
            return_value={
                "status": "ok",
                "content_id": content_id,
                "body_text": "Pipeline test",
            }
        )

        # Real PipelineLoader backed by the real content-process.yaml
        mock_pipeline_loader = MagicMock()
        loaded_cfg = MagicMock()
        loaded_cfg.mode = "strict"
        loaded_cfg.steps = []
        mock_pipeline_loader.load.return_value = loaded_cfg

        tasks = CeleryTasks(
            agent_runner=mock_runner,
            pipeline_config=mock_pipeline_loader,
            session_factory=None,  # TaskChain persistence skipped
            idempotency_guard=None,
            fingerprint_checker=None,
            content_repository=content_repo,
        )

        tasks.run_pipeline(
            "content-process",
            {"content_id": content_id, "task_id": "test-t096"},
        )

        # Verify DB state
        await pg_session.refresh(raw)

        assert raw.status == "processed", (  # type: ignore[attr-defined]
            f"AC-8: RawContent.status must be 'processed' after run_pipeline, "
            f"got {raw.status!r}"  # type: ignore[attr-defined]
        )
        assert raw.processed_at is not None, (  # type: ignore[attr-defined]
            "AC-8: RawContent.processed_at must be set after run_pipeline"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sessionmaker_from_session(session: AsyncSession) -> Any:
    """Return a fake async_sessionmaker-shaped callable that yields *session*.

    _RawContentResultRepo calls `async with self._session_factory() as session:`
    so the factory must return an async context manager.
    """

    class _FakeCM:
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *_: Any) -> None:
            pass

    class _FakeSessionmaker:
        def __call__(self) -> _FakeCM:
            return _FakeCM()

    return _FakeSessionmaker()
