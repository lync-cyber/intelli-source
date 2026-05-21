"""Tests for APICollector adapter.

Covers:
- AC-006: APICollector sends HTTP requests per config and parses JSON responses
- AC-007: Field mapping config converts API response to unified RawContent format
- AC-008: Support third-party API integration via generic API configuration
- AC-T013-1: Support GET/POST methods with configurable headers/params/body
- AC-T013-2: Support JSONPath expressions for response field mapping
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from intellisource.collector.adapters.api import APICollector
from intellisource.collector.base import BaseCollector, RawContent

# ---------------------------------------------------------------------------
# Fixtures: sample API responses and configs
# ---------------------------------------------------------------------------

SAMPLE_API_RESPONSE = {
    "data": {
        "articles": [
            {
                "headline": "Breaking News",
                "writer": {"name": "Alice Johnson"},
                "content": "This is the full article text about breaking news.",
                "url": "https://api.example.com/articles/1",
                "date": "2024-03-15T10:30:00Z",
            },
            {
                "headline": "Tech Update",
                "writer": {"name": "Bob Smith"},
                "content": "Latest technology trends and updates.",
                "url": "https://api.example.com/articles/2",
                "date": "2024-03-16T14:00:00Z",
            },
        ]
    },
    "meta": {"total": 2, "page": 1},
}

SINGLE_ITEM_RESPONSE = {
    "data": {
        "articles": [
            {
                "headline": "Solo Article",
                "writer": {"name": "Charlie"},
                "content": "A single article response.",
                "url": "https://api.example.com/articles/99",
                "date": "2024-06-01T09:00:00Z",
            }
        ]
    }
}

FLAT_RESPONSE = {
    "results": [
        {
            "title": "Flat Item",
            "author": "Dana",
            "text": "Flat structure content.",
            "link": "https://other-api.com/item/1",
            "pub_date": "2024-07-20T12:00:00Z",
        }
    ]
}


def _make_source_config(
    url: str = "https://api.example.com/data",
    method: str = "GET",
    headers: dict | None = None,
    params: dict | None = None,
    body: dict | None = None,
    field_mapping: dict | None = None,
) -> dict:
    """Build a source_config dict for APICollector."""
    if field_mapping is None:
        field_mapping = {
            "items_path": "$.data.articles",
            "title": "$.headline",
            "author": "$.writer.name",
            "body_text": "$.content",
            "source_url": "$.url",
            "published_at": "$.date",
        }
    metadata: dict = {
        "method": method,
        "field_mapping": field_mapping,
    }
    if headers is not None:
        metadata["headers"] = headers
    if params is not None:
        metadata["params"] = params
    if body is not None:
        metadata["body"] = body
    return {
        "url": url,
        "type": "api",
        "metadata": metadata,
    }


def _make_httpx_response(data: dict | list, status_code: int = 200) -> httpx.Response:
    """Helper to build a mock httpx.Response with JSON content."""
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(data).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


# ===================================================================
# AC-006: APICollector sends HTTP requests and parses JSON responses
# ===================================================================


class TestAPICollectorBasic:
    """Verify APICollector inherits BaseCollector and handles basic requests."""

    def test_api_collector_inherits_base_collector(self):
        """APICollector must be a subclass of BaseCollector."""
        assert issubclass(APICollector, BaseCollector)

    def test_api_collector_is_instantiable(self):
        """APICollector can be instantiated without arguments."""
        collector = APICollector()
        assert isinstance(collector, BaseCollector)

    @pytest.mark.asyncio
    async def test_collect_returns_list_of_raw_content(self):
        """collect() returns a list of RawContent objects from JSON API response."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert isinstance(result, list)
        assert len(result) == 2
        for item in result:
            assert isinstance(item, RawContent)

    @pytest.mark.asyncio
    async def test_collect_parses_json_response_correctly(self):
        """collect() correctly extracts items from JSON response using items_path."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert result[0].title == "Breaking News"
        assert result[1].title == "Tech Update"


# ===================================================================
# AC-007: Field mapping converts API response to RawContent format
# ===================================================================


class TestAPICollectorFieldMapping:
    """Verify field_mapping configuration correctly maps API response
    fields to RawContent attributes."""

    @pytest.mark.asyncio
    async def test_title_mapping(self):
        """title field is extracted via configured JSONPath '$.headline'."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert result[0].title == "Breaking News"

    @pytest.mark.asyncio
    async def test_author_mapping_nested_path(self):
        """author field is extracted via nested JSONPath '$.writer.name'."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert result[0].author == "Alice Johnson"
        assert result[1].author == "Bob Smith"

    @pytest.mark.asyncio
    async def test_body_text_mapping(self):
        """body_text field is extracted via configured JSONPath '$.content'."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert (
            result[0].body_text == "This is the full article text about breaking news."
        )

    @pytest.mark.asyncio
    async def test_source_url_mapping(self):
        """source_url field is extracted via configured JSONPath '$.url'."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert result[0].source_url == "https://api.example.com/articles/1"

    @pytest.mark.asyncio
    async def test_published_at_mapping(self):
        """published_at is parsed from the mapped date string to a datetime."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert result[0].published_at is not None
        assert isinstance(result[0].published_at, datetime)

    @pytest.mark.asyncio
    async def test_custom_field_mapping_different_paths(self):
        """A different field_mapping config extracts fields from a flat structure."""
        collector = APICollector()
        config = _make_source_config(
            url="https://other-api.com/data",
            field_mapping={
                "items_path": "$.results",
                "title": "$.title",
                "author": "$.author",
                "body_text": "$.text",
                "source_url": "$.link",
                "published_at": "$.pub_date",
            },
        )

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(FLAT_RESPONSE)
            result = await collector.collect(config)

        assert len(result) == 1
        assert result[0].title == "Flat Item"
        assert result[0].author == "Dana"
        assert result[0].body_text == "Flat structure content."
        assert result[0].source_url == "https://other-api.com/item/1"

    @pytest.mark.asyncio
    async def test_missing_optional_field_returns_none(self):
        """When a mapped field path does not exist in an item, the
        corresponding RawContent field is None (not an error)."""
        collector = APICollector()
        response_with_missing = {
            "data": {
                "articles": [
                    {
                        "headline": "Partial Article",
                        "url": "https://api.example.com/articles/partial",
                        # No writer, content, or date fields
                    }
                ]
            }
        }
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(response_with_missing)
            result = await collector.collect(config)

        assert len(result) == 1
        assert result[0].title == "Partial Article"
        assert result[0].author is None
        assert result[0].body_text is None
        assert result[0].published_at is None


