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
  outside a container call :func:`enforce_utf8_runtime`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

ENCODING: Final = "utf-8"


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
    """Pin the interpreter's standard streams to UTF-8.

    Idempotent and safe to call at any process entrypoint. No-ops on streams
    that are already UTF-8, lack ``reconfigure`` (e.g. replaced by a non-text
    object such as a captured buffer), or have been detached.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding=ENCODING)
        except (ValueError, OSError):
            continue


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
