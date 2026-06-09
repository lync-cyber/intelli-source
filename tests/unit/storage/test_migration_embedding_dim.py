"""T-EMB-1 AC-5: Alembic migration for embedding dimension resize (1536 → 1024).

Validates migration structure without a real DB:
- The migration module exists in alembic/versions/
- down_revision points to the previous head (a2b3c4d5e6f7)
- upgrade() and downgrade() are importable
- upgrade() source involves 1024 (new dimension) and the two affected tables
- downgrade() source involves 1536 (old dimension) and the two affected tables
- upgrade() drops and recreates HNSW indexes (vector_cosine_ops)
- downgrade() drops and recreates HNSW indexes (vector_cosine_ops)
"""

from __future__ import annotations

import importlib
import pathlib
import re
import types

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
VERSIONS_DIR = PROJECT_ROOT / "alembic" / "versions"

# The previous head revision that the new migration must descend from.
_EXPECTED_DOWN_REVISION = "a2b3c4d5e6f7"
_NEW_REVISION_PREFIX = "g0h1i2j3k4l5"


def _find_dim_migration_file() -> pathlib.Path | None:
    """Locate the embedding-dim migration file by revision ID prefix."""
    for f in VERSIONS_DIR.glob("*.py"):
        if f.name.startswith(_NEW_REVISION_PREFIX):
            return f
    return None


def _load_migration_module() -> types.ModuleType:
    """Import the embedding-dim migration as a Python module."""
    f = _find_dim_migration_file()
    assert f is not None, (
        f"Migration file starting with '{_NEW_REVISION_PREFIX}' not found in"
        f" {VERSIONS_DIR}. "
        "The embedding-dim resize migration has not been created."
    )
    spec = importlib.util.spec_from_file_location("_emb_dim_migration", f)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _read_migration_source() -> str:
    f = _find_dim_migration_file()
    assert f is not None, (
        f"Migration file starting with '{_NEW_REVISION_PREFIX}'"
        f" not found in {VERSIONS_DIR}."
    )
    return f.read_text(encoding="utf-8")


class TestMigrationExists:
    def test_migration_file_found(self) -> None:
        """AC-5: Migration file for embedding-dim resize must exist."""
        f = _find_dim_migration_file()
        assert f is not None, (
            f"No migration file starting with '{_NEW_REVISION_PREFIX}'"
            f" in {VERSIONS_DIR}. "
            "Create the migration for embedding dimension resize."
        )


class TestMigrationChainLinkage:
    def test_down_revision_points_to_previous_head(self) -> None:
        """AC-5: Migration down_revision must be 'a2b3c4d5e6f7'."""
        mod = _load_migration_module()
        actual = getattr(mod, "down_revision", None)
        assert actual == _EXPECTED_DOWN_REVISION, (
            f"Expected down_revision='{_EXPECTED_DOWN_REVISION}', got {actual!r}"
        )

    def test_revision_id_matches_prefix(self) -> None:
        """AC-5: Migration revision attribute starts with expected prefix."""
        mod = _load_migration_module()
        actual = getattr(mod, "revision", None)
        assert actual is not None and actual.startswith(_NEW_REVISION_PREFIX[:8]), (
            f"Expected revision starting with '{_NEW_REVISION_PREFIX[:8]}',"
            f" got {actual!r}"
        )


class TestMigrationFunctions:
    def test_upgrade_function_importable(self) -> None:
        """AC-5: upgrade() function must be importable from the migration module."""
        mod = _load_migration_module()
        fn = getattr(mod, "upgrade", None)
        assert callable(fn), f"upgrade() must be a callable, got {type(fn)}"
        # Call upgrade() — must not raise when op is not connected (unit test context
        # only exercises importability and structure, not DB execution).

    def test_downgrade_function_importable(self) -> None:
        """AC-5: downgrade() function must be importable from the migration module."""
        mod = _load_migration_module()
        fn = getattr(mod, "downgrade", None)
        assert callable(fn), f"downgrade() must be a callable, got {type(fn)}"


