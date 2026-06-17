"""Tests for Authentication middleware, request logging, and tracing.

Covers:
  AC-T043-1: AuthMiddleware validates X-API-Key header, returns 401 if invalid
  AC-T043-2: API Key configured via environment variable IS_API_KEY
  AC-T043-3: Health (/health) and Webhook (/api/v1/webhooks) endpoints exempt from auth
  AC-T043-4: RequestLogger logs method/path/status_code/duration_ms per request
  AC-T043-5: TracingMiddleware injects trace_id into logging context + X-Trace-ID header
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Import guard: module does not exist yet during RED phase.
# ---------------------------------------------------------------------------
try:
    from intellisource.api.middleware import (  # type: ignore[import-untyped]
        AuthMiddleware,
        RequestLoggerMiddleware,
        TracingMiddleware,
    )
except ImportError:
    AuthMiddleware = None  # type: ignore[assignment,misc]
    RequestLoggerMiddleware = None  # type: ignore[assignment,misc]
    TracingMiddleware = None  # type: ignore[assignment,misc]

_MIDDLEWARE_MISSING = AuthMiddleware is None

_SKIP_REASON = (
    "intellisource.api.middleware not implemented: "
    "cannot import AuthMiddleware / RequestLoggerMiddleware / TracingMiddleware"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_API_KEY = "test-secret-key-12345"


def _create_app_with_auth(api_key_env: str | None = TEST_API_KEY) -> FastAPI:
    """Create a minimal FastAPI app with AuthMiddleware applied.

    The *api_key_env* value simulates what IS_API_KEY would resolve to at
    middleware construction time.
    """
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/webhooks/github")
    async def webhook_github() -> dict[str, str]:
        return {"received": "ok"}

    @app.get("/api/v1/sources")
    async def list_sources() -> dict[str, str]:
        return {"sources": "list"}

    # Apply auth middleware
    app.add_middleware(AuthMiddleware)  # type: ignore[arg-type]
    return app


def _create_app_with_logger() -> FastAPI:
    """Create a minimal FastAPI app with RequestLoggerMiddleware applied."""
    app = FastAPI()

    @app.get("/api/v1/items")
    async def list_items() -> dict[str, str]:
        return {"items": "list"}

    @app.get("/api/v1/error")
    async def error_endpoint() -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "server error"})

    app.add_middleware(RequestLoggerMiddleware)  # type: ignore[arg-type]
    return app


def _create_app_with_tracing() -> FastAPI:
    """Create a minimal FastAPI app with TracingMiddleware applied."""
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        return {"pong": "ok"}

    app.add_middleware(TracingMiddleware)  # type: ignore[arg-type]
    return app


# ===========================================================================
# AC-T043-1 & AC-T043-2: AuthMiddleware validates X-API-Key
# ===========================================================================


class TestAuthMiddleware:
    """Verify AuthMiddleware enforces X-API-Key header validation."""

    @pytest.mark.asyncio
    async def test_request_without_api_key_returns_401(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-T043-1: Missing X-API-Key header yields 401."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        monkeypatch.setenv("IS_API_KEY", TEST_API_KEY)
        app = _create_app_with_auth()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/sources")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_request_with_wrong_api_key_returns_401(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-T043-1: Incorrect X-API-Key header yields 401."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        monkeypatch.setenv("IS_API_KEY", TEST_API_KEY)
        app = _create_app_with_auth()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/sources", headers={"X-API-Key": "wrong-key"}
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_request_with_correct_api_key_returns_200(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-T043-1: Valid X-API-Key header yields 200."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        monkeypatch.setenv("IS_API_KEY", TEST_API_KEY)
        app = _create_app_with_auth()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/sources", headers={"X-API-Key": TEST_API_KEY}
            )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_api_key_read_from_env_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-T043-2: Middleware reads key from IS_API_KEY env var."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        custom_key = "custom-env-key-67890"
        monkeypatch.setenv("IS_API_KEY", custom_key)
        app = _create_app_with_auth()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/sources", headers={"X-API-Key": custom_key}
            )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_api_key_disables_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-T043-2: Empty IS_API_KEY means auth is disabled."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        monkeypatch.setenv("IS_API_KEY", "")
        app = _create_app_with_auth()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/sources")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_401_response_contains_error_detail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-T043-1: 401 response body includes an error detail message."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        monkeypatch.setenv("IS_API_KEY", TEST_API_KEY)
        app = _create_app_with_auth()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/sources")
        assert resp.status_code == 401
        body = resp.json()
        assert "error" in body


# ===========================================================================
# AC-T043-3: Exempt paths bypass authentication
# ===========================================================================


class TestAuthExemptPaths:
    """Verify health and webhook endpoints are exempt from API key auth."""

    @pytest.mark.asyncio
    async def test_health_endpoint_exempt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-T043-3: GET /health passes without API key."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        monkeypatch.setenv("IS_API_KEY", TEST_API_KEY)
        app = _create_app_with_auth()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_webhook_endpoint_exempt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-T043-3: POST /api/v1/webhooks/... passes without API key."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        monkeypatch.setenv("IS_API_KEY", TEST_API_KEY)
        app = _create_app_with_auth()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/webhooks/github")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_non_exempt_path_still_requires_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-T043-3: Non-exempt paths still require API key."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        monkeypatch.setenv("IS_API_KEY", TEST_API_KEY)
        app = _create_app_with_auth()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/sources")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exempt_path",
        [
            "/health",
            "/api/v1/health",
            "/api/v1/system/health",
            "/metrics",
            "/api/v1/metrics",
            "/api/v1/system/metrics",
        ],
    )
    async def test_observability_paths_exempt(
        self, monkeypatch: pytest.MonkeyPatch, exempt_path: str
    ) -> None:
        """F-25: probe + scrape endpoints bypass auth even when IS_API_KEY is set."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        monkeypatch.setenv("IS_API_KEY", TEST_API_KEY)

        app = FastAPI()

        async def _ok() -> dict[str, str]:
            return {"status": "ok"}

        # Register the path under test as a real endpoint so the response is 200,
        # not 404. The middleware decision is what we're testing here.
        app.add_api_route(exempt_path, _ok, methods=["GET"])
        app.add_middleware(AuthMiddleware)  # type: ignore[arg-type]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(exempt_path)
        assert resp.status_code != 401, (
            f"{exempt_path} must be exempt from API key check; got {resp.status_code}"
        )
        assert resp.status_code == 200


