"""Unit-test suite fixtures.

Slow subprocess checks (mypy/ruff/uv dry-run, file-watcher polling) are marked
``@pytest.mark.slow`` and excluded from default runs via ``-m 'not slow'`` in
pyproject.toml. Run them explicitly with ``pytest -m slow``.

Also installs the PostgreSQL JSONB / ARRAY → SQLite compatibility shim once for
every unit test that builds tables from ``Base.metadata`` against an in-memory
SQLite engine (storage, source, pipeline, api routers, ...). Idempotent and a
no-op on PostgreSQL.
"""

from sqlalchemy import JSON, Text
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

from intellisource.storage.models import Base

if getattr(SQLiteTypeCompiler, "visit_JSONB", None) is None:

    def _visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
        return self.visit_JSON(JSON(), **kw)

    SQLiteTypeCompiler.visit_JSONB = _visit_jsonb  # type: ignore[attr-defined]

if getattr(SQLiteTypeCompiler, "visit_ARRAY", None) is None:

    def _visit_array(self, type_, **kw):  # type: ignore[no-untyped-def]
        return self.visit_TEXT(Text(), **kw)

    SQLiteTypeCompiler.visit_ARRAY = _visit_array  # type: ignore[attr-defined]

# CREATE TABLE DDL is handled by the visitors above; at runtime SQLAlchemy still
# routes binds through the ARRAY type, and sqlite3 cannot bind a ``list``. Mutate
# the ARRAY columns to JSON once so ``[]`` round-trips as ``'[]'``.
for _table in Base.metadata.tables.values():
    for _col in _table.columns:
        if type(_col.type).__name__ == "ARRAY":
            _col.type = JSON()
