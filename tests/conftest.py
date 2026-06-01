"""Root conftest for IntelliSource test suite."""

from __future__ import annotations

import warnings
from collections.abc import Iterator

import pytest
import structlog

from intellisource.core.encoding import is_utf8_environment
from intellisource.core.settings import get_settings


def pytest_configure(config: pytest.Config) -> None:
    """Flag a launch context that skipped the UTF-8 process floor.

    ``make test-unit`` / CI set ``PYTHONUTF8=1``; a bare ``pytest`` on a
    non-UTF-8 console (e.g. Windows cp936) resolves False here. Warn rather
    than fail so the suite still runs, but the drift is visible.
    """
    if not is_utf8_environment():
        warnings.warn(
            "UTF-8 process floor not applied (stdout/filesystem codec is not "
            "UTF-8). Run via `make test-unit` or set PYTHONUTF8=1 to match the "
            "container runtime.",
            stacklevel=2,
        )


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    """Reset structlog to defaults around each test.

    ``setup_logging()`` (triggered by app/lifespan tests) reconfigures the
    process-wide structlog with the stdlib BoundLogger wrapper. Left in place
    it leaks into later tests and changes how ``structlog.testing.capture_logs``
    renders events (raw ``%s`` + positional_args vs interpolated). Resetting
    per test keeps log capture deterministic and isolates config side effects.
    """
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Drop the cached Settings so each test re-reads its monkeypatched env."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop unit tests from auto-loading the developer's real docker/.env.

    ``get_settings()`` / ``load_provider_env()`` resolve the env file via the
    ``settings`` module's ``resolve_env_file`` reference; docker/.env holds
    real, gitignored secrets on a dev machine. Stubbing that reference (not the
    paths-module original) isolates them while leaving test_paths.py free to
    exercise the real resolver, and survives ``patch.dict(os.environ,
    clear=True)`` since it does not rely on env vars. Tests needing a specific
    env file re-stub this reference themselves.
    """
    monkeypatch.setattr("intellisource.core.settings.resolve_env_file", lambda: None)


@pytest.fixture(autouse=True)
def _stub_distributor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default fake env for distributor channels.

    sprint-9 用户决策：`build_distributor_facade` 在 env 缺失时启动期硬失败
    （`IS_WECHAT_APP_ID` / `IS_WEWORK_CORP_ID` / `IS_SMTP_*` 等），但绝大多数
    测试不关心凭证内容、只关心 composition 装配能跑通。本 fixture 提供 fake
    默认值；专门验证 hard-fail 的测试（test_facade.py 中
    TestBuildDistributorFacadeEnvGuard）在测试体内通过 `monkeypatch.delenv`
    精准移除目标 env 来覆盖本 fixture，pytest 顺序保证 fixture 先 setup，
    测试体的 delenv 后生效。
    """
    monkeypatch.setenv("IS_WECHAT_APP_ID", "test_wechat_app_id")
    monkeypatch.setenv("IS_WECHAT_APP_SECRET", "test_wechat_app_secret")
    monkeypatch.setenv("IS_WEWORK_CORP_ID", "test_wework_corp_id")
    monkeypatch.setenv("IS_WEWORK_CORP_SECRET", "test_wework_corp_secret")
    monkeypatch.setenv("IS_WEWORK_AGENT_ID", "1000001")
    monkeypatch.setenv("IS_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("IS_SMTP_USER", "test@example.com")
    monkeypatch.setenv("IS_SMTP_PASSWORD", "test_password")
