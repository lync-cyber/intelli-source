"""Tests for RSSCollector adapter.

Covers:
- AC-006: RSSCollector correctly parses RSS 2.0 and Atom 1.0 formats
- AC-007: RawContent contains title/author/body_html/body_text/source_url/published_at
- AC-008: RSSHub URL works as a source (same RSS logic)
- AC-T011-1: Parse failure (malformed feed) logs error and returns empty list
- AC-T011-2: Each item gets a fingerprint (SHA-256 of source_url + title + published_at)
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from intellisource.collector.adapters.rss import RSSCollector
from intellisource.collector.base import BaseCollector, RawContent

# ---------------------------------------------------------------------------
# Fixtures: sample feed XML
# ---------------------------------------------------------------------------

RSS_20_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Blog</title>
    <link>https://example.com</link>
    <description>A test RSS 2.0 feed</description>
    <item>
      <title>First Post</title>
      <link>https://example.com/first-post</link>
      <author>alice@example.com (Alice)</author>
      <description>&lt;p&gt;Hello from RSS 2.0&lt;/p&gt;</description>
      <pubDate>Mon, 01 Jan 2024 12:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Second Post</title>
      <link>https://example.com/second-post</link>
      <author>bob@example.com (Bob)</author>
      <description>&lt;p&gt;Another post&lt;/p&gt;</description>
      <pubDate>Tue, 02 Jan 2024 12:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_10_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom Blog</title>
  <link href="https://example.com"/>
  <entry>
    <title>Atom Entry One</title>
    <link href="https://example.com/atom-one"/>
    <author><name>Charlie</name></author>
    <content type="html">&lt;p&gt;Hello from Atom&lt;/p&gt;</content>
    <published>2024-01-15T10:00:00Z</published>
  </entry>
</feed>
"""

MALFORMED_FEED = """\
This is not valid XML or feed content at all.
<broken><unclosed>
"""

RSSHUB_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>RSSHub - GitHub Trending</title>
    <link>https://rsshub.app/github/trending/daily/python</link>
    <description>GitHub trending repos</description>
    <item>
      <title>awesome-project</title>
      <link>https://github.com/user/awesome-project</link>
      <author>dev@example.com (dev)</author>
      <description>&lt;p&gt;An awesome project&lt;/p&gt;</description>
      <pubDate>Wed, 10 Jan 2024 08:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


