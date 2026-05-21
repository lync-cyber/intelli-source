"""Tests for WebCollector adapter.

Covers:
- AC-006: WebCollector correctly fetches web pages and extracts body content
- AC-007: Output RawContent contains title/author/body_html/body_text/source_url
- AC-T012-1: Uses BeautifulSoup4 + lxml to parse HTML
- AC-T012-2: Body extraction filters out nav, ads, sidebar, footer (heuristic rules)
- AC-T012-3: Supports custom CSS selector for body extraction via source metadata
- AC-T012-4: Request timeout (default 30s) and connection errors handled gracefully
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from intellisource.collector.adapters.web import WebCollector
from intellisource.collector.base import BaseCollector, RawContent

# ---------------------------------------------------------------------------
# Fixtures: sample HTML strings
# ---------------------------------------------------------------------------

SIMPLE_PAGE = """\
<!DOCTYPE html>
<html>
<head><title>Test Page Title</title></head>
<body>
  <article>
    <h1>Test Page Title</h1>
    <p class="author">By Jane Doe</p>
    <div class="content">
      <p>This is the main body content of the page.</p>
      <p>It has multiple paragraphs with meaningful text.</p>
    </div>
  </article>
</body>
</html>
"""

PAGE_WITH_NOISE = """\
<!DOCTYPE html>
<html>
<head><title>Article With Noise</title></head>
<body>
  <nav>
    <ul><li><a href="/">Home</a></li><li><a href="/about">About</a></li></ul>
  </nav>
  <div class="sidebar">
    <h3>Popular Posts</h3>
    <ul><li>Post A</li><li>Post B</li></ul>
  </div>
  <div class="advertisement">
    <p>Buy our product now!</p>
  </div>
  <header>
    <div class="site-branding">My Blog</div>
  </header>
  <main>
    <article>
      <h1>Article With Noise</h1>
      <p>This is the real article content that should be extracted.</p>
      <p>Second paragraph of real content.</p>
    </article>
  </main>
  <footer>
    <p>Copyright 2024 Example Corp</p>
  </footer>
</body>
</html>
"""

PAGE_WITH_CUSTOM_SELECTOR = """\
<!DOCTYPE html>
<html>
<head><title>Custom Selector Page</title></head>
<body>
  <div id="wrapper">
    <div class="nav-bar">Navigation links here</div>
    <div class="my-custom-content">
      <h2>Custom Content Title</h2>
      <p>This content should be extracted using a custom CSS selector.</p>
    </div>
    <div class="sidebar">Sidebar stuff</div>
  </div>
</body>
</html>
"""

MINIMAL_PAGE = """\
<!DOCTYPE html>
<html>
<head><title>Minimal</title></head>
<body>
  <p>Just a paragraph.</p>
</body>
</html>
"""

PAGE_WITH_META_AUTHOR = """\
<!DOCTYPE html>
<html>
<head>
  <title>Meta Author Page</title>
  <meta name="author" content="John Smith">
</head>
<body>
  <article>
    <p>Content with author in meta tag.</p>
  </article>
</body>
</html>
"""


def _make_httpx_response(content: str, status_code: int = 200) -> httpx.Response:
    """Helper to build a mock httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        content=content.encode("utf-8"),
        headers={"content-type": "text/html; charset=utf-8"},
    )


# ===================================================================
# AC-006: WebCollector correctly fetches web pages and extracts body
# ===================================================================


class TestWebCollectorBasic:
    """Verify WebCollector can fetch and parse web pages."""

    def test_web_collector_inherits_base_collector(self):
        """WebCollector must be a subclass of BaseCollector."""
        assert issubclass(WebCollector, BaseCollector)

    @pytest.mark.asyncio
    async def test_collect_returns_list_of_raw_content(self):
        """Collecting a simple page returns a list with one RawContent item."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(SIMPLE_PAGE)
            result = await collector.collect(source_config)

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], RawContent)

    @pytest.mark.asyncio
    async def test_collect_extracts_body_text(self):
        """The body_text field should contain the main text content."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(SIMPLE_PAGE)
            result = await collector.collect(source_config)

        item = result[0]
        assert item.body_text is not None
        assert "main body content" in item.body_text


# ===================================================================
# AC-007: Output RawContent contains required fields
# ===================================================================


