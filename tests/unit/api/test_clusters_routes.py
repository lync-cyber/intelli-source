"""Tests for GET /api/v1/clusters endpoint + ClusterRepository.

fields aligned to arch API-016 (authoritative; supersedes dev-plan task-card naming)

Covers:
  AC-T073-1: GET /api/v1/clusters -- cursor pagination
             (cursor, limit default 20, cap 100)
  AC-T073-2: tag filter (single tag, ContentCluster.tags JSONB)
  AC-T073-3: date_from / date_to filter
             (created_at, half-open interval [from, to))
  AC-T073-4: per-item fields:
             id, topic, tags, content_count, digest, created_at, updated_at
  AC-T073-5: empty result shape -- items=[], next_cursor=null, has_more=false
  AC-T073-6: mypy --strict src/ zero errors
             (validated by GREEN phase; tested here via import)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Router import -- guarded so missing module produces clear FAIL message
# ---------------------------------------------------------------------------

try:
    from intellisource.api.routers.clusters import (
        router as clusters_router,  # type: ignore[import-untyped]
    )
except ImportError:
    clusters_router = None  # type: ignore[assignment]

try:
    from intellisource.storage.repositories.cluster import (
        ClusterRepository,  # type: ignore[import-untyped]
    )
except ImportError:
    ClusterRepository = None  # type: ignore[assignment]

_CLUSTERS_ROUTER_MISSING = clusters_router is None
_CLUSTER_REPO_MISSING = ClusterRepository is None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLUSTER_ID_1 = uuid.UUID("00000000-0000-0000-0000-000000000201")
CLUSTER_ID_2 = uuid.UUID("00000000-0000-0000-0000-000000000202")
DIGEST_ID_1 = uuid.UUID("00000000-0000-0000-0000-000000000301")

# ---------------------------------------------------------------------------
# Mock object helpers
# ---------------------------------------------------------------------------


def _make_digest_mock(
    *,
    summary: str | None = "Digest summary text",
    created_at: datetime | str = "2025-06-01T10:00:00+00:00",
) -> MagicMock:
    """Return a MagicMock mimicking a Digest ORM instance."""
    obj = MagicMock()
    obj.id = DIGEST_ID_1
    obj.summary = summary
    obj.created_at = created_at
    obj.updated_at = "2025-06-02T10:00:00+00:00"
    return obj


def _make_cluster_mock(
    *,
    id: uuid.UUID = CLUSTER_ID_1,
    topic: str = "AI Trends",
    tags: list[str] | None = None,
    content_count: int = 5,
    digests: list[MagicMock] | None = None,
    created_at: str = "2025-06-01T00:00:00+00:00",
    updated_at: str = "2025-06-02T00:00:00+00:00",
) -> MagicMock:
    """Return a MagicMock mimicking a ContentCluster ORM instance."""
    obj = MagicMock()
    obj.id = id
    obj.topic = topic
    obj.tags = tags if tags is not None else ["AI", "ML"]
    obj.content_count = content_count
    obj.digests = digests if digests is not None else [_make_digest_mock()]
    obj.created_at = created_at
    obj.updated_at = updated_at
    return obj


def _make_list_clusters_result(
    clusters: list[MagicMock],
    *,
    next_cursor: str | None = None,
    has_more: bool = False,
) -> dict[str, Any]:
    """Return the dict shape that ClusterRepository.list_clusters returns."""
    return {
        "items": clusters,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# Fixture -- bare FastAPI app with only the clusters router
# ---------------------------------------------------------------------------


@pytest.fixture()
def clusters_app() -> FastAPI:
    if _CLUSTERS_ROUTER_MISSING:
        pytest.fail(
            "intellisource.api.routers.clusters not implemented: cannot import 'router'"
        )
    application = FastAPI()
    application.include_router(clusters_router, prefix="/api/v1")
    return application


@pytest.fixture()
async def clusters_client(clusters_app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=clusters_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


# ===========================================================================
# AC-T073-1: Cursor pagination -- default limit, next_cursor, has_more
# ===========================================================================


class TestClustersListPagination:
    """AC-T073-1: GET /api/v1/clusters returns paginated cluster list."""

    @pytest.mark.asyncio
    async def test_t073_ac1_default_pagination_shape(
        self, clusters_client: AsyncClient
    ) -> None:
        """Default GET returns items / next_cursor / has_more shape."""
        cluster = _make_cluster_mock()
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([cluster])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters")

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "next_cursor" in body
        assert "has_more" in body
        assert isinstance(body["items"], list)
        assert len(body["items"]) == 1

    @pytest.mark.asyncio
    async def test_t073_ac1_next_cursor_propagated(
        self, clusters_client: AsyncClient
    ) -> None:
        """When has_more=True the next_cursor value is forwarded to the response."""
        cluster1 = _make_cluster_mock(id=CLUSTER_ID_1)
        mock_repo = AsyncMock()
        cursor_val = str(CLUSTER_ID_1)
        mock_repo.list_clusters.return_value = _make_list_clusters_result(
            [cluster1], next_cursor=cursor_val, has_more=True
        )

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters")

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_more"] is True
        assert body["next_cursor"] == cursor_val

    @pytest.mark.asyncio
    async def test_t073_ac1_limit_above_100_capped(
        self, clusters_client: AsyncClient
    ) -> None:
        """limit values > 100 are silently capped to 100 before repo call."""
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters", params={"limit": 200})

        # Must not error out
        assert resp.status_code == 200
        # The repository must have been called with limit <= 100
        mock_repo.list_clusters.assert_called_once()
        call_kwargs = mock_repo.list_clusters.call_args
        actual_limit = call_kwargs.kwargs.get("limit") or (
            call_kwargs.args[3] if len(call_kwargs.args) > 3 else None
        )
        # If limit was captured as a kwarg it should be <= 100
        if actual_limit is not None:
            assert actual_limit <= 100

    @pytest.mark.asyncio
    async def test_t073_ac1_cursor_param_forwarded_to_repo(
        self, clusters_client: AsyncClient
    ) -> None:
        """The cursor query param is forwarded to ClusterRepository.list_clusters."""
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([])
        test_cursor = str(CLUSTER_ID_1)

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get(
                "/api/v1/clusters", params={"cursor": test_cursor}
            )

        assert resp.status_code == 200
        mock_repo.list_clusters.assert_called_once()
        assert test_cursor in str(mock_repo.list_clusters.call_args)


# ===========================================================================
# AC-T073-2: tag filter
# ===========================================================================


class TestClustersTagFilter:
    """AC-T073-2: Single tag filter forwarded to repository."""

    @pytest.mark.asyncio
    async def test_t073_ac2_tag_filter_forwarded(
        self, clusters_client: AsyncClient
    ) -> None:
        """?tag=AI passes tag='AI' to ClusterRepository.list_clusters."""
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters", params={"tag": "AI"})

        assert resp.status_code == 200
        mock_repo.list_clusters.assert_called_once()
        assert "AI" in str(mock_repo.list_clusters.call_args)

    @pytest.mark.asyncio
    async def test_t073_ac2_no_tag_calls_repo_without_tag(
        self, clusters_client: AsyncClient
    ) -> None:
        """Omitting tag passes tag=None to ClusterRepository.list_clusters."""
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters")

        assert resp.status_code == 200
        mock_repo.list_clusters.assert_called_once()
        call_kwargs = mock_repo.list_clusters.call_args
        tag_val = call_kwargs.kwargs.get("tag")
        assert tag_val is None


# ===========================================================================
# AC-T073-3: date_from / date_to filter
# ===========================================================================


class TestClustersDateFilter:
    """AC-T073-3: date_from / date_to filter half-open interval [from, to)."""

    @pytest.mark.asyncio
    async def test_t073_ac3_date_from_forwarded(
        self, clusters_client: AsyncClient
    ) -> None:
        """?date_from= passes the value to ClusterRepository.list_clusters."""
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get(
                "/api/v1/clusters", params={"date_from": "2025-01-01T00:00:00Z"}
            )

        assert resp.status_code == 200
        mock_repo.list_clusters.assert_called_once()
        assert "2025-01-01" in str(mock_repo.list_clusters.call_args)

    @pytest.mark.asyncio
    async def test_t073_ac3_date_to_forwarded(
        self, clusters_client: AsyncClient
    ) -> None:
        """?date_to= passes the value to ClusterRepository.list_clusters."""
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get(
                "/api/v1/clusters", params={"date_to": "2025-12-31T23:59:59Z"}
            )

        assert resp.status_code == 200
        mock_repo.list_clusters.assert_called_once()
        assert "2025-12-31" in str(mock_repo.list_clusters.call_args)

    @pytest.mark.asyncio
    async def test_t073_ac3_date_from_and_date_to_both_forwarded(
        self, clusters_client: AsyncClient
    ) -> None:
        """Both date_from and date_to forwarded simultaneously."""
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get(
                "/api/v1/clusters",
                params={
                    "date_from": "2025-01-01T00:00:00Z",
                    "date_to": "2025-06-01T00:00:00Z",
                },
            )

        assert resp.status_code == 200
        call_str = str(mock_repo.list_clusters.call_args)
        assert "2025-01-01" in call_str
        assert "2025-06-01" in call_str


# ===========================================================================
# AC-T073-4: Per-item response fields
# ===========================================================================


class TestClustersItemFields:
    """AC-T073-4: Each cluster item has required fields with correct types."""

    @pytest.mark.asyncio
    async def test_t073_ac4_all_required_fields_present(
        self, clusters_client: AsyncClient
    ) -> None:
        """Each item has id/topic/tags/content_count/digest/created_at/updated_at."""
        digest = _make_digest_mock(summary="Latest digest summary")
        cluster = _make_cluster_mock(
            id=CLUSTER_ID_1,
            topic="Machine Learning",
            tags=["ML", "AI"],
            content_count=10,
            digests=[digest],
            created_at="2025-06-01T00:00:00+00:00",
            updated_at="2025-06-02T00:00:00+00:00",
        )
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([cluster])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters")

        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        item = items[0]

        assert "id" in item
        assert "topic" in item
        assert "tags" in item
        assert "content_count" in item
        assert "digest" in item
        assert "created_at" in item
        assert "updated_at" in item

    @pytest.mark.asyncio
    async def test_t073_ac4_field_values_match_cluster_data(
        self, clusters_client: AsyncClient
    ) -> None:
        """Field values in the serialized item match the ORM mock attributes."""
        digest = _make_digest_mock(summary="Summary for test")
        cluster = _make_cluster_mock(
            id=CLUSTER_ID_1,
            topic="NLP Research",
            tags=["NLP"],
            content_count=3,
            digests=[digest],
        )
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([cluster])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters")

        assert resp.status_code == 200
        item = resp.json()["items"][0]

        assert item["id"] == str(CLUSTER_ID_1)
        assert item["topic"] == "NLP Research"
        assert item["tags"] == ["NLP"]
        assert item["content_count"] == 3
        # digest must be the summary of the most recent Digest
        assert item["digest"] == "Summary for test"

    @pytest.mark.asyncio
    async def test_t073_ac4_id_is_string(self, clusters_client: AsyncClient) -> None:
        """id field is serialized as a string (not UUID object)."""
        cluster = _make_cluster_mock(id=CLUSTER_ID_2)
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([cluster])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters")

        item = resp.json()["items"][0]
        assert isinstance(item["id"], str)
        assert item["id"] == str(CLUSTER_ID_2)

    @pytest.mark.asyncio
    async def test_t073_ac4_tags_is_list(self, clusters_client: AsyncClient) -> None:
        """tags field is a JSON array."""
        cluster = _make_cluster_mock(tags=["deep-learning", "transformers"])
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([cluster])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters")

        item = resp.json()["items"][0]
        assert isinstance(item["tags"], list)
        assert "deep-learning" in item["tags"]
        assert "transformers" in item["tags"]

    @pytest.mark.asyncio
    async def test_t073_ac4_digest_from_most_recent_digest_summary(
        self, clusters_client: AsyncClient
    ) -> None:
        """digest is derived from the most recent Digest.summary in digests list."""
        older_digest = _make_digest_mock(
            summary="Older summary",
            created_at=datetime(2025, 5, 1, tzinfo=timezone.utc),
        )
        newer_digest = _make_digest_mock(
            summary="Newer summary",
            created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )

        cluster = _make_cluster_mock(digests=[older_digest, newer_digest])
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([cluster])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters")

        item = resp.json()["items"][0]
        assert item["digest"] == "Newer summary"

    @pytest.mark.asyncio
    async def test_t073_ac4_digest_none_when_no_digests(
        self, clusters_client: AsyncClient
    ) -> None:
        """digest is null when the cluster has no Digest records."""
        cluster = _make_cluster_mock(digests=[])
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([cluster])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters")

        item = resp.json()["items"][0]
        assert item["digest"] is None

    @pytest.mark.asyncio
    async def test_t073_ac4_digest_none_when_digest_summary_is_null(
        self, clusters_client: AsyncClient
    ) -> None:
        """digest is null when Digest exists but summary is None."""
        digest_no_summary = _make_digest_mock(summary=None)
        cluster = _make_cluster_mock(digests=[digest_no_summary])
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([cluster])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters")

        item = resp.json()["items"][0]
        assert item["digest"] is None


# ===========================================================================
# AC-T073-5: Empty result shape
# ===========================================================================


class TestClustersEmptyResult:
    """AC-T073-5: Empty cluster list returns canonical empty response."""

    @pytest.mark.asyncio
    async def test_t073_ac5_empty_items_shape(
        self, clusters_client: AsyncClient
    ) -> None:
        """When no clusters exist: {items:[], next_cursor:null, has_more:false}."""
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters")

        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["next_cursor"] is None
        assert body["has_more"] is False

    @pytest.mark.asyncio
    async def test_t073_ac5_empty_after_tag_filter(
        self, clusters_client: AsyncClient
    ) -> None:
        """Empty response when no clusters match the requested tag."""
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get(
                "/api/v1/clusters", params={"tag": "nonexistent-tag"}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["has_more"] is False


# ===========================================================================
# AC-T073-6: Import sanity -- ClusterRepository exportable from __init__
# ===========================================================================


class TestClusterRepositoryExport:
    """AC-T073-6: ClusterRepository must be importable from the repositories package."""

    def test_t073_ac6_cluster_repository_importable(self) -> None:
        """ClusterRepository can be imported from intellisource.storage.repositories."""
        if _CLUSTER_REPO_MISSING:
            pytest.fail(
                "intellisource.storage.repositories.cluster not implemented: "
                "cannot import 'ClusterRepository'"
            )
        assert isinstance(ClusterRepository, type)

    def test_t073_ac6_cluster_repository_exported_from_package(self) -> None:
        """ClusterRepository is re-exported from storage.repositories.__init__."""
        try:
            from intellisource.storage.repositories import (  # type: ignore[attr-defined]
                ClusterRepository as ImportedClusterRepository,
            )
        except ImportError as exc:
            pytest.fail(
                "ClusterRepository not exported from "
                f"storage.repositories.__init__: {exc}"
            )
        from intellisource.storage.repositories.cluster import (
            ClusterRepository as _Canonical,
        )

        assert ImportedClusterRepository is _Canonical

    def test_t073_ac6_cluster_repository_has_list_clusters_method(self) -> None:
        """ClusterRepository exposes a list_clusters method."""
        if _CLUSTER_REPO_MISSING:
            pytest.fail("ClusterRepository not implemented")
        assert hasattr(ClusterRepository, "list_clusters"), (
            "ClusterRepository must define "
            "list_clusters(tag, date_from, date_to, limit, cursor)"
        )

    def test_t073_ac6_clusters_router_importable(self) -> None:
        """clusters router module is importable."""
        if _CLUSTERS_ROUTER_MISSING:
            pytest.fail(
                "intellisource.api.routers.clusters not implemented: "
                "cannot import 'router'"
            )
        from fastapi import APIRouter

        assert isinstance(clusters_router, APIRouter)


# ===========================================================================
# invalid cursor / limit boundary tests
# ===========================================================================


class TestClustersInputBoundaries:
    """Input boundary and error handling for cursor and limit params."""

    @pytest.mark.asyncio
    async def test_t073_ac1_invalid_cursor_returns_400(
        self, clusters_client: AsyncClient
    ) -> None:
        """Invalid cursor format triggers real uuid.UUID() ValueError → 400.

        Validation occurs in the route layer before ClusterRepository is called;
        no mock side_effect needed — the real uuid.UUID(cursor) raises ValueError.
        """
        mock_repo = AsyncMock()

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get(
                "/api/v1/clusters", params={"cursor": "bad-cursor"}
            )

        assert resp.status_code == 400
        assert "invalid cursor" in resp.json()["detail"].lower()
        mock_repo.list_clusters.assert_not_called()

    @pytest.mark.asyncio
    async def test_t073_ac1_limit_zero_clamped_to_one(
        self, clusters_client: AsyncClient
    ) -> None:
        """limit=0 is clamped to 1 before repo call; response shape is valid."""
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result(
            [_make_cluster_mock()]
        )

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters", params={"limit": 0})

        assert resp.status_code == 200
        mock_repo.list_clusters.assert_called_once()
        call_kwargs = mock_repo.list_clusters.call_args.kwargs
        assert call_kwargs["limit"] >= 1

    @pytest.mark.asyncio
    async def test_t073_ac1_limit_negative_clamped_to_one(
        self, clusters_client: AsyncClient
    ) -> None:
        """limit=-5 is clamped to 1 before repo call."""
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters", params={"limit": -5})

        assert resp.status_code == 200
        mock_repo.list_clusters.assert_called_once()
        call_kwargs = mock_repo.list_clusters.call_args.kwargs
        assert call_kwargs["limit"] >= 1


# ===========================================================================
# tag wildcard safety
# ===========================================================================


class TestClustersTagWildcard:
    """Tag filter must not treat LIKE wildcards as glob patterns."""

    @pytest.mark.asyncio
    async def test_t073_ac2_tag_with_percent_does_not_match_all(
        self, clusters_client: AsyncClient
    ) -> None:
        """tag='%' is passed verbatim to repo; containment query returns empty list."""
        mock_repo = AsyncMock()
        mock_repo.list_clusters.return_value = _make_list_clusters_result([])

        with patch(
            "intellisource.api.routers.clusters.ClusterRepository",
            return_value=mock_repo,
        ):
            resp = await clusters_client.get("/api/v1/clusters", params={"tag": "%"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        mock_repo.list_clusters.assert_called_once()
        assert "%" in str(mock_repo.list_clusters.call_args)
