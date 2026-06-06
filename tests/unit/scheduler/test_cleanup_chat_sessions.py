"""cleanup_chat_sessions beat task body wiring (S-2 Piece B)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import intellisource.storage.repositories.chat_session as chat_repo_mod
from intellisource.scheduler import tasks as tasks_mod
from intellisource.scheduler.tasks import (
    CHAT_SESSION_TTL_DAYS,
    _cleanup_chat_sessions_body,
)


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


def test_cleanup_body_purges_expired_when_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    assert result == {"deleted": 7}
    assert sess.committed is True
    expected = datetime.now(timezone.utc) - timedelta(days=CHAT_SESSION_TTL_DAYS)
    assert abs((captured["before"] - expected).total_seconds()) < 3600
