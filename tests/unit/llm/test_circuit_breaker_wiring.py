"""Tests for T-088: CircuitBreaker + PriorityQueue wiring into LLMGateway.

Covers:
  AC-1: LLMGateway.__init__ accepts circuit_breaker kwarg (backward-compatible)
  AC-2: _call_with_retry checks allow_request(); circuit OPEN → CircuitOpenError,
        litellm NOT called
  AC-3: LLM success → record_success() called; LLM failure → record_failure() called
  AC-4: LLMGateway enqueues via PriorityQueue; interactive → HIGH priority,
        background → lower priority; worker coroutine consumes queue
  AC-5: GET /api/v1/llm/status returns circuit_state + queue_lengths structure;
        endpoint requires X-API-Key auth (R-001); reads real gateway state (R-002)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tenacity import wait_fixed

from intellisource.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from intellisource.llm.gateway import LLMGateway
from intellisource.llm.priority_queue import PriorityLevel, PriorityQueue, QueuedRequest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_circuit_breaker(*, allow: bool = True) -> AsyncMock:
    """Return an AsyncMock standing in for CircuitBreaker."""
    cb = AsyncMock(spec=CircuitBreaker)
    cb.allow_request.return_value = allow
    cb.record_success.return_value = None
    cb.record_failure.return_value = None
    cb.get_state.return_value = CircuitState.CLOSED
    return cb


def _make_litellm_response(content: str = "hello") -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    resp.model = "gpt-4o-mini"
    return resp


def _make_gateway(
    *,
    circuit_breaker: Any = None,
    priority_queue: Any = None,
) -> LLMGateway:
    """Construct LLMGateway with injected circuit_breaker/priority_queue."""
    return LLMGateway(
        circuit_breaker=circuit_breaker,
        priority_queue=priority_queue,
        _retry_wait=wait_fixed(0),
    )


# ---------------------------------------------------------------------------
# AC-1: LLMGateway accepts circuit_breaker= kwarg (backward-compatible)
# ---------------------------------------------------------------------------


class TestCircuitBreakerInit:
    """AC-1: LLMGateway.__init__ accepts circuit_breaker kwarg."""

    def test_accepts_circuit_breaker_instance(self) -> None:
        """LLMGateway can be instantiated with a CircuitBreaker instance."""
        cb = _make_mock_circuit_breaker()
        gw = _make_gateway(circuit_breaker=cb)
        assert gw.circuit_breaker is cb  # type: ignore[attr-defined]

    def test_circuit_breaker_defaults_to_none(self) -> None:
        """Omitting circuit_breaker= is backward-compatible (defaults to None)."""
        gw = LLMGateway(_retry_wait=wait_fixed(0))
        assert gw.circuit_breaker is None  # type: ignore[attr-defined]

    def test_accepts_none_circuit_breaker_explicitly(self) -> None:
        """Passing circuit_breaker=None is explicitly supported."""
        gw = _make_gateway(circuit_breaker=None)
        assert gw.circuit_breaker is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC-2: allow_request() guard — circuit OPEN blocks litellm call
# ---------------------------------------------------------------------------


class TestCircuitBreakerAllowRequest:
    """AC-2: _call_with_retry calls allow_request(); OPEN raises, litellm skipped."""

    @pytest.mark.asyncio
    async def test_circuit_open_raises_and_skips_litellm(self) -> None:
        """allow_request()==False raises CircuitOpenError and skips litellm."""
        cb = _make_mock_circuit_breaker(allow=False)
        gw = _make_gateway(circuit_breaker=cb)

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            with pytest.raises(CircuitOpenError):
                await gw._call_with_retry(  # type: ignore[attr-defined]
                    call_kwargs={"model": "gpt-4o-mini", "messages": []},
                    prompt="test prompt",
                    task_type="search",
                )
            # Circuit is OPEN — litellm must NOT have been called
            mock_acompletion.assert_not_called()

    @pytest.mark.asyncio
    async def test_allow_request_called_before_litellm(self) -> None:
        """allow_request() is invoked before any litellm call when cb is attached."""
        cb = _make_mock_circuit_breaker(allow=True)
        gw = _make_gateway(circuit_breaker=cb)

        fake_response = _make_litellm_response()
        with patch(
            "litellm.acompletion", new_callable=AsyncMock, return_value=fake_response
        ):
            await gw._call_with_retry(  # type: ignore[attr-defined]
                call_kwargs={"model": "gpt-4o-mini", "messages": []},
                prompt="hello",
                task_type="search",
            )

        cb.allow_request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_circuit_breaker_does_not_block_call(self) -> None:
        """Without a circuit_breaker, _call_with_retry proceeds normally."""
        gw = _make_gateway(circuit_breaker=None)

        fake_response = _make_litellm_response()
        with patch(
            "litellm.acompletion", new_callable=AsyncMock, return_value=fake_response
        ) as mock_acompletion:
            await gw._call_with_retry(  # type: ignore[attr-defined]
                call_kwargs={"model": "gpt-4o-mini", "messages": []},
                prompt="hello",
                task_type=None,
            )

        mock_acompletion.assert_awaited_once()


# ---------------------------------------------------------------------------
# AC-3: record_success / record_failure called on correct paths
# ---------------------------------------------------------------------------


class TestCircuitBreakerRecording:
    """AC-3: record_success on LLM success; record_failure on exception."""

    @pytest.mark.asyncio
    async def test_record_success_called_on_successful_llm_call(self) -> None:
        """record_success() is awaited when litellm responds without error."""
        cb = _make_mock_circuit_breaker(allow=True)
        gw = _make_gateway(circuit_breaker=cb)

        fake_response = _make_litellm_response()
        with patch(
            "litellm.acompletion", new_callable=AsyncMock, return_value=fake_response
        ):
            await gw._call_with_retry(  # type: ignore[attr-defined]
                call_kwargs={"model": "gpt-4o-mini", "messages": []},
                prompt="hello",
                task_type=None,
            )

        cb.record_success.assert_awaited_once()
        cb.record_failure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_record_failure_called_on_llm_exception(self) -> None:
        """record_failure() is awaited exactly once on a non-transient LLM exception."""
        import litellm.exceptions as le

        cb = _make_mock_circuit_breaker(allow=True)
        gw = _make_gateway(circuit_breaker=cb)

        # Use an UNRECOVERABLE (non-transient) exception so tenacity does not retry,
        # ensuring record_failure is called exactly once and intent is unambiguous.
        err = le.BadRequestError(
            message="bad request",
            model="gpt-4o-mini",
            llm_provider="openai",
        )
        with patch("litellm.acompletion", new_callable=AsyncMock, side_effect=err):
            with pytest.raises(Exception):
                await gw._call_with_retry(  # type: ignore[attr-defined]
                    call_kwargs={"model": "gpt-4o-mini", "messages": []},
                    prompt="boom",
                    task_type=None,
                )

        cb.record_failure.assert_awaited_once()
        cb.record_success.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_circuit_breaker_no_recording_calls(self) -> None:
        """Without circuit_breaker, recording methods are not invoked."""
        gw = _make_gateway(circuit_breaker=None)

        fake_response = _make_litellm_response()
        with patch(
            "litellm.acompletion", new_callable=AsyncMock, return_value=fake_response
        ):
            result = await gw._call_with_retry(  # type: ignore[attr-defined]
                call_kwargs={"model": "gpt-4o-mini", "messages": []},
                prompt="ok",
                task_type=None,
            )
        # Completed without error and returned the litellm response unchanged;
        # no recording side-effects to assert.
        assert result is fake_response


# ---------------------------------------------------------------------------
# AC-4: PriorityQueue wiring — interactive vs background priority
# ---------------------------------------------------------------------------


class TestPriorityQueueWiring:
    """AC-4: LLMGateway enqueues to PriorityQueue with correct priority levels."""

    @pytest.mark.asyncio
    async def test_interactive_request_uses_high_priority(self) -> None:
        """interactive task_type (e.g. 'search') enqueues with PriorityLevel.HIGH."""
        mock_queue = AsyncMock(spec=PriorityQueue)
        mock_queue.interactive_queue_size.return_value = 0
        mock_queue.background_queue_size.return_value = 0
        gw = _make_gateway(priority_queue=mock_queue)

        await gw.enqueue_request(  # type: ignore[attr-defined]
            prompt="find me something",
            model="gpt-4o-mini",
            task_type="search",
        )

        mock_queue.enqueue.assert_awaited_once()
        call_args = mock_queue.enqueue.call_args
        queued: QueuedRequest = call_args.args[0] if call_args.args else call_args[0][0]
        assert queued.priority == PriorityLevel.HIGH

    @pytest.mark.asyncio
    async def test_background_request_uses_lower_priority(self) -> None:
        """background task_type enqueues with PriorityLevel.NORMAL or LOW (not HIGH)."""
        mock_queue = AsyncMock(spec=PriorityQueue)
        mock_queue.interactive_queue_size.return_value = 0
        mock_queue.background_queue_size.return_value = 0
        gw = _make_gateway(priority_queue=mock_queue)

        await gw.enqueue_request(  # type: ignore[attr-defined]
            prompt="batch process this",
            model="gpt-4o-mini",
            task_type="background",
        )

        mock_queue.enqueue.assert_awaited_once()
        call_args = mock_queue.enqueue.call_args
        queued = call_args.args[0] if call_args.args else call_args[0][0]
        assert queued.priority != PriorityLevel.HIGH

    @pytest.mark.asyncio
    async def test_interactive_priority_higher_than_background(self) -> None:
        """Interactive priority < background priority (HIGH before NORMAL/LOW)."""
        mock_queue = AsyncMock(spec=PriorityQueue)
        gw = _make_gateway(priority_queue=mock_queue)

        await gw.enqueue_request(  # type: ignore[attr-defined]
            prompt="interactive",
            model="gpt-4o-mini",
            task_type="search",
        )
        await gw.enqueue_request(  # type: ignore[attr-defined]
            prompt="background",
            model="gpt-4o-mini",
            task_type="background",
        )

        assert mock_queue.enqueue.await_count == 2
        calls = mock_queue.enqueue.await_args_list
        interactive_req: QueuedRequest = (
            calls[0].args[0] if calls[0].args else calls[0][0][0]
        )
        background_req: QueuedRequest = (
            calls[1].args[0] if calls[1].args else calls[1][0][0]
        )
        # HIGH sorts before NORMAL/LOW in PriorityLevel.value ordering
        assert interactive_req.priority == PriorityLevel.HIGH
        assert background_req.priority in (PriorityLevel.NORMAL, PriorityLevel.LOW)

    @pytest.mark.asyncio
    async def test_queue_worker_consumes_and_calls_retry(self) -> None:
        """Queue worker coroutine dequeues a request and calls _call_with_retry."""
        # Build a real PriorityQueue with one item so the worker has work to do
        real_queue = PriorityQueue()
        req = QueuedRequest(
            prompt="worker task", model="gpt-4o-mini", priority=PriorityLevel.HIGH
        )
        await real_queue.enqueue(req)

        gw = _make_gateway(priority_queue=real_queue)

        fake_response = _make_litellm_response("worker response")
        with patch(
            "litellm.acompletion", new_callable=AsyncMock, return_value=fake_response
        ):
            # The worker must exist as an async method / coroutine on LLMGateway
            await gw.process_queue_item()  # type: ignore[attr-defined]

        # Queue should now be empty after processing one item
        assert real_queue.interactive_queue_size() == 0


# ---------------------------------------------------------------------------
# AC-5: GET /api/v1/llm/status endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def llm_status_app() -> FastAPI:
    """Minimal FastAPI app with only the llm router (IS_API_KEY unset)."""
    from intellisource.api.routers.llm import router as llm_router

    application = FastAPI()
    application.include_router(llm_router, prefix="/api/v1")
    return application


@pytest.fixture()
async def llm_status_client(llm_status_app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=llm_status_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


class TestLLMStatusEndpoint:
    """AC-5: GET /api/v1/llm/status returns circuit_state and queue_lengths.

    All tests in this class run with IS_API_KEY unset, so require_api_key
    short-circuits (no key required). See TestLLMStatusAuth for auth scenarios.
    """

    @pytest.fixture(autouse=True)
    def _unset_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ensure IS_API_KEY is unset so auth is skipped in this test class."""
        monkeypatch.delenv("IS_API_KEY", raising=False)

    @pytest.mark.asyncio
    async def test_status_returns_200(self, llm_status_client: AsyncClient) -> None:
        """GET /api/v1/llm/status responds with HTTP 200 when IS_API_KEY is unset."""
        resp = await llm_status_client.get("/api/v1/llm/status")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_status_contains_circuit_state_field(
        self, llm_status_client: AsyncClient
    ) -> None:
        """Response body contains 'circuit_state' key."""
        resp = await llm_status_client.get("/api/v1/llm/status")
        body = resp.json()
        assert "circuit_state" in body

    @pytest.mark.asyncio
    async def test_status_circuit_state_is_known_value(
        self, llm_status_client: AsyncClient
    ) -> None:
        """circuit_state value is one of CLOSED, OPEN, HALF_OPEN, UNKNOWN."""
        resp = await llm_status_client.get("/api/v1/llm/status")
        body = resp.json()
        assert body["circuit_state"] in {"CLOSED", "OPEN", "HALF_OPEN", "UNKNOWN"}

    @pytest.mark.asyncio
    async def test_status_contains_queue_lengths_field(
        self, llm_status_client: AsyncClient
    ) -> None:
        """Response body contains 'queue_lengths' key."""
        resp = await llm_status_client.get("/api/v1/llm/status")
        body = resp.json()
        assert "queue_lengths" in body

    @pytest.mark.asyncio
    async def test_status_queue_lengths_has_interactive_and_background(
        self, llm_status_client: AsyncClient
    ) -> None:
        """queue_lengths contains both 'interactive' and 'background' integer counts."""
        resp = await llm_status_client.get("/api/v1/llm/status")
        body = resp.json()
        ql = body["queue_lengths"]
        assert "interactive" in ql
        assert "background" in ql
        assert isinstance(ql["interactive"], int)
        assert isinstance(ql["background"], int)

    @pytest.mark.asyncio
    async def test_status_circuit_state_reflects_mock_closed(
        self, llm_status_client: AsyncClient
    ) -> None:
        """When gateway reports CLOSED state, endpoint returns circuit_state=CLOSED."""
        with patch(
            "intellisource.api.routers.llm.get_llm_gateway_status",
            new_callable=AsyncMock,
            return_value={
                "circuit_state": "CLOSED",
                "queue_lengths": {"interactive": 0, "background": 0},
            },
        ):
            resp = await llm_status_client.get("/api/v1/llm/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["circuit_state"] == "CLOSED"
        assert body["queue_lengths"]["interactive"] == 0
        assert body["queue_lengths"]["background"] == 0

    @pytest.mark.asyncio
    async def test_status_circuit_state_reflects_mock_open(
        self, llm_status_client: AsyncClient
    ) -> None:
        """When gateway reports OPEN state, endpoint returns circuit_state=OPEN."""
        with patch(
            "intellisource.api.routers.llm.get_llm_gateway_status",
            new_callable=AsyncMock,
            return_value={
                "circuit_state": "OPEN",
                "queue_lengths": {"interactive": 3, "background": 12},
            },
        ):
            resp = await llm_status_client.get("/api/v1/llm/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["circuit_state"] == "OPEN"
        assert body["queue_lengths"]["interactive"] == 3
        assert body["queue_lengths"]["background"] == 12


# ---------------------------------------------------------------------------
# R-001: Auth enforcement — /api/v1/llm/status rejects missing/invalid key
# ---------------------------------------------------------------------------


class TestLLMStatusAuth:
    """R-001: /api/v1/llm/status enforces X-API-Key when IS_API_KEY is set."""

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_401(
        self, llm_status_app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without X-API-Key header, endpoint returns 401 when IS_API_KEY is set."""
        monkeypatch.setenv("IS_API_KEY", "secret-key")
        transport = ASGITransport(app=llm_status_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/llm/status")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_api_key_returns_401(
        self, llm_status_app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Wrong X-API-Key value returns 401 when IS_API_KEY is configured."""
        monkeypatch.setenv("IS_API_KEY", "secret-key")
        transport = ASGITransport(app=llm_status_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/llm/status", headers={"x-api-key": "wrong-key"}
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_correct_api_key_returns_200(
        self, llm_status_app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Correct X-API-Key value returns 200 when IS_API_KEY is configured."""
        monkeypatch.setenv("IS_API_KEY", "secret-key")
        transport = ASGITransport(app=llm_status_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/llm/status", headers={"x-api-key": "secret-key"}
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# R-002: get_llm_gateway_status reads real LLMGateway from app.state
# ---------------------------------------------------------------------------


class TestLLMStatusRealGateway:
    """R-002: /api/v1/llm/status reflects actual circuit state from app.state."""

    @pytest.mark.asyncio
    async def test_status_reflects_injected_open_circuit(self) -> None:
        """When app.state.llm_gateway has OPEN circuit breaker, status returns OPEN."""
        from intellisource.api.routers.llm import router as llm_router

        app = FastAPI()
        app.include_router(llm_router, prefix="/api/v1")

        mock_cb = AsyncMock(spec=CircuitBreaker)
        mock_cb.get_state.return_value = CircuitState.OPEN

        mock_queue = MagicMock(spec=PriorityQueue)
        mock_queue.interactive_queue_size.return_value = 5
        mock_queue.background_queue_size.return_value = 10

        mock_gateway = MagicMock(spec=LLMGateway)
        mock_gateway.circuit_breaker = mock_cb
        mock_gateway._priority_queue = mock_queue

        app.state.llm_gateway = mock_gateway

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/llm/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["circuit_state"] == "OPEN"
        assert body["queue_lengths"]["interactive"] == 5
        assert body["queue_lengths"]["background"] == 10

    @pytest.mark.asyncio
    async def test_status_reflects_injected_closed_circuit(self) -> None:
        """When app.state.llm_gateway has CLOSED breaker, status returns CLOSED."""
        from intellisource.api.routers.llm import router as llm_router

        app = FastAPI()
        app.include_router(llm_router, prefix="/api/v1")

        mock_cb = AsyncMock(spec=CircuitBreaker)
        mock_cb.get_state.return_value = CircuitState.CLOSED

        mock_queue = MagicMock(spec=PriorityQueue)
        mock_queue.interactive_queue_size.return_value = 0
        mock_queue.background_queue_size.return_value = 0

        mock_gateway = MagicMock(spec=LLMGateway)
        mock_gateway.circuit_breaker = mock_cb
        mock_gateway._priority_queue = mock_queue

        app.state.llm_gateway = mock_gateway

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/llm/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["circuit_state"] == "CLOSED"
        assert body["queue_lengths"]["interactive"] == 0
        assert body["queue_lengths"]["background"] == 0

    @pytest.mark.asyncio
    async def test_status_returns_unknown_when_gateway_not_in_app_state(self) -> None:
        """When llm_gateway is absent from app.state, circuit_state returns UNKNOWN."""
        from intellisource.api.routers.llm import router as llm_router

        app = FastAPI()
        app.include_router(llm_router, prefix="/api/v1")
        # Deliberately do not set app.state.llm_gateway

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/llm/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["circuit_state"] == "UNKNOWN"
