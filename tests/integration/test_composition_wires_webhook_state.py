"""Integration tests for build_api_composition webhook wiring (R-001).

Closes the EXP-005 assembly gap surfaced in T-098 r1 code-review: the
webhook router reads `app.state.wechat_webhook_token` /
`wework_webhook_token` / `wechat_cs_messenger` / `wework_cs_messenger` /
`background_tasks` but no production code path was setting them. These
tests assert composition.build_api_composition sets each slot.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI


def _make_db_manager() -> Any:
    """Return a minimal DatabaseManager mock — composition only stores it."""
    return MagicMock()


def _clean_env() -> dict[str, str]:
    """Copy current env minus all IS_WECHAT_* / IS_WEWORK_* keys."""
    return {
        k: v
        for k, v in os.environ.items()
        if not (k.startswith("IS_WECHAT_") or k.startswith("IS_WEWORK_"))
    }


@contextmanager
def _isolated_composition_env(env: dict[str, str]) -> Iterator[None]:
    """Patch upstream composition helpers so only webhook wiring is exercised.

    `build_api_composition` calls `_build_deps_bundle` which in turn pulls
    `WeChatDistributor.from_env` — this fails when IS_WECHAT_APP_* is unset
    and would block the webhook-only assertion under test. Stub those out
    so the test only exercises `_install_webhook_state`.
    """
    from intellisource.agent.runner import AgentRunner

    deps_bundle_stub = MagicMock()
    deps_bundle_stub.llm_gateway = MagicMock()
    deps_bundle_stub.collector_registry = MagicMock()
    deps_bundle_stub.distributor = MagicMock()
    pipeline_loader_stub = MagicMock()
    agent_runner_stub = MagicMock(spec=AgentRunner)

    with (
        patch.dict(os.environ, env, clear=True),
        patch(
            "intellisource.composition.api._build_deps_bundle",
            return_value=deps_bundle_stub,
        ),
        patch(
            "intellisource.composition.api._install_agent_runner",
            return_value=agent_runner_stub,
        ),
        patch(
            "intellisource.composition.api.build_pipeline_loader",
            return_value=pipeline_loader_stub,
        ),
    ):
        yield


class TestWebhookStateAssembly:
    """R-001: build_api_composition must populate webhook state slots."""

    def test_tokens_set_when_env_present(self) -> None:
        """Both webhook tokens land on app.state when env vars are configured."""
        from intellisource.composition import build_api_composition

        app = FastAPI()
        env = _clean_env()
        env["IS_WECHAT_WEBHOOK_TOKEN"] = "wx_token_value"
        env["IS_WEWORK_WEBHOOK_TOKEN"] = "ww_token_value"

        with _isolated_composition_env(env):
            build_api_composition(app, _make_db_manager(), MagicMock())

        assert app.state.wechat_webhook_token == "wx_token_value"
        assert app.state.wework_webhook_token == "ww_token_value"

    def test_tokens_empty_when_env_absent(self) -> None:
        """Tokens default to '' when env vars are unset — router will 403."""
        from intellisource.composition import build_api_composition

        app = FastAPI()

        with _isolated_composition_env(_clean_env()):
            build_api_composition(app, _make_db_manager(), MagicMock())

        assert app.state.wechat_webhook_token == ""
        assert app.state.wework_webhook_token == ""

    def test_cs_messenger_none_when_fully_unset(self) -> None:
        """CS messengers stay None when IS_WECHAT_APP_* / IS_WEWORK_* unset."""
        from intellisource.composition import build_api_composition

        app = FastAPI()

        with _isolated_composition_env(_clean_env()):
            build_api_composition(app, _make_db_manager(), MagicMock())

        assert app.state.wechat_cs_messenger is None
        assert app.state.wework_cs_messenger is None

    def test_wechat_cs_messenger_set_when_env_complete(self) -> None:
        """WeChat CS messenger is constructed when both app_id + secret set."""
        from intellisource.composition import build_api_composition
        from intellisource.distributor.wechat_cs_client import (
            WeChatCustomerServiceClient,
        )

        app = FastAPI()
        env = _clean_env()
        env["IS_WECHAT_APP_ID"] = "wx_app_id"
        env["IS_WECHAT_APP_SECRET"] = "wx_secret"

        with _isolated_composition_env(env):
            build_api_composition(app, _make_db_manager(), MagicMock())

        assert isinstance(app.state.wechat_cs_messenger, WeChatCustomerServiceClient)

    def test_wechat_partial_env_hard_fails(self) -> None:
        """Partial IS_WECHAT_* env raises during build (sprint-9 locked policy)."""
        from intellisource.composition import build_api_composition

        app = FastAPI()
        env = _clean_env()
        env["IS_WECHAT_APP_ID"] = (
            "wx_app_id"  # IS_WECHAT_APP_SECRET intentionally unset
        )

        with _isolated_composition_env(env):
            with pytest.raises(ValueError, match="IS_WECHAT_APP_SECRET"):
                build_api_composition(app, _make_db_manager(), MagicMock())

    def test_wework_cs_messenger_set_when_env_complete(self) -> None:
        """WeWork CS messenger constructed when corp_id + secret + agent_id set."""
        from intellisource.composition import build_api_composition
        from intellisource.distributor.wework_cs_client import (
            WeWorkCustomerServiceClient,
        )

        app = FastAPI()
        env = _clean_env()
        env["IS_WEWORK_CORP_ID"] = "ww_corp_id"
        env["IS_WEWORK_CORP_SECRET"] = "ww_secret"
        env["IS_WEWORK_AGENT_ID"] = "1000007"

        with _isolated_composition_env(env):
            build_api_composition(app, _make_db_manager(), MagicMock())

        assert isinstance(app.state.wework_cs_messenger, WeWorkCustomerServiceClient)

    def test_wework_partial_env_hard_fails(self) -> None:
        """Partial IS_WEWORK_* env raises during build."""
        from intellisource.composition import build_api_composition

        app = FastAPI()
        env = _clean_env()
        env["IS_WEWORK_CORP_ID"] = "ww_corp_id"  # missing CORP_SECRET + AGENT_ID

        with _isolated_composition_env(env):
            with pytest.raises(ValueError, match="IS_WEWORK"):
                build_api_composition(app, _make_db_manager(), MagicMock())

    def test_background_tasks_set_initialised(self) -> None:
        """app.state.background_tasks is an empty set after composition."""
        from intellisource.composition import build_api_composition

        app = FastAPI()
        with _isolated_composition_env(_clean_env()):
            build_api_composition(app, _make_db_manager(), MagicMock())

        assert isinstance(app.state.background_tasks, set)
        assert len(app.state.background_tasks) == 0
