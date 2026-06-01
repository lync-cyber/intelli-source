"""Circuit breaker with Redis-backed state persistence.

Implements a state machine: CLOSED -> OPEN -> HALF_OPEN -> CLOSED.
State is stored in a Redis HASH, enabling shared circuit state across workers.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Protocol

from intellisource.core.errors import ErrorCategory, LLMError


class AsyncRedis(Protocol):
    """Protocol for async Redis client methods used by CircuitBreaker."""

    async def hgetall(self, name: str) -> dict[bytes, bytes]: ...
    async def hset(self, name: str, mapping: dict[str, str]) -> Any: ...
    async def delete(self, *names: str) -> Any: ...


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(LLMError):
    """Raised when a request is blocked because the circuit breaker is OPEN."""

    def __init__(self, message: str = "Circuit breaker is OPEN") -> None:
        super().__init__(message, category=ErrorCategory.RECOVERABLE_DEGRADED)


class CircuitBreaker:
    """Redis-backed circuit breaker with per-model/provider tracking.

    Args:
        redis: Async Redis client instance.
        failure_threshold: Number of consecutive failures to trip the breaker.
        recovery_timeout: Seconds to wait before transitioning OPEN -> HALF_OPEN.
        model: Optional model identifier for namespacing.
        provider: Optional provider identifier for namespacing.
    """

    def __init__(
        self,
        redis: Any,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        model: str = "default",
        provider: str = "default",
    ) -> None:
        self._redis = redis
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._model = model
        self._provider = provider
        self._key = f"circuit_breaker:{provider}:{model}"
        # Register the aggregate gauge at construction so a quiet API process
        # (which builds a breaker at startup) exposes llm_circuit_open at 0,
        # instead of the family only appearing after the first state transition.
        try:
            from intellisource.observability.metrics import (  # noqa: PLC0415
                MetricsCollector,
            )

            _ensure_circuit_metric_registered(MetricsCollector.get_instance())
        except Exception:  # noqa: BLE001 — metrics must never break the breaker
            pass

    async def _read_state(self) -> tuple[CircuitState, int, float]:
        """Read circuit state from Redis.

        Always fetches latest for multi-Worker consistency.
        """
        data: dict[bytes, bytes] = await self._redis.hgetall(self._key)
        if not data:
            return CircuitState.CLOSED, 0, 0.0
        raw_state = data.get(b"state", b"CLOSED").decode()
        failure_count = int(data.get(b"failure_count", b"0").decode())
        last_failure_at = float(data.get(b"last_failure_at", b"0").decode())
        state = CircuitState(raw_state)
        return state, failure_count, last_failure_at

    async def _write_state(
        self,
        state: CircuitState,
        failure_count: int,
        last_failure_at: float,
    ) -> None:
        """Persist circuit state to Redis HASH and update local cache."""
        await self._redis.hset(
            self._key,
            mapping={
                "state": state.value,
                "failure_count": str(failure_count),
                "last_failure_at": str(last_failure_at),
            },
        )

    async def get_state(self) -> CircuitState:
        """Return the current circuit state, applying timeout transitions."""
        state, _failure_count, last_failure_at = await self._read_state()
        if state == CircuitState.OPEN:
            elapsed = time.time() - last_failure_at
            if elapsed >= self._recovery_timeout:
                return CircuitState.HALF_OPEN
        return state

    async def record_failure(self) -> None:
        """Record a failure and potentially trip the breaker."""
        state, failure_count, last_failure_at = await self._read_state()

        # Check if currently in HALF_OPEN (OPEN + timeout expired)
        if state == CircuitState.OPEN:
            elapsed = time.time() - last_failure_at
            if elapsed >= self._recovery_timeout:
                # HALF_OPEN: failure re-opens circuit
                await self._write_state(CircuitState.OPEN, failure_count, time.time())
                _publish_state_gauge(self._provider, self._model, CircuitState.OPEN)
                return

        new_count = failure_count + 1
        now = time.time()
        if new_count >= self._failure_threshold:
            await self._write_state(CircuitState.OPEN, new_count, now)
            _publish_state_gauge(self._provider, self._model, CircuitState.OPEN)
        else:
            await self._write_state(CircuitState.CLOSED, new_count, now)
            _publish_state_gauge(self._provider, self._model, CircuitState.CLOSED)

    async def record_success(self) -> None:
        """Record a success, resetting failure count and closing the breaker."""
        await self._write_state(CircuitState.CLOSED, 0, 0.0)
        _publish_state_gauge(self._provider, self._model, CircuitState.CLOSED)

    async def allow_request(self) -> bool:
        """Check whether a request is allowed through the breaker."""
        state = await self.get_state()
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            return True
        return False


_METRIC_LLM_CIRCUIT_OPEN: str = "llm_circuit_open"


def _ensure_circuit_metric_registered(mc: Any) -> None:
    """Idempotently register the aggregate llm_circuit_open gauge."""
    if _METRIC_LLM_CIRCUIT_OPEN not in mc._gauges:
        mc.register_gauge(
            _METRIC_LLM_CIRCUIT_OPEN,
            "1 when any LLM circuit breaker is OPEN, else 0",
        )


def _publish_state_gauge(provider: str, model: str, state: CircuitState) -> None:
    """Publish a 0/1 gauge for the circuit state.

    Aggregated across all (provider, model) pairs into a single gauge so the
    Prometheus alert ``llm_circuit_open > 0 for 1m`` fires when *any* breaker
    is OPEN. Per-pair labelling is intentionally omitted to match the
    label-less MetricsCollector contract.
    """
    try:
        from intellisource.observability.metrics import (  # noqa: PLC0415
            MetricsCollector,
        )

        mc = MetricsCollector.get_instance()
        _ensure_circuit_metric_registered(mc)
        # Last-writer-wins: any transition to OPEN sets the gauge to 1;
        # transition to CLOSED sets it back to 0. With multiple
        # (provider, model) pairs the gauge tracks the most recent
        # transition.
        value = 1.0 if state == CircuitState.OPEN else 0.0
        mc.set_gauge(_METRIC_LLM_CIRCUIT_OPEN, value)
    except Exception:  # noqa: BLE001 — metrics must never break the breaker
        pass
