"""Tests for T-040: Source CRUD API endpoints.

Covers:
  AC-061:     API supports source creation/query/update/delete operations
  AC-065:     FastAPI auto-generates OpenAPI documentation
  AC-T040-1:  GET /api/v1/sources supports pagination and filtering (type/tag/status)
  AC-T040-2:  POST /api/v1/sources creates source, correctly handles 409 conflicts
  AC-T040-3:  PATCH /api/v1/sources/{id} supports partial updates
  AC-T040-4:  DELETE /api/v1/sources/{id} deletes source
  AC-T040-5:  POST /api/v1/sources/reload reloads configuration (whitelist validation)
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# The router module does not exist yet -- import may fail during RED phase.
# We capture the error so individual tests fail with a clear message rather
# than the entire module being uncollectable.
try:
    from intellisource.api.routers.sources import router  # type: ignore[import-untyped]
except ImportError:
    router = None  # type: ignore[assignment]

_ROUTER_MISSING = router is None

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
SOURCE_ID_2 = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _make_source_dict(
    *,
    id: uuid.UUID = SOURCE_ID,
    name: str = "test-source",
    type: str = "rss",
    url: str = "https://example.com/feed",
    tags: list[str] | None = None,
    status: str = "active",
) -> dict[str, Any]:
    """Return a plain dict representing a serialised Source."""
    return {
        "id": str(id),
        "name": name,
        "type": type,
        "url": url,
        "tags": tags or [],
        "status": status,
        "created_at": "2025-01-01T00:00:00+00:00",
    }


def _make_source_obj(
    *,
    id: uuid.UUID = SOURCE_ID,
    name: str = "test-source",
    type: str = "rss",
    url: str = "https://example.com/feed",
    tags: list[str] | None = None,
    status: str = "active",
) -> MagicMock:
    """Return a MagicMock that mimics a Source ORM instance."""
    obj = MagicMock()
    obj.id = id
    obj.name = name
    obj.type = type
    obj.url = url
    obj.tags = tags or []
    obj.status = status
    obj.created_at = "2025-01-01T00:00:00+00:00"
    obj.updated_at = None
    obj.schedule_interval = 3600
    obj.schedule_adaptive = True
    obj.proxy = None
    obj.rate_limit_qps = None
    obj.rate_limit_concurrency = None
    obj.metadata_ = {}
    obj.last_collected_at = None
    obj.next_collect_at = None
    obj.error_count = 0
    obj.avg_update_interval = None
    obj.http_etag = None
    obj.http_last_modified = None
    obj.config_version = 1
    return obj


@pytest.fixture()
def app() -> FastAPI:
    """Create a minimal FastAPI app with the sources router mounted."""
    if _ROUTER_MISSING:
        pytest.fail(
            "intellisource.api.routers.sources not implemented: cannot import 'router'"
        )
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    return application


@pytest.fixture()
async def client(app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    """Yield an httpx AsyncClient bound to the test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


# ===========================================================================
# AC-T040-1: GET /api/v1/sources — pagination and filtering
# ===========================================================================


class TestSourceListEndpoint:
    """AC-T040-1: GET /api/v1/sources supports pagination and filtering."""

    @pytest.mark.asyncio
    async def test_list_sources_returns_paginated_result(
        self, client: AsyncClient
    ) -> None:
        """Default GET returns items list with pagination metadata."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [_make_source_obj()],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.get("/api/v1/sources")

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "next_cursor" in body
        assert "has_more" in body
        assert isinstance(body["items"], list)

    @pytest.mark.asyncio
    async def test_list_sources_filter_by_type(self, client: AsyncClient) -> None:
        """Filtering by type=rss passes the parameter to the repository."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.get("/api/v1/sources", params={"type": "rss"})

        assert resp.status_code == 200
        mock_repo.list.assert_called_once()
        call_kwargs = mock_repo.list.call_args
        # The 'type' filter must have been forwarded
        assert call_kwargs.kwargs.get("type") == "rss" or (
            call_kwargs.args and "rss" in str(call_kwargs)
        )

    @pytest.mark.asyncio
    async def test_list_sources_filter_by_tag(self, client: AsyncClient) -> None:
        """Filtering by tag passes the parameter to the repository."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.get("/api/v1/sources", params={"tag": "news"})

        assert resp.status_code == 200
        call_kwargs = mock_repo.list.call_args
        assert call_kwargs.kwargs.get("tag") == "news" or ("news" in str(call_kwargs))

    @pytest.mark.asyncio
    async def test_list_sources_filter_by_status(self, client: AsyncClient) -> None:
        """Filtering by status passes the parameter to the repository."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.get("/api/v1/sources", params={"status": "paused"})

        assert resp.status_code == 200
        call_kwargs = mock_repo.list.call_args
        assert call_kwargs.kwargs.get("status") == "paused" or (
            "paused" in str(call_kwargs)
        )

    @pytest.mark.asyncio
    async def test_list_sources_pagination_cursor_and_limit(
        self, client: AsyncClient
    ) -> None:
        """Cursor and limit params are forwarded to the repository."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [_make_source_obj(id=SOURCE_ID_2)],
            "next_cursor": str(SOURCE_ID_2),
            "has_more": True,
        }

        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.get(
                "/api/v1/sources",
                params={"cursor": str(SOURCE_ID), "limit": 10},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_more"] is True
        assert body["next_cursor"] is not None

    @pytest.mark.asyncio
    async def test_list_sources_limit_capped_at_100(self, client: AsyncClient) -> None:
        """Limit values above 100 should be capped or rejected."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.get("/api/v1/sources", params={"limit": 200})

        # Either the router caps limit to 100 (200->OK) or rejects (422).
        # In either case the repo must not receive limit > 100.
        if resp.status_code == 200:
            call_kwargs = mock_repo.list.call_args
            actual_limit = call_kwargs.kwargs.get(
                "limit", call_kwargs.args[0] if call_kwargs.args else None
            )
            assert actual_limit is not None and actual_limit <= 100


