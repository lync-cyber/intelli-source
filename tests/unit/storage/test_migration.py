"""Unit tests for Alembic migration infrastructure (T-046).

Validates that:
- alembic/env.py exists and is correctly configured
- Initial migration script exists in alembic/versions/
- Migration script creates all 11 ORM tables
- Migration script includes required PostgreSQL extensions
- Migration script includes LLMCallLog partition configuration
- Migration downgrade removes all tables

These tests verify migration file structure and content without
requiring a real database connection.
"""

from __future__ import annotations

import pathlib
import re

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
ALEMBIC_DIR = PROJECT_ROOT / "alembic"
VERSIONS_DIR = ALEMBIC_DIR / "versions"

# All 11 ORM table names from models.py (E-001 through E-011)
EXPECTED_TABLES = [
    "sources",  # E-001
    "task_chains",  # E-008
    "collect_tasks",  # E-002
    "raw_contents",  # E-003
    "content_clusters",  # E-005
    "processed_contents",  # E-004
    "digests",  # E-006
    "llm_call_logs",  # E-007
    "subscriptions",  # E-009
    "push_records",  # E-010
    "chat_sessions",  # E-011
]


def _find_migration_files() -> list[pathlib.Path]:
    """Return all .py migration files in alembic/versions/ sorted by filename
    so 001_initial_schema.py precedes later revisions, regardless of filesystem order.
    """
    if not VERSIONS_DIR.exists():
        return []
    return sorted(f for f in VERSIONS_DIR.glob("*.py") if f.name != "__init__.py")


def _read_migration_source() -> str:
    """Read the source code of the initial migration file.

    Returns concatenated source if multiple files exist.
    Raises FileNotFoundError if no migration files found.
    """
    files = _find_migration_files()
    if not files:
        raise FileNotFoundError("No migration files found in alembic/versions/")
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


# ===========================================================================
# AC-054: Database table structure is consistent with ORM models
# ===========================================================================


class TestOrmMigrationConsistency:
    """AC-054: Verify migration creates tables matching ORM model definitions."""

    def test_env_py_exists(self) -> None:
        """alembic/env.py must exist as the Alembic environment configuration."""
        env_py = ALEMBIC_DIR / "env.py"
        assert env_py.exists(), (
            f"alembic/env.py not found at {env_py}. "
            "Alembic environment configuration has not been created."
        )

    def test_env_py_imports_orm_base(self) -> None:
        """env.py must import and reference Base.metadata for autogenerate support."""
        env_py = ALEMBIC_DIR / "env.py"
        assert env_py.exists(), "alembic/env.py does not exist"
        source = env_py.read_text(encoding="utf-8")
        # Must reference target_metadata with Base.metadata or equivalent
        assert "target_metadata" in source, (
            "env.py does not set target_metadata; "
            "Alembic needs this to detect ORM model changes"
        )
        # Should import from the models module
        assert "models" in source.lower() or "Base" in source, (
            "env.py does not reference ORM models or Base; "
            "it should import Base.metadata from intellisource.storage.models"
        )

    def test_migration_file_exists(self) -> None:
        """At least one migration file must exist in alembic/versions/."""
        files = _find_migration_files()
        assert len(files) > 0, (
            f"No migration files found in {VERSIONS_DIR}. "
            "Initial migration script has not been generated."
        )

    def test_migration_creates_all_tables(self) -> None:
        """Migration upgrade() must create all 11 ORM entity tables."""
        source = _read_migration_source()
        for table_name in EXPECTED_TABLES:
            # Look for create_table('table_name' or op.create_table("table_name"
            pattern = rf"""create_table\s*\(\s*['\"]{table_name}['\"]"""
            assert re.search(pattern, source), (
                f"Migration does not create table '{table_name}'. "
                f"All 11 ORM tables must be created in the initial migration."
            )

    def test_migration_has_upgrade_function(self) -> None:
        """Migration script must define an upgrade() function."""
        source = _read_migration_source()
        assert re.search(r"def\s+upgrade\s*\(", source), (
            "Migration script does not define an upgrade() function"
        )

    def test_migration_has_downgrade_function(self) -> None:
        """Migration script must define a downgrade() function."""
        source = _read_migration_source()
        assert re.search(r"def\s+downgrade\s*\(", source), (
            "Migration script does not define a downgrade() function"
        )


