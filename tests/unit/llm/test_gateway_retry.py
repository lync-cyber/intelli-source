"""Tests for LLMGateway exponential backoff retry logic.

Covers:
- AC-T057-1: RECOVERABLE_TRANSIENT errors retried up to 3 times (4 total calls max)
- AC-T057-2: Exponential backoff with min=1s, max=30s
- AC-T057-3: UNRECOVERABLE/RECOVERABLE_DEGRADED errors not retried
- AC-T057-4: FallbackManager.execute_fallback() called after retries exhausted
- AC-T057-5: Each retry logged to LLMCallLog with status=retry, retry_attempt=N
- AC-T057-6: litellm.acompletion() receives profile timeout_seconds
- AC-T057-7: mypy --strict zero errors (enforced by CI)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import litellm.exceptions as le
import pytest
from tenacity import wait_fixed

from intellisource.core.errors import ErrorCategory
from intellisource.llm.gateway import LLMGateway, _classify_error

# ---------------------------------------------------------------------------
# Shared fixtures & helpers
# ---------------------------------------------------------------------------

_PROFILE_CONFIG_WITH_TIMEOUT = {
    "models": {},
    "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
    "profiles": {
        "gpt-4o-mini": {
            "temperature": 0.7,
            "max_tokens": 4096,
            "context_window": 128000,
            "prompt_style": "structured",
            "timeout_seconds": 45,
        },
    },
}


def _make_litellm_response(content: str = "ok") -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    resp.model = "gpt-4o-mini"
    return resp


def _make_transient_error() -> Exception:
    """Return a litellm Timeout-like exception."""
    import litellm.exceptions as le

    return le.Timeout(message="timeout", model="gpt-4o-mini", llm_provider="openai")


def _make_rate_limit_error() -> Exception:
    import litellm.exceptions as le

    return le.RateLimitError(
        message="rate limit", model="gpt-4o-mini", llm_provider="openai"
    )


def _make_bad_request_error() -> Exception:
    import litellm.exceptions as le

    return le.BadRequestError(
        message="bad request", model="gpt-4o-mini", llm_provider="openai"
    )


def _make_auth_error() -> Exception:
    import litellm.exceptions as le

    return le.AuthenticationError(
        message="auth fail", model="gpt-4o-mini", llm_provider="openai"
    )


def _make_fallback_manager(registered: bool = True) -> MagicMock:
    fm = MagicMock()
    fm.execute_fallback = AsyncMock(return_value="fallback_result")
    if not registered:
        fm.execute_fallback.side_effect = KeyError("no fallback for task_type")
    return fm


def _make_cost_tracker() -> MagicMock:
    ct = MagicMock()
    ct.log_call = AsyncMock()
    return ct


def _make_gateway(
    fallback_manager: Any = None,
    cost_tracker: Any = None,
    config: dict[str, Any] | None = None,
    retry_wait: Any = None,
) -> LLMGateway:
    with patch(
        "intellisource.llm.gateway._load_routing_config",
        return_value=config or _PROFILE_CONFIG_WITH_TIMEOUT,
    ):
        gw = LLMGateway(
            fallback_manager=fallback_manager,
            cost_tracker=cost_tracker,
        )
    if retry_wait is not None:
        gw._retry_wait = retry_wait
    return gw


# ---------------------------------------------------------------------------
# AC-T057-1: RECOVERABLE_TRANSIENT retried at most 3 times (4 total calls)
# ---------------------------------------------------------------------------


class TestRetryOnTransient:
    async def test_retries_on_transient_then_succeeds(self) -> None:
        """Transient errors are retried; success on 2nd attempt returns result."""
        transient = _make_transient_error()
        success_resp = _make_litellm_response("hello")
        gw = _make_gateway(retry_wait=wait_fixed(0))

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=[transient, success_resp])
            mock_litellm.token_counter = MagicMock(return_value=10)
            result = await gw.complete(prompt="test", model="gpt-4o-mini")

        assert result.content == "hello"
        assert mock_litellm.acompletion.call_count == 2

    async def test_retry_count_capped_at_3(self) -> None:
        """After 3 retries (4 total calls), retries exhaust and exception raises."""
        transient = _make_transient_error()
        gw = _make_gateway(retry_wait=wait_fixed(0))

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[transient, transient, transient, transient]
            )
            mock_litellm.token_counter = MagicMock(return_value=10)
            with pytest.raises(le.Timeout):
                await gw.complete(prompt="test", model="gpt-4o-mini")

        # 1 initial + 3 retries = 4 total
        assert mock_litellm.acompletion.call_count == 4


# ---------------------------------------------------------------------------
# AC-T057-2: Exponential backoff bounded by min=1s, max=30s
# ---------------------------------------------------------------------------


class TestExponentialBackoff:
    def test_exponential_backoff_bounded_by_min_max(self) -> None:
        """Gateway uses wait_exponential strategy with min=1, max=30."""
        from tenacity import wait_exponential

        gw = _make_gateway()
        wait = gw._retry_wait
        assert isinstance(wait, wait_exponential), (
            f"Expected wait_exponential, got {type(wait)}"
        )
        assert wait.min == 1, f"Expected min=1, got {wait.min}"
        assert wait.max == 30, f"Expected max=30, got {wait.max}"


# ---------------------------------------------------------------------------
# AC-T057-3: UNRECOVERABLE/RECOVERABLE_DEGRADED not retried
# ---------------------------------------------------------------------------


class TestNoRetryOnNonTransient:
    async def test_unrecoverable_error_does_not_retry(self) -> None:
        """BadRequestError (UNRECOVERABLE) does not trigger retries."""
        bad_req = _make_bad_request_error()
        gw = _make_gateway(retry_wait=wait_fixed(0))

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=bad_req)
            mock_litellm.token_counter = MagicMock(return_value=10)
            with pytest.raises(le.BadRequestError):
                await gw.complete(prompt="test", model="gpt-4o-mini")

        assert mock_litellm.acompletion.call_count == 1

    async def test_degraded_error_does_not_retry(self) -> None:
        """AuthenticationError (RECOVERABLE_DEGRADED) does not trigger retries."""
        auth_err = _make_auth_error()
        gw = _make_gateway(retry_wait=wait_fixed(0))

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=auth_err)
            mock_litellm.token_counter = MagicMock(return_value=10)
            with pytest.raises(le.AuthenticationError):
                await gw.complete(prompt="test", model="gpt-4o-mini")

        assert mock_litellm.acompletion.call_count == 1


# ---------------------------------------------------------------------------
# T4-1c: complete() model failover (parity with chat())
# ---------------------------------------------------------------------------

_FAILOVER_CONFIG: dict[str, Any] = {
    "default_model": {"model": "primary/m", "provider": "p"},
    "models": {
        "summarize": {
            "model": "primary/m",
            "provider": "p",
            "fallback_models": ["fallback/m"],
        },
    },
    "profiles": {},
}


class TestCompleteModelFailover:
    async def test_complete_fails_over_to_configured_fallback_model(self) -> None:
        """A primary-model failure falls over to the task's configured fallback."""
        gw = _make_gateway(config=_FAILOVER_CONFIG, retry_wait=wait_fixed(0))
        success_resp = _make_litellm_response("from fallback")
        seen: list[str] = []

        async def fake_acompletion(**kwargs: Any) -> Any:
            seen.append(str(kwargs["model"]))
            if kwargs["model"] == "primary/m":
                raise RuntimeError("primary down")  # DEGRADED → fail over, no retry
            return success_resp

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=fake_acompletion)
            mock_litellm.token_counter = MagicMock(return_value=10)
            result = await gw.complete(prompt="test", task_type="summarize")

        assert result.content == "from fallback"
        assert seen == ["primary/m", "fallback/m"]


