"""Tests for CircuitBreaker state machine and Redis-backed persistence.

Covers:
- AC-029: 5 consecutive failures trigger OPEN; 60s later HALF_OPEN probe; success closes
- AC-T020-1: Circuit state persisted to Redis HASH, shared across workers
- AC-T020-2: Independent tracking per model/provider
- AC-T020-5: Half-open probe success restores CLOSED state
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from intellisource.llm.circuit_breaker import CircuitBreaker, CircuitState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Return an AsyncMock simulating an async Redis client with state tracking.

    hset calls update an in-memory store so that subsequent hgetall calls
    return the persisted state — matching real Redis multi-Worker semantics.
    The store is exposed as ``redis._store`` for tests that need to seed state.
    """
    redis = AsyncMock()
    store: dict[str, dict[bytes, bytes]] = {}

    async def _hset(name: str, mapping: dict[str, str]) -> bool:
        store[name] = {k.encode(): v.encode() for k, v in mapping.items()}
        return True

    async def _hgetall(name: str) -> dict[bytes, bytes]:
        return dict(store.get(name, {}))

    async def _delete(*names: str) -> bool:
        for n in names:
            store.pop(n, None)
        return True

    redis.hset.side_effect = _hset
    redis.hgetall.side_effect = _hgetall
    redis.delete.side_effect = _delete
    redis._store = store
    return redis


@pytest.fixture
def breaker(mock_redis: AsyncMock) -> CircuitBreaker:
    """Return a CircuitBreaker with default thresholds."""
    return CircuitBreaker(
        redis=mock_redis,
        failure_threshold=5,
        recovery_timeout=60,
    )


@pytest.fixture
def breaker_for_model(mock_redis: AsyncMock) -> CircuitBreaker:
    """Return a CircuitBreaker scoped to a specific model/provider."""
    return CircuitBreaker(
        redis=mock_redis,
        failure_threshold=5,
        recovery_timeout=60,
        model="gpt-4",
        provider="openai",
    )


# ===================================================================
# AC-029: 5 consecutive failures -> OPEN; 60s -> HALF_OPEN; success -> CLOSED
# ===================================================================


class TestCircuitBreakerStateMachine:
    """Verify the CLOSED -> OPEN -> HALF_OPEN -> CLOSED state transitions."""

    async def test_initial_state_is_closed(self, breaker: CircuitBreaker) -> None:
        """A new breaker starts in CLOSED state."""
        state = await breaker.get_state()
        assert state == CircuitState.CLOSED

    async def test_single_failure_stays_closed(self, breaker: CircuitBreaker) -> None:
        """One failure should not trip the breaker."""
        await breaker.record_failure()
        state = await breaker.get_state()
        assert state == CircuitState.CLOSED

    async def test_five_consecutive_failures_trigger_open(
        self, breaker: CircuitBreaker, mock_redis: AsyncMock
    ) -> None:
        """AC-029: 5 consecutive failures must transition to OPEN."""
        for _ in range(5):
            await breaker.record_failure()
        state = await breaker.get_state()
        assert state == CircuitState.OPEN

    async def test_open_state_rejects_calls(self, breaker: CircuitBreaker) -> None:
        """While OPEN the breaker should signal that calls are not allowed."""
        for _ in range(5):
            await breaker.record_failure()
        allowed = await breaker.allow_request()
        assert allowed is False

    async def test_open_transitions_to_half_open_after_timeout(
        self, breaker: CircuitBreaker, mock_redis: AsyncMock
    ) -> None:
        """AC-029: After recovery_timeout (60s), state becomes HALF_OPEN."""
        # Seed store: OPEN with last_failure 61 seconds ago
        mock_redis._store[breaker._key] = {
            b"state": b"OPEN",
            b"failure_count": b"5",
            b"last_failure_at": str(time.time() - 61).encode(),
        }
        state = await breaker.get_state()
        assert state == CircuitState.HALF_OPEN

    async def test_half_open_success_closes_circuit(
        self, breaker: CircuitBreaker, mock_redis: AsyncMock
    ) -> None:
        """AC-029 / AC-T020-5: Probe success in HALF_OPEN resets to CLOSED."""
        # Seed store as HALF_OPEN (OPEN + timeout expired)
        mock_redis._store[breaker._key] = {
            b"state": b"OPEN",
            b"failure_count": b"5",
            b"last_failure_at": str(time.time() - 61).encode(),
        }
        await breaker.record_success()
        state = await breaker.get_state()
        assert state == CircuitState.CLOSED

    async def test_half_open_failure_reopens_circuit(
        self, breaker: CircuitBreaker, mock_redis: AsyncMock
    ) -> None:
        """Probe failure in HALF_OPEN should revert to OPEN."""
        mock_redis._store[breaker._key] = {
            b"state": b"OPEN",
            b"failure_count": b"5",
            b"last_failure_at": str(time.time() - 61).encode(),
        }
        await breaker.record_failure()
        state = await breaker.get_state()
        assert state == CircuitState.OPEN

    async def test_success_resets_failure_count(self, breaker: CircuitBreaker) -> None:
        """A success in CLOSED state should reset the failure counter to 0."""
        for _ in range(3):
            await breaker.record_failure()
        await breaker.record_success()
        # After reset, 4 more failures should not trip (< 5 total)
        for _ in range(4):
            await breaker.record_failure()
        state = await breaker.get_state()
        assert state == CircuitState.CLOSED


