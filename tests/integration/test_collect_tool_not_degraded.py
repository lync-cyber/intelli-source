"""Integration test for AC-6 — T-097 RED phase.

AC-6: With build_worker_composition injecting a complete ToolDeps (including a
real CollectorRegistry), calling _collect_execute(source_id, source_type='rss',
tool_deps=deps) must return status='ok' with a non-empty collected list.  The
result must NOT contain 'degraded'.

These tests are expected to FAIL in RED phase because:
- _collect_execute currently calls collector.collect(source_id=source_id, **kwargs)
  where source_id is a plain string UUID.
- RSSCollector.collect(source_config: dict) expects a dict with at least a 'url'
  key — passing a raw UUID string causes a TypeError or returns an empty list.
- After T-097 GREEN lands, _collect_execute will look up the Source row in DB
  using source_id, build a source_config dict from it, and call
  collector.collect(source_config=source_config) to return real items.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from intellisource.agent.deps import ToolDeps
from intellisource.agent.tools import _collect_execute
from intellisource.collector.base import BaseCollector, RawContent
from intellisource.composition import build_collector_registry

# ---------------------------------------------------------------------------
# Minimal RSS feed XML returned by mock conditional_fetch
# ---------------------------------------------------------------------------

_MOCK_RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://feeds.example.com/rss</link>
    <description>Test RSS feed</description>
    <item>
      <title>Test Article</title>
      <link>https://feeds.example.com/articles/1</link>
      <description>Test article body text</description>
    </item>
  </channel>
</rss>"""


def _make_mock_rss_response() -> httpx.Response:
    """Return a minimal httpx.Response carrying RSS XML content."""
    return httpx.Response(200, content=_MOCK_RSS_XML)


def _make_mock_session_factory_for_collector(source_url: str) -> Any:
    """Return an asynccontextmanager session_factory that yields a mock Source row."""
    mock_source = MagicMock()
    mock_source.url = source_url
    mock_source.proxy = None
    mock_source.rate_limit_qps = None
    mock_source.rate_limit_concurrency = None
    mock_source.metadata_ = {}

    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_source)
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_execute_result)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    @asynccontextmanager
    async def _session_factory() -> AsyncIterator[Any]:
        yield mock_session

    return _session_factory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_deps_with_registry(session_factory: object = None) -> ToolDeps:
    """Build ToolDeps with a real CollectorRegistry and a mock session_factory."""
    if session_factory is None:
        session_factory = _make_mock_session_factory_for_collector(
            "https://feeds.example.com/rss"
        )
    return ToolDeps(
        session_factory=session_factory,
        llm_gateway=None,
        pipeline_engine=None,
        search_engine_factory=None,
        collector_registry=build_collector_registry(),
        distributor=None,
    )


def _make_raw_content_fixture(source_id_str: str) -> RawContent:
    """Minimal RawContent object returned from a mock feed fetch."""
    return RawContent(
        source_url=f"https://example.com/articles/{source_id_str[:8]}",
        fingerprint=uuid.uuid4().hex,
        title="Test RSS item",
        author=None,
        body_html="<p>Hello world</p>",
        body_text="Hello world",
        published_at=None,
    )


# ---------------------------------------------------------------------------
# AC-6: tests that verify real DB-backed source_config wiring
# ---------------------------------------------------------------------------


