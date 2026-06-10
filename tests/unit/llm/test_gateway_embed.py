"""T-EMB-1 AC-6 + B-045: LLMGateway.embed() updated for TEI/BGE-M3 contract.

Tests updated for the new embed() contract:
- 1024-dim vectors (BGE-M3 dimension, not 1536)
- embed() requires IS_EMBEDDING_API_BASE to be set before calling _aembedding
- empty-text and exception paths still return None (contract preserved)
- session_factory path still emits llm_call_log (contract preserved)
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
    resp.model = "openai/bge-m3"
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
            "model": "openai/bge-m3",
            "provider": "openai",
        },
    },
    "profiles": {},
}

# TEI base URL required for embed() to route to _aembedding (AC-1/AC-2 contract).
_TEI_API_BASE = "http://embedding/v1"
_TEI_API_KEY = "tei"


# ---------------------------------------------------------------------------
# AC-6: embed() happy path — 1024-dim vectors, requires api_base
# ---------------------------------------------------------------------------


class TestEmbedHappyPath:
    @pytest.mark.asyncio
    async def test_embed_returns_1024_dim_vector_from_aembedding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6: embed() returns a 1024-dim vector (BGE-M3 dimension, not 1536)."""
        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", _TEI_API_BASE)
        monkeypatch.setenv("IS_EMBEDDING_API_KEY", _TEI_API_KEY)
        get_settings.cache_clear()

        gw = _gateway_with_routing(_OPENAI_ROUTING)
        vec = [0.5] * 1024

        async def fake_aembedding(**_kwargs: Any) -> Any:
            return _make_embedding_response(vec)

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("hello world")
        assert isinstance(result, list)
        assert len(result) == 1024, (
            f"Expected 1024-dim vector (BGE-M3), got length {len(result)}"
        )
        assert result[0] == 0.5

        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_embed_returns_vector_from_dict_shaped_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6: litellm's dict-shaped data[0] ({"embedding": [...]}) also works.

        embed() accepts both the object shape (data[0].embedding) and the dict
        shape (data[0]["embedding"]); only the object path had coverage, so a
        regression in the dict branch would have gone unnoticed.
        """
        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", _TEI_API_BASE)
        monkeypatch.setenv("IS_EMBEDDING_API_KEY", _TEI_API_KEY)
        get_settings.cache_clear()

        gw = _gateway_with_routing(_OPENAI_ROUTING)
        vec = [0.25] * 1024

        async def fake_aembedding(**_kwargs: Any) -> Any:
            resp = MagicMock()
            resp.data = [{"embedding": vec}]
            resp.usage = MagicMock()
            resp.usage.prompt_tokens = 8
            resp.usage.total_tokens = 8
            resp.model = "openai/bge-m3"
            return resp

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("hello dict shape")
        assert isinstance(result, list)
        assert len(result) == 1024
        assert result[0] == 0.25

        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_embed_empty_text_returns_none_without_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6: empty text returns None; _aembedding not called (any api_base)."""
        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", _TEI_API_BASE)
        monkeypatch.setenv("IS_EMBEDDING_API_KEY", _TEI_API_KEY)
        get_settings.cache_clear()

        gw = _gateway_with_routing(_OPENAI_ROUTING)

        called = {"hit": False}

        async def fake_aembedding(**_kwargs: Any) -> Any:
            called["hit"] = True
            return _make_embedding_response([0.0] * 1024)

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("")
        assert result is None
        assert called["hit"] is False

        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# AC-6: Failure paths — must return None, never raise;
# api_base must be set to reach _aembedding
# ---------------------------------------------------------------------------


class TestEmbedSwallowsFailures:
    @pytest.mark.asyncio
    async def test_embed_returns_none_on_aembedding_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6: _aembedding exception → None (api_base must be set to reach call)."""
        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", _TEI_API_BASE)
        monkeypatch.setenv("IS_EMBEDDING_API_KEY", _TEI_API_KEY)
        get_settings.cache_clear()

        gw = _gateway_with_routing(_OPENAI_ROUTING)

        async def fake_aembedding(**_kwargs: Any) -> Any:
            raise RuntimeError("API key missing")

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("some content")
        assert result is None

        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_embed_retries_transient_error_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P4: a transient embed failure is retried (parity with chat/complete)."""
        from tenacity import wait_none

        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", _TEI_API_BASE)
        monkeypatch.setenv("IS_EMBEDDING_API_KEY", _TEI_API_KEY)
        get_settings.cache_clear()

        gw = _gateway_with_routing(_OPENAI_ROUTING, _retry_wait=wait_none())
        calls = {"n": 0}

        class APIConnectionError(Exception):
            pass

        async def flaky(**_kwargs: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise APIConnectionError("connection reset")
            return _make_embedding_response([0.5] * 1024)

        monkeypatch.setattr(gw, "_aembedding", flaky, raising=False)

        result = await gw.embed("hello")
        assert result is not None
        assert len(result) == 1024
        assert calls["n"] == 2

        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_embed_returns_none_on_malformed_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6: malformed response → None (api_base must be set to reach call)."""
        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", _TEI_API_BASE)
        monkeypatch.setenv("IS_EMBEDDING_API_KEY", _TEI_API_KEY)
        get_settings.cache_clear()

        gw = _gateway_with_routing(_OPENAI_ROUTING)

        async def fake_aembedding(**_kwargs: Any) -> Any:
            bad = MagicMock()
            bad.data = []  # no entries
            return bad

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("text")
        assert result is None

        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# AC-6: embed() emits llm_call_log via session_factory (contract preserved with
# api_base set)
# ---------------------------------------------------------------------------


class TestEmbedEmitsCallLog:
    @pytest.mark.asyncio
    async def test_embed_writes_call_log_via_session_factory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6: session_factory receives a call_log record with call_type='embed'."""
        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", _TEI_API_BASE)
        monkeypatch.setenv("IS_EMBEDDING_API_KEY", _TEI_API_KEY)
        get_settings.cache_clear()

        factory = _StubSessionFactory()
        gw = _gateway_with_routing(_OPENAI_ROUTING, session_factory=factory)
        vec = [0.1] * 1024

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

        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_embed_failure_does_not_break_call_log_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6: _aembedding exception still returns None cleanly (api_base set)."""
        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", _TEI_API_BASE)
        monkeypatch.setenv("IS_EMBEDDING_API_KEY", _TEI_API_KEY)
        get_settings.cache_clear()

        factory = _StubSessionFactory()
        gw = _gateway_with_routing(_OPENAI_ROUTING, session_factory=factory)

        async def fake_aembedding(**_kwargs: Any) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("text")
        assert result is None

        get_settings.cache_clear()
