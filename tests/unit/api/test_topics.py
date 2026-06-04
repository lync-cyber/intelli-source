"""Tests for the /topics API endpoints (built-in topic catalog)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.routers.topics import _get_service, router
from intellisource.config.subscription_validator import SubscriptionValidationError
from intellisource.topic.service import TopicNotFoundError, TopicService


def _make_app(service: TopicService) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[_get_service] = lambda: service
    return app


def _real_service() -> TopicService:
    # list_topics / get_topic only touch the loader, not the DB.
    return TopicService(MagicMock())


@pytest.fixture()
async def client_factory():
    clients: list[AsyncClient] = []

    def _make(service: TopicService) -> AsyncClient:
        app = _make_app(service)
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        return c

    yield _make
    for c in clients:
        await c.aclose()


class TestListTopics:
    async def test_list_returns_builtin_catalog(self, client_factory: Any) -> None:
        client = client_factory(_real_service())
        resp = await client.get("/api/v1/topics")
        assert resp.status_code == 200
        items = resp.json()["items"]
        ids = {i["id"] for i in items}
        assert "electrical-engineering" in ids
        assert "artificial-intelligence" in ids
        assert len(items) == 6

    async def test_list_items_expose_dimension_and_source_count(
        self, client_factory: Any
    ) -> None:
        client = client_factory(_real_service())
        resp = await client.get("/api/v1/topics")
        item = next(
            i for i in resp.json()["items"] if i["id"] == "artificial-intelligence"
        )
        assert item["dimension"] == "industry"
        assert item["source_count"] >= 1


class TestGetTopic:
    async def test_get_topic_detail_includes_sources(self, client_factory: Any) -> None:
        client = client_factory(_real_service())
        resp = await client.get("/api/v1/topics/electrical-engineering")
        assert resp.status_code == 200
        body = resp.json()
        assert body["dimension"] == "discipline"
        assert len(body["sources"]) >= 1
        assert body["subscription_template"] is not None

    async def test_get_unknown_topic_returns_404(self, client_factory: Any) -> None:
        client = client_factory(_real_service())
        resp = await client.get("/api/v1/topics/nope")
        assert resp.status_code == 404


class TestEnableTopic:
    async def test_enable_returns_service_payload(self, client_factory: Any) -> None:
        service = _real_service()
        service.enable = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "topic_id": "technology",
                "sources_loaded": 3,
                "subscription": {
                    "id": "x",
                    "name": "科技互联网 订阅",
                    "channel": "wework",
                },
            }
        )
        client = client_factory(service)
        resp = await client.post(
            "/api/v1/topics/technology/enable",
            json={"channel": "wework", "channel_config": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["sources_loaded"] == 3
        service.enable.assert_awaited_once()

    async def test_enable_unknown_topic_returns_404(self, client_factory: Any) -> None:
        service = _real_service()
        service.enable = AsyncMock(side_effect=TopicNotFoundError("x"))  # type: ignore[method-assign]
        client = client_factory(service)
        resp = await client.post("/api/v1/topics/x/enable", json={})
        assert resp.status_code == 404

    async def test_enable_validation_error_returns_400(
        self, client_factory: Any
    ) -> None:
        service = _real_service()
        service.enable = AsyncMock(  # type: ignore[method-assign]
            side_effect=SubscriptionValidationError("email channel requires to_addr")
        )
        client = client_factory(service)
        resp = await client.post(
            "/api/v1/topics/finance/enable",
            json={"channel": "email", "channel_config": {}},
        )
        assert resp.status_code == 400
        assert "to_addr" in resp.json()["error"]["message"]
