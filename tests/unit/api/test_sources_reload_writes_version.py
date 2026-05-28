"""RED tests for B-058a: POST /sources/reload must write a version snapshot.

Current implementation (routers/sources.py reload_source_configs) calls
bulk_upsert but does NOT call ConfigVersionManager.record_version_async.
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


def _make_source_config(name: str = "test-source") -> MagicMock:
    cfg = MagicMock()
    cfg.name = name
    return cfg


class TestReloadEndpointWritesVersion:
    async def test_reload_writes_record_version_after_bulk_upsert(
        self, app: FastAPI
    ) -> None:
        """B-058a: reload must call record_version_async once with validated configs.

        Current reload_source_configs does NOT call record_version_async.
        This test will FAIL until the implementation is updated.
        """
        config_a = _make_source_config("source-a")
        config_b = _make_source_config("source-b")

        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[config_a, config_b])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=lambda cfg: cfg)
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        mock_version_manager = MagicMock()
        mock_version_manager.record_version_async = AsyncMock(return_value="1")

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigVersionManager",
                return_value=mock_version_manager,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/sources/reload", json={"config_name": None}
                )

        assert response.status_code == 200, (
            f"reload must return 200; got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert data.get("loaded_count") == 2, (
            f"loaded_count must be 2; got {data.get('loaded_count')}"
        )
        assert data.get("errors") == [], (
            f"errors must be empty; got {data.get('errors')}"
        )
        # Core B-058a assertion: record_version_async must be called once
        # (current implementation does NOT call it — this is the B-058a gap)
        mock_version_manager.record_version_async.assert_awaited_once()
        call_kwargs = mock_version_manager.record_version_async.await_args
        # The configs argument (positional or keyword) must have 2 items
        passed_configs = (
            call_kwargs.args[0]
            if call_kwargs.args
            else call_kwargs.kwargs.get("configs", call_kwargs.kwargs.get(0))
        )
        assert passed_configs is not None and len(passed_configs) == 2, (
            "record_version_async must be called with the 2 validated configs; "
            f"got {passed_configs}"
        )

    async def test_reload_response_includes_version_field(self, app: FastAPI) -> None:
        """B-058a schema: response body must contain a non-empty 'version' field.

        Current response shape: {loaded_count, errors}.  After the fix it must
        also include {version}.  This test will FAIL until implemented.
        """
        config_a = _make_source_config("source-a")

        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[config_a])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=lambda cfg: cfg)
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        mock_version_manager = MagicMock()
        mock_version_manager.record_version_async = AsyncMock(return_value="1")

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigVersionManager",
                return_value=mock_version_manager,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/sources/reload", json={"config_name": None}
                )

        data = response.json()
        assert "version" in data, (
            "'version' field must be present in reload response body. "
            f"Current response shape: {list(data.keys())}. "
            "This is the B-058a gap — record_version_async result is not returned."
        )
        assert data["version"] != "" and data["version"] is not None, (
            f"'version' must be a non-empty string; got '{data['version']}'"
        )
