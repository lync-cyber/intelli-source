"""Integration test for CLI `pipeline list` against the live router (AC-T099-3).

The CLI `pipeline list` command issues GET /api/v1/pipelines. The router is a
thin shell over PipelineDefinitionService, so this test wires a real SQLite-backed
service seeded from the shipped YAML configs and drives the CLI against it.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import JSON
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from typer.testing import CliRunner

from intellisource.storage.models import Base, Pipeline, PipelineStep

# Render PostgreSQL JSONB as JSON for SQLite DDL only (no-op on real PG). This
# patches the SQLite compiler exclusively and never mutates Base.metadata, so it
# cannot leak into the real-PG integration tests sharing this process.
if getattr(SQLiteTypeCompiler, "visit_JSONB", None) is None:

    def _visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
        return self.visit_JSON(JSON(), **kw)

    SQLiteTypeCompiler.visit_JSONB = _visit_jsonb  # type: ignore[attr-defined]


async def _fetch_pipeline_list() -> Response:
    """Build a seeded SQLite-backed pipelines app and GET /pipelines once.

    Only the pipeline tables are created (they carry no ARRAY columns), so no
    global metadata mutation is needed.
    """
    from intellisource.api.routers.pipelines import _get_service
    from intellisource.api.routers.pipelines import router as pipelines_router
    from intellisource.pipeline.definition_service import PipelineDefinitionService

    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    pipeline_tables = [Pipeline.__table__, PipelineStep.__table__]
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=pipeline_tables)
    factory = async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
    session = factory()
    await PipelineDefinitionService(session).seed_from_yaml()

    app = FastAPI()
    app.include_router(pipelines_router, prefix="/api/v1")
    app.dependency_overrides[_get_service] = lambda: PipelineDefinitionService(session)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/v1/pipelines")
    finally:
        await session.close()
        await eng.dispose()


def test_pipeline_list_returns_known_configs() -> None:
    """CLI `pipeline list --json` exits 0 with at least one pipeline name."""
    from intellisource.cli.main import app as cli_app

    real_response = asyncio.run(_fetch_pipeline_list())
    assert real_response.status_code == 200, real_response.text

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