class TestUpgradeSourceContent:
    def test_upgrade_references_1024(self) -> None:
        """AC-5: upgrade() source must reference dimension 1024 (the new target)."""
        src = _read_migration_source()
        upgrade_match = re.search(
            r"def\s+upgrade\s*\(\s*\).*?(?=\ndef\s|\Z)", src, re.DOTALL
        )
        assert upgrade_match, "No upgrade() function found in migration source"
        body = upgrade_match.group()
        assert "1024" in body, (
            "upgrade() must reference dimension 1024 for the new vector column size"
        )

    def test_upgrade_references_processed_contents(self) -> None:
        """AC-5: upgrade() must alter the processed_contents.embedding column."""
        src = _read_migration_source()
        upgrade_match = re.search(
            r"def\s+upgrade\s*\(\s*\).*?(?=\ndef\s|\Z)", src, re.DOTALL
        )
        assert upgrade_match, "No upgrade() function found"
        body = upgrade_match.group()
        assert "processed_contents" in body, (
            "upgrade() must reference processed_contents table"
            " to alter embedding column"
        )

    def test_upgrade_references_content_clusters(self) -> None:
        """AC-5: upgrade() must alter the content_clusters.centroid column."""
        src = _read_migration_source()
        upgrade_match = re.search(
            r"def\s+upgrade\s*\(\s*\).*?(?=\ndef\s|\Z)", src, re.DOTALL
        )
        assert upgrade_match, "No upgrade() function found"
        body = upgrade_match.group()
        assert "content_clusters" in body, (
            "upgrade() must reference content_clusters table to alter centroid column"
        )

    def test_upgrade_recreates_hnsw_index_with_cosine_ops(self) -> None:
        """AC-5: upgrade() must drop and recreate HNSW index with vector_cosine_ops."""
        src = _read_migration_source()
        upgrade_match = re.search(
            r"def\s+upgrade\s*\(\s*\).*?(?=\ndef\s|\Z)", src, re.DOTALL
        )
        assert upgrade_match, "No upgrade() function found"
        body = upgrade_match.group()
        assert re.search(r"hnsw", body, re.IGNORECASE), (
            "upgrade() must recreate the HNSW index after resizing vector column"
        )
        assert re.search(r"vector_cosine_ops", body), (
            "upgrade() must use vector_cosine_ops in the HNSW index definition"
        )


class TestDowngradeSourceContent:
    def test_downgrade_references_1536(self) -> None:
        """AC-5: downgrade() must reference dimension 1536 (reverting to old size)."""
        src = _read_migration_source()
        downgrade_match = re.search(
            r"def\s+downgrade\s*\(\s*\).*?(?=\ndef\s|\Z)", src, re.DOTALL
        )
        assert downgrade_match, "No downgrade() function found in migration source"
        body = downgrade_match.group()
        assert "1536" in body, (
            "downgrade() must reference dimension 1536"
            " to restore the original column size"
        )

    def test_downgrade_references_both_tables(self) -> None:
        """AC-5: downgrade() must reference processed_contents and content_clusters."""
        src = _read_migration_source()
        downgrade_match = re.search(
            r"def\s+downgrade\s*\(\s*\).*?(?=\ndef\s|\Z)", src, re.DOTALL
        )
        assert downgrade_match, "No downgrade() function found"
        body = downgrade_match.group()
        assert "processed_contents" in body, (
            "downgrade() must reference processed_contents to restore embedding column"
        )
        assert "content_clusters" in body, (
            "downgrade() must reference content_clusters to restore centroid column"
        )

    def test_downgrade_recreates_hnsw_index(self) -> None:
        """AC-5: downgrade() recreates HNSW index with vector_cosine_ops."""
        src = _read_migration_source()
        downgrade_match = re.search(
            r"def\s+downgrade\s*\(\s*\).*?(?=\ndef\s|\Z)", src, re.DOTALL
        )
        assert downgrade_match, "No downgrade() function found"
        body = downgrade_match.group()
        assert re.search(r"hnsw", body, re.IGNORECASE), (
            "downgrade() must recreate the HNSW index after reverting vector column"
        )
        assert re.search(r"vector_cosine_ops", body), (
            "downgrade() must use vector_cosine_ops in the HNSW index definition"
        )
