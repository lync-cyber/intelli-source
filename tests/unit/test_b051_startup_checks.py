"""B-051 Phase D: startup config warnings and IS_API_KEY placeholder guard."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestCollectStartupWarnings:
    """_collect_startup_warnings returns human-readable warning strings."""

    def _call(
        self,
        env: dict[str, str],
        *,
        src_dir_exists: bool = True,
        src_dir_has_yaml: bool = True,
    ) -> list[str]:
        from intellisource.main import _collect_startup_warnings

        with (
            patch.dict("os.environ", env, clear=True),
            patch("os.path.isdir", return_value=src_dir_exists),
            patch(
                "os.listdir",
                return_value=(["sources.yaml"] if src_dir_has_yaml else []),
            ),
        ):
            return _collect_startup_warnings()

    def test_no_required_warnings_when_core_configured(self) -> None:
        env = {
            "IS_API_KEY": "my-real-key",
            "DEEPSEEK_API_KEY": "sk-deepseek",
        }
        warnings = self._call(env)
        # LLM key and IS_API_KEY warnings are absent when properly set
        assert not any("LLM" in w for w in warnings)
        assert not any("IS_API_KEY not set" in w for w in warnings)

    def test_warns_when_llm_key_absent(self) -> None:
        env = {"IS_API_KEY": "real-key"}
        warnings = self._call(env)
        assert any("LLM" in w for w in warnings)

    def test_warns_when_sources_dir_missing(self) -> None:
        env = {"IS_API_KEY": "real-key", "DEEPSEEK_API_KEY": "sk-x"}
        warnings = self._call(env, src_dir_exists=False, src_dir_has_yaml=False)
        assert any("missing" in w for w in warnings)

    def test_warns_when_sources_dir_empty(self) -> None:
        env = {"IS_API_KEY": "real-key", "DEEPSEEK_API_KEY": "sk-x"}
        warnings = self._call(env, src_dir_exists=True, src_dir_has_yaml=False)
        assert any("empty" in w or "no YAML" in w for w in warnings)

    def test_warns_for_each_unconfigured_channel(self) -> None:
        env = {"IS_API_KEY": "real-key", "DEEPSEEK_API_KEY": "sk-x"}
        warnings = self._call(env)
        channel_warns = [w for w in warnings if "channel" in w]
        assert len(channel_warns) == 3

    def test_no_api_key_warn(self) -> None:
        env: dict[str, str] = {}
        warnings = self._call(env)
        assert any("IS_API_KEY" in w for w in warnings)

    def test_placeholder_api_key_not_in_warnings(self) -> None:
        env = {"IS_API_KEY": "change-me-in-production"}
        warnings = self._call(env)
        # placeholder triggers startup refusal, not just a warning
        assert not any("placeholder" in w.lower() for w in warnings)


class TestLifespanApiKeyGuard:
    """_lifespan raises RuntimeError when IS_API_KEY is the default placeholder."""

    def test_placeholder_raises_runtime_error(self) -> None:
        from intellisource.main import _API_KEY_PLACEHOLDER

        assert _API_KEY_PLACEHOLDER == "change-me-in-production"

    @pytest.mark.asyncio
    async def test_lifespan_raises_on_placeholder(self) -> None:
        from fastapi import FastAPI

        from intellisource.main import _lifespan

        app = FastAPI(lifespan=_lifespan)
        with patch.dict("os.environ", {"IS_API_KEY": "change-me-in-production"}):
            with pytest.raises(RuntimeError, match="placeholder"):
                async with _lifespan(app):
                    pass


class TestDoctorEnvCheck:
    """doctor _doctor_env returns correct ok/fail tuples."""

    def test_placeholder_api_key_is_fail(self) -> None:
        from intellisource.cli.main import _doctor_env

        items = dict(
            (label, (ok, msg))
            for label, ok, msg in _doctor_env({"IS_API_KEY": "change-me-in-production"})
        )
        ok, msg = items["IS_API_KEY"]
        assert ok is False
        assert "placeholder" in msg

    def test_real_api_key_passes(self) -> None:
        from intellisource.cli.main import _doctor_env

        env = {
            "IS_API_KEY": "my-secret-key",
            "IS_DATABASE_URL": "postgresql+asyncpg://...",
            "IS_REDIS_URL": "redis://localhost:6379/0",
            "IS_CELERY_BROKER_URL": "redis://localhost:6379/0",
            "DEEPSEEK_API_KEY": "sk-x",
        }
        items = dict((label, (ok, msg)) for label, ok, msg in _doctor_env(env))
        assert items["IS_API_KEY"][0] is True
        assert items["LLM key"][0] is True

    def test_missing_llm_key_fails(self) -> None:
        from intellisource.cli.main import _doctor_env

        items = dict(
            (label, (ok, msg)) for label, ok, msg in _doctor_env({"IS_API_KEY": "x"})
        )
        assert items["LLM key"][0] is False

    def test_channel_without_creds_is_optional(self) -> None:
        from intellisource.cli.main import _doctor_env

        items = dict((label, (ok, msg)) for label, ok, msg in _doctor_env({}))
        # ok is None for optional items
        assert items.get("channel wework", (None, ""))[0] is None


class TestLoadDotenvFile:
    """_load_dotenv_file parses key=value correctly."""

    def test_parses_simple_pairs(self, tmp_path: pytest.TempPathFactory) -> None:
        from intellisource.cli.main import _load_dotenv_file

        env_file = tmp_path / ".env"  # type: ignore[operator]
        env_file.write_text("IS_API_KEY=secret\nIS_DB_USER=admin\n", encoding="utf-8")
        result = _load_dotenv_file(str(env_file))
        assert result["IS_API_KEY"] == "secret"
        assert result["IS_DB_USER"] == "admin"

    def test_skips_comments_and_blanks(self, tmp_path: pytest.TempPathFactory) -> None:
        from intellisource.cli.main import _load_dotenv_file

        env_file = tmp_path / ".env"  # type: ignore[operator]
        env_file.write_text("# comment\n\nKEY=val\n", encoding="utf-8")
        result = _load_dotenv_file(str(env_file))
        assert list(result.keys()) == ["KEY"]

    def test_returns_empty_for_missing_file(self) -> None:
        from intellisource.cli.main import _load_dotenv_file

        result = _load_dotenv_file("/nonexistent/.env")
        assert result == {}
