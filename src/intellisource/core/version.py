"""Single source of truth for the package version.

The value is read from the installed distribution metadata so it always tracks
``pyproject.toml``'s ``[project].version`` with no hand-maintained copy to drift.
"""

from __future__ import annotations

from importlib import metadata

_DISTRIBUTION_NAME = "intellisource"

# Returned when the package is not installed (e.g. running from a source tree
# without an editable install). Never expected in deployed images.
_UNKNOWN_VERSION = "0.0.0+unknown"


def get_version() -> str:
    """Return the installed ``intellisource`` version, or a sentinel if absent."""
    try:
        return metadata.version(_DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return _UNKNOWN_VERSION
