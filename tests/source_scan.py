"""Cross-platform helpers replacing shell grep in tests."""

from __future__ import annotations

import re
from pathlib import Path


def find_substring_in_tree(
    root: str | Path,
    pattern: str,
    *,
    glob: str = "*.py",
) -> list[str]:
    """Return ``path:line:content`` lines containing ``pattern``."""
    matches: list[str] = []
    base = Path(root)
    for path in sorted(base.rglob(glob)):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if pattern in line:
                matches.append(f"{path}:{line_no}:{line}")
    return matches


def find_regex_in_tree(
    root: str | Path,
    pattern: str,
    *,
    glob: str = "*.py",
) -> list[str]:
    """Return ``path:line:content`` lines matching regex ``pattern``."""
    rx = re.compile(pattern)
    matches: list[str] = []
    base = Path(root)
    for path in sorted(base.rglob(glob)):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                matches.append(f"{path}:{line_no}:{line}")
    return matches
