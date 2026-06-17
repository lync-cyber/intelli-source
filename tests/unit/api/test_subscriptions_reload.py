"""Tests for /subscriptions router endpoints (Phase 1+2 + Layer 1+2)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.deps import get_db_session
from intellisource.api.routers.subscriptions import router


@pytest.fixture()
def mock_session() -> AsyncMock:
    sess = AsyncMock()
    sess.execute = AsyncMock()
    sess.commit = AsyncMock()
    return sess


@pytest.fixture()
def mock_service() -> MagicMock:
    svc = MagicMock()
    svc.bulk_sync_with_version = AsyncMock(
        return_value={"loaded_count": 0, "version": "1", "errors": []}
    )
    svc.rollback_to_version = AsyncMock(
        return_value={
            "rolled_back_to": "1",
            "config_count": 0,
            "subscription_names": [],
        }
    )
    svc.create = AsyncMock()
    svc.patch = AsyncMock()
    svc.delete = AsyncMock(return_value=True)
    return svc


@pytest.fixture()
def app(mock_session: AsyncMock, mock_service: MagicMock) -> FastAPI:
    _app = FastAPI()
    _app.include_router(router, prefix="/api/v1")

    async def _override_session() -> AsyncIterator[Any]:
        yield mock_session

    from intellisource.api.routers.subscriptions import _get_service

    def _override_service() -> MagicMock:
        return mock_service

    _app.dependency_overrides[get_db_session] = _override_session
    _app.dependency_overrides[_get_service] = _override_service
    return _app


# ---------------------------------------------------------------------------
# reload endpoint — thin shell calling service.bulk_sync_with_version
# ---------------------------------------------------------------------------


class TestReloadShell:
    async def test_reload_returns_service_result(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        mock_service.bulk_sync_with_version = AsyncMock(
            return_value={"loaded_count": 3, "version": "1", "errors": []}
        )
        mock_loader = MagicMock()
        mock_loader.load_subscription_configs = MagicMock(
            return_value=["c1", "c2", "c3"]
        )

        with patch(
            "intellisource.api.routers.subscriptions.SubscriptionConfigLoader",
            return_value=mock_loader,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/v1/subscriptions/reload")

        assert response.status_code == 200
        body = response.json()
        assert body == {"loaded_count": 3, "version": "1", "errors": []}
        mock_service.bulk_sync_with_version.assert_awaited_once()

    async def test_loader_scan_failure_short_circuits(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        mock_loader = MagicMock()
        mock_loader.load_subscription_configs = MagicMock(
            side_effect=RuntimeError("scan failed")
        )
        with patch(
            "intellisource.api.routers.subscriptions.SubscriptionConfigLoader",
            return_value=mock_loader,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/v1/subscriptions/reload")

        body = response.json()
        assert body["loaded_count"] == 0
        assert body["errors"][0]["file"] == "(scan)"
        mock_service.bulk_sync_with_version.assert_not_awaited()

    async def test_service_sync_failure_reported(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        mock_service.bulk_sync_with_version = AsyncMock(
            side_effect=RuntimeError("db down")
        )
        mock_loader = MagicMock()
        mock_loader.load_subscription_configs = MagicMock(return_value=["c1"])
        with patch(
            "intellisource.api.routers.subscriptions.SubscriptionConfigLoader",
            return_value=mock_loader,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/v1/subscriptions/reload")

        body = response.json()
        assert body["loaded_count"] == 0
        assert body["errors"][0]["file"] == "(sync)"
        assert "db down" in body["errors"][0]["error"]


# ---------------------------------------------------------------------------
# rollback endpoint — thin shell calling service.rollback_to_version
# ---------------------------------------------------------------------------


class TestRollbackShell:
    async def test_rollback_passes_version_to_service(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        mock_service.rollback_to_version = AsyncMock(
            return_value={
                "rolled_back_to": "3",
                "config_count": 2,
                "subscription_names": ["a", "b"],
            }
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/subscriptions/config/rollback/3")
        assert response.status_code == 200
        assert response.json()["rolled_back_to"] == "3"
        mock_service.rollback_to_version.assert_awaited_once_with("3")

    async def test_rollback_unknown_version_returns_404(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        mock_service.rollback_to_version = AsyncMock(
            side_effect=ValueError("Version '99' not found")
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/subscriptions/config/rollback/99")
        assert response.status_code == 404
        assert "not found" in response.json()["error"]["message"]


# ---------------------------------------------------------------------------
# CRUD endpoints — POST / PATCH / DELETE go through service
# ---------------------------------------------------------------------------


class TestCRUDShell:
    async def test_post_uses_subscription_config_schema(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        # Field set: SubscriptionConfig (full) — `frequency` was unreachable
        # via the old SubscriptionCreateRequest and now must round-trip.
        from datetime import UTC, datetime

        fake_orm = MagicMock()
        fake_orm.id = "00000000-0000-0000-0000-000000000abc"
        fake_orm.name = "new"
        fake_orm.source_id = None
        fake_orm.channel = "wework"
        fake_orm.channel_config = {"user_id": "@all", "msg_type": "text"}
        fake_orm.match_rules = {"tags": ["ai"]}
        fake_orm.frequency = "daily"
        fake_orm.quiet_hours = None
        fake_orm.timezone = "Asia/Shanghai"
        fake_orm.discipline_tags = []
        fake_orm.status = "active"
        fake_orm.created_at = datetime.now(UTC)
        fake_orm.updated_at = datetime.now(UTC)
        mock_service.create = AsyncMock(return_value=fake_orm)

        payload = {
            "name": "new",
            "channel": "wework",
            "channel_config": {"user_id": "@all", "msg_type": "text"},
            "match_rules": {"tags": ["ai"]},
            "frequency": "daily",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/subscriptions", json=payload)
        assert response.status_code == 201
        body = response.json()
        assert body["frequency"] == "daily"
        # Verify service got a parsed SubscriptionConfig
        from intellisource.config.subscription_models import SubscriptionConfig

        passed = mock_service.create.await_args.args[0]
        assert isinstance(passed, SubscriptionConfig)
        assert passed.frequency == "daily"

    async def test_post_validator_failure_returns_422(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        from intellisource.config.subscription_validator import (
            SubscriptionValidationError,
        )

        mock_service.create = AsyncMock(
            side_effect=SubscriptionValidationError("email channel requires to_addr")
        )
        payload = {
            "name": "x",
            "channel": "email",
            "channel_config": {},
            "match_rules": {},
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/subscriptions", json=payload)
        assert response.status_code == 422
        assert "to_addr" in response.json()["error"]["message"]

    async def test_delete_calls_service_returns_204(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        mock_service.delete = AsyncMock(return_value=True)
        sub_id = "00000000-0000-0000-0000-000000000001"
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.delete(f"/api/v1/subscriptions/{sub_id}")
        assert response.status_code == 204
        mock_service.delete.assert_awaited_once()

    async def test_delete_missing_returns_404(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        mock_service.delete = AsyncMock(return_value=False)
        sub_id = "00000000-0000-0000-0000-000000000002"
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.delete(f"/api/v1/subscriptions/{sub_id}")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /{id} + config/versions + config/diff (new read/inspect endpoints)
# ---------------------------------------------------------------------------


def _make_sub_obj() -> MagicMock:
    obj = MagicMock()
    obj.id = "11111111-1111-1111-1111-111111111111"
    obj.name = "digest-sub"
    obj.source_id = None
    obj.channel = "email"
    obj.channel_config = {
        "to_addr": "u@x.com",
        "template_config": {"render_mode": "code"},
    }
    obj.match_rules = {"tags": ["ai"]}
    obj.frequency = "daily"
    obj.quiet_hours = None
    obj.timezone = "Asia/Shanghai"
    obj.discipline_tags = []
    obj.status = "active"
    obj.created_at = "2026-01-01T00:00:00+00:00"
    obj.updated_at = None
    return obj


class TestGetSubscriptionEndpoint:
    async def test_get_returns_serialized_subscription(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        mock_service.get = AsyncMock(return_value=_make_sub_obj())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/subscriptions/11111111-1111-1111-1111-111111111111"
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "digest-sub"
        assert body["channel_config"]["template_config"]["render_mode"] == "code"

    async def test_get_missing_returns_404(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        mock_service.get = AsyncMock(return_value=None)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/subscriptions/22222222-2222-2222-2222-222222222222"
            )
        assert resp.status_code == 404


class TestListVersionsEndpoint:
    async def test_versions_returns_service_list(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        mock_service.list_versions = AsyncMock(
            return_value=[
                {"version": "2", "author": None, "created_at": "t2", "config_count": 3},
                {"version": "1", "author": "x", "created_at": "t1", "config_count": 1},
            ]
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/subscriptions/config/versions")
        assert resp.status_code == 200
        versions = resp.json()["versions"]
        assert [v["version"] for v in versions] == ["2", "1"]
        assert versions[0]["config_count"] == 3


class TestDiffEndpoint:
    async def test_diff_returns_partitioned_names(
        self, app: FastAPI, mock_service: MagicMock
    ) -> None:
        mock_service.diff_with_yaml = AsyncMock(
            return_value={
                "yaml_only": ["fresh"],
                "db_only": ["gone"],
                "both": ["keep"],
                "db_only_action": "pause",
            }
        )
        mock_loader = MagicMock()
        mock_loader.load_subscription_configs = MagicMock(return_value=["c1"])
        with patch(
            "intellisource.api.routers.subscriptions.SubscriptionConfigLoader",
            return_value=mock_loader,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/subscriptions/config/diff")
        assert resp.status_code == 200
        body = resp.json()
        assert body["yaml_only"] == ["fresh"]
        assert body["db_only_action"] == "pause"
        mock_service.diff_with_yaml.assert_awaited_once()