# ===========================================================================
# AC-T040-2: POST /api/v1/sources — creation and 409 conflict
# ===========================================================================


class TestSourceCreateEndpoint:
    """AC-T040-2: POST /api/v1/sources creates source, handles 409."""

    @pytest.mark.asyncio
    async def test_create_source_success(self, client: AsyncClient) -> None:
        """Successful creation returns 201 with id, name, type, status, created_at."""
        mock_repo = AsyncMock()
        created = _make_source_obj()
        mock_repo.create.return_value = created

        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.post(
                "/api/v1/sources",
                json={
                    "name": "test-source",
                    "type": "rss",
                    "url": "https://example.com/feed",
                },
            )

        assert resp.status_code == 201
        body = resp.json()
        assert "id" in body
        assert body["name"] == "test-source"
        assert body["type"] == "rss"
        assert "status" in body
        assert "created_at" in body

    @pytest.mark.asyncio
    async def test_create_source_with_optional_fields(
        self, client: AsyncClient
    ) -> None:
        """Creation with tags, schedule, proxy, rate_limit, metadata succeeds."""
        mock_repo = AsyncMock()
        created = _make_source_obj(tags=["news", "tech"])
        mock_repo.create.return_value = created

        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.post(
                "/api/v1/sources",
                json={
                    "name": "test-source",
                    "type": "rss",
                    "url": "https://example.com/feed",
                    "tags": ["news", "tech"],
                    "schedule": {"interval": 1800, "adaptive": False},
                    "proxy": "http://proxy:8080",
                    "rate_limit": {"qps": 2.0, "concurrency": 5},
                    "metadata": {"key": "value"},
                },
            )

        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_create_source_conflict_409(self, client: AsyncClient) -> None:
        """Duplicate name returns 409."""
        mock_repo = AsyncMock()
        # Simulate IntegrityError for duplicate name
        from sqlalchemy.exc import IntegrityError

        mock_repo.create.side_effect = IntegrityError(
            "duplicate", params=None, orig=Exception("unique constraint")
        )

        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.post(
                "/api/v1/sources",
                json={
                    "name": "existing-source",
                    "type": "rss",
                    "url": "https://example.com/feed",
                },
            )

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_create_source_missing_required_field_422(
        self, client: AsyncClient
    ) -> None:
        """Missing required field (name) returns 422 validation error."""
        resp = await client.post(
            "/api/v1/sources",
            json={
                "type": "rss",
                "url": "https://example.com/feed",
            },
        )

        assert resp.status_code == 422


# ===========================================================================
# AC-T040-3: PATCH /api/v1/sources/{id} — partial update
# ===========================================================================


