"""Inc3: distribution control-plane router (channels / templates / push / trigger)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.api.routers.distribution import router
from intellisource.distributor.channels.registry import (
    channel_is_configured,
    list_channel_descriptors,
)


def _make_mock_db() -> MagicMock:
    mock_session = MagicMock(spec=AsyncSession)

    @asynccontextmanager
    async def _get_session() -> AsyncIterator[MagicMock]:
        yield mock_session

    db = MagicMock()
    db.get_session = _get_session
    return db


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.db = _make_mock_db()
    app.state.celery_app = None
    return app


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Channel registry (SSOT catalog)
# ---------------------------------------------------------------------------


class TestChannelRegistry:
    def test_registry_lists_the_three_channels(self) -> None:
        names = {d.name for d in list_channel_descriptors()}
        assert names == {"email", "wechat", "wework"}

    def test_is_configured_true_only_when_all_env_present(self) -> None:
        email = next(d for d in list_channel_descriptors() if d.name == "email")
        full = {var: "x" for var in email.required_env}
        partial = dict(list(full.items())[:1])
        assert channel_is_configured(email, full) is True
        assert channel_is_configured(email, partial) is False
        assert channel_is_configured(email, {}) is False


# ---------------------------------------------------------------------------
# GET /channels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_channels_reports_each_channel_with_configured_flag() -> None:
    app = _build_app()
    with patch.dict("os.environ", {}, clear=True):
        async with await _client(app) as client:
            resp = await client.get("/api/v1/channels")
    assert resp.status_code == 200
    items = resp.json()["items"]
    by_name = {c["name"]: c for c in items}
    assert set(by_name) == {"email", "wechat", "wework"}
    assert by_name["email"]["display_name"] == "邮件"
    assert "IS_SMTP_HOST" in by_name["email"]["required_env"]
    # No env set → every channel reports unconfigured.
    assert all(c["configured"] is False for c in items)


# ---------------------------------------------------------------------------
# GET /templates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_templates_returns_registered_templates() -> None:
    app = _build_app()
    async with await _client(app) as client:
        resp = await client.get("/api/v1/templates")
    assert resp.status_code == 200
    items = resp.json()["items"]
    names = {t["name"] for t in items}
    assert "daily-brief" in names
    daily = next(t for t in items if t["name"] == "daily-brief")
    assert isinstance(daily["formats"], list) and daily["formats"]
    assert daily["default_format"] in daily["formats"]


# ---------------------------------------------------------------------------
# GET /push-records (PII masking)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_records_mask_recipient_pii() -> None:
    record = MagicMock()
    record.id = "11111111-1111-1111-1111-111111111111"
    record.subscription_id = "22222222-2222-2222-2222-222222222222"
    record.content_id = "33333333-3333-3333-3333-333333333333"
    record.channel = "email"
    record.status = "sent"
    record.retry_count = 0
    record.error_message = None
    record.recipient_id = "alice@example.com"
    record.sent_at = None
    record.delivered_at = None
    record.created_at = "2026-01-01T00:00:00+00:00"

    mock_repo = AsyncMock()
    mock_repo.list.return_value = {
        "items": [record],
        "next_cursor": None,
        "has_more": False,
    }

    app = _build_app()
    with patch(
        "intellisource.api.routers.distribution.PushRepository",
        return_value=mock_repo,
    ):
        async with await _client(app) as client:
            resp = await client.get("/api/v1/push-records")

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["recipient"] == "a***@example.com"
    assert "recipient_id" not in item  # raw PII never leaves the API
    assert item["channel"] == "email"
    assert item["status"] == "sent"


# ---------------------------------------------------------------------------
# POST /distributions/assemble
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_dispatches_digest_task() -> None:
    app = _build_app()
    app.state.celery_app = MagicMock()
    fake_result = MagicMock()
    fake_result.id = "task-abc"

    with patch(
        "intellisource.api.routers.distribution.send_task_with_trace",
        return_value=fake_result,
    ) as mock_dispatch:
        async with await _client(app) as client:
            resp = await client.post("/api/v1/distributions/assemble")

    assert resp.status_code == 200
    assert resp.json()["task_id"] == "task-abc"
    assert mock_dispatch.call_args.args[0] == "assemble_daily_weekly_digests"


@pytest.mark.asyncio
async def test_assemble_returns_503_when_celery_absent() -> None:
    app = _build_app()
    app.state.celery_app = None
    async with await _client(app) as client:
        resp = await client.post("/api/v1/distributions/assemble")
    assert resp.status_code == 503
