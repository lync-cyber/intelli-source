"""Unit-test suite fixtures.

Slow subprocess checks (mypy/ruff/uv dry-run, file-watcher polling) are marked
``@pytest.mark.slow`` and excluded from default runs via ``-m 'not slow'`` in
pyproject.toml. Run them explicitly with ``pytest -m slow``.
"""
