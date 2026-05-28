"""RED tests for B-058b: POST /sources/config/rollback/{version} must write DB.

Current implementation (routers/sources.py:224-249) calls
rollback_by_label then returns the config list directly — it NEVER calls
bulk_sync_from_configs to write the snapshot back to the database.

These tests verify the missing behaviour and are expected to FAIL in RED phase.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.deps import get_db_session
from intellisource.api.routers.sources import router


@pytest.fixture()
def mock_session() -> AsyncMock:
    sess = AsyncMock()
    sess.execute = AsyncMock()
    sess.commit = AsyncMock()
    return sess


@pytest.fixture()
def app(mock_session: AsyncMock) -> FastAPI:
    _app = FastAPI()
    _app.include_router(router, prefix="/api/v1")

    async def _override_session() -> AsyncIterator[Any]:
        yield mock_session

    _app.dependency_overrides[get_db_session] = _override_session
    return _app


class TestRollbackEndpointRestoresDb:
    async def test_rollback_endpoint_calls_bulk_sync_from_configs_after_snapshot_load(
        self, app: FastAPI
    ) -> None:
        """B-058b: rollback endpoint must call bulk_sync_from_configs to write back.

        The current router implementation returns the snapshot dict directly
        without calling bulk_sync_from_configs / SourceRepository at all.
        This test will FAIL until the router is updated to use SourceConfigService.
        """
        from intellisource.config.models import SourceConfig

        snap_a = SourceConfig(
            name="src-a", type="rss", url="https://example.com/src-a.rss", tags=["x"]
        )
        snap_b = SourceConfig(
            name="src-b", type="rss", url="https://example.com/src-b.rss", tags=["x"]
        )

        mock_repo = AsyncMock()
        mock_repo.bulk_sync_from_configs = AsyncMock()

        mock_manager = MagicMock()
        mock_manager.rollback_by_label = AsyncMock(return_value=[snap_a, snap_b])

        with (
            patch(
                "intellisource.api.routers.sources.ConfigVersionManager",
                return_value=mock_manager,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/v1/sources/config/rollback/1")

        assert response.status_code == 200, (
            f"rollback must return 200; got {response.status_code}: {response.text}"
        )
        # Core B-058b assertion: bulk_sync_from_configs must be called by the
        # rollback endpoint to actually write the snapshot back to DB
        # (current implementation never calls it — this is the B-058b real bug)
        mock_repo.bulk_sync_from_configs.assert_awaited_once()
        call_args = mock_repo.bulk_sync_from_configs.await_args
        passed = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("configs")
        )
        assert passed is not None and len(passed) == 2, (
            f"bulk_sync_from_configs must receive both snapshot configs; got {passed}"
        )

    async def test_rollback_endpoint_returns_summary_with_config_count_and_names(
        self, app: FastAPI
    ) -> None:
        """B-058b: rollback response must include config_count and source_names.

        Current implementation returns a dict with those fields but does not
        write to DB; the service-based version will do both.
        This test verifies the response schema contract from the AC.
        """
        from intellisource.config.models import SourceConfig

        snap_a = SourceConfig(
            name="src-rollback-a",
            type="rss",
            url="https://example.com/a.rss",
            tags=["x"],
        )

        mock_repo = AsyncMock()
        mock_repo.bulk_sync_from_configs = AsyncMock()

        mock_manager = MagicMock()
        mock_manager.rollback_by_label = AsyncMock(return_value=[snap_a])

        with (
            patch(
                "intellisource.api.routers.sources.ConfigVersionManager",
                return_value=mock_manager,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/v1/sources/config/rollback/2")

        data = response.json()
        assert data.get("rolled_back_to") == "2", (
            f"rolled_back_to must be '2'; got '{data.get('rolled_back_to')}'"
        )
        assert data.get("config_count") == 1, (
            f"config_count must be 1; got {data.get('config_count')}"
        )
        assert "source_names" in data, "'source_names' must be present in response"
        assert data["source_names"] == ["src-rollback-a"], (
            f"source_names must contain 'src-rollback-a'; got {data['source_names']}"
        )
        # Also verify bulk_sync was called (DB was updated)
        mock_repo.bulk_sync_from_configs.assert_awaited_once()