# ===========================================================================
# AC-T046-1: alembic upgrade head creates all tables and indexes
# ===========================================================================


class TestUpgradeCreatesTablesAndIndexes:
    """AC-T046-1: Verify upgrade() includes table and index creation."""

    def test_upgrade_creates_indexes_for_sources(self) -> None:
        """upgrade() must create indexes defined on the sources table."""
        source = _read_migration_source()
        # Sources has ix_sources_status, ix_sources_next_collect_at, ix_sources_tags
        assert re.search(r"ix_sources_status", source), (
            "Migration does not create ix_sources_status index"
        )

    def test_upgrade_creates_hnsw_index(self) -> None:
        """upgrade() must create the HNSW vector index on processed_contents."""
        source = _read_migration_source()
        assert re.search(r"hnsw", source, re.IGNORECASE), (
            "Migration does not create HNSW index for vector similarity search"
        )

    def test_upgrade_creates_gin_indexes(self) -> None:
        """upgrade() must create GIN indexes (for JSONB and text search)."""
        source = _read_migration_source()
        assert re.search(r"gin", source, re.IGNORECASE), (
            "Migration does not create any GIN indexes"
        )


# ===========================================================================
# AC-T046-2: alembic downgrade base rolls back all migrations
# ===========================================================================


class TestDowngradeRemovesTables:
    """AC-T046-2: Verify downgrade() removes all tables."""

    def test_downgrade_drops_all_tables(self) -> None:
        """downgrade() must drop all 11 ORM entity tables."""
        source = _read_migration_source()
        # Extract downgrade function body
        downgrade_match = re.search(
            r"def\s+downgrade\s*\(\s*\).*?(?=\ndef\s|\Z)",
            source,
            re.DOTALL,
        )
        assert downgrade_match, "No downgrade() function found in migration"
        downgrade_body = downgrade_match.group()

        for table_name in EXPECTED_TABLES:
            pattern = rf"""drop_table\s*\(\s*['\"]{table_name}['\"]"""
            assert re.search(pattern, downgrade_body), (
                f"downgrade() does not drop table '{table_name}'. "
                f"All tables must be removed on downgrade to base."
            )

    def test_downgrade_drops_extensions(self) -> None:
        """downgrade() should drop the pgvector and zhparser extensions."""
        source = _read_migration_source()
        downgrade_match = re.search(
            r"def\s+downgrade\s*\(\s*\).*?(?=\ndef\s|\Z)",
            source,
            re.DOTALL,
        )
        assert downgrade_match, "No downgrade() function found in migration"
        downgrade_body = downgrade_match.group()

        # Should contain DROP EXTENSION for vector
        assert re.search(r"DROP\s+EXTENSION.*vector", downgrade_body, re.IGNORECASE), (
            "downgrade() does not drop the vector extension"
        )


# ===========================================================================
# AC-T046-3: Migration includes pgvector extension creation
# ===========================================================================


class TestPgvectorExtension:
    """AC-T046-3: Migration must create pgvector extension."""

    def test_creates_vector_extension(self) -> None:
        """Migration must include CREATE EXTENSION IF NOT EXISTS vector."""
        source = _read_migration_source()
        pattern = r"CREATE\s+EXTENSION\s+IF\s+NOT\s+EXISTS\s+vector"
        assert re.search(pattern, source, re.IGNORECASE), (
            "Migration does not include 'CREATE EXTENSION IF NOT EXISTS vector'. "
            "pgvector extension is required for Vector column types."
        )

    def test_vector_extension_in_upgrade(self) -> None:
        """The vector extension creation must be in the upgrade() function."""
        source = _read_migration_source()
        upgrade_match = re.search(
            r"def\s+upgrade\s*\(\s*\).*?(?=\ndef\s|\Z)",
            source,
            re.DOTALL,
        )
        assert upgrade_match, "No upgrade() function found in migration"
        upgrade_body = upgrade_match.group()
        pattern = r"CREATE\s+EXTENSION\s+IF\s+NOT\s+EXISTS\s+vector"
        assert re.search(pattern, upgrade_body, re.IGNORECASE), (
            "CREATE EXTENSION vector is not in the upgrade() function"
        )


