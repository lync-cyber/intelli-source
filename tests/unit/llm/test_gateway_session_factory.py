"""B-042: LLMGateway accepts session_factory and emits llm_call_logs.

Backlog: docs/BACKLOG-intellisource-v1.md §B-042.

CostTracker(session) binds to one session at construction, so the existing
singleton LLMGateway cannot reuse it across requests. B-042 wires a
session_factory through the gateway: each log_call opens its own session via
``async with session_factory() as s: await CostTracker(s).log_call(record)``.

Tests verify:
- LLMGateway.__init__ accepts session_factory kwarg.
- chat() / complete() / stream_complete() each emit a log row through that
  factory after a successful call.
- The legacy ``cost_tracker=`` constructor still wins when both are present
  (backward compat for the existing per-test fixtures).
- composition.build_llm_gateway forwards the factory into the gateway.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.llm.gateway import LLMGateway

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubSession:
    """Async-context-manager-compatible stub returned by session_factory()."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits: int = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


class _StubSessionContext:
    """`async with session_factory() as s` yields the stub session."""

    def __init__(self, session: _StubSession) -> None:
        self._session = session
        self.entered: int = 0
        self.exited: int = 0

    async def __aenter__(self) -> _StubSession:
        self.entered += 1
        return self._session

    async def __aexit__(self, *_exc_info: Any) -> None:
        self.exited += 1


class _StubSessionFactory:
    """Callable that emulates `async_sessionmaker[AsyncSession]` semantics."""

    def __init__(self) -> None:
        self.session = _StubSession()
        self.contexts: list[_StubSessionContext] = []

    def __call__(self) -> _StubSessionContext:
        ctx = _StubSessionContext(self.session)
        self.contexts.append(ctx)
        return ctx


def _make_chat_response(content: str = "ok") -> MagicMock:
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    del msg.reasoning_content
    resp.choices = [MagicMock(message=msg, finish_reason="stop")]
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    resp.usage.__iter__ = lambda self: iter([])
    resp.model = "gpt-4o-mini"
    return resp


def _make_complete_response(content: str = "summary text") -> MagicMock:
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    del msg.reasoning_content
    resp.choices = [MagicMock(message=msg, finish_reason="stop")]
    resp.usage.prompt_tokens = 12
    resp.usage.completion_tokens = 7
    resp.model = "gpt-4o-mini"
    return resp


def _gateway_with_routing(
    routing: dict[str, Any], **kwargs: Any
) -> LLMGateway:
    gw = LLMGateway(**kwargs)
    gw._routing_config = routing
    from intellisource.llm.model_config import ModelRoutingConfig

    gw._model_routing = ModelRoutingConfig(routing)
    return gw


_OPENAI_ROUTING = {
    "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
    "models": {
        "chat": {"model": "gpt-4o-mini", "provider": "openai"},
        "summarize": {"model": "gpt-4o-mini", "provider": "openai"},
    },
    "profiles": {},
}


# ---------------------------------------------------------------------------
# Constructor wiring
# ---------------------------------------------------------------------------


class TestSessionFactoryConstructor:
    def test_session_factory_kwarg_accepted(self) -> None:
        factory = _StubSessionFactory()
        gw = LLMGateway(session_factory=factory)
        assert gw._session_factory is factory

    def test_session_factory_defaults_to_none(self) -> None:
        gw = LLMGateway()
        assert gw._session_factory is None


# ---------------------------------------------------------------------------
# chat() emits via session_factory
# ---------------------------------------------------------------------------


class TestChatEmitsViaSessionFactory:
    @pytest.mark.asyncio
    async def test_chat_writes_llm_call_log_via_factory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        factory = _StubSessionFactory()
        gw = _gateway_with_routing(_OPENAI_ROUTING, session_factory=factory)

        async def fake_acompletion(**_kwargs: Any) -> Any:
            return _make_chat_response()

        monkeypatch.setattr(gw, "_acompletion", fake_acompletion)

        await gw.chat(messages=[{"role": "user", "content": "hi"}])

        assert len(factory.contexts) == 1
        assert factory.contexts[0].entered == 1
        assert factory.contexts[0].exited == 1
        assert factory.session.commits == 1
        assert len(factory.session.added) == 1
        record = factory.session.added[0]
        assert getattr(record, "call_type", None) == "chat"
        assert getattr(record, "status", None) == "success"
        assert getattr(record, "input_tokens", 0) == 10
        assert getattr(record, "output_tokens", 0) == 5


# ---------------------------------------------------------------------------
# complete() emits via session_factory (currently missing in production code)
# ---------------------------------------------------------------------------