class TestWebCollectorOutputFields:
    """Verify collected RawContent items contain title, author,
    body_html, body_text, and source_url."""

    @pytest.mark.asyncio
    async def test_output_has_title(self):
        """RawContent title should match the page's <title> tag."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(SIMPLE_PAGE)
            result = await collector.collect(source_config)

        assert result[0].title == "Test Page Title"

    @pytest.mark.asyncio
    async def test_output_has_source_url(self):
        """RawContent source_url should match the configured URL."""
        collector = WebCollector()
        url = "https://example.com/page"
        source_config = {"url": url, "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(SIMPLE_PAGE)
            result = await collector.collect(source_config)

        assert result[0].source_url == url

    @pytest.mark.asyncio
    async def test_output_has_body_html(self):
        """RawContent body_html should contain HTML markup of the body."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(SIMPLE_PAGE)
            result = await collector.collect(source_config)

        item = result[0]
        assert item.body_html is not None
        assert len(item.body_html) > 0
        # body_html should contain actual HTML tags
        assert "<" in item.body_html

    @pytest.mark.asyncio
    async def test_output_has_body_text(self):
        """RawContent body_text should contain plain text without HTML tags."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(SIMPLE_PAGE)
            result = await collector.collect(source_config)

        item = result[0]
        assert item.body_text is not None
        assert "<p>" not in item.body_text
        assert "<div>" not in item.body_text
        assert len(item.body_text.strip()) > 0

    @pytest.mark.asyncio
    async def test_output_has_author_from_meta(self):
        """RawContent author should be extracted from <meta name='author'>."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(PAGE_WITH_META_AUTHOR)
            result = await collector.collect(source_config)

        assert result[0].author == "John Smith"


# ===================================================================
# AC-T012-1: Uses BeautifulSoup4 + lxml to parse HTML
# ===================================================================


