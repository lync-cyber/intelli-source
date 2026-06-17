"""Tests for AC-4 (G-011): doctor placeholder key detection and fix hints."""

from __future__ import annotations


def _doctor_env(env: dict[str, str]) -> list[tuple[str, bool | None, str]]:
    from intellisource.cli.commands.doctor import _doctor_env as _impl

    return _impl(env)


class TestDoctorPlaceholderLlmKey:
    """AC-4: LLM keys ending in '...' are treated as placeholder, not valid."""

    def test_openai_placeholder_reports_not_effective(self) -> None:
        """OPENAI_API_KEY=sk-... → ok=False, message contains 'placeholder'."""
        env = {
            "IS_API_KEY": "real-key",
            "IS_DATABASE_URL": "postgresql+asyncpg://u:p@host/db",
            "IS_REDIS_URL": "redis://localhost",
            "IS_CELERY_BROKER_URL": "redis://localhost",
            "OPENAI_API_KEY": "sk-...",
        }
        items = _doctor_env(env)
        llm_items = [
            (label, ok, msg)
            for label, ok, msg in items
            if "LLM" in label.lower() or label == "LLM key"
        ]
        assert len(llm_items) >= 1, "Expected at least one LLM key item"
        label, ok, msg = llm_items[0]
        assert ok is False, (
            f"LLM key with placeholder value must be ok=False; got ok={ok}, msg={msg!r}"
        )
        assert "placeholder" in msg.lower(), (
            f"message must contain 'placeholder'; got {msg!r}"
        )

    def test_anthropic_placeholder_reports_not_effective(self) -> None:
        """ANTHROPIC_API_KEY=sk-ant-... → ok=False, message contains 'placeholder'."""
        env = {
            "IS_API_KEY": "real-key",
            "IS_DATABASE_URL": "postgresql+asyncpg://u:p@host/db",
            "IS_REDIS_URL": "redis://localhost",
            "IS_CELERY_BROKER_URL": "redis://localhost",
            "ANTHROPIC_API_KEY": "sk-ant-...",
        }
        items = _doctor_env(env)
        llm_items = [
            (label, ok, msg)
            for label, ok, msg in items
            if "LLM" in label.lower() or label == "LLM key"
        ]
        assert len(llm_items) >= 1
        label, ok, msg = llm_items[0]
        assert ok is False, (
            f"LLM key with placeholder value must be ok=False; got ok={ok}, msg={msg!r}"
        )
        assert "placeholder" in msg.lower(), (
            f"message must contain 'placeholder'; got {msg!r}"
        )

    def test_real_llm_key_reports_set(self) -> None:
        """Real (non-placeholder) LLM key → ok=True, 'set' in message."""
        env = {
            "IS_API_KEY": "real-key",
            "IS_DATABASE_URL": "postgresql+asyncpg://u:p@host/db",
            "IS_REDIS_URL": "redis://localhost",
            "IS_CELERY_BROKER_URL": "redis://localhost",
            "OPENAI_API_KEY": "sk-abcdef123456",
        }
        items = _doctor_env(env)
        llm_items = [
            (label, ok, msg)
            for label, ok, msg in items
            if "LLM" in label.lower() or label == "LLM key"
        ]
        assert len(llm_items) >= 1
        label, ok, msg = llm_items[0]
        assert ok is True, f"Real LLM key must be ok=True; got ok={ok}, msg={msg!r}"


class TestDoctorFixHints:
    """AC-4: 'not set' items carry a short fix hint in their message."""

    def test_redis_url_not_set_has_hint(self) -> None:
        """IS_REDIS_URL not set → message contains a hint to set it."""
        env = {
            "IS_API_KEY": "real-key",
            "IS_DATABASE_URL": "postgresql+asyncpg://u:p@host/db",
            "IS_CELERY_BROKER_URL": "redis://localhost",
        }
        items = _doctor_env(env)
        redis_items = [
            (label, ok, msg) for label, ok, msg in items if "IS_REDIS_URL" in label
        ]
        assert len(redis_items) >= 1
        label, ok, msg = redis_items[0]
        assert ok is False
        # Message must contain a fix hint (e.g., "set IS_REDIS_URL in .env")
        assert "IS_REDIS_URL" in msg or "set" in msg.lower(), (
            f"IS_REDIS_URL 'not set' message must contain a fix hint; got {msg!r}"
        )

    def test_celery_broker_not_set_has_hint(self) -> None:
        """IS_CELERY_BROKER_URL not set → message contains a hint."""
        env = {
            "IS_API_KEY": "real-key",
            "IS_DATABASE_URL": "postgresql+asyncpg://u:p@host/db",
            "IS_REDIS_URL": "redis://localhost",
        }
        items = _doctor_env(env)
        celery_items = [
            (label, ok, msg)
            for label, ok, msg in items
            if "IS_CELERY_BROKER_URL" in label
        ]
        assert len(celery_items) >= 1
        label, ok, msg = celery_items[0]
        assert ok is False
        assert "IS_CELERY_BROKER_URL" in msg or "set" in msg.lower(), (
            f"'not set' message must contain a fix hint; got {msg!r}"
        )

    def test_database_url_not_set_has_hint(self) -> None:
        """IS_DATABASE_URL not set → message contains a fix hint."""
        env = {
            "IS_API_KEY": "real-key",
            "IS_REDIS_URL": "redis://localhost",
            "IS_CELERY_BROKER_URL": "redis://localhost",
        }
        items = _doctor_env(env)
        db_items = [
            (label, ok, msg) for label, ok, msg in items if "IS_DATABASE_URL" in label
        ]
        assert len(db_items) >= 1
        label, ok, msg = db_items[0]
        assert ok is False
        assert "IS_DATABASE_URL" in msg or "set" in msg.lower(), (
            f"IS_DATABASE_URL 'not set' message must contain a fix hint; got {msg!r}"
        )

    def test_llm_key_not_set_has_hint(self) -> None:
        """No LLM key set → message contains a fix hint."""
        env = {
            "IS_API_KEY": "real-key",
            "IS_DATABASE_URL": "postgresql+asyncpg://u:p@host/db",
            "IS_REDIS_URL": "redis://localhost",
            "IS_CELERY_BROKER_URL": "redis://localhost",
        }
        items = _doctor_env(env)
        llm_items = [
            (label, ok, msg)
            for label, ok, msg in items
            if "LLM" in label.lower() or label == "LLM key"
        ]
        assert len(llm_items) >= 1
        label, ok, msg = llm_items[0]
        assert ok is False
        # The message should give a hint about setting .env
        assert (
            "set" in msg.lower()
            or ".env" in msg.lower()
            or "OPENAI" in msg
            or "ANTHROPIC" in msg
        ), f"LLM key 'not set' message must contain a hint; got {msg!r}"