class TestCompleteEmitsViaSessionFactory:
    @pytest.mark.asyncio
    async def test_complete_writes_llm_call_log_via_factory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        factory = _StubSessionFactory()
        gw = _gateway_with_routing(_OPENAI_ROUTING, session_factory=factory)

        async def fake_acompletion(**_kwargs: Any) -> Any:
            return _make_complete_response()

        monkeypatch.setattr(gw, "_acompletion", fake_acompletion)

        await gw.complete(prompt="summarize foo", task_type="summarize")

        assert len(factory.contexts) == 1, (
            "complete() must open exactly one session via session_factory"
        )
        assert factory.session.commits == 1
        assert len(factory.session.added) == 1
        record = factory.session.added[0]
        assert getattr(record, "call_type", None) == "complete"
        assert getattr(record, "status", None) == "success"
        assert getattr(record, "input_tokens", 0) == 12
        assert getattr(record, "output_tokens", 0) == 7


# ---------------------------------------------------------------------------
# stream_complete() emits via session_factory
# ---------------------------------------------------------------------------


class TestStreamCompleteEmitsViaSessionFactory:
    @pytest.mark.asyncio
    async def test_stream_writes_llm_call_log_via_factory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        factory = _StubSessionFactory()
        gw = _gateway_with_routing(_OPENAI_ROUTING, session_factory=factory)

        async def fake_stream() -> AsyncIterator[Any]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = "hello"
            chunk.usage = None
            chunk.model = "gpt-4o-mini"
            yield chunk
            done = MagicMock()
            done.choices = [MagicMock()]
            done.choices[0].delta.content = ""
            usage = MagicMock()
            usage.prompt_tokens = 4
            usage.completion_tokens = 3
            done.usage = usage
            done.model = "gpt-4o-mini"
            yield done

        async def fake_acompletion(**_kwargs: Any) -> Any:
            return fake_stream()

        monkeypatch.setattr(gw, "_acompletion", fake_acompletion)

        chunks: list[dict[str, Any]] = []
        async for chunk in gw.stream_complete(
            prompt="hi there", task_type="chat"
        ):
            chunks.append(chunk)

        assert chunks[-1]["done"] is True
        assert len(factory.contexts) == 1
        assert factory.session.commits == 1
        record = factory.session.added[0]
        assert getattr(record, "call_type", None) == "stream_complete"
        assert getattr(record, "status", None) == "success"


# ---------------------------------------------------------------------------
# Backward compat: explicit cost_tracker overrides session_factory
# ---------------------------------------------------------------------------


class TestExplicitCostTrackerWins:
    @pytest.mark.asyncio
    async def test_cost_tracker_takes_precedence_over_session_factory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        factory = _StubSessionFactory()
        explicit = MagicMock()
        explicit.log_call = AsyncMock()

        gw = _gateway_with_routing(
            _OPENAI_ROUTING,
            cost_tracker=explicit,
            session_factory=factory,
        )

        async def fake_acompletion(**_kwargs: Any) -> Any:
            return _make_chat_response()

        monkeypatch.setattr(gw, "_acompletion", fake_acompletion)

        await gw.chat(messages=[{"role": "user", "content": "hi"}])

        explicit.log_call.assert_awaited_once()
        assert len(factory.contexts) == 0, (
            "session_factory must NOT be invoked when cost_tracker is set"
        )


# ---------------------------------------------------------------------------
# Both unset → silent no-op
# ---------------------------------------------------------------------------


class TestNoTrackerNoFactory:
    @pytest.mark.asyncio
    async def test_chat_does_not_crash_when_both_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _gateway_with_routing(_OPENAI_ROUTING)

        async def fake_acompletion(**_kwargs: Any) -> Any:
            return _make_chat_response()

        monkeypatch.setattr(gw, "_acompletion", fake_acompletion)

        result = await gw.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "ok"


# ---------------------------------------------------------------------------
# session_factory failure must not break the LLM path
# ---------------------------------------------------------------------------


class TestSessionFactoryFailureIsSwallowed:
    @pytest.mark.asyncio
    async def test_chat_swallows_session_factory_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _BrokenFactory:
            def __call__(self) -> Any:
                raise RuntimeError("DB unavailable")

        gw = _gateway_with_routing(_OPENAI_ROUTING, session_factory=_BrokenFactory())

        async def fake_acompletion(**_kwargs: Any) -> Any:
            return _make_chat_response()

        monkeypatch.setattr(gw, "_acompletion", fake_acompletion)

        result = await gw.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "ok"


# ---------------------------------------------------------------------------
# composition.build_llm_gateway wires session_factory
# ---------------------------------------------------------------------------


class TestCompositionWiresSessionFactory:
    def test_build_llm_gateway_accepts_and_attaches_session_factory(self) -> None:
        from intellisource.composition import build_llm_gateway

        redis_client = MagicMock()
        factory = _StubSessionFactory()
        gw = build_llm_gateway(redis_client, session_factory=factory)

        assert gw._session_factory is factory

    def test_build_llm_gateway_works_without_session_factory(self) -> None:
        from intellisource.composition import build_llm_gateway

        redis_client = MagicMock()
        gw = build_llm_gateway(redis_client)
        assert gw._session_factory is None
