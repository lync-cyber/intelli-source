"""RED-phase tests for backfill_embeddings Celery task (T-BF-1 AC-3~AC-7).

AC-3: backfill_embeddings(batch_size=10) calls embed 3 times (once per NULL row),
      updates each row's embedding to the mock list[float] value, and skips
      already-embedded rows (idempotency).
AC-4: When embed returns None for a row, the row's embedding stays None, task does
      not crash, and a skip/embed_failed log entry is emitted.
AC-5: backfill_embeddings is registered in celery_app.tasks under the key
      "backfill_embeddings" (production path verified via task registry).
AC-6: When body_text is "" and title is non-empty, embed is called with title --
      verified via mock.call_args_list exact parameter matching.
AC-7 (OPTIONAL): When embed returns list[float] with wrong length (not 1024),
      the row is skipped, a warning is logged, task does not crash.

Design note on patch targets:
  The implementation is expected to expose two internal helpers:
    _get_backfill_deps()  -> (LLMGateway, session_factory)
    _open_content_repo()  -> ContentRepository (async context / direct return)
  Tests patch these helpers to inject controllable mocks. When the
  implementation uses a different internal factoring, only these patch
  paths need updating; the assertions remain identical.

GREEN seam contract (tasks.py must provide):
  - `_get_backfill_deps() -> tuple[Any, Any]` returning (gateway, session_factory)
  - `_open_content_repo(session_factory) -> ContentRepository` (or equivalent)
  - `async def backfill_embeddings(batch_size: int) -> dict` -- the async
    implementation, decorated with @celery_app.task(name="backfill_embeddings")
    or exposed as an awaitable for tests. If the Celery task is a sync wrapper,
    expose the inner async body as `_backfill_embeddings_impl` and the import
    helper below resolves it automatically.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import structlog.testing

from intellisource.storage.models import EMBEDDING_DIM

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

FAKE_EMBEDDING: list[float] = [0.1] * EMBEDDING_DIM  # 1024-dim -- faithful shape


def _make_processed_content_mock(
    *,
    body_text: str | None = "some body text",
    title: str | None = "Some Title",
    embedding: list[float] | None = None,
) -> MagicMock:
    """Return a mock ProcessedContent row with controllable fields."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.body_text = body_text
    row.title = title
    row.embedding = embedding
    return row


