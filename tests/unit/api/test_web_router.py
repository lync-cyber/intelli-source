"""Tests for the minimal chat web UI router (GET /chat).

The page is a static HTML+SSE frontend that streams the protected
``/api/v1/agent/chat/stream`` endpoint; the page itself must be public so a
browser (which cannot attach the X-API-Key header) can load it.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.middleware import AuthMiddleware, is_exempt_path
from intellisource.api.routers import web
from intellisource.main import create_app

TEST_API_KEY = "test-secret-key-web"


def _app_with_web_and_auth() -> FastAPI:
    app = FastAPI()
    app.include_router(web.router)
    app.add_middleware(AuthMiddleware)
    return app


@pytest.mark.asyncio
async def test_chat_page_served_as_html_and_wires_sse_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /chat returns the HTML page (auth-exempt) wired to the SSE endpoint."""
    monkeypatch.setenv("IS_API_KEY", TEST_API_KEY)
    app = _app_with_web_and_auth()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/chat")  # deliberately no X-API-Key header
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "/api/v1/agent/chat/stream" in resp.text


def test_chat_path_is_auth_exempt() -> None:
    """The /chat page is public so a browser can load it without the API key."""
    assert is_exempt_path("/chat") is True


def test_chat_route_registered_on_main_app() -> None:
    """create_app wires the chat UI at root /chat (no /api/v1 prefix)."""
    app = create_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/chat" in paths
