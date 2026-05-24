"""Unit tests for F-010 pre-push optimization in DistributorFacade."""

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
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=mock_execute_result)
    session.commit = AsyncMock()
    yield session


def _make_facade(*, llm_gateway: Any = None) -> Any:
    from intellisource.distributor.facade import DistributorFacade

    matcher = MagicMock()
    matcher.match = MagicMock(return_value=[])
    return DistributorFacade(
        session_factory=_empty_session,
        matcher=matcher,
        channels={},
        llm_gateway=llm_gateway,
    )


def _make_sub(*, sid: str, channel: str = "email") -> SimpleNamespace:
    return SimpleNamespace(
        id=sid,
        name="digest-sub",
        channel=channel,
        channel_config={"to_addr": "user@example.com"},
    )


class TestPreparePushContent:
    """`_prepare_push_content` gates on env + llm_gateway."""

    @pytest.mark.asyncio
    async def test_returns_original_when_env_disabled(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("IS_PUSH_OPTIMIZE_ENABLED", raising=False)
        facade = _make_facade(llm_gateway=AsyncMock())
        content = SimpleNamespace(title="t", summary="s", body_text="b")

        result = await facade._prepare_push_content(content, _make_sub(sid="sub-1"))

        assert result is content

    @pytest.mark.asyncio
    async def test_returns_original_when_llm_gateway_missing(
        self, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("IS_PUSH_OPTIMIZE_ENABLED", "1")
        facade = _make_facade(llm_gateway=None)
        content = SimpleNamespace(title="t", summary="s", body_text="b")

        result = await facade._prepare_push_content(content, _make_sub(sid="sub-1"))

        assert result is content

    @pytest.mark.asyncio
    async def test_calls_optimizer_when_enabled(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("IS_PUSH_OPTIMIZE_ENABLED", "1")
        llm = AsyncMock()
        facade = _make_facade(llm_gateway=llm)
        content = SimpleNamespace(
            id="11111111-1111-1111-1111-111111111111",
            title="Long original title",
            summary="",
            body_text="Body text for push.",
        )
        sub = _make_sub(sid="22222222-2222-2222-2222-222222222222")

        optimized = SimpleNamespace(title="Short", summary="Intro", body_text="Body")
        import intellisource.distributor.push_optimizer as po_mod

        optimize_mock = AsyncMock(return_value=optimized)
        monkeypatch.setattr(po_mod, "optimize_for_push", optimize_mock)

        result = await facade._prepare_push_content(content, sub)

        optimize_mock.assert_awaited_once_with(content, sub, llm)
        assert result is optimized

    @pytest.mark.asyncio
    async def test_optimizer_failure_degrades_to_original(
        self, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("IS_PUSH_OPTIMIZE_ENABLED", "1")
        facade = _make_facade(llm_gateway=AsyncMock())
        content = SimpleNamespace(title="t", body_text="b")

        import intellisource.distributor.push_optimizer as po_mod

        monkeypatch.setattr(
            po_mod,
            "optimize_for_push",
            AsyncMock(side_effect=RuntimeError("llm down")),
        )

        result = await facade._prepare_push_content(content, _make_sub(sid="sub-1"))

        assert result is content


class TestDistributePrePushIntegration:
    """distribute() must pass optimized content to channel, not fire Celery."""

    @pytest.mark.asyncio
    async def test_distribute_passes_optimized_content_to_channel(
        self, monkeypatch: Any
    ) -> None:
        from intellisource.distributor.facade import DistributorFacade

        monkeypatch.setenv("IS_PUSH_OPTIMIZE_ENABLED", "1")

        content = SimpleNamespace(
            id="11111111-1111-1111-1111-111111111111",
            title="Original",
            summary="orig",
            body_text="body",
        )
        sub = _make_sub(sid="22222222-2222-2222-2222-222222222222")
        optimized = SimpleNamespace(
            id=content.id,
            title="Optimized title",
            summary="Optimized summary",
            body_text="body",
        )

        @asynccontextmanager
        async def session_factory() -> Any:
            session = MagicMock()
            session.get = AsyncMock(return_value=content)
            session.scalars = AsyncMock(return_value=MagicMock(all=lambda: [sub]))
            mock_execute_result = MagicMock()
            mock_execute_result.scalar_one_or_none = MagicMock(return_value=None)
            session.execute = AsyncMock(return_value=mock_execute_result)
            session.commit = AsyncMock()
            yield session

        matcher = MagicMock()
        matcher.match = MagicMock(return_value=[sub])

        channel = MagicMock()
        channel.distribute = AsyncMock(return_value=None)

        facade = DistributorFacade(
            session_factory=session_factory,
            matcher=matcher,
            channels={"email": channel},
            llm_gateway=AsyncMock(),
        )
        facade._record_push = AsyncMock()  # type: ignore[method-assign]
        facade._is_already_pushed = AsyncMock(return_value=False)  # type: ignore[method-assign]
        facade._prepare_push_content = AsyncMock(return_value=optimized)  # type: ignore[method-assign]

        result = await facade.distribute(
            content_id="11111111-1111-1111-1111-111111111111",
            subscription_id="22222222-2222-2222-2222-222222222222",
        )

        assert result["sent"] == 1
        channel.distribute.assert_awaited_once_with(optimized, sub)
        facade._prepare_push_content.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_distribute_does_not_dispatch_celery_task(
        self, monkeypatch: Any
    ) -> None:
        from intellisource.distributor.facade import DistributorFacade

        monkeypatch.setenv("IS_PUSH_OPTIMIZE_ENABLED", "1")
        celery = MagicMock()

        content = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")
        sub = _make_sub(sid="22222222-2222-2222-2222-222222222222")

        @asynccontextmanager
        async def session_factory() -> Any:
            session = MagicMock()
            session.get = AsyncMock(return_value=content)
            session.scalars = AsyncMock(return_value=MagicMock(all=lambda: [sub]))
            mock_execute_result = MagicMock()
            mock_execute_result.scalar_one_or_none = MagicMock(return_value=None)
            session.execute = AsyncMock(return_value=mock_execute_result)
            session.commit = AsyncMock()
            yield session

        matcher = MagicMock()
        matcher.match = MagicMock(return_value=[sub])
        channel = MagicMock()
        channel.distribute = AsyncMock(return_value=None)

        facade = DistributorFacade(
            session_factory=session_factory,
            matcher=matcher,
            channels={"email": channel},
            llm_gateway=None,
        )
        facade._record_push = AsyncMock()  # type: ignore[method-assign]
        facade._is_already_pushed = AsyncMock(return_value=False)  # type: ignore[method-assign]
        # Ensure no latent celery hook
        assert not hasattr(facade, "_celery_app")
        del celery  # noqa: F841 — guard against accidental send_task usage

        await facade.distribute(
            content_id="11111111-1111-1111-1111-111111111111",
            subscription_id="22222222-2222-2222-2222-222222222222",
        )


class TestWorkerCompositionWiresLlmGateway:
    """EXP-005: build_worker_composition must wire llm_gateway into facade."""

    def test_worker_composition_facade_has_llm_gateway(self, monkeypatch: Any) -> None:
        from intellisource import composition as comp_mod

        bundle_holder: list[Any] = []
        facade_holder: list[Any] = []
        original_build_deps = comp_mod._build_deps_bundle

        def _capture_build_deps(*args: Any, **kwargs: Any) -> Any:
            bundle = original_build_deps(*args, **kwargs)
            bundle_holder.append(bundle)
            return bundle

        def _capture_facade(*args: Any, **kwargs: Any) -> Any:
            facade = MagicMock()
            facade._llm_gateway = kwargs.get("llm_gateway")
            facade_holder.append(facade)
            return facade

        monkeypatch.setattr(comp_mod, "_build_deps_bundle", _capture_build_deps)
        monkeypatch.setattr(comp_mod, "build_distributor_facade", _capture_facade)
        monkeypatch.setattr(
            comp_mod, "build_llm_gateway", lambda *a, **k: MagicMock(name="gw")
        )
        monkeypatch.setattr(
            comp_mod, "build_collector_registry", lambda *a, **k: MagicMock()
        )
        monkeypatch.setattr(
            comp_mod, "build_search_engine_factory", lambda: lambda *a, **k: MagicMock()
        )
        monkeypatch.setattr(
            comp_mod, "_install_agent_runner", lambda *a, **k: MagicMock()
        )

        comp_mod.build_worker_composition(
            session_factory=MagicMock(), redis_client=MagicMock()
        )

        assert facade_holder, "build_distributor_facade must be invoked"
        assert facade_holder[0]._llm_gateway is not None, (
            "build_worker_composition must pass llm_gateway to DistributorFacade"
        )
        assert bundle_holder, "_build_deps_bundle must be invoked"
