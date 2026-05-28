"""Conftest — SQLite in-memory engine + session fixtures for source service tests."""

from __future__ import annotations

from sqlalchemy import JSON, Text
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

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
