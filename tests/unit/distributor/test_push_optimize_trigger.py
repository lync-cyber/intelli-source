"""Unit tests for AC-T100-3: DistributorFacade push-optimize follow-up trigger."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@asynccontextmanager
async def _empty_session() -> Any:
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    session.scalars = AsyncMock(return_value=MagicMock(all=lambda: []))
    yield session


def _make_facade(*, celery_app: Any) -> Any:
    from intellisource.distributor.facade import DistributorFacade

    matcher = MagicMock()
    matcher.match = MagicMock(return_value=[])
    return DistributorFacade(
        session_factory=_empty_session,
        matcher=matcher,
        channels={},
        celery_app=celery_app,
    )


def _make_sub(*, sid: str, channel: str = "wechat") -> SimpleNamespace:
    return SimpleNamespace(id=sid, channel=channel, recipient="user-1")


class TestPushOptimizeTrigger:
    """`_maybe_trigger_push_optimize` only fires when env flag is on."""

    def test_no_trigger_when_env_disabled(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("IS_PUSH_OPTIMIZE_ENABLED", raising=False)
        celery = MagicMock()
        facade = _make_facade(celery_app=celery)

        facade._maybe_trigger_push_optimize(content_id="c-1", channel="wechat")

        celery.send_task.assert_not_called()

    def test_no_trigger_when_celery_app_missing(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("IS_PUSH_OPTIMIZE_ENABLED", "1")
        facade = _make_facade(celery_app=None)

        # Should not raise, just no-op
        facade._maybe_trigger_push_optimize(content_id="c-1", channel="wechat")

    def test_trigger_when_enabled(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("IS_PUSH_OPTIMIZE_ENABLED", "1")
        celery = MagicMock()
        facade = _make_facade(celery_app=celery)

        facade._maybe_trigger_push_optimize(content_id="c-42", channel="wework")

        celery.send_task.assert_called_once()
        call = celery.send_task.call_args
        assert call.args[0] == "run_pipeline"
        kwargs = call.kwargs["kwargs"]
        assert kwargs["pipeline_name"] == "push-optimize"
        assert kwargs["params"] == {"content_id": "c-42", "channel": "wework"}

    def test_send_task_exception_is_swallowed(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("IS_PUSH_OPTIMIZE_ENABLED", "1")
        celery = MagicMock()
        celery.send_task = MagicMock(side_effect=RuntimeError("broker down"))
        facade = _make_facade(celery_app=celery)

        # Must not raise — push-optimize failure cannot block main distribute
        facade._maybe_trigger_push_optimize(content_id="c-1", channel="wechat")


class TestDistributeIntegration:
    """End-to-end: distribute() triggers push-optimize after successful send."""

    @pytest.mark.asyncio
    async def test_distribute_invokes_optimize_after_send(
        self, monkeypatch: Any
    ) -> None:
        from intellisource.distributor.facade import DistributorFacade

        monkeypatch.setenv("IS_PUSH_OPTIMIZE_ENABLED", "1")

        content = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")
        sub = _make_sub(sid="22222222-2222-2222-2222-222222222222")

        @asynccontextmanager
        async def session_factory() -> Any:
            session = MagicMock()
            session.get = AsyncMock(return_value=content)
            session.scalars = AsyncMock(return_value=MagicMock(all=lambda: [sub]))
            session.commit = AsyncMock()
            yield session

        matcher = MagicMock()
        matcher.match = MagicMock(return_value=[sub])

        channel = MagicMock()
        channel.distribute = AsyncMock(return_value=None)

        celery = MagicMock()
        facade = DistributorFacade(
            session_factory=session_factory,
            matcher=matcher,
            channels={"wechat": channel},
            celery_app=celery,
        )
        # _record_push touches the real PushRepository; bypass for unit test.
        facade._record_push = AsyncMock()  # type: ignore[method-assign]

        result = await facade.distribute(
            content_id="11111111-1111-1111-1111-111111111111",
            subscription_id="22222222-2222-2222-2222-222222222222",
        )

        assert result["sent"] == 1
        celery.send_task.assert_called_once()
        call = celery.send_task.call_args
        assert call.kwargs["kwargs"]["pipeline_name"] == "push-optimize"

    @pytest.mark.asyncio
    async def test_push_optimize_dedup_per_channel(self, monkeypatch: Any) -> None:
        """R-004: 多个匹配同 channel 的订阅只触发一次 push-optimize."""
        from intellisource.distributor.facade import DistributorFacade

        monkeypatch.setenv("IS_PUSH_OPTIMIZE_ENABLED", "1")

        content = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")
        # 3 subs same channel (wechat) + 2 subs another channel (wework)
        subs = [
            _make_sub(sid=f"{i:08d}-0000-0000-0000-000000000000", channel="wechat")
            for i in range(3)
        ] + [
            _make_sub(sid=f"{i:08d}-0000-0000-0000-000000000000", channel="wework")
            for i in range(3, 5)
        ]

        @asynccontextmanager
        async def session_factory() -> Any:
            session = MagicMock()
            session.get = AsyncMock(return_value=content)
            session.scalars = AsyncMock(return_value=MagicMock(all=lambda: subs))
            session.commit = AsyncMock()
            yield session

        matcher = MagicMock()
        matcher.match = MagicMock(return_value=subs)

        wechat_channel = MagicMock()
        wechat_channel.distribute = AsyncMock(return_value=None)
        wework_channel = MagicMock()
        wework_channel.distribute = AsyncMock(return_value=None)

        celery = MagicMock()
        facade = DistributorFacade(
            session_factory=session_factory,
            matcher=matcher,
            channels={"wechat": wechat_channel, "wework": wework_channel},
            celery_app=celery,
        )
        facade._record_push = AsyncMock()  # type: ignore[method-assign]

        await facade.distribute(
            content_id="11111111-1111-1111-1111-111111111111",
            subscription_id=None,
        )

        # 5 sends but only 2 push-optimize calls (one per unique channel)
        assert celery.send_task.call_count == 2, (
            f"Expected 2 dedup'd send_task calls, got {celery.send_task.call_count}"
        )
        channels_dispatched = {
            call.kwargs["kwargs"]["params"]["channel"]
            for call in celery.send_task.call_args_list
        }
        assert channels_dispatched == {"wechat", "wework"}


class TestWorkerCompositionWiresCeleryApp:
    """R-001: build_worker_composition 必须向 DistributorFacade 透传 celery_app."""

    def test_worker_composition_facade_has_celery_app(self, monkeypatch: Any) -> None:
        """build_worker_composition's DistributorFacade must hold celery_app."""
        from intellisource.scheduler.celery_app import (
            celery_app as module_celery_app,
        )

        bundle_holder: list[Any] = []

        original_build_deps = None

        def _capture_build_deps(*args: Any, **kwargs: Any) -> Any:
            assert original_build_deps is not None
            bundle = original_build_deps(*args, **kwargs)
            bundle_holder.append((bundle, kwargs.get("celery_app")))
            return bundle

        from intellisource import composition as comp_mod

        original_build_deps = comp_mod._build_deps_bundle
        monkeypatch.setattr(comp_mod, "_build_deps_bundle", _capture_build_deps)

        # Stub out network-dependent helpers so we exercise only the wiring path.
        monkeypatch.setattr(
            comp_mod, "build_distributor_facade", lambda *a, **k: MagicMock()
        )
        monkeypatch.setattr(
            comp_mod,
            "build_llm_gateway",
            lambda *a, **k: MagicMock(),
        )
        monkeypatch.setattr(
            comp_mod,
            "build_collector_registry",
            lambda: MagicMock(),
        )
        monkeypatch.setattr(
            comp_mod,
            "build_search_engine_factory",
            lambda: lambda *a, **k: MagicMock(),
        )
        monkeypatch.setattr(
            comp_mod, "_install_agent_runner", lambda *a, **k: MagicMock()
        )

        comp_mod.build_worker_composition(
            session_factory=MagicMock(), redis_client=MagicMock()
        )

        assert bundle_holder, (
            "_build_deps_bundle was not invoked from build_worker_composition"
        )
        _, celery_arg = bundle_holder[0]
        assert celery_arg is module_celery_app, (
            f"build_worker_composition must pass module celery_app to facade; "
            f"got {celery_arg!r}"
        )
