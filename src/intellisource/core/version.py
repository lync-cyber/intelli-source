"""Single source of truth for the package version.

Resolution order: installed distribution metadata first (editable or wheel
installs), then the ``[project].version`` of the nearest ``pyproject.toml`` found
by walking up from this file, then a sentinel. Deployed images ship the source
via ``PYTHONPATH`` without installing the package, so distribution metadata is
absent there while ``pyproject.toml`` is present — the pyproject step keeps
``/health`` reporting the real version in that layout.
"""

from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

_DISTRIBUTION_NAME = "intellisource"
_UNKNOWN_VERSION = "0.0.0+unknown"


def _version_from_pyproject() -> str | None:
    """Read ``[project].version`` from the nearest ancestor ``pyproject.toml``."""
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if not pyproject.is_file():
            continue
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return None
        version = data.get("project", {}).get("version")
        return version if isinstance(version, str) else None
    return None


def get_version() -> str:
    """Return the ``intellisource`` version from metadata, pyproject, or sentinel."""
    try:
        return metadata.version(_DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return _version_from_pyproject() or _UNKNOWN_VERSION