class TestCollectToolNotDegraded:
    """AC-6: _collect_execute with a real DB-backed source_config returns ok."""

    async def test_collect_execute_with_source_config_dict_returns_ok(self) -> None:
        """_collect_execute must resolve source_id to a source_config dict and
        pass it to collector.collect(), returning status='ok'.

        RED failure: current implementation passes source_id string directly to
        collect(source_id=...) but RSSCollector.collect expects source_config dict.
        When the real collect() is called with a string instead of dict, it returns
        [] (empty) or raises — either way collected is empty, which fails the assertion.
        """
        source_id = str(uuid.uuid4())
        tool_deps = _make_tool_deps_with_registry()

        # Do NOT mock collector.collect — we want the real routing to run.
        # Mock conditional_fetch at the HTTP transport layer so no real network
        # connection is attempted while still exercising the full collect() path.
        mock_fetch = AsyncMock(return_value=_make_mock_rss_response())
        with patch.object(BaseCollector, "conditional_fetch", new=mock_fetch):
            result = await _collect_execute(
                source_id=source_id,
                source_type="rss",
                tool_deps=tool_deps,
            )

        # After T-097: status should be 'ok' with real items from DB-backed source.
        assert result["status"] == "ok", (
            f"_collect_execute must return status='ok' when registry is wired; "
            f"got {result['status']!r}. T-097 must wire source_config from DB."
        )
        collected = result.get("collected", [])
        assert len(collected) >= 1, (
            f"_collect_execute must return at least 1 item when source is RSS; "
            f"got {len(collected)}. T-097 must fetch real feed data."
        )

    async def test_collect_execute_result_not_degraded_when_registry_wired(
        self,
    ) -> None:
        """Result must not carry status='degraded' when collector_registry is present.

        RED failure: because the current _collect_execute passes source_id string
        to collect(), the collector returns [] — the test verifies the collected
        list is non-empty (which will fail), proving T-097 wiring is incomplete.
        """
        source_id = str(uuid.uuid4())
        tool_deps = _make_tool_deps_with_registry()

        mock_fetch = AsyncMock(return_value=_make_mock_rss_response())
        with patch.object(BaseCollector, "conditional_fetch", new=mock_fetch):
            result = await _collect_execute(
                source_id=source_id,
                source_type="rss",
                tool_deps=tool_deps,
            )

        # Primary assertion: not degraded when registry is wired.
        assert result.get("status") != "degraded", (
            "Result must not be 'degraded' when tool_deps.collector_registry is set. "
            "If degraded, the wiring in _collect_execute is broken."
        )

        # Secondary assertion: collected list must be non-empty.
        collected = result.get("collected", [])
        assert len(collected) >= 1, (
            f"collected list is empty (got {collected!r}) even though registry "
            "is wired — T-097 must build source_config from DB before calling collect()"
        )

    async def test_collect_execute_passes_url_to_rss_collector(self) -> None:
        """_collect_execute must pass a source_config dict with 'url' to RSSCollector.

        RED failure: current code passes source_id (string UUID) as keyword arg
        to collect(). RSSCollector.collect(source_config: dict) gets called with
        a dict-incompatible argument, so source_config.get('url') returns None
        and collect() returns [].
        """
        from intellisource.collector.adapters.rss import RSSCollector

        source_id = str(uuid.uuid4())
        tool_deps = _make_tool_deps_with_registry()

        received_kwargs: list[dict[str, object]] = []

        async def _spy_collect(
            self_: object, source_config: object = None, **kwargs: object
        ) -> list[object]:
            # collect_with_retry forwards source_config positionally to collect();
            # capture it alongside any kwargs so the assertions below see it.
            received_kwargs.append({"source_config": source_config, **kwargs})
            return [_make_raw_content_fixture(source_id)]

        with patch.object(RSSCollector, "collect", new=_spy_collect):
            await _collect_execute(
                source_id=source_id,
                source_type="rss",
                tool_deps=tool_deps,
            )

        assert len(received_kwargs) == 1, (
            "RSSCollector.collect must be called exactly once"
        )
        captured = received_kwargs[0]
        # After T-097: collect(source_config={"url": ..., ...}).
        # Before T-097: collect(source_id=<uuid_str>) — no 'url' key.
        assert "source_config" in captured, (
            f"_collect_execute must pass source_config={{...}} to collect(); "
            f"got kwargs keys: {list(captured.keys())}. "
            "T-097 must fetch the Source row from DB and build source_config dict."
        )
        sc = captured["source_config"]
        assert isinstance(sc, dict) and "url" in sc, (
            f"source_config must be a dict with 'url' key; got {sc!r}"
        )

    async def test_collect_execute_null_tool_deps_is_degraded_control(self) -> None:
        """Control case: tool_deps=None always returns status='degraded'."""
        result = await _collect_execute(
            source_id=str(uuid.uuid4()),
            source_type="rss",
            tool_deps=None,
        )
        assert result["status"] == "degraded", (
            "With tool_deps=None the result must be 'degraded' (sanity control)"
        )

    async def test_collect_execute_source_type_api_returns_ok(self) -> None:
        """_collect_execute(source_type='api') also returns ok when source is wired.

        RED failure: same issue as RSS — source_config dict not built from DB.
        """
        from intellisource.collector.adapters.api import APICollector

        source_id = str(uuid.uuid4())
        tool_deps = _make_tool_deps_with_registry()

        received: list[dict[str, object]] = []

        async def _spy_api_collect(
            self_: object, source_config: object = None, **kwargs: object
        ) -> list[object]:
            # collect_with_retry forwards source_config positionally to collect();
            # capture it alongside any kwargs so the assertions below see it.
            received.append({"source_config": source_config, **kwargs})
            return [_make_raw_content_fixture(source_id)]

        with patch.object(APICollector, "collect", new=_spy_api_collect):
            result = await _collect_execute(
                source_id=source_id,
                source_type="api",
                tool_deps=tool_deps,
            )

        assert result["status"] == "ok", (
            f"Expected status='ok' for api source_type when spy collect returns items, "
            f"got {result['status']!r}"
        )
        # The kwargs dict captured by spy must include source_config (not source_id).
        assert len(received) == 1, "APICollector.collect must be called exactly once"
        received_kwargs = received[0]
        assert "source_config" in received_kwargs, (
            f"APICollector.collect must be called with source_config kwarg; "
            f"got keys: {list(received_kwargs.keys()) if received_kwargs else []}. "
            "T-097 must build source_config dict from the DB Source row."
        )

    async def test_collect_execute_unregistered_source_type_returns_degraded(
        self,
    ) -> None:
        """Anti-regression (R-005): unregistered source_type must return degraded,
        not raise CollectorError."""
        tool_deps = _make_tool_deps_with_registry()
        result = await _collect_execute(
            source_id=str(uuid.uuid4()),
            source_type="nonexistent_type_xyz",
            tool_deps=tool_deps,
        )
        assert result["status"] == "degraded", (
            f"_collect_execute with unknown source_type must return status='degraded'; "
            f"got {result['status']!r}. R-005: CollectorError must be caught."
        )
        assert "unknown source_type" in result.get("reason", ""), (
            f"degraded reason must mention 'unknown source_type'; "
            f"got reason={result.get('reason')!r}"
        )
