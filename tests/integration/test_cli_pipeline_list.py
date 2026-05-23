"""Integration test for CLI `pipeline list` against the live router (AC-T099-3).

Before T-099 the CLI `pipeline list` command sent a GET /api/v1/pipelines
that returned 404 — there was no router. This test asserts the CLI now
reaches the router by mocking httpx.get with a Response built from an
in-process FastAPI app.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from typer.testing import CliRunner


def _make_app() -> FastAPI:
    from intellisource.api.routers.pipelines import router as pipelines_router

    app = FastAPI()
    app.include_router(pipelines_router, prefix="/api/v1")
    return app


def test_pipeline_list_returns_known_configs() -> None:
    """CLI `pipeline list --json` exits 0 with at least one pipeline name."""
    from intellisource.cli.main import app as cli_app

    fastapi_app = _make_app()

    async def _fetch() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as client:
            return await client.get("/api/v1/pipelines")

    real_response = asyncio.run(_fetch())
    mock_resp = MagicMock()
    mock_resp.json.return_value = real_response.json()
    mock_resp.status_code = real_response.status_code

    def fake_get(url: str, **kwargs: Any) -> Any:
        assert "/api/v1/pipelines" in url
        return mock_resp

    with patch("intellisource.cli.main.httpx.get", side_effect=fake_get):
        runner = CliRunner()
        result = runner.invoke(cli_app, ["pipeline", "list", "--json"])

    assert result.exit_code == 0, (
        f"pipeline list exited {result.exit_code}: {result.stdout}"
    )
    assert "instant-search" in result.stdout, (
        f"expected 'instant-search' in CLI output, got: {result.stdout}"
    )
