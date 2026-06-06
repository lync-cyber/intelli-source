"""Tests for F-17 (fan-out), F-18 (to_thread), F-19 (DTO) fixes."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_deps(
    *,
    pipeline_engine: Any = None,
    session_factory: Any = None,
    distributor: Any = None,
) -> Any:
    from intellisource.agent.deps import ToolDeps  # type: ignore[import]

    return ToolDeps(
        session_factory=session_factory or MagicMock(),
        llm_gateway=AsyncMock(),
        pipeline_engine=pipeline_engine or MagicMock(),
        search_engine_factory=MagicMock(),
        collector_registry=MagicMock(),
        distributor=distributor or AsyncMock(),
    )


# ---------------------------------------------------------------------------
# F-17: collect returns raw_content_ids list + is_batch
# ---------------------------------------------------------------------------


class TestCollectReturnsBatch:
    """F-17: _collect_execute returns raw_content_ids list and is_batch flag."""

    @pytest.mark.asyncio
    async def test_collect_returns_raw_content_ids_list(self) -> None:
        """_collect_execute always returns raw_content_ids as list, is_batch=True."""
        from intellisource.agent.tools import (
            _collect_execute,  # type: ignore[attr-defined]
        )
        from intellisource.collector.base import RawContent as CollectedRaw

        item1 = CollectedRaw(
            source_url="http://a.com",
            fingerprint="fp1",
            title="T1",
            author=None,
            body_html=None,
            body_text="b1",
            published_at=None,
            raw_metadata={},
        )
        item2 = CollectedRaw(
            source_url="http://b.com",
            fingerprint="fp2",
            title="T2",
            author=None,
            body_html=None,
            body_text="b2",
            published_at=None,
            raw_metadata={},
        )

        collector_mock = AsyncMock()
        collector_mock.collect_with_retry = AsyncMock(return_value=[item1, item2])
        registry_mock = MagicMock()
        registry_mock.get = MagicMock(return_value=collector_mock)

        tool_deps = _make_tool_deps()
        tool_deps = MagicMock()
        tool_deps.collector_registry = registry_mock
        tool_deps.session_factory = None  # skip DB path

        result = await _collect_execute(
            source_id="sid",
            source_type="rss",
            tool_deps=tool_deps,
        )

        assert result["status"] == "ok"
        assert isinstance(result["raw_content_ids"], list)
        assert result["is_batch"] is True
        # content_id backward compat: None when no DB path
        assert "content_id" in result


# ---------------------------------------------------------------------------
# F-17: process fans-out over raw_content_ids list
# ---------------------------------------------------------------------------


class TestProcessFansOut:
    """F-17: _process_execute iterates over raw_content_ids list."""

    @pytest.mark.asyncio
    async def test_process_fans_out_over_list(self) -> None:
        """raw_content_ids list with 2 items fans-out and collects processed ids."""
        from intellisource.agent.tools import (
            _process_execute,  # type: ignore[attr-defined]
        )
        from intellisource.core.processor import PipelineContext

        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        proc_id1 = str(uuid.uuid4())
        proc_id2 = str(uuid.uuid4())

        raw1 = MagicMock()
        raw1.id = uuid.UUID(id1)
        raw1.body_html = "h1"
        raw1.body_text = "b1"
        raw1.title = "T1"
        raw1.fingerprint = "fp1"
        raw1.source_url = "http://a.com"

        raw2 = MagicMock()
        raw2.id = uuid.UUID(id2)
        raw2.body_html = "h2"
        raw2.body_text = "b2"
        raw2.title = "T2"
        raw2.fingerprint = "fp2"
        raw2.source_url = "http://b.com"

        processed1 = MagicMock()
        processed1.id = uuid.UUID(proc_id1)

        processed2 = MagicMock()
        processed2.id = uuid.UUID(proc_id2)

        raws = {uuid.UUID(id1): raw1, uuid.UUID(id2): raw2}
        processed_map = {uuid.UUID(id1): processed1, uuid.UUID(id2): processed2}

        repo_mock = AsyncMock()
        repo_mock.get_raw_by_id = AsyncMock(side_effect=lambda rid: raws.get(rid))
        repo_mock.get_processed_by_raw_id = AsyncMock(return_value=None)
        repo_mock.create = AsyncMock(
            side_effect=lambda **kw: processed_map[kw["raw_content_id"]]
        )

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=False)
        session_mock.commit = AsyncMock()

        session_factory = MagicMock(return_value=session_mock)

        ctx_out = PipelineContext()
        ctx_out.set("tags", ["t1"])
        ctx_out.set("title", "processed-title")
        ctx_out.set("body_text", "processed-body")
        ctx_out.set("fingerprint", "fp-processed")
        ctx_out.set("body_html", "")

        engine_mock = MagicMock()
        engine_mock.execute = MagicMock(return_value=ctx_out)

        tool_deps = MagicMock()
        tool_deps.pipeline_engine = engine_mock
        tool_deps.session_factory = session_factory

        with patch(
            "intellisource.storage.repositories.content.ContentRepository",
            return_value=repo_mock,
        ):
            result = await _process_execute(
                raw_content_ids=[id1, id2],
                tool_deps=tool_deps,
            )

        assert result["status"] == "ok"
        assert isinstance(result["processed_content_ids"], list)
        assert len(result["processed_content_ids"]) == 2
        assert proc_id1 in result["processed_content_ids"]
        assert proc_id2 in result["processed_content_ids"]


# ---------------------------------------------------------------------------
# F-17: distribute fans-out over processed_content_ids list
# ---------------------------------------------------------------------------


class TestDistributeFansOut:
    """F-17: _distribute_execute iterates over processed_content_ids list."""

    @pytest.mark.asyncio
    async def test_distribute_fans_out_over_processed_list(self) -> None:
        """When processed_content_ids has 2 items, distribute is called twice."""
        from intellisource.agent.tools import (
            _distribute_execute,  # type: ignore[attr-defined]
        )

        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        sub_id = str(uuid.uuid4())

        distributor_mock = AsyncMock()
        distributor_mock.distribute = AsyncMock(return_value={"sent": True})

        tool_deps = MagicMock()
        tool_deps.distributor = distributor_mock

        result = await _distribute_execute(
            processed_content_ids=[id1, id2],
            subscription_id=sub_id,
            tool_deps=tool_deps,
        )

        assert result["status"] == "ok"
        assert distributor_mock.distribute.call_count == 2
        called_ids = {
            call.kwargs["content_id"]
            for call in distributor_mock.distribute.call_args_list
        }
        assert called_ids == {id1, id2}


# ---------------------------------------------------------------------------
# F-18: async tool wraps pipeline_engine.execute in asyncio.to_thread
# ---------------------------------------------------------------------------


class TestAsyncToolUsesToThread:
    """F-18: _process_execute uses asyncio.to_thread for synchronous engine.execute."""

    @pytest.mark.asyncio
    async def test_async_tool_uses_to_thread_for_engine_execute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pipeline_engine.execute is called via asyncio.to_thread, not directly."""
        import intellisource.agent.tools as tools_mod
        from intellisource.core.processor import PipelineContext

        cid = str(uuid.uuid4())
        proc_id = str(uuid.uuid4())

        raw = MagicMock()
        raw.id = uuid.UUID(cid)
        raw.body_html = ""
        raw.body_text = "text"
        raw.title = "T"
        raw.fingerprint = "fp"
        raw.source_url = "http://x.com"

        processed = MagicMock()
        processed.id = uuid.UUID(proc_id)

        repo_mock = AsyncMock()
        repo_mock.get_raw_by_id = AsyncMock(return_value=raw)
        repo_mock.get_processed_by_raw_id = AsyncMock(return_value=None)
        repo_mock.create = AsyncMock(return_value=processed)

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=False)
        session_mock.commit = AsyncMock()
        session_factory = MagicMock(return_value=session_mock)

        ctx_out = PipelineContext()
        ctx_out.set("tags", [])
        ctx_out.set("title", "T")
        ctx_out.set("body_text", "text")
        ctx_out.set("fingerprint", "fp")
        ctx_out.set("body_html", "")

        engine_mock = MagicMock()
        engine_mock.execute = MagicMock(return_value=ctx_out)

        to_thread_calls: list[tuple[Any, ...]] = []
        original_to_thread = asyncio.to_thread

        async def recording_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
            to_thread_calls.append((func,) + args)
            return await original_to_thread(func, *args, **kwargs)

        from intellisource.agent.tools.executes import (  # noqa: PLC0415
            process as process_mod,
        )

        monkeypatch.setattr(process_mod.asyncio, "to_thread", recording_to_thread)

        tool_deps = MagicMock()
        tool_deps.pipeline_engine = engine_mock
        tool_deps.session_factory = session_factory

        with patch(
            "intellisource.storage.repositories.content.ContentRepository",
            return_value=repo_mock,
        ):
            result = await tools_mod._process_execute(  # type: ignore[attr-defined]
                content_id=cid,
                tool_deps=tool_deps,
            )

        assert result["status"] == "ok"
        assert any(engine_mock.execute in call for call in to_thread_calls), (
            "pipeline_engine.execute was not invoked via asyncio.to_thread"
        )


