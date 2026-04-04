"""Conftest for config tests -- register PostgreSQL JSONB type for SQLite."""

from sqlalchemy import JSON
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

_original_visit = getattr(SQLiteTypeCompiler, "visit_JSONB", None)

if _original_visit is None:

    def _visit_jsonb(self, type_, **kw):  # type: ignore[override]
        return self.visit_JSON(JSON(), **kw)

    SQLiteTypeCompiler.visit_JSONB = _visit_jsonb  # type: ignore[attr-defined]
