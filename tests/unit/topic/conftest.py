"""Conftest — SQLite in-memory engine + session fixtures for topic tests."""

from __future__ import annotations

import pytest
from sqlalchemy import JSON, Text, event
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from intellisource.storage.models import Base

# ---------------------------------------------------------------------------
# SQLite dialect patches — JSONB → JSON, ARRAY → TEXT/JSON
# ---------------------------------------------------------------------------

if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):

    def _visit_jsonb(self, type_, **kw):  # type: ignore[override]
        return self.visit_JSON(JSON(), **kw)

    SQLiteTypeCompiler.visit_JSONB = _visit_jsonb  # type: ignore[attr-defined]

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):

    def _visit_array(self, type_, **kw):  # type: ignore[override]
        return self.visit_TEXT(Text(), **kw)

    SQLiteTypeCompiler.visit_ARRAY = _visit_array  # type: ignore[attr-defined]

for _table in Base.metadata.tables.values():
    for _col in _table.columns:
        if type(_col.type).__name__ == "ARRAY":
            _col.type = JSON()


SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _set_sqlite_fk_pragma(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _remove_pg_only_indexes(base: type[Base]) -> None:
    for table in base.metadata.tables.values():
        to_remove = []
        for idx in table.indexes:
            opts = getattr(idx, "dialect_options", {}).get("postgresql", {})
            if opts.get("using") or opts.get("ops"):
                to_remove.append(idx)
        for idx in to_remove:
            table.indexes.discard(idx)


@pytest.fixture
async def engine():
    eng = create_async_engine(SQLITE_TEST_URL, echo=False)
    event.listen(eng.sync_engine, "connect", _set_sqlite_fk_pragma)
    _remove_pg_only_indexes(Base)
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if type(col.type).__name__ == "Vector":
                col.type = Text()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS config_versions ("
            " id TEXT PRIMARY KEY,"
            " version TEXT NOT NULL UNIQUE,"
            " snapshot_yaml TEXT NOT NULL,"
            " author TEXT,"
            " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def session(engine):
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as sess:
        yield sess
