"""Tests for T-001: Project skeleton and base configuration.

Covers:
  AC-T001-1: pyproject.toml contains all core dependencies and is installable
  AC-T001-2: ruff check/format pass with zero errors on src/
  AC-T001-3: mypy strict mode passes on src/
  AC-T001-4: pytest can execute and conftest.py loads successfully
  AC-T001-5: Directory structure matches arch#§6
"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
PACKAGE_ROOT = SRC_ROOT / "intellisource"
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"

CORE_DEPENDENCIES = [
    "fastapi",
    "sqlalchemy",
    "celery",
    "redis",
    "httpx",
    "feedparser",
    "litellm",
    "structlog",
    "pydantic",
    "pyyaml",
    "starlette",
    "jsonschema",
    "kombu",
    "typer",
    "alembic",
    "pgvector",
    "beautifulsoup4",
    "lxml",
]

# All sub-packages that must contain __init__.py according to arch#§6
EXPECTED_SUBPACKAGES = [
    "config",
    "core",
    "collector",
    "collector/adapters",
    "pipeline",
    "pipeline/processors",
    "agent",
    "llm",
    "llm/prompts",
    "llm/schemas",
    "scheduler",
    "distributor",
    "distributor/channels",
    "search",
    "storage",
    "storage/repositories",
    "observability",
    "api",
    "api/routers",
    "cli",
]

# Top-level directories that must exist
EXPECTED_TOP_DIRS = [
    "src/intellisource",
    "tests",
    "tests/unit",
    "tests/integration",
    "config",
    "config/pipelines",
    "docker",
    "alembic",
    "alembic/versions",
]


# ===========================================================================
# AC-T001-1: pyproject.toml contains all core dependencies
# ===========================================================================


class TestPyprojectDependencies:
    """AC-T001-1: pyproject.toml includes all required core dependencies."""

    def test_pyproject_toml_exists_in_project_root(self) -> None:
        """An IntelliSource-specific pyproject.toml must exist and declare
        the 'intellisource' project (not 'cataforge')."""
        assert PYPROJECT_PATH.exists(), "pyproject.toml does not exist"
        content = PYPROJECT_PATH.read_text(encoding="utf-8")
        assert "intellisource" in content.lower(), (
            "pyproject.toml does not declare the 'intellisource' project"
        )

    @pytest.mark.parametrize("dep", CORE_DEPENDENCIES)
    def test_core_dependency_declared(self, dep: str) -> None:
        """Each core dependency must appear in pyproject.toml dependencies."""
        content = PYPROJECT_PATH.read_text(encoding="utf-8").lower()
        # Normalize: both underscore and hyphen forms should match
        dep_normalized = dep.lower().replace("-", "[-_]")
        import re

        assert re.search(dep_normalized, content), (
            f"Dependency '{dep}' not found in pyproject.toml"
        )

    @pytest.mark.slow
    def test_package_installable(self) -> None:
        """The IntelliSource package must be installable via uv (dry-run).

        This test depends on pyproject.toml declaring 'intellisource' as the
        project name (validated by test_pyproject_toml_exists_in_project_root).
        """
        # First verify pyproject.toml declares intellisource, not something else
        content = PYPROJECT_PATH.read_text(encoding="utf-8")
        assert "intellisource" in content.lower(), (
            "pyproject.toml does not declare 'intellisource' project"
        )
        result = subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "-e",
                str(PROJECT_ROOT),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, (
            f"uv pip install --dry-run failed:\n{result.stdout}\n{result.stderr}"
        )


# ===========================================================================
# AC-T001-2: ruff check and ruff format pass on src/
# ===========================================================================


class TestRuffLinting:
    """AC-T001-2: ruff check and ruff format --check produce zero errors on src/."""

    @pytest.mark.slow
    def test_ruff_check_passes(self) -> None:
        """ruff check src/ must exit with code 0."""
        result = subprocess.run(
            ["ruff", "check", str(SRC_ROOT)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, (
            f"ruff check failed:\n{result.stdout}\n{result.stderr}"
        )

    @pytest.mark.slow
    def test_ruff_format_check_passes(self) -> None:
        """ruff format --check src/ must exit with code 0."""
        result = subprocess.run(
            ["ruff", "format", "--check", str(SRC_ROOT)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, (
            f"ruff format --check failed:\n{result.stdout}\n{result.stderr}"
        )


# ===========================================================================
# AC-T001-3: mypy strict mode passes on src/
# ===========================================================================


class TestMypyStrict:
    """AC-T001-3: mypy src/ in strict mode produces zero errors."""

    @pytest.mark.slow
    def test_mypy_strict_passes(self) -> None:
        """mypy --strict src/ must exit with code 0."""
        result = subprocess.run(
            ["mypy", "--strict", str(SRC_ROOT)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, (
            f"mypy --strict failed:\n{result.stdout}\n{result.stderr}"
        )


# ===========================================================================
# AC-T001-4: pytest executes and conftest.py loads
# ===========================================================================


class TestPytestSetup:
    """AC-T001-4: pytest can execute and conftest.py loads successfully."""

    def test_conftest_exists(self) -> None:
        """tests/conftest.py must exist."""
        conftest = PROJECT_ROOT / "tests" / "conftest.py"
        assert conftest.exists(), "tests/conftest.py does not exist"

    def test_conftest_is_loadable(self) -> None:
        """tests/conftest.py must be importable without errors."""
        conftest = PROJECT_ROOT / "tests" / "conftest.py"
        # Compile the file to check for syntax errors
        source = conftest.read_text(encoding="utf-8")
        compile(source, str(conftest), "exec")

    def test_intellisource_package_importable(self) -> None:
        """The intellisource package must be importable after installation."""
        try:
            importlib.import_module("intellisource")
        except ModuleNotFoundError:
            pytest.fail(
                "Cannot import 'intellisource' -- package not installed or src/ missing"
            )


# ===========================================================================
# AC-T001-5: Directory structure matches arch#§6
# ===========================================================================


class TestDirectoryStructure:
    """AC-T001-5: Directory layout matches the architecture specification."""

    def test_src_intellisource_exists(self) -> None:
        """src/intellisource/ must exist as a directory."""
        assert PACKAGE_ROOT.is_dir(), f"{PACKAGE_ROOT} does not exist"

    def test_package_init_exists(self) -> None:
        """src/intellisource/__init__.py must exist."""
        init_file = PACKAGE_ROOT / "__init__.py"
        assert init_file.is_file(), f"{init_file} does not exist"

    def test_main_py_exists(self) -> None:
        """src/intellisource/main.py must exist."""
        main_file = PACKAGE_ROOT / "main.py"
        assert main_file.is_file(), f"{main_file} does not exist"

    @pytest.mark.parametrize("subpkg", EXPECTED_SUBPACKAGES)
    def test_subpackage_has_init(self, subpkg: str) -> None:
        """Each sub-package directory must contain an __init__.py file."""
        pkg_dir = PACKAGE_ROOT / subpkg
        init_file = pkg_dir / "__init__.py"
        assert pkg_dir.is_dir(), f"Directory {pkg_dir} does not exist"
        assert init_file.is_file(), f"{init_file} does not exist"

    @pytest.mark.parametrize("top_dir", EXPECTED_TOP_DIRS)
    def test_top_level_directory_exists(self, top_dir: str) -> None:
        """Top-level directories required by arch#§6 must exist."""
        dir_path = PROJECT_ROOT / top_dir
        assert dir_path.is_dir(), f"Directory {dir_path} does not exist"

    def test_alembic_ini_exists(self) -> None:
        """alembic/alembic.ini must exist."""
        alembic_ini = PROJECT_ROOT / "alembic" / "alembic.ini"
        assert alembic_ini.is_file(), f"{alembic_ini} does not exist"
