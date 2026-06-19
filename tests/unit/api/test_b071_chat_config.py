"""B-071: chat compaction params resolve from Settings (IS_CHAT_*).

Verifies the convergence decision — the chat compaction token budget and the
session TTL are operator-tunable via env, replacing the former hardcoded
module constants, while the compaction library keeps no opinion of its own.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from intellisource.api.chat_sessions import _compact_token_budget
from intellisource.core.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_chat_budget_default_is_6000(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IS_CHAT_COMPACT_TOKEN_BUDGET", raising=False)
    assert get_settings().chat_compact_token_budget == 6000


def test_chat_budget_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IS_CHAT_COMPACT_TOKEN_BUDGET", "12345")
    assert get_settings().chat_compact_token_budget == 12345


def test_compact_token_budget_helper_resolves_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IS_CHAT_COMPACT_TOKEN_BUDGET", "777")
    assert _compact_token_budget() == 777


def test_session_ttl_default_is_30(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IS_CHAT_SESSION_TTL_DAYS", raising=False)
    assert get_settings().chat_session_ttl_days == 30


def test_session_ttl_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IS_CHAT_SESSION_TTL_DAYS", "1")
    assert get_settings().chat_session_ttl_days == 1


@pytest.mark.parametrize(
    "var", ["IS_CHAT_SESSION_TTL_DAYS", "IS_CHAT_COMPACT_TOKEN_BUDGET"]
)
def test_zero_is_rejected(monkeypatch: pytest.MonkeyPatch, var: str) -> None:
    # ge=1 guards a footgun: TTL=0 would purge every session; budget=0 is nonsense.
    monkeypatch.setenv(var, "0")
    with pytest.raises(ValidationError):
        get_settings()