# ===================================================================
# AC-008: Third-party API integration via generic configuration
# ===================================================================


class TestAPICollectorThirdPartyIntegration:
    """Verify APICollector can integrate with various third-party APIs
    through generic configuration."""

    @pytest.mark.asyncio
    async def test_custom_headers_passed_through(self):
        """Custom headers (e.g. Authorization) from config are included in request."""
        collector = APICollector()
        config = _make_source_config(
            headers={"Authorization": "Bearer test-token-123"},
        )

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SINGLE_ITEM_RESPONSE)
            await collector.collect(config)

        mock_req.assert_called_once()
        call_kwargs = mock_req.call_args
        # The _request method should receive headers including Authorization
        assert "Authorization" in (
            call_kwargs.kwargs.get("headers", {}) or call_kwargs.args[2]
            if len(call_kwargs.args) > 2
            else {}
        )

    @pytest.mark.asyncio
    async def test_custom_params_passed_through(self):
        """Query parameters from config are included in the request."""
        collector = APICollector()
        config = _make_source_config(
            params={"page": 1, "per_page": 50},
        )

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SINGLE_ITEM_RESPONSE)
            await collector.collect(config)

        mock_req.assert_called_once()

    @pytest.mark.asyncio
    async def test_different_api_url_works(self):
        """APICollector works with arbitrary API URLs (third-party integration)."""
        collector = APICollector()
        config = _make_source_config(
            url="https://newsapi.org/v2/top-headlines",
            headers={"X-Api-Key": "secret-key"},
            params={"country": "us"},
        )

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SINGLE_ITEM_RESPONSE)
            result = await collector.collect(config)

        assert isinstance(result, list)
        assert len(result) == 1


# ===================================================================
# AC-T013-1: GET/POST methods with configurable headers/params/body
# ===================================================================