def _make_mock_deps(
    *,
    embed_side_effect: list | None = None,
    embed_return_value: list[float] | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Build (mock_llm_gateway, mock_session_factory) with configurable embed behaviour.

    Returns a pair suitable for injection into backfill_embeddings.
    ``embed_side_effect`` takes priority over ``embed_return_value`` when set.
    """
    mock_gateway = MagicMock()
    if embed_side_effect is not None:
        mock_gateway.embed = AsyncMock(side_effect=embed_side_effect)
    else:
        rv = embed_return_value or FAKE_EMBEDDING
        mock_gateway.embed = AsyncMock(return_value=rv)

    mock_session_factory = MagicMock()
    return mock_gateway, mock_session_factory


def _import_backfill_embeddings():
    """Import backfill_embeddings (or its async impl) or raise AssertionError."""
    try:
        from intellisource.scheduler.tasks import (  # noqa: PLC0415
            backfill_embeddings,
        )

        return backfill_embeddings
    except ImportError as exc:
        raise AssertionError(
            "backfill_embeddings is not importable from "
            f"intellisource.scheduler.tasks: {exc}. "
            "Implement @celery_app.task(name='backfill_embeddings') in tasks.py."
        ) from exc


# ---------------------------------------------------------------------------
# AC-5 -- Production path: task must be registered in celery_app.tasks
# ---------------------------------------------------------------------------


class TestBackfillDepsGuard:
    """R-003: None deps raise RuntimeError with a clear message before crashing."""

    async def test_raises_runtime_error_when_gateway_is_none(self) -> None:
        """RuntimeError raised immediately when gateway is None."""
        backfill_embeddings = _import_backfill_embeddings()

        with patch(
            "intellisource.scheduler.tasks._get_backfill_deps",
            return_value=(None, MagicMock()),
        ):
            try:
                await backfill_embeddings(batch_size=10)
                raise AssertionError("Expected RuntimeError, got no exception")
            except RuntimeError as exc:
                assert "llm_gateway" in str(exc) or "session_factory" in str(exc), (
                    f"RuntimeError message must mention deps, got: {exc}"
                )

    async def test_raises_runtime_error_when_session_factory_is_none(self) -> None:
        """RuntimeError raised immediately when session_factory is None."""
        backfill_embeddings = _import_backfill_embeddings()

        with patch(
            "intellisource.scheduler.tasks._get_backfill_deps",
            return_value=(MagicMock(), None),
        ):
            try:
                await backfill_embeddings(batch_size=10)
                raise AssertionError("Expected RuntimeError, got no exception")
            except RuntimeError as exc:
                assert "llm_gateway" in str(exc) or "session_factory" in str(exc), (
                    f"RuntimeError message must mention deps, got: {exc}"
                )


class TestBackfillEmbeddingsTaskRegistration:
    """AC-5: backfill_embeddings registered in celery_app.tasks["backfill_embeddings"].

    Production path: task must appear in the Celery task registry by string key.
    """

    def test_task_registered_in_celery_task_registry(self) -> None:
        """celery_app.tasks["backfill_embeddings"] must resolve to the task object."""
        from intellisource.scheduler.celery_app import celery_app  # noqa: PLC0415

        # AC-5 contract: the literal string key "backfill_embeddings" must be
        # present in the registry. Importing celery_app triggers tasks.py which
        # must register the task.
        assert "backfill_embeddings" in celery_app.tasks, (
            '"backfill_embeddings" is not in celery_app.tasks -- '
            "ensure @celery_app.task(name='backfill_embeddings') is in tasks.py"
        )

    def test_task_registry_entry_is_callable(self) -> None:
        """The registered task must be callable (Celery Task wrapper)."""
        from intellisource.scheduler.celery_app import celery_app  # noqa: PLC0415

        task = celery_app.tasks["backfill_embeddings"]
        assert callable(task), (
            "celery_app.tasks['backfill_embeddings'] must be callable"
        )

    def test_task_name_attribute_matches_registry_key(self) -> None:
        """task.name must equal 'backfill_embeddings'."""
        from intellisource.scheduler.celery_app import celery_app  # noqa: PLC0415

        task = celery_app.tasks["backfill_embeddings"]
        assert task.name == "backfill_embeddings", (
            f"task.name must be 'backfill_embeddings', got {task.name!r}"
        )


# ---------------------------------------------------------------------------
# AC-3 -- Happy path: 3 NULL rows backfilled, non-NULL rows untouched
# ---------------------------------------------------------------------------


class TestBackfillEmbeddingsAC3:
    """AC-3: 3 NULL rows all get embeddings; embed called 3 times; non-NULL skipped."""

    async def test_embed_called_once_per_null_row(self) -> None:
        """embed must be called exactly 3 times for 3 NULL-embedding rows."""
        backfill_embeddings = _import_backfill_embeddings()

        null_rows = [
            _make_processed_content_mock(body_text=f"body {i}", embedding=None)
            for i in range(3)
        ]

        mock_gateway, mock_session_factory = _make_mock_deps()
        mock_repo = AsyncMock()
        # list_missing_embeddings returns 3 rows on first call, [] on next page
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[null_rows, []])
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            await backfill_embeddings(batch_size=10)

        assert mock_gateway.embed.call_count == 3, (
            f"embed must be called 3 times (once per NULL row), "
            f"got {mock_gateway.embed.call_count}"
        )

    async def test_embed_args_are_body_text(self) -> None:
        """embed must be called with each row's body_text (non-empty body path)."""
        backfill_embeddings = _import_backfill_embeddings()

        body_texts = ["article alpha", "article beta", "article gamma"]
        null_rows = [
            _make_processed_content_mock(body_text=bt, embedding=None)
            for bt in body_texts
        ]

        mock_gateway, mock_session_factory = _make_mock_deps()
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[null_rows, []])
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            await backfill_embeddings(batch_size=10)

        actual_args = [c.args[0] for c in mock_gateway.embed.call_args_list]
        assert actual_args == body_texts, (
            f"embed call args must equal body_texts={body_texts}, got {actual_args}"
        )

    async def test_update_called_with_embedding_list(self) -> None:
        """repo.update must be called with embedding=<list[float], 1024-dim>."""
        backfill_embeddings = _import_backfill_embeddings()

        row_id = uuid.uuid4()
        null_row = _make_processed_content_mock(body_text="content", embedding=None)
        null_row.id = row_id

        mock_gateway, mock_session_factory = _make_mock_deps(
            embed_return_value=FAKE_EMBEDDING
        )
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[[null_row], []])
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            await backfill_embeddings(batch_size=10)

        mock_repo.update.assert_called_once()
        call_args = mock_repo.update.call_args
        # First positional arg must be the row's id
        assert call_args.args[0] == row_id or call_args.kwargs.get("id") == row_id, (
            f"update must be called with the row id={row_id}"
        )
        # embedding kwarg must be the exact list returned by embed
        embedding_kwarg = call_args.kwargs.get("embedding")
        assert embedding_kwarg == FAKE_EMBEDDING, (
            f"update(embedding=...) must equal the embed return value, "
            f"got {embedding_kwarg!r}"
        )
        assert len(embedding_kwarg) == EMBEDDING_DIM, (
            f"embedding must have {EMBEDDING_DIM} elements, got {len(embedding_kwarg)}"
        )

    async def test_non_null_rows_not_passed_to_embed(self) -> None:
        """Rows with existing embeddings must not be processed (idempotency).

        list_missing_embeddings only returns NULL rows by contract, so if the
        task correctly relies on that query, embed call count for a run where
        all queried rows are NULL must equal the count of those NULL rows.
        This test seeds only 1 NULL row to isolate the count.
        """
        backfill_embeddings = _import_backfill_embeddings()

        null_row = _make_processed_content_mock(body_text="new content", embedding=None)

        mock_gateway, mock_session_factory = _make_mock_deps()
        mock_repo = AsyncMock()
        # Only 1 NULL row: second page is empty
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[[null_row], []])
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            await backfill_embeddings(batch_size=10)

        assert mock_gateway.embed.call_count == 1, (
            f"embed must be called exactly once (only 1 NULL row), "
            f"got {mock_gateway.embed.call_count}"
        )