def _make_httpx_response(content: str, status_code: int = 200) -> httpx.Response:
    """Helper to build a mock httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        content=content.encode("utf-8"),
        headers={"content-type": "application/xml"},
    )


def _expected_fingerprint(source_url: str, title: str, published_at: str) -> str:
    """Compute the expected SHA-256 fingerprint."""
    raw = source_url + title + published_at
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ===================================================================
# AC-006: RSSCollector correctly parses RSS 2.0 and Atom 1.0 formats
# ===================================================================


class TestRSSCollectorParseFormats:
    """Verify RSSCollector can parse both RSS 2.0 and Atom 1.0 feeds."""

    def test_rss_collector_inherits_base_collector(self):
        """RSSCollector must be a subclass of BaseCollector."""
        assert issubclass(RSSCollector, BaseCollector)

    @pytest.mark.asyncio
    async def test_parse_rss_20_returns_items(self):
        """Parsing a valid RSS 2.0 feed returns a non-empty list of RawContent."""
        collector = RSSCollector()
        source_config = {"url": "https://example.com/feed.xml", "type": "rss"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(RSS_20_FEED)
            result = await collector.collect(source_config)

        assert isinstance(result, list)
        assert len(result) == 2
        for item in result:
            assert isinstance(item, RawContent)

    @pytest.mark.asyncio
    async def test_parse_atom_10_returns_items(self):
        """Parsing a valid Atom 1.0 feed returns a non-empty list of RawContent."""
        collector = RSSCollector()
        source_config = {"url": "https://example.com/atom.xml", "type": "rss"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(ATOM_10_FEED)
            result = await collector.collect(source_config)

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], RawContent)


# ===================================================================
# AC-007: Output RawContent contains required fields
# ===================================================================


class TestRSSCollectorOutputFields:
    """Verify collected RawContent items contain all required fields:
    title, author, body_html, body_text, source_url, published_at."""

    @pytest.mark.asyncio
    async def test_rss_20_output_has_all_fields(self):
        """RSS 2.0 parsed items have title, author, body_html, body_text,
        source_url, and published_at populated."""
        collector = RSSCollector()
        source_config = {"url": "https://example.com/feed.xml", "type": "rss"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(RSS_20_FEED)
            result = await collector.collect(source_config)

        first = result[0]
        assert first.title == "First Post"
        assert first.author is not None and "Alice" in first.author
        assert first.body_html is not None and "<p>" in first.body_html
        assert first.body_text is not None and len(first.body_text) > 0
        assert first.source_url == "https://example.com/first-post"
        assert first.published_at is not None
        assert isinstance(first.published_at, datetime)

    @pytest.mark.asyncio
    async def test_atom_10_output_has_all_fields(self):
        """Atom 1.0 parsed items have title, author, body_html, body_text,
        source_url, and published_at populated."""
        collector = RSSCollector()
        source_config = {"url": "https://example.com/atom.xml", "type": "rss"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(ATOM_10_FEED)
            result = await collector.collect(source_config)

        entry = result[0]
        assert entry.title == "Atom Entry One"
        assert entry.author is not None and "Charlie" in entry.author
        assert entry.body_html is not None and "<p>" in entry.body_html
        assert entry.body_text is not None and len(entry.body_text) > 0
        assert entry.source_url == "https://example.com/atom-one"
        assert entry.published_at is not None
        assert isinstance(entry.published_at, datetime)


# ===================================================================
# AC-008: RSSHub URL as source works with standard RSS logic
# ===================================================================


class TestRSSHubCompatibility:
    """Verify RSSHub URLs work identically to standard RSS feeds."""

    @pytest.mark.asyncio
    async def test_rsshub_url_collects_items(self):
        """An RSSHub URL is treated as a normal RSS feed and returns items."""
        collector = RSSCollector()
        source_config = {
            "url": "https://rsshub.app/github/trending/daily/python",
            "type": "rss",
        }

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(RSSHUB_FEED)
            result = await collector.collect(source_config)

        assert isinstance(result, list)
        assert len(result) == 1
        item = result[0]
        assert item.title == "awesome-project"
        assert item.source_url == "https://github.com/user/awesome-project"


# ===================================================================
# AC-T011-1: Parse failure returns empty list, no exception
# ===================================================================


class TestRSSCollectorErrorHandling:
    """Verify graceful error handling for malformed or empty feeds."""

    @pytest.mark.asyncio
    async def test_malformed_feed_returns_empty_list(self):
        """A malformed feed should return an empty list, not raise an exception."""
        collector = RSSCollector()
        source_config = {"url": "https://example.com/broken.xml", "type": "rss"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(MALFORMED_FEED)
            result = await collector.collect(source_config)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_empty_feed_body_returns_empty_list(self):
        """An empty response body should return an empty list."""
        collector = RSSCollector()
        source_config = {"url": "https://example.com/empty.xml", "type": "rss"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response("")
            result = await collector.collect(source_config)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_list(self):
        """When the HTTP fetch returns None (e.g. 304 or failure),
        collect should return an empty list."""
        collector = RSSCollector()
        source_config = {"url": "https://example.com/feed.xml", "type": "rss"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = None
            result = await collector.collect(source_config)

        assert isinstance(result, list)
        assert len(result) == 0


# ===================================================================
# AC-T011-2: Fingerprint is SHA-256(source_url + title + published_at)
# ===================================================================


class TestRSSCollectorFingerprint:
    """Verify each item's fingerprint is SHA-256(source_url + title + published_at)."""

    @pytest.mark.asyncio
    async def test_fingerprint_is_sha256_of_composite_key(self):
        """The fingerprint for each item must be SHA-256 of
        (source_url + title + published_at) concatenation."""
        collector = RSSCollector()
        source_config = {"url": "https://example.com/feed.xml", "type": "rss"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(RSS_20_FEED)
            result = await collector.collect(source_config)

        first = result[0]
        # The published_at should be converted to an ISO string for hashing,
        # or the implementation must document its serialization. We verify the
        # fingerprint is a valid 64-char hex SHA-256 digest.
        assert isinstance(first.fingerprint, str)
        assert len(first.fingerprint) == 64
        # Verify it is valid hex
        int(first.fingerprint, 16)

        # Verify determinism: the fingerprint should be reproducible from
        # source_url + title + published_at string representation.
        # The exact serialization of published_at depends on implementation,
        # but the fingerprint must match a SHA-256 hash.
        expected = hashlib.sha256(
            (
                first.source_url
                + (first.title or "")
                + (first.published_at.isoformat() if first.published_at else "")
            ).encode("utf-8")
        ).hexdigest()
        assert first.fingerprint == expected

    @pytest.mark.asyncio
    async def test_different_items_have_different_fingerprints(self):
        """Two distinct items from the same feed must have different fingerprints."""
        collector = RSSCollector()
        source_config = {"url": "https://example.com/feed.xml", "type": "rss"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(RSS_20_FEED)
            result = await collector.collect(source_config)

        assert len(result) == 2
        assert result[0].fingerprint != result[1].fingerprint

    @pytest.mark.asyncio
    async def test_fingerprint_consistent_across_calls(self):
        """Calling collect twice with the same feed produces identical fingerprints."""
        collector = RSSCollector()
        source_config = {"url": "https://example.com/feed.xml", "type": "rss"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(RSS_20_FEED)
            result1 = await collector.collect(source_config)

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(RSS_20_FEED)
            result2 = await collector.collect(source_config)

        assert result1[0].fingerprint == result2[0].fingerprint