class TestStreamModelFailover:
    async def test_stream_fails_over_to_fallback_model(self) -> None:
        """A stream-establishment failure falls over to the configured fallback."""
        gw = _make_gateway(config=_FAILOVER_CONFIG, retry_wait=wait_fixed(0))
        seen: list[str] = []

        class _AsyncIter:
            def __init__(self, items: list[Any]) -> None:
                self._it = iter(items)

            def __aiter__(self) -> "_AsyncIter":
                return self

            async def __anext__(self) -> Any:
                try:
                    return next(self._it)
                except StopIteration:
                    raise StopAsyncIteration from None

        def _chunk(text: str) -> MagicMock:
            m = MagicMock()
            m.choices = [MagicMock()]
            m.choices[0].delta = MagicMock(content=text)
            m.usage = None
            m.model = "fallback/m"
            return m

        async def fake_acompletion(**kwargs: Any) -> Any:
            seen.append(str(kwargs["model"]))
            if kwargs["model"] == "primary/m":
                raise RuntimeError("primary stream down")  # DEGRADED → fail over
            return _AsyncIter([_chunk("hi")])

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=fake_acompletion)
            mock_litellm.token_counter = MagicMock(return_value=10)
            events = [
                e async for e in gw.stream_complete(prompt="x", task_type="summarize")
            ]

        contents = "".join(str(e.get("content", "")) for e in events)
        assert "hi" in contents
        assert seen == ["primary/m", "fallback/m"]


# ---------------------------------------------------------------------------
# AC-T057-4: FallbackManager.execute_fallback() after retries exhausted
# ---------------------------------------------------------------------------