class TestWebCollectorParser:
    """Verify WebCollector uses BeautifulSoup4 with lxml parser."""

    @pytest.mark.asyncio
    async def test_uses_beautifulsoup_with_lxml(self):
        """WebCollector must use BeautifulSoup with 'lxml' parser.
        We verify by patching BeautifulSoup and checking the parser argument."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(SIMPLE_PAGE)

            with patch("intellisource.collector.adapters.web.BeautifulSoup") as mock_bs:
                # Make BeautifulSoup return a mock that supports enough
                # interface for collect to proceed
                mock_soup = mock_bs.return_value
                mock_soup.title = None
                mock_soup.find.return_value = None
                mock_soup.find_all.return_value = []
                mock_soup.select.return_value = []
                mock_soup.get_text.return_value = ""

                await collector.collect(source_config)

                # Verify BeautifulSoup was called with 'lxml' parser
                mock_bs.assert_called()
                call_args = mock_bs.call_args
                # Second positional arg or 'features' kwarg should be 'lxml'
                args, kwargs = call_args
                parser_arg = args[1] if len(args) > 1 else kwargs.get("features")
                assert parser_arg == "lxml", (
                    f"Expected BeautifulSoup to use 'lxml' parser, got '{parser_arg}'"
                )


# ===================================================================
# AC-T012-2: Body extraction filters nav, ads, sidebar, footer
# ===================================================================


class TestWebCollectorNoiseFiltering:
    """Verify body extraction filters out navigation, ads, sidebar, footer."""

    @pytest.mark.asyncio
    async def test_filters_nav_element(self):
        """Extracted body_text should not contain navigation content."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(PAGE_WITH_NOISE)
            result = await collector.collect(source_config)

        item = result[0]
        assert item.body_text is not None
        # Nav content should be filtered out
        assert "Home" not in item.body_text
        assert "About" not in item.body_text

    @pytest.mark.asyncio
    async def test_filters_footer_element(self):
        """Extracted body_text should not contain footer content."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(PAGE_WITH_NOISE)
            result = await collector.collect(source_config)

        item = result[0]
        assert item.body_text is not None
        assert "Copyright" not in item.body_text

    @pytest.mark.asyncio
    async def test_filters_sidebar(self):
        """Extracted body_text should not contain sidebar content."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(PAGE_WITH_NOISE)
            result = await collector.collect(source_config)

        item = result[0]
        assert item.body_text is not None
        assert "Popular Posts" not in item.body_text

    @pytest.mark.asyncio
    async def test_filters_advertisement(self):
        """Extracted body_text should not contain advertisement content."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(PAGE_WITH_NOISE)
            result = await collector.collect(source_config)

        item = result[0]
        assert item.body_text is not None
        assert "Buy our product" not in item.body_text

    @pytest.mark.asyncio
    async def test_preserves_article_content(self):
        """Extracted body_text should preserve the actual article content."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(PAGE_WITH_NOISE)
            result = await collector.collect(source_config)

        item = result[0]
        assert item.body_text is not None
        assert "real article content" in item.body_text

    @pytest.mark.asyncio
    async def test_body_html_also_excludes_noise(self):
        """body_html should also exclude nav/footer/sidebar/ad elements."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(PAGE_WITH_NOISE)
            result = await collector.collect(source_config)

        item = result[0]
        assert item.body_html is not None
        assert "<nav>" not in item.body_html.lower()
        assert "<footer>" not in item.body_html.lower()


# ===================================================================
# AC-T012-3: Custom CSS selector for body extraction
# ===================================================================


class TestWebCollectorCustomSelector:
    """Verify custom CSS selector support via source metadata."""

    @pytest.mark.asyncio
    async def test_custom_css_selector_extracts_matching_content(self):
        """When css_selector is provided in metadata, only matching
        elements should be extracted."""
        collector = WebCollector()
        source_config = {
            "url": "https://example.com/page",
            "type": "web",
            "metadata": {"css_selector": ".my-custom-content"},
        }

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(PAGE_WITH_CUSTOM_SELECTOR)
            result = await collector.collect(source_config)

        item = result[0]
        assert item.body_text is not None
        assert (
            "This content should be extracted using a custom CSS selector"
            in item.body_text
        )

    @pytest.mark.asyncio
    async def test_custom_css_selector_excludes_non_matching(self):
        """When css_selector is specified, content outside the selector
        should not appear in body_text."""
        collector = WebCollector()
        source_config = {
            "url": "https://example.com/page",
            "type": "web",
            "metadata": {"css_selector": ".my-custom-content"},
        }

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(PAGE_WITH_CUSTOM_SELECTOR)
            result = await collector.collect(source_config)

        item = result[0]
        assert item.body_text is not None
        assert "Navigation links here" not in item.body_text
        assert "Sidebar stuff" not in item.body_text

    @pytest.mark.asyncio
    async def test_without_custom_selector_uses_heuristic(self):
        """Without css_selector in metadata, the default heuristic
        extraction should be used."""
        collector = WebCollector()
        source_config = {
            "url": "https://example.com/page",
            "type": "web",
        }

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(SIMPLE_PAGE)
            result = await collector.collect(source_config)

        item = result[0]
        assert item.body_text is not None
        assert "main body content" in item.body_text


# ===================================================================
# AC-T012-4: Timeout and connection error handling
# ===================================================================


class TestWebCollectorErrorHandling:
    """Verify graceful handling of timeouts and connection errors."""

    @pytest.mark.asyncio
    async def test_timeout_returns_empty_list(self):
        """When the request times out, collect should return an empty list."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/slow", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.side_effect = httpx.TimeoutException("Connection timed out")
            result = await collector.collect(source_config)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_connection_error_returns_empty_list(self):
        """When a connection error occurs, collect should return an empty list."""
        collector = WebCollector()
        source_config = {"url": "https://unreachable.example.com", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.side_effect = httpx.ConnectError("Connection refused")
            result = await collector.collect(source_config)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_http_error_status_returns_empty_list(self):
        """When the server returns an error status (e.g. 500),
        collect should return an empty list."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/error", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(
                "Internal Server Error", status_code=500
            )
            result = await collector.collect(source_config)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_timeout_does_not_raise_exception(self):
        """Timeout should be handled gracefully without propagating exceptions."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/slow", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.side_effect = httpx.TimeoutException("timed out")
            # Should not raise
            result = await collector.collect(source_config)
            assert result == []

    @pytest.mark.asyncio
    async def test_conditional_fetch_none_returns_empty_list(self):
        """When conditional_fetch returns None (304 Not Modified),
        collect should return an empty list."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = None
            result = await collector.collect(source_config)

        assert isinstance(result, list)
        assert len(result) == 0


# ===================================================================
# Fingerprint: SHA-256 based
# ===================================================================


class TestWebCollectorFingerprint:
    """Verify fingerprint is a valid SHA-256 hex digest."""

    @pytest.mark.asyncio
    async def test_fingerprint_is_sha256(self):
        """The fingerprint should be a valid 64-char hex SHA-256 digest."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(SIMPLE_PAGE)
            result = await collector.collect(source_config)

        item = result[0]
        assert isinstance(item.fingerprint, str)
        assert len(item.fingerprint) == 64
        # Verify it is valid hex
        int(item.fingerprint, 16)

    @pytest.mark.asyncio
    async def test_fingerprint_contains_source_url(self):
        """The fingerprint should incorporate the source_url, so different
        URLs with the same content produce different fingerprints."""
        collector = WebCollector()

        results = []
        for url in ["https://example.com/page-a", "https://example.com/page-b"]:
            source_config = {"url": url, "type": "web"}
            with patch.object(
                collector, "conditional_fetch", new_callable=AsyncMock
            ) as mock_fetch:
                mock_fetch.return_value = _make_httpx_response(SIMPLE_PAGE)
                result = await collector.collect(source_config)
                results.append(result[0])

        assert results[0].fingerprint != results[1].fingerprint

    @pytest.mark.asyncio
    async def test_fingerprint_deterministic(self):
        """Same URL and content should produce the same fingerprint."""
        collector = WebCollector()
        source_config = {"url": "https://example.com/page", "type": "web"}

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(SIMPLE_PAGE)
            result1 = await collector.collect(source_config)

        with patch.object(
            collector, "conditional_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _make_httpx_response(SIMPLE_PAGE)
            result2 = await collector.collect(source_config)

        assert result1[0].fingerprint == result2[0].fingerprint
