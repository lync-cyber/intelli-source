"""Print which test categories to run based on the current diff vs main.

Triggered via ``make contract-check``. Looks at staged + unstaged changes
relative to ``origin/main`` and maps each touched file to one or more
test categories. Surfaces a recommendation so contract-sensitive changes
are caught before push instead of in CI.

This is a guidance tool, not a gate. It returns exit code 0 always so it
can run inline in ``make`` without failing the pipeline; the human
decides whether to act on the suggestion.

Sensitivity map (mirrors the historical regression patterns the PR-#64
review surfaced):

- ``src/intellisource/api/routers/``   → integration (FastAPI strict
  response_model validation; router signature changes invalidated three
  integration mocks in test_pg_vector_search.py)
- ``src/intellisource/search/``        → integration (SearchResponse /
  EnrichedSearchResult dataclass fields are part of the public API
  contract; mock fixtures must match)
- ``src/intellisource/storage/``       → integration (SearchResult /
  SQL column lists; ORM model fields)
- ``src/intellisource/llm/gateway/``   → integration (model resolution
  fallback path; streaming codepath)
- ``src/intellisource/agent/tools/``   → integration (atomic-execute
  contracts feed the agent runner that the chat / stream routes invoke)
"""

from __future__ import annotations

import subprocess
import sys

_SENSITIVE_PREFIXES: dict[str, tuple[str, ...]] = {
    "integration": (
        "src/intellisource/api/routers/",
        "src/intellisource/search/",
        "src/intellisource/storage/",
        "src/intellisource/llm/gateway/",
        "src/intellisource/agent/tools/",
    ),
}


def _git_diff_files() -> list[str]:
    """Return files changed vs ``origin/main`` (staged + unstaged + untracked)."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        committed = proc.stdout.splitlines() if proc.returncode == 0 else []
    except OSError:
        committed = []

    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
            check=False,
        )
        unstaged = proc.stdout.splitlines() if proc.returncode == 0 else []
    except OSError:
        unstaged = []

    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=False,
        )
        staged = proc.stdout.splitlines() if proc.returncode == 0 else []
    except OSError:
        staged = []

    return sorted({*committed, *unstaged, *staged})


def main() -> int:
    files = _git_diff_files()
    if not files:
        print("contract-check: no diff vs origin/main; nothing to recommend.")
        return 0

    triggered: dict[str, list[str]] = {}
    for category, prefixes in _SENSITIVE_PREFIXES.items():
        for f in files:
            normalized = f.replace("\\", "/")
            if any(normalized.startswith(p) for p in prefixes):
                triggered.setdefault(category, []).append(normalized)

    if not triggered:
        print(
            "contract-check: no contract-sensitive files touched. "
            "`make test-unit` is sufficient."
        )
        return 0

    print("contract-check: contract-sensitive files touched:")
    for category, hits in triggered.items():
        print(f"  category: {category}")
        for h in hits:
            print(f"    - {h}")
        print(f"  → recommended: make test-{category}")
    print()
    print(
        "Reminder: the PR-#64 integration regression (3 pg_vector_search mocks "
        "broken by router signature change) would have been caught here."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
