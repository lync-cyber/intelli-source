"""Tests for BaseCollector abstract base class and RawContent data model.

Covers:
- AC-005: BaseCollector defines collect(source_config) -> list[RawContent]
- AC-T010-4: Output conforms to unified data model
- AC-T010-7: Built-in HTTP conditional request support (ETag / If-Modified-Since)
"""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from intellisource.collector.base import BaseCollector, RawContent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubCollector(BaseCollector):
    """Minimal concrete subclass used for testing the ABC contract."""

    async def collect(self, source_config: dict) -> list[RawContent]:
        return [
            RawContent(
                title="Test Article",
                author="tester",
                body_html="<p>hello</p>",
                body_text="hello",
                source_url="https://example.com/1",
                published_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                fingerprint="a" * 64,
                raw_metadata={"key": "value"},
            )
        ]


# ===================================================================
# AC-005: BaseCollector defines collect(source_config) -> list[RawContent]
# ===================================================================


class TestBaseCollectorInterface:
    """Verify BaseCollector is an ABC with the correct abstract interface."""

    def test_base_collector_is_abstract(self):
        """BaseCollector cannot be instantiated directly."""
        assert issubclass(BaseCollector, abc.ABC)
        with pytest.raises(TypeError):
            BaseCollector()  # type: ignore[abstract]

    def test_collect_is_abstract_method(self):
        """The `collect` method must be declared abstract."""
        assert "collect" in getattr(BaseCollector, "__abstractmethods__", set())

    @pytest.mark.asyncio
    async def test_collect_returns_list_of_raw_content(self):
        """A concrete subclass's collect() returns list[RawContent]."""
        collector = _StubCollector()
        result = await collector.collect({"url": "https://example.com/feed"})
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], RawContent)


# ===================================================================
# AC-T010-4: Output conforms to unified data model
# ===================================================================


class TestRawContentModel:
    """Verify RawContent has all required fields with correct semantics."""

    def test_required_field_source_url(self):
        """source_url is mandatory (NOT NULL in schema)."""
        rc = RawContent(
            source_url="https://example.com/article",
            fingerprint="b" * 64,
        )
        assert rc.source_url == "https://example.com/article"

    def test_required_field_fingerprint(self):
        """fingerprint is mandatory (NOT NULL, UNIQUE in schema)."""
        rc = RawContent(
            source_url="https://example.com/article",
            fingerprint="c" * 64,
        )
        assert rc.fingerprint == "c" * 64

    def test_optional_fields_default_to_none(self):
        """Optional fields (title, author, body_html, body_text,
        published_at) default to None."""
        rc = RawContent(
            source_url="https://example.com/article",
            fingerprint="d" * 64,
        )
        assert rc.title is None
        assert rc.author is None
        assert rc.body_html is None
        assert rc.body_text is None
        assert rc.published_at is None

    def test_raw_metadata_defaults_to_empty_dict(self):
        """raw_metadata defaults to an empty dict (DEFAULT '{}')."""
        rc = RawContent(
            source_url="https://example.com/article",
            fingerprint="e" * 64,
        )
        assert rc.raw_metadata == {}

    def test_all_fields_populated(self):
        """All fields can be set explicitly."""
        now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        rc = RawContent(
            title="Full Article",
            author="Author Name",
            body_html="<p>content</p>",
            body_text="content",
            source_url="https://example.com/full",
            published_at=now,
            fingerprint="f" * 64,
            raw_metadata={"tag": "science"},
        )
        assert rc.title == "Full Article"
        assert rc.author == "Author Name"
        assert rc.body_html == "<p>content</p>"
        assert rc.body_text == "content"
        assert rc.source_url == "https://example.com/full"
        assert rc.published_at == now
        assert rc.fingerprint == "f" * 64
        assert rc.raw_metadata == {"tag": "science"}

    def test_source_url_is_required_validation(self):
        """Constructing RawContent without source_url should raise."""
        with pytest.raises((TypeError, ValueError)):
            RawContent(fingerprint="g" * 64)  # type: ignore[call-arg]

    def test_fingerprint_is_required_validation(self):
        """Constructing RawContent without fingerprint should raise."""
        with pytest.raises((TypeError, ValueError)):
            RawContent(source_url="https://example.com/x")  # type: ignore[call-arg]


# ===================================================================
# AC-T010-7: Built-in HTTP conditional request support
# ===================================================================


class TestConditionalFetch:
    """Verify BaseCollector.conditional_fetch handles ETag and
    If-Modified-Since headers, and correctly interprets 304 responses."""

    @pytest.mark.asyncio
    async def test_conditional_fetch_sets_if_none_match_header(self):
        """When etag is provided, the request includes If-None-Match."""
        collector = _StubCollector()
        mock_response = httpx.Response(
            status_code=200,
            content=b"<html>data</html>",
            headers={"ETag": '"new-etag"'},
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            result = await collector.conditional_fetch(
                url="https://example.com/feed",
                etag='"old-etag"',
            )

        # Verify the If-None-Match header was sent
        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("If-None-Match") == '"old-etag"'
        assert result is not None
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_conditional_fetch_sets_if_modified_since_header(self):
        """When last_modified is provided, the request includes
        If-Modified-Since."""
        collector = _StubCollector()
        mock_response = httpx.Response(
            status_code=200,
            content=b"<html>data</html>",
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            await collector.conditional_fetch(
                url="https://example.com/feed",
                last_modified="Wed, 01 Jan 2025 00:00:00 GMT",
            )

        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("If-Modified-Since") == "Wed, 01 Jan 2025 00:00:00 GMT"

    @pytest.mark.asyncio
    async def test_conditional_fetch_both_headers(self):
        """When both etag and last_modified are provided, both headers
        are set."""
        collector = _StubCollector()
        mock_response = httpx.Response(status_code=200, content=b"data")

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            await collector.conditional_fetch(
                url="https://example.com/feed",
                etag='"some-etag"',
                last_modified="Wed, 01 Jan 2025 00:00:00 GMT",
            )

        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("If-None-Match") == '"some-etag"'
        assert headers.get("If-Modified-Since") == "Wed, 01 Jan 2025 00:00:00 GMT"

    @pytest.mark.asyncio
    async def test_conditional_fetch_returns_none_on_304(self):
        """A 304 Not Modified response means content has not changed;
        conditional_fetch should return None."""
        collector = _StubCollector()
        mock_response = httpx.Response(status_code=304, content=b"")

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            result = await collector.conditional_fetch(
                url="https://example.com/feed",
                etag='"cached-etag"',
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_conditional_fetch_without_cache_headers(self):
        """When neither etag nor last_modified is provided, a normal
        GET request is made (no conditional headers)."""
        collector = _StubCollector()
        mock_response = httpx.Response(status_code=200, content=b"fresh")

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            result = await collector.conditional_fetch(
                url="https://example.com/feed",
            )

        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert "If-None-Match" not in headers
        assert "If-Modified-Since" not in headers
        assert isinstance(result, httpx.Response)
        assert result.status_code == 200