# ===========================================================================
# AC-T046-4: Migration includes zhparser extension creation
# ===========================================================================


class TestZhparserExtension:
    """AC-T046-4: Migration must create zhparser extension."""

    def test_creates_zhparser_extension(self) -> None:
        """Migration must include CREATE EXTENSION IF NOT EXISTS zhparser."""
        source = _read_migration_source()
        pattern = r"CREATE\s+EXTENSION\s+IF\s+NOT\s+EXISTS\s+zhparser"
        assert re.search(pattern, source, re.IGNORECASE), (
            "Migration does not include 'CREATE EXTENSION IF NOT EXISTS zhparser'. "
            "zhparser extension is required for Chinese full-text search."
        )

    def test_zhparser_extension_in_upgrade(self) -> None:
        """The zhparser extension creation must be in the upgrade() function."""
        source = _read_migration_source()
        upgrade_match = re.search(
            r"def\s+upgrade\s*\(\s*\).*?(?=\ndef\s|\Z)",
            source,
            re.DOTALL,
        )
        assert upgrade_match, "No upgrade() function found in migration"
        upgrade_body = upgrade_match.group()
        pattern = r"CREATE\s+EXTENSION\s+IF\s+NOT\s+EXISTS\s+zhparser"
        assert re.search(pattern, upgrade_body, re.IGNORECASE), (
            "CREATE EXTENSION zhparser is not in the upgrade() function"
        )


# ===========================================================================
# AC-T046-5: LLMCallLog partitioned table is created correctly
# ===========================================================================


class TestLlmCallLogPartition:
    """AC-T046-5: E-007 LLMCallLog must be created as a partitioned table."""

    def test_llm_call_logs_partition_by_range(self) -> None:
        """Migration must create llm_call_logs with PARTITION BY RANGE."""
        source = _read_migration_source()
        pattern = r"PARTITION\s+BY\s+RANGE"
        assert re.search(pattern, source, re.IGNORECASE), (
            "Migration does not include 'PARTITION BY RANGE' for llm_call_logs. "
            "LLMCallLog table must be range-partitioned by created_at."
        )

    def test_llm_call_logs_partition_on_created_at(self) -> None:
        """Partition key must be created_at column."""
        source = _read_migration_source()
        # Look for PARTITION BY RANGE (created_at) or similar
        pattern = r"PARTITION\s+BY\s+RANGE\s*\(\s*created_at\s*\)"
        assert re.search(pattern, source, re.IGNORECASE), (
            "LLMCallLog partition key is not 'created_at'. "
            "The table must be partitioned by RANGE on created_at."
        )

    def test_llm_call_logs_uses_raw_sql_for_partition(self) -> None:
        """Partition creation likely uses op.execute() with raw SQL since
        Alembic's create_table doesn't natively support PARTITION BY."""
        source = _read_migration_source()
        # The migration should use op.execute() or text() for the partitioned table
        assert re.search(r"llm_call_logs", source), (
            "Migration does not reference llm_call_logs table at all"
        )
        # There should be raw SQL execution for the partition syntax
        has_execute = re.search(r"op\.execute\s*\(", source) is not None
        has_partition = (
            re.search(r"PARTITION\s+BY\s+RANGE", source, re.IGNORECASE) is not None
        )
        assert has_execute and has_partition, (
            "Migration should use op.execute() with raw SQL to create "
            "the partitioned llm_call_logs table, since Alembic's create_table "
            "does not natively support PARTITION BY RANGE."
        )
