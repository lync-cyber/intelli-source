"""B-045: LLMGateway.embed() method backs EmbeddingProcessor.

Backlog: docs/BACKLOG-intellisource-v1.md §B-045.

EmbeddingProcessor calls ``llm_gateway.embed(text)`` to get a 1536-dim
vector for ProcessedContent.embedding. This module tests that the gateway:
- exposes async ``embed(text: str) -> list[float] | None``;
- delegates to ``litellm.aembedding`` (patched via ``_aembedding`` hook);
- returns None on any failure (network down, missing model, empty input);
- emits llm_call_logs via session_factory when configured (mirroring chat /
  complete / stream behavior from B-042).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from intellisource.llm.gateway import LLMGateway

# ---------------------------------------------------------------------------
# Stub session factory (mirror test_gateway_session_factory.py)
# ---------------------------------------------------------------------------


class _StubSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits: int = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


class _StubSessionContext:
    def __init__(self, session: _StubSession) -> None:
        self._session = session

    async def __aenter__(self) -> _StubSession:
        return self._session

    async def __aexit__(self, *_exc_info: Any) -> None:
        return None


class _StubSessionFactory:
    def __init__(self) -> None:
        self.session = _StubSession()
        self.contexts: list[_StubSessionContext] = []

    def __call__(self) -> _StubSessionContext:
        ctx = _StubSessionContext(self.session)
        self.contexts.append(ctx)
        return ctx


def _make_embedding_response(vec: list[float]) -> MagicMock:
    resp = MagicMock()
    resp.data = [MagicMock(embedding=vec)]
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 8
    resp.usage.total_tokens = 8
    resp.model = "text-embedding-3-small"
    return resp


def _gateway_with_routing(routing: dict[str, Any], **kwargs: Any) -> LLMGateway:
    gw = LLMGateway(**kwargs)
    gw._routing_config = routing
    from intellisource.llm.model_config import ModelRoutingConfig

    gw._model_routing = ModelRoutingConfig(routing)
    return gw


_OPENAI_ROUTING = {
    "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
    "models": {
        "embed": {
            "model": "text-embedding-3-small",
            "provider": "openai",
        },
    },
    "profiles": {},
}


# ---------------------------------------------------------------------------
# Method existence
# ---------------------------------------------------------------------------


class TestEmbedMethodExists:
    def test_gateway_has_embed_method(self) -> None:
        assert hasattr(LLMGateway, "embed")
        assert callable(getattr(LLMGateway, "embed", None))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestEmbedHappyPath:
    @pytest.mark.asyncio
    async def test_embed_returns_vector_from_aembedding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _gateway_with_routing(_OPENAI_ROUTING)
        vec = [0.5] * 1536

        async def fake_aembedding(**_kwargs: Any) -> Any:
            return _make_embedding_response(vec)

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("hello world")
        assert isinstance(result, list)
        assert len(result) == 1536
        assert result[0] == 0.5

    @pytest.mark.asyncio
    async def test_embed_empty_text_returns_none_without_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _gateway_with_routing(_OPENAI_ROUTING)

        called = {"hit": False}

        async def fake_aembedding(**_kwargs: Any) -> Any:
            called["hit"] = True
            return _make_embedding_response([0.0] * 1536)

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("")
        assert result is None
        assert called["hit"] is False


# ---------------------------------------------------------------------------
# Failure path — must return None, never raise
# ---------------------------------------------------------------------------


class TestEmbedSwallowsFailures:
    @pytest.mark.asyncio
    async def test_embed_returns_none_on_aembedding_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _gateway_with_routing(_OPENAI_ROUTING)

        async def fake_aembedding(**_kwargs: Any) -> Any:
            raise RuntimeError("API key missing")

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("some content")
        assert result is None

    @pytest.mark.asyncio
    async def test_embed_returns_none_on_malformed_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _gateway_with_routing(_OPENAI_ROUTING)

        async def fake_aembedding(**_kwargs: Any) -> Any:
            bad = MagicMock()
            bad.data = []  # no entries
            return bad

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("text")
        assert result is None


# ---------------------------------------------------------------------------
# embed() emits llm_call_log via session_factory (B-042 contract)
# ---------------------------------------------------------------------------


class TestEmbedEmitsCallLog:
    @pytest.mark.asyncio
    async def test_embed_writes_call_log_via_session_factory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        factory = _StubSessionFactory()
        gw = _gateway_with_routing(_OPENAI_ROUTING, session_factory=factory)
        vec = [0.1] * 1536

        async def fake_aembedding(**_kwargs: Any) -> Any:
            return _make_embedding_response(vec)

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        await gw.embed("hello world")

        assert len(factory.contexts) == 1
        assert factory.session.commits == 1
        assert len(factory.session.added) == 1
        record = factory.session.added[0]
        assert getattr(record, "call_type", None) == "embed"
        assert getattr(record, "status", None) == "success"

    @pytest.mark.asyncio
    async def test_embed_failure_does_not_break_call_log_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        factory = _StubSessionFactory()
        gw = _gateway_with_routing(_OPENAI_ROUTING, session_factory=factory)

        async def fake_aembedding(**_kwargs: Any) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("text")
        assert result is None
