"""Conftest for storage tests — register PostgreSQL JSONB and ARRAY types for SQLite."""

from sqlalchemy import JSON, Text

# Make JSONB compile as JSON on SQLite so in-memory tests work.
# This is a no-op on PostgreSQL where JSONB is natively supported.
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

from intellisource.storage.models import Base

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


# Replace ORM ARRAY columns with JSON at module import time. The DDL hack above
# only handles CREATE TABLE; at runtime SQLAlchemy still routes binds through
# the ARRAY type, and Python's sqlite3 cannot bind `list` (ProgrammingError:
# "type 'list' is not supported"). Mutating Base.metadata once here makes the
# JSON serializer take over so `[]` round-trips as `'[]'`. Idempotent: a second
# pass finds no ARRAY columns left.
for _table in Base.metadata.tables.values():
    for _col in _table.columns:
        if type(_col.type).__name__ == "ARRAY":
            _col.type = JSON()