# ---------------------------------------------------------------------------
# AC-4 -- embed returns None: row stays NULL, task does not crash, log emitted
# ---------------------------------------------------------------------------


class TestBackfillEmbeddingsAC4:
    """AC-4: embed returns None -> row stays NULL, no crash, skip logged."""

    async def test_row_not_updated_when_embed_returns_none(self) -> None:
        """repo.update must NOT be called when embed returns None."""
        backfill_embeddings = _import_backfill_embeddings()

        null_row = _make_processed_content_mock(body_text="bad content", embedding=None)

        mock_gateway, mock_session_factory = _make_mock_deps(embed_side_effect=[None])
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[[null_row], []])
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            await backfill_embeddings(batch_size=10)

        mock_repo.update.assert_not_called()

    async def test_task_does_not_raise_when_embed_returns_none(self) -> None:
        """backfill_embeddings must complete without raising when embed returns None."""
        backfill_embeddings = _import_backfill_embeddings()

        null_row = _make_processed_content_mock(body_text="bad content", embedding=None)

        mock_gateway, mock_session_factory = _make_mock_deps(embed_side_effect=[None])
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[[null_row], []])
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            # Must not raise
            await backfill_embeddings(batch_size=10)

    async def test_skip_logged_when_embed_returns_none(self) -> None:
        """A structlog entry containing 'skipped' or 'embed_failed' must be emitted."""
        backfill_embeddings = _import_backfill_embeddings()

        null_row = _make_processed_content_mock(body_text="bad content", embedding=None)

        mock_gateway, mock_session_factory = _make_mock_deps(embed_side_effect=[None])
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[[null_row], []])
        mock_repo.update = AsyncMock(return_value=None)

        with structlog.testing.capture_logs() as captured:
            with (
                patch(
                    "intellisource.scheduler.tasks._get_backfill_deps",
                    return_value=(mock_gateway, mock_session_factory),
                ),
                patch(
                    "intellisource.scheduler.tasks._open_content_repo",
                    return_value=mock_repo,
                ),
            ):
                await backfill_embeddings(batch_size=10)

        skip_keywords = {"skipped", "embed_failed"}
        found = any(
            any(kw in str(entry).lower() for kw in skip_keywords) for entry in captured
        )
        assert found, (
            f"Expected a log entry containing 'skipped' or 'embed_failed' when "
            f"embed returns None. Captured logs: {captured}"
        )

    async def test_other_rows_still_backfilled_when_one_embed_returns_none(
        self,
    ) -> None:
        """Rows after a None-embed row must still be processed (no early exit)."""
        backfill_embeddings = _import_backfill_embeddings()

        rows = [
            _make_processed_content_mock(body_text="ok row 1", embedding=None),
            _make_processed_content_mock(body_text="fail row", embedding=None),
            _make_processed_content_mock(body_text="ok row 2", embedding=None),
        ]
        # embed returns None only for the middle row
        embed_results = [FAKE_EMBEDDING, None, FAKE_EMBEDDING]

        mock_gateway, mock_session_factory = _make_mock_deps(
            embed_side_effect=embed_results
        )
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[rows, []])
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            await backfill_embeddings(batch_size=10)

        # Only 2 successful embeds must result in 2 update calls
        assert mock_repo.update.call_count == 2, (
            f"repo.update must be called for the 2 rows with successful embeds, "
            f"got call_count={mock_repo.update.call_count}"
        )


