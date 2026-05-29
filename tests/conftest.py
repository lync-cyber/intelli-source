"""Root conftest for IntelliSource test suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from intellisource.core.settings import get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Drop the cached Settings so each test re-reads its monkeypatched env."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
