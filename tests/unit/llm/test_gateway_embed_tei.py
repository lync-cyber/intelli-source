"""T-EMB-1: LLMGateway.embed() routes api_base/api_key to litellm for TEI.

AC-1: embed() passes api_base and api_key to _aembedding when configured.
AC-2: embed() returns None and never calls _aembedding when embedding_api_base is empty.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.llm.gateway import LLMGateway
from intellisource.llm.model_config import ModelRoutingConfig

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TEI_ROUTING = {
    "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
    "models": {
        "embed": {
            "model": "openai/bge-m3",
            "provider": "openai",
        },
    },
    "profiles": {},
}

_EMBED_VEC_1024 = [float(i) / 1024 for i in range(1024)]


def _make_embedding_response(vec: list[float]) -> MagicMock:
    resp = MagicMock()
    # litellm's EmbeddingResponse.data items are dicts, not attribute objects.
    resp.data = [{"embedding": vec, "index": 0, "object": "embedding"}]
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 4
    resp.usage.total_tokens = 4
    resp.model = "openai/bge-m3"
    return resp


def _gateway_with_routing(routing: dict[str, Any], **kwargs: Any) -> LLMGateway:
    gw = LLMGateway(**kwargs)
    gw._routing_config = routing
    gw._model_routing = ModelRoutingConfig(routing)
    return gw


# ---------------------------------------------------------------------------
# AC-1: embed forwards api_base and api_key to _aembedding
# ---------------------------------------------------------------------------


class TestEmbedForwardsApiBase:
    @pytest.mark.asyncio
    async def test_embed_passes_api_base_and_api_key_to_aembedding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-1: _aembedding called with api_base, api_key, model, input."""
        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", "http://embedding/v1")
        monkeypatch.setenv("IS_EMBEDDING_API_KEY", "tei")
        get_settings.cache_clear()

        gw = _gateway_with_routing(_TEI_ROUTING)

        captured: dict[str, Any] = {}

        async def fake_aembedding(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return _make_embedding_response(_EMBED_VEC_1024)

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("中文文本")

        # Verify _aembedding was called with the correct kwargs
        assert captured.get("model") == "openai/bge-m3", (
            f"Expected model='openai/bge-m3', got {captured.get('model')!r}"
        )
        assert captured.get("input") == "中文文本", (
            f"Expected input='中文文本', got {captured.get('input')!r}"
        )
        assert captured.get("api_base") == "http://embedding/v1", (
            f"Expected api_base='http://embedding/v1', got {captured.get('api_base')!r}"
        )
        assert captured.get("api_key") == "tei", (
            f"Expected api_key='tei', got {captured.get('api_key')!r}"
        )
        # Return value must equal the mock response's embedding data
        assert result == _EMBED_VEC_1024, (
            "Expected result to equal the 1024-dim mock embedding vector"
        )
        assert len(result) == 1024, (  # type: ignore[arg-type]
            f"Expected 1024-dim vector, got length {len(result)}"  # type: ignore[arg-type]
        )

        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_embed_returns_full_1024_vector_from_mock_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-1: embed() returns exactly data[0].embedding (1024 floats)."""
        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", "http://tei-host/v1")
        monkeypatch.setenv("IS_EMBEDDING_API_KEY", "secret")
        get_settings.cache_clear()

        gw = _gateway_with_routing(_TEI_ROUTING)

        expected_vec = [0.001 * i for i in range(1024)]

        async def fake_aembedding(**_kwargs: Any) -> Any:
            return _make_embedding_response(expected_vec)

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("test text")

        assert result == expected_vec, (
            "embed() must return exactly the embedding list from the mock response"
        )
        assert len(result) == 1024  # type: ignore[arg-type]

        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_embed_passes_encoding_format_float_to_aembedding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """embed() must pin encoding_format='float' for TEI /v1/embeddings.

        litellm's default embeddings request serialises encoding_format into a
        body token that TEI's serde rejects (`Failed to parse the request body
        as JSON: encoding_format: expected value`), so every embed() degrades to
        None at runtime. Pinning 'float' keeps the vector write path live.
        """
        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", "http://embedding/v1")
        monkeypatch.setenv("IS_EMBEDDING_API_KEY", "tei")
        get_settings.cache_clear()

        gw = _gateway_with_routing(_TEI_ROUTING)

        captured: dict[str, Any] = {}

        async def fake_aembedding(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return _make_embedding_response(_EMBED_VEC_1024)

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        await gw.embed("encoding format probe")

        assert captured.get("encoding_format") == "float", (
            "embed() must pass encoding_format='float' so TEI can parse the "
            f"request body; got {captured.get('encoding_format')!r}"
        )

        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# AC-2: empty embedding_api_base → None, _aembedding never called
# ---------------------------------------------------------------------------


class TestEmbedGracefulDegradationNoApiBase:
    @pytest.mark.asyncio
    async def test_embed_returns_none_when_api_base_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-2: embed() returns None; _aembedding NOT called when api_base is empty."""
        from intellisource.core.settings import get_settings

        # Ensure IS_EMBEDDING_API_BASE is absent/empty
        monkeypatch.delenv("IS_EMBEDDING_API_BASE", raising=False)
        get_settings.cache_clear()

        gw = _gateway_with_routing(_TEI_ROUTING)

        mock_aembedding = AsyncMock()

        monkeypatch.setattr(gw, "_aembedding", mock_aembedding, raising=False)

        result = await gw.embed("text")

        assert result is None, (
            f"embed() must return None when embedding_api_base is empty, got {result!r}"
        )
        mock_aembedding.assert_not_awaited()

        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_embed_keyless_tei_uses_placeholder_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R-001: IS_EMBEDDING_API_KEY unset → api_key fallback 'tei', result non-None.

        TEI keyless deployments omit IS_EMBEDDING_API_KEY.  embed() must reach
        _aembedding with a non-empty api_key and return a real vector, not None.
        """
        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", "http://embedding/v1")
        monkeypatch.delenv("IS_EMBEDDING_API_KEY", raising=False)
        get_settings.cache_clear()

        gw = _gateway_with_routing(_TEI_ROUTING)

        captured: dict[str, Any] = {}

        async def fake_aembedding(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return _make_embedding_response(_EMBED_VEC_1024)

        monkeypatch.setattr(gw, "_aembedding", fake_aembedding, raising=False)

        result = await gw.embed("keyless text")

        assert result is not None, (
            "embed() must return a vector (not None) when IS_EMBEDDING_API_KEY is unset"
        )
        assert result == _EMBED_VEC_1024, (
            "embed() must return the mock embedding vector for keyless TEI"
        )
        assert len(result) == 1024
        received_key = captured.get("api_key")
        assert received_key, (
            f"_aembedding must receive a non-empty api_key, got {received_key!r}"
        )
        assert received_key == "tei", (
            f"Expected api_key='tei' (keyless placeholder), got {received_key!r}"
        )

        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_embed_returns_none_and_no_call_when_api_base_explicitly_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-2: embed() returns None without calling litellm when api_base is ''."""
        from intellisource.core.settings import get_settings

        monkeypatch.setenv("IS_EMBEDDING_API_BASE", "")
        get_settings.cache_clear()

        gw = _gateway_with_routing(_TEI_ROUTING)

        call_count = {"n": 0}

        async def spy_aembedding(**_kwargs: Any) -> Any:
            call_count["n"] += 1
            return _make_embedding_response([0.0] * 1024)

        monkeypatch.setattr(gw, "_aembedding", spy_aembedding, raising=False)

        result = await gw.embed("some input")

        assert result is None, (
            f"embed() must return None when embedding_api_base='', got {result!r}"
        )
        assert call_count["n"] == 0, (
            f"_aembedding must not be called when api_base is empty, "
            f"but was called {call_count['n']} time(s)"
        )

        get_settings.cache_clear()
