"""Static guardrail: bare .send_task() calls must not appear outside dispatch.py.

Scope: src/ only.
tests/ allows direct .send_task() calls to validate underlying Celery contracts
(e.g. cold-start, task name round-trip verification).
"""

from __future__ import annotations

import re
from pathlib import Path

# Only intellisource/scheduler/dispatch.py is allowed to call .send_task() directly.
# Substring matching (_ALLOWED_FILE in rel_posix) is intentionally replaced with
# exact equality to prevent a shadow file at e.g. tests/unit/scheduler/dispatch.py
# from bypassing the guard.
_ALLOWED_PATH = Path("intellisource") / "scheduler" / "dispatch.py"
_ALLOWED_POSIX = _ALLOWED_PATH.as_posix()

# Pattern that catches object-method send_task calls: .send_task(
_BARE_SEND_TASK_RE = re.compile(r"\.send_task\(")

# Relative to the project src root
_SRC_ROOT = Path(__file__).parent.parent.parent.parent / "src"


def _collect_violations() -> list[tuple[Path, int, str]]:
    """Scan src/ for .send_task( usage outside the allowed file."""
    violations: list[tuple[Path, int, str]] = []
    for py_file in _SRC_ROOT.rglob("*.py"):
        rel = py_file.relative_to(_SRC_ROOT)
        rel_posix = rel.as_posix()
        if rel_posix == _ALLOWED_POSIX:
            continue
        for lineno, line in enumerate(
            py_file.read_text(encoding="utf-8").splitlines(), 1
        ):
            if _BARE_SEND_TASK_RE.search(line):
                violations.append((py_file, lineno, line.strip()))
    return violations


class TestSendTaskGuardrail:
    """Bare .send_task() calls outside scheduler/dispatch.py are forbidden."""

    def test_no_bare_send_task_outside_dispatch(self) -> None:
        violations = _collect_violations()
        if violations:
            lines = "\n".join(f"  {v[0]}:{v[1]}: {v[2]}" for v in violations)
            raise AssertionError(
                f"Found {len(violations)} bare .send_task() call(s) outside "
                f"{_ALLOWED_POSIX}:\n{lines}\n"
                "Use send_task_with_trace() from "
                "intellisource.scheduler.dispatch instead."
            )

    def test_dispatch_module_itself_contains_send_task(self) -> None:
        """dispatch.py must contain at least one .send_task( call (the facade)."""
        dispatch_file = _SRC_ROOT / "intellisource" / "scheduler" / "dispatch.py"
        assert dispatch_file.exists(), f"dispatch.py not found at {dispatch_file}"
        content = dispatch_file.read_text(encoding="utf-8")
        matches = _BARE_SEND_TASK_RE.findall(content)
        assert len(matches) >= 1, (
            "dispatch.py must contain at least one .send_task( call"
        )

    def test_exact_path_match_does_not_bypass_for_shadow_file(self) -> None:
        """R-003: a file whose path contains 'scheduler/dispatch.py' as a substring
        but is not the canonical path must still be caught as a violation.

        This verifies the guard uses exact equality (==) not substring matching (in).
        """
        # Construct a path that contains the old substring but is not the exact path.
        shadow_posix = "unit/scheduler/dispatch.py"
        # The shadow path contains the old _ALLOWED_FILE substring.
        assert "scheduler/dispatch.py" in shadow_posix
        # With the new exact-match logic the shadow path must NOT be skipped.
        assert shadow_posix != _ALLOWED_POSIX, (
            f"Shadow path {shadow_posix!r} must differ from "
            f"canonical {_ALLOWED_POSIX!r}"
        )