# ---------------------------------------------------------------------------
# AC-6 -- body_text empty string -> fallback to title
# ---------------------------------------------------------------------------


class TestBackfillEmbeddingsAC6:
    """AC-6: body_text="" -> embed called with title; verified via call_args_list."""

    async def test_embed_uses_title_when_body_text_is_empty_string(self) -> None:
        """When body_text is '', embed must receive title, not ''."""
        backfill_embeddings = _import_backfill_embeddings()

        title_value = "Article Title Fallback"
        row = _make_processed_content_mock(
            body_text="", title=title_value, embedding=None
        )

        mock_gateway, mock_session_factory = _make_mock_deps()
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[[row], []])
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            await backfill_embeddings(batch_size=10)

        assert len(mock_gateway.embed.call_args_list) == 1, (
            f"embed must be called exactly once, "
            f"got {mock_gateway.embed.call_args_list}"
        )
        actual_text = mock_gateway.embed.call_args_list[0].args[0]
        assert actual_text == title_value, (
            f"embed must be called with title={title_value!r} when body_text='', "
            f"got {actual_text!r}"
        )

    async def test_embed_not_called_with_empty_string(self) -> None:
        """embed must never receive '' as its argument (empty string is invalid)."""
        backfill_embeddings = _import_backfill_embeddings()

        row = _make_processed_content_mock(
            body_text="", title="Valid Title", embedding=None
        )

        mock_gateway, mock_session_factory = _make_mock_deps()
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[[row], []])
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            await backfill_embeddings(batch_size=10)

        for c in mock_gateway.embed.call_args_list:
            text_arg = c.args[0] if c.args else c.kwargs.get("text", "")
            assert text_arg != "", f"embed must not be called with '' -- got call {c}"

    async def test_mixed_rows_body_text_and_title_fallback(self) -> None:
        """Mixed rows: non-empty body_text uses body_text; empty uses title fallback."""
        backfill_embeddings = _import_backfill_embeddings()

        row_with_body = _make_processed_content_mock(
            body_text="body content", title="Title A", embedding=None
        )
        row_with_empty_body = _make_processed_content_mock(
            body_text="", title="Title B", embedding=None
        )
        row_with_none_body = _make_processed_content_mock(
            body_text=None, title="Title C", embedding=None
        )

        mock_gateway, mock_session_factory = _make_mock_deps()
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(
            side_effect=[
                [row_with_body, row_with_empty_body, row_with_none_body],
                [],
            ]
        )
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            await backfill_embeddings(batch_size=10)

        call_args = [c.args[0] for c in mock_gateway.embed.call_args_list]
        assert call_args == ["body content", "Title B", "Title C"], (
            f"embed call args must be ['body content', 'Title B', 'Title C'], "
            f"got {call_args}"
        )


# ---------------------------------------------------------------------------
# AC-7 (OPTIONAL) -- Wrong embedding dimension: skip with warn log, no crash
# ---------------------------------------------------------------------------


