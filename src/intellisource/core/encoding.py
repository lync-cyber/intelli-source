"""Single source of truth for the project's text-encoding contract.

The contract is one sentence: every text boundary is UTF-8.

Two layers enforce it, and this module is the connective tissue between them:

* **File IO** declares ``encoding=`` at every call (machine-enforced by ruff
  ``PLW1514``). This is a local, always-correct guarantee independent of the
  host locale.
* **The process floor** covers the surfaces no per-call argument can reach —
  stdout/stderr, subprocess text streams and the filesystem-path codec — which
  otherwise fall back to the host locale (e.g. cp936/gbk on a default Windows
  console, where printing Chinese raises ``UnicodeEncodeError``). Containers
  pin this via ``PYTHONUTF8`` / ``PYTHONIOENCODING``; entrypoints that may run
  outside a container call :func:`enforce_utf8_runtime`, which self-applies the
  same floor so a bare ``intellisource ...`` needs no ``PYTHONUTF8=1`` prefix.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

ENCODING: Final = "utf-8"

# Set on a child relaunched by enforce_utf8_runtime; a still-misdetected
# environment then falls through to stream reconfigure instead of re-exec'ing
# again, bounding the chain at one relaunch.
_REEXEC_SENTINEL: Final = "_INTELLISOURCE_UTF8_REEXEC"


def read_text(path: Path | str) -> str:
    """Read a whole text file under the UTF-8 contract.

    The single read entrypoint for the project: callers pass only the path,
    never an ``encoding=`` — the contract lives here, not at each call site.
    """
    return Path(path).read_text(encoding=ENCODING)


def write_text(path: Path | str, data: str) -> None:
    """Write a whole text file under the UTF-8 contract.

    The single write entrypoint; see :func:`read_text`.
    """
    Path(path).write_text(data, encoding=ENCODING)


def enforce_utf8_runtime() -> None:
    """Pin the current process's standard streams (stdin/stdout/stderr) to UTF-8.

    Idempotent and safe to call anywhere — at a genuine entrypoint, inside a
    test harness, or from an embedding host — because it only touches this
    interpreter's own streams. No-ops on streams that are already UTF-8, lack
    ``reconfigure`` (e.g. replaced by a non-text object such as a captured
    buffer), or have been detached.

    This is the always-safe half of the contract. Relaunching a bare command
    into *full* UTF-8 mode is the entrypoint-only :func:`reexec_in_utf8_mode_if_needed`.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding=ENCODING)
        except (ValueError, OSError):
            continue


def reexec_in_utf8_mode_if_needed() -> None:
    """Relaunch the process in UTF-8 mode when it did not start there, then exit.

    Call **only from a real process entrypoint** (a console-script ``main``),
    never from library code, a test harness, or an embedding host — it
    re-executes ``sys.orig_argv`` and exits with the child's status, which is
    correct only when this process exists solely to run that command. A bare
    ``intellisource ...`` on a non-UTF-8 console (e.g. Windows cp936) then
    behaves as if ``PYTHONUTF8=1`` were typed: full UTF-8 mode that also fixes
    ``locale.getpreferredencoding()``, the default ``open()`` codec for any
    third-party library, and is inherited by every subprocess.

    No-ops (returns) when already in UTF-8 mode, or when relaunch is not viable —
    already attempted once (sentinel), unknown argv, or no interpreter path
    (frozen build, embedded interpreter) — leaving :func:`enforce_utf8_runtime`
    to apply the stream floor.
    """
    if _utf8_mode_active():
        return
    argv = list(getattr(sys, "orig_argv", ()) or ())
    if os.environ.get(_REEXEC_SENTINEL) or not argv or not sys.executable:
        return
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": ENCODING,
        _REEXEC_SENTINEL: "1",
    }
    completed = subprocess.run(argv, env=env, check=False)
    raise SystemExit(completed.returncode)


def _utf8_mode_active() -> bool:
    """True when the interpreter runs in UTF-8 mode (``PYTHONUTF8`` / ``-X utf8``)."""
    return bool(sys.flags.utf8_mode)


def _normalize(name: str | None) -> str:
    return (name or "").replace("-", "").replace("_", "").lower()


def is_utf8_environment() -> bool:
    """True when stdout and the filesystem codec already resolve to UTF-8.

    Used to detect drift: a launch context that forgot the process floor (bare
    ``pytest`` on a non-UTF-8 Windows console) resolves False, while any
    UTF-8 locale or ``PYTHONUTF8=1`` interpreter resolves True.
    """
    out = _normalize(getattr(sys.stdout, "encoding", None))
    fs = _normalize(sys.getfilesystemencoding())
    return out == "utf8" and fs == "utf8"
