"""Tests for T-040: Source CRUD API endpoints.

Covers:
  AC-061:     API supports source creation/query/update/delete operations
  AC-065:     FastAPI auto-generates OpenAPI documentation
  AC-T040-1:  GET /api/v1/sources supports pagination and filtering (type/tag/status)
  AC-T040-2:  POST /api/v1/sources creates source (idempotent upsert by name)
  AC-T040-3:  PATCH /api/v1/sources/{id} supports partial updates
  AC-T040-4:  DELETE /api/v1/sources/{id} deletes source (soft, status='paused')
  AC-T040-5:  POST /api/v1/sources/reload reloads configuration from disk
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.deps import get_db_session
from intellisource.api.routers.sources import _get_service, router

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
SOURCE_ID_2 = uuid.UUID("00000000-0000-0000-0000-000000000002")


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
def mock_service() -> MagicMock:
    svc = MagicMock()
    svc.list_paginated = AsyncMock(
        return_value={"items": [], "next_cursor": None, "has_more": False}
    )
    svc.create = AsyncMock(return_value=_make_source_obj())
    svc.patch = AsyncMock(return_value=_make_source_obj())
    svc.delete = AsyncMock(return_value=True)
    svc.bulk_sync_with_version = AsyncMock(
        return_value={"loaded_count": 0, "version": "1", "errors": []}
    )
    svc.rollback_to_version = AsyncMock(
        return_value={"rolled_back_to": "1", "config_count": 0, "source_names": []}
    )
    return svc


@pytest.fixture()
def app(mock_service: MagicMock) -> FastAPI:
    _app = FastAPI()
    _app.include_router(router, prefix="/api/v1")

    async def _override_session() -> AsyncIterator[Any]:
        yield AsyncMock()

    def _override_service() -> MagicMock:
        return mock_service

    _app.dependency_overrides[get_db_session] = _override_session
    _app.dependency_overrides[_get_service] = _override_service
    return _app


@pytest.fixture()
async def client(app: FastAPI) -> AsyncClient:  # type: ignore[misc]
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
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Default GET returns items list with pagination metadata."""
        mock_service.list_paginated = AsyncMock(
            return_value={
                "items": [_make_source_obj()],
                "next_cursor": None,
                "has_more": False,
            }
        )

        resp = await client.get("/api/v1/sources")

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "next_cursor" in body
        assert "has_more" in body
        assert isinstance(body["items"], list)
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "test-source"

    @pytest.mark.asyncio
    async def test_list_sources_filter_by_type(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Filtering by type=rss forwards the parameter to the service."""
        resp = await client.get("/api/v1/sources", params={"type": "rss"})

        assert resp.status_code == 200
        mock_service.list_paginated.assert_called_once()
        assert mock_service.list_paginated.call_args.kwargs.get("type") == "rss"

    @pytest.mark.asyncio
    async def test_list_sources_filter_by_tag(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Filtering by tag forwards the parameter to the service."""
        resp = await client.get("/api/v1/sources", params={"tag": "news"})

        assert resp.status_code == 200
        assert mock_service.list_paginated.call_args.kwargs.get("tag") == "news"

    @pytest.mark.asyncio
    async def test_list_sources_filter_by_status(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Filtering by status forwards the parameter to the service."""
        resp = await client.get("/api/v1/sources", params={"status": "paused"})

        assert resp.status_code == 200
        assert mock_service.list_paginated.call_args.kwargs.get("status") == "paused"

    @pytest.mark.asyncio
    async def test_list_sources_pagination_cursor_and_limit(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Cursor and limit params are forwarded to the service."""
        mock_service.list_paginated = AsyncMock(
            return_value={
                "items": [_make_source_obj(id=SOURCE_ID_2)],
                "next_cursor": str(SOURCE_ID_2),
                "has_more": True,
            }
        )

        resp = await client.get(
            "/api/v1/sources",
            params={"cursor": str(SOURCE_ID), "limit": 10},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_more"] is True
        assert body["next_cursor"] == str(SOURCE_ID_2)
        call_kwargs = mock_service.list_paginated.call_args.kwargs
        assert call_kwargs.get("cursor") == str(SOURCE_ID)
        assert call_kwargs.get("limit") == 10

    @pytest.mark.asyncio
    async def test_list_sources_limit_capped_at_100(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Limit values above 100 are capped before reaching the service."""
        resp = await client.get("/api/v1/sources", params={"limit": 200})

        assert resp.status_code == 200
        assert mock_service.list_paginated.call_args.kwargs.get("limit") == 100


# ===========================================================================
# AC-T040-2: POST /api/v1/sources — idempotent upsert by name
# ===========================================================================


class TestSourceCreateEndpoint:
    """AC-T040-2: POST /api/v1/sources upserts a source by name."""

    @pytest.mark.asyncio
    async def test_create_source_success(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Successful upsert returns 201 with id, name, type, status, created_at."""
        mock_service.create = AsyncMock(return_value=_make_source_obj())

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
        assert body["status"] == "active"
        assert "created_at" in body

    @pytest.mark.asyncio
    async def test_create_source_with_optional_fields(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Creation with all SourceConfig fields succeeds (flat schema)."""
        mock_service.create = AsyncMock(
            return_value=_make_source_obj(tags=["news", "tech"])
        )

        resp = await client.post(
            "/api/v1/sources",
            json={
                "name": "test-source",
                "type": "rss",
                "url": "https://example.com/feed",
                "tags": ["news", "tech"],
                "schedule_interval": 1800,
                "schedule_adaptive": False,
                "proxy": "http://proxy:8080",
                "rate_limit_qps": 2.0,
                "rate_limit_concurrency": 5,
                "metadata": {"key": "value"},
            },
        )

        assert resp.status_code == 201
        # Service must have received a parsed SourceConfig with those fields.
        passed_cfg = mock_service.create.call_args.args[0]
        assert passed_cfg.schedule_interval == 1800
        assert passed_cfg.schedule_adaptive is False
        assert passed_cfg.rate_limit_qps == 2.0
        assert passed_cfg.rate_limit_concurrency == 5
        assert passed_cfg.metadata == {"key": "value"}

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
    async def test_partial_update_success(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Partial update with only name returns 200 with updated source."""
        mock_service.patch = AsyncMock(
            return_value=_make_source_obj(name="updated-name")
        )

        resp = await client.patch(
            f"/api/v1/sources/{SOURCE_ID}",
            json={"name": "updated-name"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "updated-name"
        call_kwargs = mock_service.patch.call_args
        assert call_kwargs.args[1] == {"name": "updated-name"}

    @pytest.mark.asyncio
    async def test_partial_update_multiple_fields(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Updating multiple fields at once (tags, status, url)."""
        mock_service.patch = AsyncMock(
            return_value=_make_source_obj(
                tags=["updated"], status="paused", url="https://new.example.com"
            )
        )

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
        assert body["tags"] == ["updated"]

    @pytest.mark.asyncio
    async def test_update_not_found_404(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Updating a non-existent source returns 404."""
        mock_service.patch = AsyncMock(return_value=None)

        nonexistent_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        resp = await client.patch(
            f"/api/v1/sources/{nonexistent_id}",
            json={"name": "nope"},
        )

        assert resp.status_code == 404


# ===========================================================================
# AC-T040-4: DELETE /api/v1/sources/{id}
# ===========================================================================


class TestSourceDeleteEndpoint:
    """AC-T040-4: DELETE /api/v1/sources/{id} soft-deletes a source."""

    @pytest.mark.asyncio
    async def test_delete_success_204(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Deleting an existing source returns 204 No Content."""
        mock_service.delete = AsyncMock(return_value=True)

        resp = await client.delete(f"/api/v1/sources/{SOURCE_ID}")

        assert resp.status_code == 204
        assert resp.content == b""

    @pytest.mark.asyncio
    async def test_delete_not_found_404(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Deleting a non-existent source returns 404."""
        mock_service.delete = AsyncMock(return_value=False)

        nonexistent_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        resp = await client.delete(f"/api/v1/sources/{nonexistent_id}")

        assert resp.status_code == 404


# ===========================================================================
# AC-T040-5: POST /api/v1/sources/reload
# ===========================================================================


class TestSourceReloadEndpoint:
    """AC-T040-5: POST /api/v1/sources/reload reloads configuration from disk."""

    @pytest.mark.asyncio
    async def test_reload_success(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Successful reload returns 200 with loaded_count and version."""
        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=["c1", "c2", "c3"])
        mock_service.bulk_sync_with_version = AsyncMock(
            return_value={"loaded_count": 3, "version": "1", "errors": []}
        )

        with patch(
            "intellisource.api.routers.sources.ConfigLoader",
            return_value=mock_loader,
        ):
            resp = await client.post("/api/v1/sources/reload")

        assert resp.status_code == 200
        body = resp.json()
        assert body["loaded_count"] == 3
        assert body["version"] == "1"
        assert body["errors"] == []
        mock_service.bulk_sync_with_version.assert_awaited_once()


# ===========================================================================
# POST /api/v1/sources/config/rollback/{version}
# ===========================================================================


class TestSourceRollbackEndpoint:
    """rollback endpoint forwards to service.rollback_to_version."""

    @pytest.mark.asyncio
    async def test_rollback_returns_service_summary(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """Successful rollback returns 200 with service summary dict."""
        mock_service.rollback_to_version = AsyncMock(
            return_value={
                "rolled_back_to": "2",
                "config_count": 1,
                "source_names": ["src-a"],
            }
        )

        resp = await client.post("/api/v1/sources/config/rollback/2")

        assert resp.status_code == 200
        body = resp.json()
        assert body["rolled_back_to"] == "2"
        assert body["config_count"] == 1
        assert body["source_names"] == ["src-a"]
        mock_service.rollback_to_version.assert_awaited_once_with("2")

    @pytest.mark.asyncio
    async def test_rollback_unknown_version_404(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        """ValueError from service (unknown version) becomes 404."""
        mock_service.rollback_to_version = AsyncMock(
            side_effect=ValueError("version 99 not found")
        )

        resp = await client.post("/api/v1/sources/config/rollback/99")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]


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
        assert "get" in sources_path
        assert "post" in sources_path
        item_path = body["paths"].get("/api/v1/sources/{id}", {})
        assert "patch" in item_path
        assert "delete" in item_path


# ===========================================================================
# GET /{id} + config/versions + config/diff (new read/inspect endpoints)
# ===========================================================================


class TestGetSourceEndpoint:
    @pytest.mark.asyncio
    async def test_get_returns_serialized_source(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        mock_service.get = AsyncMock(return_value=_make_source_obj())
        resp = await client.get(f"/api/v1/sources/{SOURCE_ID}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-source"

    @pytest.mark.asyncio
    async def test_get_missing_returns_404(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        mock_service.get = AsyncMock(return_value=None)
        resp = await client.get(f"/api/v1/sources/{SOURCE_ID_2}")
        assert resp.status_code == 404


class TestSourceVersionsEndpoint:
    @pytest.mark.asyncio
    async def test_versions_returns_service_list(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        mock_service.list_versions = AsyncMock(
            return_value=[
                {"version": "2", "author": None, "created_at": "t2", "config_count": 5},
            ]
        )
        resp = await client.get("/api/v1/sources/config/versions")
        assert resp.status_code == 200
        versions = resp.json()["versions"]
        assert versions[0]["version"] == "2"
        assert versions[0]["config_count"] == 5


class TestSourceDiffEndpoint:
    @pytest.mark.asyncio
    async def test_diff_marks_db_only_preserve(
        self, client: AsyncClient, mock_service: MagicMock
    ) -> None:
        mock_service.diff_with_yaml = AsyncMock(
            return_value={
                "yaml_only": ["fresh"],
                "db_only": ["kept"],
                "both": [],
                "db_only_action": "preserve",
            }
        )
        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=["c1"])
        with patch(
            "intellisource.api.routers.sources.ConfigLoader",
            return_value=mock_loader,
        ):
            resp = await client.get("/api/v1/sources/config/diff")
        assert resp.status_code == 200
        body = resp.json()
        assert body["db_only_action"] == "preserve"
        assert body["db_only"] == ["kept"]
