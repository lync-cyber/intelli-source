"""Tests for LLMGateway unified retry/CB/fallback governance.

Covers F-12, F-13, F-14:
- F-12: _unified_call_with_retry handles transient retries correctly
- F-12: _unified_call_with_retry circuit breaker blocks when OPEN
- F-13: chat() uses routing config when model=None
- F-13: chat() raises LLMError when routing config missing default_model
- F-14: stream_complete() first-chunk failure triggers circuit breaker record
- F-14: stream_complete() uses circuit breaker
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tenacity import wait_none

from intellisource.llm.circuit_breaker import CircuitOpenError
from intellisource.llm.gateway import LLMGateway

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_litellm_response(content: str = "hello") -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].message.tool_calls = None
    resp.choices[0].finish_reason = "stop"
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    resp.model = "gpt-4o-mini"
    return resp


def _make_gateway(**kwargs: object) -> LLMGateway:
    return LLMGateway(**kwargs)  # type: ignore[arg-type]


_SAMPLE_MESSAGES = [{"role": "user", "content": "hi"}]


# ===========================================================================
# F-12: _unified_call_with_retry — transient retries
# ===========================================================================


class TestUnifiedRetryTransient:
    """F-12: _unified_call_with_retry retries RECOVERABLE_TRANSIENT errors."""

    @pytest.mark.asyncio
    async def test_unified_retry_recoverable_transient_retries(self) -> None:
        """F-12: Transient error on first call is retried; second succeeds."""
        gw = _make_gateway(_retry_wait=wait_none())
        success_resp = _make_litellm_response("retried ok")
        call_count = 0

        class _FakeRateLimitError(Exception):
            pass

        _FakeRateLimitError.__name__ = "RateLimitError"

        async def _flaky() -> object:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _FakeRateLimitError("rate limited")
            return success_resp

        result = await gw._unified_call_with_retry(
            _flaky,
            model="gpt-4o-mini",
            call_type="complete",
            operation_id="test",
            enable_fallback=False,
            enable_circuit_breaker=False,
        )

        assert result is success_resp
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_unified_retry_unrecoverable_does_not_retry(self) -> None:
        """F-12: UNRECOVERABLE error is NOT retried."""
        gw = _make_gateway(_retry_wait=wait_none())
        call_count = 0

        class _FakeBadRequestError(Exception):
            pass

        _FakeBadRequestError.__name__ = "BadRequestError"

        async def _bad() -> object:
            nonlocal call_count
            call_count += 1
            raise _FakeBadRequestError("bad request")

        with pytest.raises(_FakeBadRequestError):
            await gw._unified_call_with_retry(
                _bad,
                model="gpt-4o-mini",
                call_type="complete",
                operation_id="test",
                enable_fallback=False,
                enable_circuit_breaker=False,
            )

        assert call_count == 1, "Unrecoverable error must not be retried"


# ===========================================================================
# F-12: _unified_call_with_retry — circuit breaker blocks when OPEN
# ===========================================================================


class TestUnifiedRetryCircuitBreaker:
    """F-12: _unified_call_with_retry respects circuit breaker state."""

    @pytest.mark.asyncio
    async def test_unified_circuit_breaker_blocks_when_open(self) -> None:
        """F-12: CircuitOpenError raised immediately when CB disallows the request."""
        mock_cb = AsyncMock()
        mock_cb.allow_request = AsyncMock(return_value=False)
        mock_cb.record_success = AsyncMock()
        mock_cb.record_failure = AsyncMock()

        gw = _make_gateway(circuit_breaker=mock_cb)
        call_invoked = False

        async def _call_fn() -> object:
            nonlocal call_invoked
            call_invoked = True
            return _make_litellm_response()

        with pytest.raises(CircuitOpenError):
            await gw._unified_call_with_retry(
                _call_fn,
                model="gpt-4o-mini",
                call_type="complete",
                operation_id="test",
                enable_circuit_breaker=True,
            )

        assert not call_invoked, "call_fn must not be invoked when CB is OPEN"

    @pytest.mark.asyncio
    async def test_unified_circuit_breaker_records_failure_on_error(self) -> None:
        """F-12: record_failure() called on exception."""
        mock_cb = AsyncMock()
        mock_cb.allow_request = AsyncMock(return_value=True)
        mock_cb.record_success = AsyncMock()
        mock_cb.record_failure = AsyncMock()

        gw = _make_gateway(_retry_wait=wait_none(), circuit_breaker=mock_cb)

        class _FakeBadRequestError(Exception):
            pass

        _FakeBadRequestError.__name__ = "BadRequestError"

        async def _bad() -> object:
            raise _FakeBadRequestError("bad")

        with pytest.raises(_FakeBadRequestError):
            await gw._unified_call_with_retry(
                _bad,
                model="gpt-4o-mini",
                call_type="complete",
                operation_id="test",
                enable_circuit_breaker=True,
            )

        mock_cb.record_failure.assert_awaited()

    @pytest.mark.asyncio
    async def test_unified_circuit_breaker_records_success_on_ok(self) -> None:
        """F-12: record_success() called after successful response."""
        mock_cb = AsyncMock()
        mock_cb.allow_request = AsyncMock(return_value=True)
        mock_cb.record_success = AsyncMock()
        mock_cb.record_failure = AsyncMock()

        gw = _make_gateway(circuit_breaker=mock_cb)
        resp = _make_litellm_response()

        async def _ok() -> object:
            return resp

        result = await gw._unified_call_with_retry(
            _ok,
            model="gpt-4o-mini",
            call_type="complete",
            operation_id="test",
            enable_circuit_breaker=True,
        )

        assert result is resp
        mock_cb.record_success.assert_awaited_once()


# ===========================================================================
# F-13: chat() routing config when model=None
# ===========================================================================


class TestChatRoutingConfig:
    """F-13: chat() resolves model from routing config, not hardcoded fallback."""

    @pytest.mark.asyncio
    async def test_chat_uses_routing_config_when_model_none(self) -> None:
        """F-13: chat() picks model from routing config 'chat' task_type."""
        resp = _make_litellm_response()

        # Patch _load_routing_config to return config with 'chat' model
        with patch("intellisource.llm.gateway._load_routing_config") as mock_cfg:
            mock_cfg.return_value = {
                "default_model": {"model": "default-model", "provider": "openai"},
                "models": {
                    "chat": {
                        "model": "claude-3-haiku-20240307",
                        "provider": "anthropic",
                    }
                },
                "profiles": {},
            }
            gw = _make_gateway()

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=resp)
            await gw.chat(messages=_SAMPLE_MESSAGES)

        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["model"] == "claude-3-haiku-20240307", (
            f"Expected model from routing config, got {call_kwargs['model']!r}"
        )

    @pytest.mark.asyncio
    async def test_chat_falls_back_to_default_model_when_chat_task_missing(
        self,
    ) -> None:
        """F-13: chat() uses default_model when 'chat' not in models."""
        resp = _make_litellm_response()

        with patch("intellisource.llm.gateway._load_routing_config") as mock_cfg:
            mock_cfg.return_value = {
                "default_model": {"model": "gpt-4o", "provider": "openai"},
                "models": {},
                "profiles": {},
            }
            gw = _make_gateway()

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=resp)
            await gw.chat(messages=_SAMPLE_MESSAGES)

        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_chat_raises_when_routing_missing(self) -> None:
        """F-13: chat() raises LLMError when default_model absent and no chat model."""
        from intellisource.core.errors import LLMError

        with patch("intellisource.llm.gateway._load_routing_config") as mock_cfg:
            mock_cfg.return_value = {
                "models": {},
                "profiles": {},
                # no 'default_model' key
            }
            gw = _make_gateway()

        with pytest.raises(LLMError):
            await gw.chat(messages=_SAMPLE_MESSAGES)

    @pytest.mark.asyncio
    async def test_chat_model_param_overrides_routing(self) -> None:
        """F-13: Explicit model= param takes priority over routing config."""
        resp = _make_litellm_response()

        with patch("intellisource.llm.gateway._load_routing_config") as mock_cfg:
            mock_cfg.return_value = {
                "default_model": {"model": "some-default", "provider": "openai"},
                "models": {"chat": {"model": "routing-model", "provider": "openai"}},
                "profiles": {},
            }
            gw = _make_gateway()

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=resp)
            await gw.chat(messages=_SAMPLE_MESSAGES, model="explicit-model")

        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["model"] == "explicit-model"


# ===========================================================================
# F-14: stream_complete() uses circuit breaker
# ===========================================================================


class _AsyncIter:
    def __init__(self, items: list) -> None:
        self._it = iter(items)

    def __aiter__(self) -> "_AsyncIter":
        return self

    async def __anext__(self) -> object:
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _chunk(text: str) -> MagicMock:
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].delta = MagicMock(content=text)
    m.usage = None
    m.model = "gpt-4o-mini"
    return m


class TestStreamCircuitBreaker:
    """F-14: stream_complete() first-chunk connection wrapped by unified CB/retry."""

    @pytest.mark.asyncio
    async def test_stream_circuit_breaker_blocks_when_open(self) -> None:
        """F-14: stream_complete raises CircuitOpenError when CB is OPEN."""
        mock_cb = AsyncMock()
        mock_cb.allow_request = AsyncMock(return_value=False)
        mock_cb.record_success = AsyncMock()
        mock_cb.record_failure = AsyncMock()

        gw = _make_gateway(circuit_breaker=mock_cb)

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock()
            with pytest.raises(CircuitOpenError):
                async for _ in gw.stream_complete(prompt="test", model="gpt-4o-mini"):
                    pass  # pragma: no cover

        mock_litellm.acompletion.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stream_circuit_breaker_records_failure_on_connection_error(
        self,
    ) -> None:
        """F-14: CB.record_failure() called when initial litellm.acompletion raises."""
        mock_cb = AsyncMock()
        mock_cb.allow_request = AsyncMock(return_value=True)
        mock_cb.record_success = AsyncMock()
        mock_cb.record_failure = AsyncMock()

        gw = _make_gateway(_retry_wait=wait_none(), circuit_breaker=mock_cb)

        class _FakeBadRequestError(Exception):
            pass

        _FakeBadRequestError.__name__ = "BadRequestError"

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=_FakeBadRequestError("fail")
            )
            with pytest.raises(_FakeBadRequestError):
                async for _ in gw.stream_complete(prompt="test", model="gpt-4o-mini"):
                    pass  # pragma: no cover

        mock_cb.record_failure.assert_awaited()

    @pytest.mark.asyncio
    async def test_stream_circuit_breaker_records_success_on_ok(self) -> None:
        """F-14: CB.record_success() called after successful first connection."""
        mock_cb = AsyncMock()
        mock_cb.allow_request = AsyncMock(return_value=True)
        mock_cb.record_success = AsyncMock()
        mock_cb.record_failure = AsyncMock()

        gw = _make_gateway(circuit_breaker=mock_cb)
        chunks = [_chunk("hello"), _chunk(" world")]

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=_AsyncIter(chunks))
            results = []
            async for item in gw.stream_complete(prompt="test", model="gpt-4o-mini"):
                results.append(item)

        mock_cb.record_success.assert_awaited_once()
        assert any(r.get("done") is False for r in results)