# ===========================================================================
# AC-T043-4: RequestLoggerMiddleware logs request details
# ===========================================================================


class TestRequestLoggerMiddleware:
    """Verify RequestLoggerMiddleware logs method/path/status_code/duration_ms."""

    @pytest.mark.asyncio
    async def test_logs_request_details(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC-T043-4: Log entry contains method, path, status_code, duration_ms."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = _create_app_with_logger()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with caplog.at_level("INFO"):
                await client.get("/api/v1/items")

        log_text = caplog.text
        assert "GET" in log_text
        assert "/api/v1/items" in log_text
        assert "200" in log_text
        assert "duration_ms" in log_text or "ms" in log_text

    @pytest.mark.asyncio
    async def test_duration_is_non_negative(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC-T043-4: duration_ms is a non-negative number."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = _create_app_with_logger()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with caplog.at_level("INFO"):
                await client.get("/api/v1/items")

        # Extract numeric duration from log records
        duration_found = False
        for record in caplog.records:
            message = record.getMessage()
            # Look for a duration value in the log message
            match = re.search(r"duration_ms[=: ]+(\d+(?:\.\d+)?)", message)
            if match:
                duration_found = True
                assert float(match.group(1)) >= 0
        assert duration_found, "No duration_ms found in log output"

    @pytest.mark.asyncio
    async def test_logs_error_responses(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC-T043-4: Log entry generated even for error responses."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = _create_app_with_logger()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with caplog.at_level("INFO"):
                await client.get("/api/v1/error")

        log_text = caplog.text
        assert "/api/v1/error" in log_text
        assert "500" in log_text


# ===========================================================================
# AC-T043-5: TracingMiddleware injects trace_id
# ===========================================================================


class TestTracingMiddleware:
    """Verify TracingMiddleware sets X-Trace-ID in responses and context."""

    @pytest.mark.asyncio
    async def test_response_includes_trace_id_header(self) -> None:
        """AC-T043-5: Response includes X-Trace-ID header."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = _create_app_with_tracing()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/ping")
        assert "x-trace-id" in resp.headers

    @pytest.mark.asyncio
    async def test_trace_id_is_valid_uuid(self) -> None:
        """AC-T043-5: X-Trace-ID value is a valid UUID."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = _create_app_with_tracing()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/ping")
        trace_id = resp.headers.get("x-trace-id", "")
        # Validate it parses as a UUID (raises ValueError if not)
        parsed = uuid.UUID(trace_id)
        assert str(parsed) == trace_id.lower()

    @pytest.mark.asyncio
    async def test_propagates_incoming_trace_id(self) -> None:
        """AC-T043-5: If request has X-Trace-ID, it is propagated, not overwritten."""
        if _MIDDLEWARE_MISSING:
            pytest.fail(_SKIP_REASON)
        app = _create_app_with_tracing()
        transport = ASGITransport(app=app)
        incoming_trace = str(uuid.uuid4())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/ping", headers={"X-Trace-ID": incoming_trace}
            )
        assert resp.headers.get("x-trace-id") == incoming_trace