class TestAPICollectorHTTPMethods:
    """Verify GET and POST methods are supported with proper parameter passing."""

    @pytest.mark.asyncio
    async def test_get_method_used_by_default(self):
        """When method is 'GET', the request is made with GET."""
        collector = APICollector()
        config = _make_source_config(method="GET")

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            await collector.collect(config)

        mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_method_sends_body(self):
        """When method is 'POST', the request is made with POST and includes body."""
        collector = APICollector()
        config = _make_source_config(
            method="POST",
            body={"query": "test search", "filters": {"category": "tech"}},
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            await collector.collect(config)

        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_with_params(self):
        """GET request includes query parameters from config."""
        collector = APICollector()
        config = _make_source_config(
            method="GET",
            params={"page": 2, "limit": 10},
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            await collector.collect(config)

        call_kwargs = mock_get.call_args
        # params should be passed to the GET request
        assert call_kwargs.kwargs.get("params") == {"page": 2, "limit": 10}

    @pytest.mark.asyncio
    async def test_post_with_headers_and_body(self):
        """POST request includes both custom headers and JSON body."""
        collector = APICollector()
        config = _make_source_config(
            method="POST",
            headers={"Content-Type": "application/json", "X-Custom": "value"},
            body={"search": "python"},
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            await collector.collect(config)

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs.get("json") == {"search": "python"}


# ===================================================================
# AC-T013-2: JSONPath expressions for response field mapping
# ===================================================================


class TestAPICollectorJSONPath:
    """Verify JSONPath expression support for field mapping configuration."""

    @pytest.mark.asyncio
    async def test_items_path_extracts_array(self):
        """items_path '$.data.articles' extracts the correct array from response."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_nested_jsonpath_resolves_correctly(self):
        """Nested path '$.writer.name' resolves through nested objects."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert result[0].author == "Alice Johnson"

    @pytest.mark.asyncio
    async def test_simple_jsonpath_resolves(self):
        """Simple path '$.headline' resolves a top-level field on each item."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert result[0].title == "Breaking News"

    @pytest.mark.asyncio
    async def test_nonexistent_path_returns_none(self):
        """A JSONPath that does not match any field yields None for that attribute."""
        collector = APICollector()
        config = _make_source_config(
            field_mapping={
                "items_path": "$.data.articles",
                "title": "$.nonexistent_field",
                "source_url": "$.url",
            },
        )

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert len(result) == 2
        assert result[0].title is None

    @pytest.mark.asyncio
    async def test_deeply_nested_path(self):
        """Deeply nested paths like '$.a.b.c' resolve through multiple levels."""
        collector = APICollector()
        deep_response = {
            "items": [
                {
                    "meta": {"info": {"deep_title": "Deep Value"}},
                    "link": "https://example.com/deep",
                }
            ]
        }
        config = _make_source_config(
            field_mapping={
                "items_path": "$.items",
                "title": "$.meta.info.deep_title",
                "source_url": "$.link",
            },
        )

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(deep_response)
            result = await collector.collect(config)

        assert len(result) == 1
        assert result[0].title == "Deep Value"


# ===================================================================
# Fingerprint: SHA-256 based fingerprinting
# ===================================================================


class TestAPICollectorFingerprint:
    """Verify fingerprint generation for API-collected items."""

    @pytest.mark.asyncio
    async def test_fingerprint_is_sha256_hex(self):
        """Each item's fingerprint is a valid 64-char SHA-256 hex digest."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        for item in result:
            assert isinstance(item.fingerprint, str)
            assert len(item.fingerprint) == 64
            # Verify valid hex
            int(item.fingerprint, 16)

    @pytest.mark.asyncio
    async def test_different_items_have_different_fingerprints(self):
        """Two distinct items produce different fingerprints."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert len(result) == 2
        assert result[0].fingerprint != result[1].fingerprint


# ===================================================================
# Error handling: graceful degradation
# ===================================================================


class TestAPICollectorErrorHandling:
    """Verify APICollector handles errors gracefully."""

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_list(self):
        """When the HTTP request fails (e.g. 500), collect returns empty list."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(
                {"error": "Internal Server Error"}, status_code=500
            )
            result = await collector.collect(config)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty_list(self):
        """When the response body is not valid JSON, collect returns empty list."""
        collector = APICollector()
        config = _make_source_config()

        invalid_response = httpx.Response(
            status_code=200,
            content=b"not json at all",
            headers={"content-type": "application/json"},
        )

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = invalid_response
            result = await collector.collect(config)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_items_path_not_found_returns_empty_list(self):
        """When items_path does not match any data in response, return empty list."""
        collector = APICollector()
        config = _make_source_config(
            field_mapping={
                "items_path": "$.nonexistent.path",
                "title": "$.title",
                "source_url": "$.url",
            },
        )

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(SAMPLE_API_RESPONSE)
            result = await collector.collect(config)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_network_exception_returns_empty_list(self):
        """When the HTTP request raises an exception, collect returns empty list."""
        collector = APICollector()
        config = _make_source_config()

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = httpx.ConnectError("Connection refused")
            result = await collector.collect(config)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_empty_items_array_returns_empty_list(self):
        """When the items array at items_path is empty, return empty list."""
        collector = APICollector()
        config = _make_source_config()
        empty_response = {"data": {"articles": []}}

        with patch.object(collector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _make_httpx_response(empty_response)
            result = await collector.collect(config)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_missing_url_in_config_returns_empty_list(self):
        """When source_config has no 'url' key, collect returns empty list."""
        collector = APICollector()
        config = {"type": "api", "metadata": {"method": "GET"}}

        result = await collector.collect(config)

        assert isinstance(result, list)
        assert len(result) == 0