# ---------------------------------------------------------------------------
# F-19: get_content_detail returns DTO dict, not ORM instance
# ---------------------------------------------------------------------------


class TestGetContentReturnsDTO:
    """F-19: _get_content_detail_execute returns serializable dict, not ORM object."""

    @pytest.mark.asyncio
    async def test_get_content_returns_dto_dict_not_orm(self) -> None:
        """content field in response is a plain dict with 'id', not an ORM object."""
        from intellisource.agent.tools import (
            _get_content_detail_execute,  # type: ignore[attr-defined]
        )

        proc_id = str(uuid.uuid4())
        raw_id = str(uuid.uuid4())

        orm_content = MagicMock()
        orm_content.id = proc_id
        orm_content.raw_content_id = raw_id
        orm_content.title = "Test Title"
        orm_content.body_text = "body"
        orm_content.summary = None
        orm_content.tags = []
        orm_content.fingerprint = "fp-abc"
        orm_content.source_url = "http://example.com"
        orm_content.created_at = None

        repo_mock = AsyncMock()
        repo_mock.get_by_id = AsyncMock(return_value=orm_content)

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=False)
        session_factory = MagicMock(return_value=session_mock)

        tool_deps = MagicMock()
        tool_deps.session_factory = session_factory

        with patch(
            "intellisource.storage.repositories.content.ContentRepository",
            return_value=repo_mock,
        ):
            result = await _get_content_detail_execute(
                content_id=proc_id,
                tool_deps=tool_deps,
            )

        assert result["status"] == "ok"
        content = result["content"]
        # Must be a plain dict, not an ORM instance
        assert isinstance(content, dict), f"Expected dict, got {type(content)}"
        assert "id" in content
        # Must be JSON-serializable (no ORM objects)
        import json

        json.dumps(content)  # raises TypeError if not serializable
