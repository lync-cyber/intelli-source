"""cleanup_chat_sessions beat task body wiring (S-2 Piece B)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import intellisource.storage.repositories.chat_session as chat_repo_mod
from intellisource.core.settings import get_settings
from intellisource.scheduler import tasks as tasks_mod
from intellisource.scheduler.tasks import _cleanup_chat_sessions_body


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False


def test_cleanup_body_raises_when_not_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tasks_mod.celery_app, "_chat_session_cleanup_factory", None, raising=False
    )
    with pytest.raises(RuntimeError, match="not wired"):
        _cleanup_chat_sessions_body()


def _run_cleanup_capturing_before(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], _FakeSession]:
    captured: dict[str, Any] = {}
    sess = _FakeSession()

    def _factory() -> _FakeSession:
        return sess

    class _Repo:
        def __init__(self, _s: Any) -> None: ...

        async def cleanup_expired(self, before: datetime) -> int:
            captured["before"] = before
            return 7

    monkeypatch.setattr(
        tasks_mod.celery_app, "_chat_session_cleanup_factory", _factory, raising=False
    )
    monkeypatch.setattr(chat_repo_mod, "ChatSessionRepository", _Repo)

    result = _cleanup_chat_sessions_body()
    captured["result"] = result
    return captured, sess


def test_cleanup_body_purges_expired_when_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IS_CHAT_SESSION_TTL_DAYS", raising=False)
    captured, sess = _run_cleanup_capturing_before(monkeypatch)

    assert captured["result"] == {"deleted": 7}
    assert sess.committed is True
    expected = datetime.now(timezone.utc) - timedelta(days=30)
    assert abs((captured["before"] - expected).total_seconds()) < 3600


def test_cleanup_cutoff_reads_settings_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IS_CHAT_SESSION_TTL_DAYS", "1")
    captured, _sess = _run_cleanup_capturing_before(monkeypatch)

    expected = datetime.now(timezone.utc) - timedelta(days=1)
    assert abs((captured["before"] - expected).total_seconds()) < 3600