class TestBackfillEmbeddingsAC7:
    """AC-7 (OPTIONAL): embed returns wrong-dimension vector -> skip + warn logged."""

    async def test_wrong_dimension_row_not_updated(self) -> None:
        """repo.update must NOT be called when embed returns wrong-dimension list."""
        backfill_embeddings = _import_backfill_embeddings()

        wrong_dim_embedding = [0.5] * 512  # wrong: 512 instead of 1024
        row = _make_processed_content_mock(body_text="content", embedding=None)

        mock_gateway, mock_session_factory = _make_mock_deps(
            embed_return_value=wrong_dim_embedding
        )
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[[row], []])
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            await backfill_embeddings(batch_size=10)

        mock_repo.update.assert_not_called()

    async def test_wrong_dimension_task_does_not_raise(self) -> None:
        """backfill_embeddings must not raise when embed returns wrong-dim vector."""
        backfill_embeddings = _import_backfill_embeddings()

        wrong_dim_embedding = [0.5] * 512
        row = _make_processed_content_mock(body_text="content", embedding=None)

        mock_gateway, mock_session_factory = _make_mock_deps(
            embed_return_value=wrong_dim_embedding
        )
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[[row], []])
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            await backfill_embeddings(batch_size=10)

    async def test_wrong_dimension_warn_logged(self) -> None:
        """A structlog warning containing dimension info must be emitted."""
        backfill_embeddings = _import_backfill_embeddings()

        wrong_dim_embedding = [0.5] * 512
        row = _make_processed_content_mock(body_text="content", embedding=None)

        mock_gateway, mock_session_factory = _make_mock_deps(
            embed_return_value=wrong_dim_embedding
        )
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=[[row], []])
        mock_repo.update = AsyncMock(return_value=None)

        with structlog.testing.capture_logs() as captured:
            with (
                patch(
                    "intellisource.scheduler.tasks._get_backfill_deps",
                    return_value=(mock_gateway, mock_session_factory),
                ),
                patch(
                    "intellisource.scheduler.tasks._open_content_repo",
                    return_value=mock_repo,
                ),
            ):
                await backfill_embeddings(batch_size=10)

        dim_keywords = {"dimension", "dim", "1024", "512", "wrong"}
        found = any(
            any(kw in str(entry).lower() for kw in dim_keywords) for entry in captured
        )
        assert found, (
            f"Expected a log warning about dimension mismatch. "
            f"Captured logs: {captured}"
        )

    async def test_correct_dimension_rows_still_backfilled_alongside_wrong(
        self,
    ) -> None:
        """Correct-dim rows must succeed even when another row is wrong-dim."""
        backfill_embeddings = _import_backfill_embeddings()

        row_ok = _make_processed_content_mock(body_text="good content", embedding=None)
        row_bad = _make_processed_content_mock(body_text="bad content", embedding=None)

        embed_results = [FAKE_EMBEDDING, [0.5] * 512]  # ok, then wrong-dim

        mock_gateway, mock_session_factory = _make_mock_deps(
            embed_side_effect=embed_results
        )
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(
            side_effect=[[row_ok, row_bad], []]
        )
        mock_repo.update = AsyncMock(return_value=None)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            await backfill_embeddings(batch_size=10)

        # Only the correct-dim row must be updated
        assert mock_repo.update.call_count == 1, (
            f"Only the correct-dimension row must trigger update, "
            f"got call_count={mock_repo.update.call_count}"
        )


# ---------------------------------------------------------------------------
# R-005 -- Stateful pagination: no row is skipped due to offset mis-advance
# ---------------------------------------------------------------------------