class TestSourceUpdateEndpoint:
    """AC-T040-3: PATCH /api/v1/sources/{id} supports partial updates."""

    @pytest.mark.asyncio
    async def test_partial_update_success(self, client: AsyncClient) -> None:
        """Partial update with only name returns 200 with updated source."""
        mock_repo = AsyncMock()
        updated = _make_source_obj(name="updated-name")
        mock_repo.update.return_value = updated

        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.patch(
                f"/api/v1/sources/{SOURCE_ID}",
                json={"name": "updated-name"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "updated-name"

    @pytest.mark.asyncio
    async def test_partial_update_multiple_fields(self, client: AsyncClient) -> None:
        """Updating multiple fields at once (tags, status, url)."""
        mock_repo = AsyncMock()
        updated = _make_source_obj(
            tags=["updated"], status="paused", url="https://new.example.com"
        )
        mock_repo.update.return_value = updated

        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.patch(
                f"/api/v1/sources/{SOURCE_ID}",
                json={
                    "tags": ["updated"],
                    "status": "paused",
                    "url": "https://new.example.com",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "paused"

    @pytest.mark.asyncio
    async def test_update_not_found_404(self, client: AsyncClient) -> None:
        """Updating a non-existent source returns 404."""
        mock_repo = AsyncMock()
        mock_repo.update.return_value = None

        nonexistent_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.patch(
                f"/api/v1/sources/{nonexistent_id}",
                json={"name": "nope"},
            )

        assert resp.status_code == 404


# ===========================================================================
# AC-T040-4: DELETE /api/v1/sources/{id}
# ===========================================================================


class TestSourceDeleteEndpoint:
    """AC-T040-4: DELETE /api/v1/sources/{id} deletes source."""

    @pytest.mark.asyncio
    async def test_delete_success_204(self, client: AsyncClient) -> None:
        """Deleting an existing source returns 204 No Content."""
        mock_repo = AsyncMock()
        mock_repo.delete.return_value = True

        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.delete(f"/api/v1/sources/{SOURCE_ID}")

        assert resp.status_code == 204
        assert resp.content == b""  # No body on 204

    @pytest.mark.asyncio
    async def test_delete_not_found_404(self, client: AsyncClient) -> None:
        """Deleting a non-existent source returns 404."""
        mock_repo = AsyncMock()
        mock_repo.delete.return_value = False

        nonexistent_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        with patch(
            "intellisource.api.routers.sources.SourceRepository",
            return_value=mock_repo,
        ):
            resp = await client.delete(f"/api/v1/sources/{nonexistent_id}")

        assert resp.status_code == 404


# ===========================================================================
# AC-T040-5: POST /api/v1/sources/reload
# ===========================================================================


class TestSourceReloadEndpoint:
    """AC-T040-5: POST /api/v1/sources/reload reloads configuration."""

    @pytest.mark.asyncio
    async def test_reload_success(self, client: AsyncClient) -> None:
        """Successful reload returns 200 with loaded_count and errors list."""
        with patch(
            "intellisource.api.routers.sources.reload_source_configs",
            new_callable=AsyncMock,
            return_value={"loaded_count": 3, "errors": []},
        ):
            resp = await client.post(
                "/api/v1/sources/reload",
                json={},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "loaded_count" in body
        assert body["loaded_count"] == 3
        assert "errors" in body
        assert isinstance(body["errors"], list)

    @pytest.mark.asyncio
    async def test_reload_with_config_name(self, client: AsyncClient) -> None:
        """Reload with specific config_name filters to that config."""
        with patch(
            "intellisource.api.routers.sources.reload_source_configs",
            new_callable=AsyncMock,
            return_value={"loaded_count": 1, "errors": []},
        ):
            resp = await client.post(
                "/api/v1/sources/reload",
                json={"config_name": "my_config.yaml"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["loaded_count"] == 1

    @pytest.mark.asyncio
    async def test_reload_whitelist_validation_400(self, client: AsyncClient) -> None:
        """Config name not in whitelist returns 400."""
        with patch(
            "intellisource.api.routers.sources.reload_source_configs",
            new_callable=AsyncMock,
            side_effect=ValueError("filename not in whitelist"),
        ):
            resp = await client.post(
                "/api/v1/sources/reload",
                json={"config_name": "../../../etc/passwd"},
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_reload_config_format_error_400(self, client: AsyncClient) -> None:
        """Invalid config format returns 400."""
        with patch(
            "intellisource.api.routers.sources.reload_source_configs",
            new_callable=AsyncMock,
            side_effect=ValueError("invalid config format"),
        ):
            resp = await client.post(
                "/api/v1/sources/reload",
                json={"config_name": "bad_config.yaml"},
            )

        assert resp.status_code == 400


# ===========================================================================
# AC-065: OpenAPI documentation
# ===========================================================================


class TestOpenApiDocs:
    """AC-065: FastAPI auto-generates OpenAPI documentation."""

    @pytest.mark.asyncio
    async def test_openapi_json_accessible(self, client: AsyncClient) -> None:
        """The /openapi.json endpoint is accessible and contains paths."""
        resp = await client.get("/openapi.json")

        assert resp.status_code == 200
        body = resp.json()
        assert "paths" in body
        # Verify our source endpoints are documented
        assert "/api/v1/sources" in body["paths"]

    @pytest.mark.asyncio
    async def test_openapi_contains_source_operations(
        self, client: AsyncClient
    ) -> None:
        """OpenAPI spec documents GET, POST, PATCH, DELETE for sources."""
        resp = await client.get("/openapi.json")

        assert resp.status_code == 200
        body = resp.json()
        sources_path = body["paths"].get("/api/v1/sources", {})
        assert "get" in sources_path, "GET /api/v1/sources not documented"
        assert "post" in sources_path, "POST /api/v1/sources not documented"

        # Check source/{id} operations
        source_id_path = body["paths"].get("/api/v1/sources/{id}", {})
        assert "patch" in source_id_path, "PATCH /api/v1/sources/{id} not documented"
        assert "delete" in source_id_path, "DELETE /api/v1/sources/{id} not documented"