class TestFallbackAfterExhaustion:
    async def test_falls_back_after_retries_exhausted(self) -> None:
        """After 4 transient failures, execute_fallback() is called."""
        transient = _make_transient_error()
        fm = _make_fallback_manager()
        gw = _make_gateway(fallback_manager=fm, retry_wait=wait_fixed(0))

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[transient, transient, transient, transient]
            )
            mock_litellm.token_counter = MagicMock(return_value=10)
            result = await gw.complete(
                prompt="test prompt", model="gpt-4o-mini", task_type="extract"
            )

        fm.execute_fallback.assert_awaited_once_with(
            task_type="extract", input_data="test prompt"
        )
        assert result == "fallback_result"

    async def test_no_fallback_manager_raises_after_exhaustion(self) -> None:
        """Without fallback_manager, original exception propagates on exhaustion."""
        transient = _make_transient_error()
        gw = _make_gateway(fallback_manager=None, retry_wait=wait_fixed(0))

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[transient, transient, transient, transient]
            )
            mock_litellm.token_counter = MagicMock(return_value=10)
            with pytest.raises(le.Timeout):
                await gw.complete(prompt="test", model="gpt-4o-mini")

        assert mock_litellm.acompletion.call_count == 4

    async def test_fallback_function_raises_propagates_fallback_error(self) -> None:
        """When fallback fn raises, fallback error supersedes original transient."""
        transient = _make_transient_error()
        fm = MagicMock()
        fm.execute_fallback = AsyncMock(side_effect=ValueError("fallback boom"))
        gw = _make_gateway(fallback_manager=fm, retry_wait=wait_fixed(0))

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[transient, transient, transient, transient]
            )
            mock_litellm.token_counter = MagicMock(return_value=10)
            with pytest.raises(ValueError, match="fallback boom"):
                await gw.complete(
                    prompt="test", model="gpt-4o-mini", task_type="extract"
                )


# ---------------------------------------------------------------------------
# AC-T057-5: Retry attempts logged to LLMCallLog with status=retry, retry_attempt=N
# ---------------------------------------------------------------------------


class TestRetryLogging:
    async def test_logs_retry_attempt_to_llm_call_log(self) -> None:
        """Each retry logs a record with status='retry' and correct retry_attempt."""
        transient = _make_transient_error()
        success_resp = _make_litellm_response("done")
        ct = _make_cost_tracker()
        gw = _make_gateway(cost_tracker=ct, retry_wait=wait_fixed(0))

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[transient, transient, success_resp]
            )
            mock_litellm.token_counter = MagicMock(return_value=10)
            await gw.complete(prompt="test", model="gpt-4o-mini")

        retry_calls = [
            call
            for call in ct.log_call.call_args_list
            if call.args[0].status == "retry"
        ]
        assert len(retry_calls) == 2
        assert retry_calls[0].args[0].retry_attempt == 1
        assert retry_calls[1].args[0].retry_attempt == 2


# ---------------------------------------------------------------------------
# AC-T057-6: litellm.acompletion() receives profile timeout_seconds
# ---------------------------------------------------------------------------


class TestProfileTimeout:
    async def test_acompletion_uses_profile_timeout(self) -> None:
        """Profile timeout_seconds is passed to litellm.acompletion() as timeout."""
        success_resp = _make_litellm_response("ok")
        gw = _make_gateway(retry_wait=wait_fixed(0))

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=success_resp)
            mock_litellm.token_counter = MagicMock(return_value=10)
            await gw.complete(prompt="test", model="gpt-4o-mini")
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            assert call_kwargs.get("timeout") == 45

    async def test_acompletion_timeout_preserved_across_retries(self) -> None:
        """Profile timeout_seconds remains in call_kwargs across retry attempts."""
        transient = _make_transient_error()
        success_resp = _make_litellm_response("ok")
        gw = _make_gateway(retry_wait=wait_fixed(0))

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=[transient, success_resp])
            mock_litellm.token_counter = MagicMock(return_value=10)
            await gw.complete(prompt="test", model="gpt-4o-mini")

        # Both calls should carry timeout=45 (profile timeout_seconds)
        assert mock_litellm.acompletion.call_count == 2
        for call in mock_litellm.acompletion.call_args_list:
            assert call.kwargs.get("timeout") == 45


# ---------------------------------------------------------------------------
# _classify_error unit tests
# ---------------------------------------------------------------------------


class TestClassifyError:
    def test_classify_timeout_as_transient(self) -> None:
        import litellm.exceptions as le

        exc = le.Timeout(message="t/o", model="m", llm_provider="p")
        assert _classify_error(exc) is ErrorCategory.RECOVERABLE_TRANSIENT

    def test_classify_rate_limit_as_transient(self) -> None:
        import litellm.exceptions as le

        exc = le.RateLimitError(message="rl", model="m", llm_provider="p")
        assert _classify_error(exc) is ErrorCategory.RECOVERABLE_TRANSIENT

    def test_classify_bad_request_as_unrecoverable(self) -> None:
        import litellm.exceptions as le

        exc = le.BadRequestError(message="br", model="m", llm_provider="p")
        assert _classify_error(exc) is ErrorCategory.UNRECOVERABLE

    def test_classify_llm_error_uses_category_attr(self) -> None:
        from intellisource.core.errors import LLMError

        err = LLMError("msg", category=ErrorCategory.RECOVERABLE_TRANSIENT)
        assert _classify_error(err) is ErrorCategory.RECOVERABLE_TRANSIENT

    def test_classify_unknown_exception_as_degraded(self) -> None:
        assert (
            _classify_error(RuntimeError("oops")) is ErrorCategory.RECOVERABLE_DEGRADED
        )