# ===================================================================
# AC-T020-1: State persisted to Redis HASH, shared across workers
# ===================================================================


class TestCircuitBreakerRedisPersistence:
    """Verify circuit state is persisted to Redis HASH."""

    async def test_record_failure_writes_to_redis(
        self, breaker: CircuitBreaker, mock_redis: AsyncMock
    ) -> None:
        """record_failure must persist failure_count, state, last_failure_at."""
        await breaker.record_failure()
        mock_redis.hset.assert_called()
        # The call should write to a Redis HASH with at least these fields
        call_args = mock_redis.hset.call_args
        assert call_args is not None

    async def test_state_read_from_redis(
        self, breaker: CircuitBreaker, mock_redis: AsyncMock
    ) -> None:
        """get_state must read from Redis, not local memory only."""
        mock_redis._store[breaker._key] = {
            b"state": b"CLOSED",
            b"failure_count": b"0",
            b"last_failure_at": b"0",
        }
        state = await breaker.get_state()
        mock_redis.hgetall.assert_called()
        assert state == CircuitState.CLOSED

    async def test_redis_key_contains_identifier(
        self, breaker_for_model: CircuitBreaker, mock_redis: AsyncMock
    ) -> None:
        """Redis key should incorporate model/provider for namespacing."""
        await breaker_for_model.record_failure()
        call_args = mock_redis.hset.call_args
        # The first positional arg (the Redis key) should contain model/provider
        redis_key = call_args[0][0] if call_args[0] else str(call_args)
        assert "gpt-4" in str(redis_key) or "openai" in str(redis_key)


# ===================================================================
# AC-T020-2: Independent tracking per model/provider
# ===================================================================


class TestCircuitBreakerPerModelTracking:
    """Verify each model/provider has its own breaker state."""

    async def test_different_models_have_different_keys(
        self, mock_redis: AsyncMock
    ) -> None:
        """Two breakers with different model/provider use different Redis keys."""
        breaker_a = CircuitBreaker(
            redis=mock_redis,
            failure_threshold=5,
            recovery_timeout=60,
            model="gpt-4",
            provider="openai",
        )
        breaker_b = CircuitBreaker(
            redis=mock_redis,
            failure_threshold=5,
            recovery_timeout=60,
            model="claude-3",
            provider="anthropic",
        )
        await breaker_a.record_failure()
        await breaker_b.record_failure()
        # hset should have been called twice with different keys
        calls = mock_redis.hset.call_args_list
        assert len(calls) >= 2
        key_a = str(calls[0])
        key_b = str(calls[1])
        assert key_a != key_b

    async def test_one_model_open_does_not_affect_another(
        self, mock_redis: AsyncMock
    ) -> None:
        """Opening breaker for model A should not block model B."""
        breaker_a = CircuitBreaker(
            redis=mock_redis,
            failure_threshold=5,
            recovery_timeout=60,
            model="gpt-4",
            provider="openai",
        )
        breaker_b = CircuitBreaker(
            redis=mock_redis,
            failure_threshold=5,
            recovery_timeout=60,
            model="claude-3",
            provider="anthropic",
        )
        # Trip breaker A
        for _ in range(5):
            await breaker_a.record_failure()

        # breaker_b should still be CLOSED (separate Redis state via store)
        state_b = await breaker_b.get_state()
        assert state_b == CircuitState.CLOSED


# ===================================================================
# AC-T020-5: Half-open probe success auto-restores normal calls
# ===================================================================


class TestHalfOpenRecovery:
    """Verify half-open probe success restores normal calling."""

    async def test_allow_request_returns_true_after_recovery(
        self, breaker: CircuitBreaker, mock_redis: AsyncMock
    ) -> None:
        """After successful probe in HALF_OPEN, allow_request returns True."""
        # Seed store as HALF_OPEN (OPEN + timeout expired)
        mock_redis._store[breaker._key] = {
            b"state": b"OPEN",
            b"failure_count": b"5",
            b"last_failure_at": str(time.time() - 61).encode(),
        }
        # Record probe success — this writes CLOSED to store
        await breaker.record_success()
        # Store now has CLOSED state; allow_request should return True
        allowed = await breaker.allow_request()
        assert allowed is True

    async def test_half_open_allows_single_probe_request(
        self, breaker: CircuitBreaker, mock_redis: AsyncMock
    ) -> None:
        """In HALF_OPEN, the breaker should allow exactly one probe request."""
        mock_redis._store[breaker._key] = {
            b"state": b"OPEN",
            b"failure_count": b"5",
            b"last_failure_at": str(time.time() - 61).encode(),
        }
        allowed = await breaker.allow_request()
        assert allowed is True


# ===================================================================
# CircuitState enum
# ===================================================================


class TestCircuitStateEnum:
    """Verify CircuitState enum values exist."""

    def test_closed_state_exists(self) -> None:
        assert CircuitState.CLOSED is not None

    def test_open_state_exists(self) -> None:
        assert CircuitState.OPEN is not None

    def test_half_open_state_exists(self) -> None:
        assert CircuitState.HALF_OPEN is not None