class TestBackfillPaginationStateful:
    """R-005: Multi-page stateful mock verifies all backfillable rows are updated.

    The mock models the real DB: rows that get update() called are removed from
    the IS-NULL set; permanently-skip rows (embed returns None) stay in IS-NULL
    and must be stepped over by offset, not re-fetched infinitely.

    Setup: 6 rows, batch_size=2.
      - rows 0, 1, 3, 5 : embeddable (embed returns FAKE_EMBEDDING)
      - rows 2, 4        : permanent-skip (embed returns None)

    Correct algorithm (skip-count offset):
      Batch 1 (offset=0): rows 0,1 — both filled → offset stays 0
      Batch 2 (offset=0): rows 2,3 — row2 skip(+1), row3 filled → offset=1
      Batch 3 (offset=1): rows 4,5 — row4 skip(+1), row5 filled → offset=2
      Batch 4 (offset=2): [] — done
      update called 4 times (rows 0,1,3,5); embed called 6 times total.

    Buggy algorithm (offset += batch_size):
      Batch 1 (offset=0): rows 0,1 — filled → offset=2
      Batch 2 (offset=2): rows 4,5 — (rows 2/3 now skip 2 in IS-NULL set) → offset=4
      Batch 3 (offset=4): [] — done
      update called 4 or fewer times but rows 2/3 never visited → FAIL assertion.
    """

    async def test_all_backfillable_rows_updated_across_pages(self) -> None:
        """All 4 embeddable rows must be updated; 2 permanent-skip rows not updated."""
        backfill_embeddings = _import_backfill_embeddings()

        # Build 6 rows: indices 0-5
        all_rows = [
            _make_processed_content_mock(body_text=f"body {i}", embedding=None)
            for i in range(6)
        ]
        # Indices 2 and 4 are permanent-skip (embed returns None)
        permanent_skip_indices = {2, 4}
        embeddable_ids = {
            all_rows[i].id for i in range(6) if i not in permanent_skip_indices
        }

        # Stateful tracking: set of row indices still in IS-NULL set
        null_set: list[int] = list(range(6))  # initially all rows are NULL

        def _stateful_list(batch_size: int, offset: int) -> list:
            """Return rows from current IS-NULL set at [offset:offset+batch_size]."""
            page = null_set[offset : offset + batch_size]
            return [all_rows[i] for i in page]

        async def _mock_list(batch_size: int, offset: int) -> list:
            return _stateful_list(batch_size, offset)

        async def _mock_update(row_id: object, *, embedding: object = None) -> None:
            # Mark the row as filled: remove from null_set
            for i, idx in enumerate(null_set):
                if all_rows[idx].id == row_id:
                    null_set.pop(i)
                    break

        mock_gateway = MagicMock()

        async def _mock_embed(text: str) -> list[float] | None:
            # Determine which row this call is for (match by body_text)
            for i, row in enumerate(all_rows):
                if (row.body_text or "").strip() == text:
                    if i in permanent_skip_indices:
                        return None
                    return FAKE_EMBEDDING
            return FAKE_EMBEDDING  # fallback

        mock_gateway.embed = AsyncMock(side_effect=_mock_embed)

        mock_session_factory = MagicMock()
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=_mock_list)
        mock_repo.update = AsyncMock(side_effect=_mock_update)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            result = await backfill_embeddings(batch_size=2)

        # All 4 embeddable rows must have been updated
        updated_ids = {call.args[0] for call in mock_repo.update.call_args_list}
        assert updated_ids == embeddable_ids, (
            f"Expected update calls for rows {embeddable_ids}, "
            f"got {updated_ids}. "
            "Rows were skipped — pagination offset is mis-advancing past "
            "NULL rows that remain after backfilling."
        )
        assert result["backfilled"] == 4, (
            f"Expected backfilled=4, got {result['backfilled']}"
        )
        assert result["skipped"] == 2, (
            f"Expected skipped=2 (permanent-skip rows), got {result['skipped']}"
        )

    async def test_embed_called_finite_times_with_permanent_skip_rows(self) -> None:
        """Loop must terminate; embed called exactly once per row."""
        backfill_embeddings = _import_backfill_embeddings()

        # 4 rows: rows 0,2 are embeddable; rows 1,3 are permanent-skip
        all_rows = [
            _make_processed_content_mock(body_text=f"body {i}", embedding=None)
            for i in range(4)
        ]
        permanent_skip_indices = {1, 3}
        null_set: list[int] = list(range(4))

        async def _mock_list(batch_size: int, offset: int) -> list:
            page = null_set[offset : offset + batch_size]
            return [all_rows[i] for i in page]

        async def _mock_update(row_id: object, *, embedding: object = None) -> None:
            for i, idx in enumerate(null_set):
                if all_rows[idx].id == row_id:
                    null_set.pop(i)
                    break

        mock_gateway = MagicMock()

        async def _mock_embed(text: str) -> list[float] | None:
            for i, row in enumerate(all_rows):
                if (row.body_text or "").strip() == text:
                    return None if i in permanent_skip_indices else FAKE_EMBEDDING
            return FAKE_EMBEDDING

        mock_gateway.embed = AsyncMock(side_effect=_mock_embed)
        mock_session_factory = MagicMock()
        mock_repo = AsyncMock()
        mock_repo.list_missing_embeddings = AsyncMock(side_effect=_mock_list)
        mock_repo.update = AsyncMock(side_effect=_mock_update)

        with (
            patch(
                "intellisource.scheduler.tasks._get_backfill_deps",
                return_value=(mock_gateway, mock_session_factory),
            ),
            patch(
                "intellisource.scheduler.tasks._open_content_repo",
                return_value=mock_repo,
            ),
        ):
            # wait_for guard: if a regression reintroduces the infinite loop
            # (re-fetching permanent-skip rows), fail fast instead of hanging
            # the whole suite.
            result = await asyncio.wait_for(
                backfill_embeddings(batch_size=2), timeout=5.0
            )

        # embed must be called exactly 4 times (once per row, no re-tries)
        assert mock_gateway.embed.call_count == 4, (
            f"Expected embed called 4 times (once per row), "
            f"got {mock_gateway.embed.call_count}. "
            "Loop may be cycling permanently-skip rows."
        )
        assert result["backfilled"] == 2
        assert result["skipped"] == 2
