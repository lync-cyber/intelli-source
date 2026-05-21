"""Conftest for config tests -- register PostgreSQL JSONB and ARRAY types for SQLite."""

from sqlalchemy import JSON, Text
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

_original_visit_jsonb = getattr(SQLiteTypeCompiler, "visit_JSONB", None)

if _original_visit_jsonb is None:

    def _visit_jsonb(self, type_, **kw):  # type: ignore[override]
        return self.visit_JSON(JSON(), **kw)

    SQLiteTypeCompiler.visit_JSONB = _visit_jsonb  # type: ignore[attr-defined]

_original_visit_array = getattr(SQLiteTypeCompiler, "visit_ARRAY", None)

if _original_visit_array is None:

    def _visit_array(self, type_, **kw):  # type: ignore[override]
        return self.visit_TEXT(Text(), **kw)

    SQLiteTypeCompiler.visit_ARRAY = _visit_array  # type: ignore[attr-defined]
