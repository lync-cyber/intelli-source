"""Tests for T-007: Health check -- HealthChecker business logic.

Covers:
  AC-060: /api/v1/health returns component health status (database/redis/celery)
  AC-T007-1: Health check accessible without authentication (API layer concern,
             tested here as: HealthChecker has no auth dependency)
  AC-T007-2: Any critical component unavailable -> status=degraded/unhealthy
  AC-T007-3: /api/v1/metrics returns Prometheus text (API layer; out of scope)
  AC-T007-4: Metrics endpoint requires API Key auth (API layer; out of scope)

Note: AC-T007-3 and AC-T007-4 concern the metrics *endpoint* (API layer M-011),
not HealthChecker. They are out of scope for this unit test file.
"""

from __future__ import annotations

from datetime import datetime

import pytest

# ---------------------------------------------------------------------------
# AC-060 / AC-T007-1: HealthChecker import and instantiation
# ---------------------------------------------------------------------------


class TestHealthCheckerImport:
    """HealthChecker must be importable from observability.health."""

    def test_import_health_checker(self) -> None:
        """HealthChecker class must be importable."""
        from intellisource.observability.health import HealthChecker

        assert HealthChecker is not None

    def test_import_health_result(self) -> None:
        """HealthResult data class must be importable."""
        from intellisource.observability.health import HealthResult

        assert HealthResult is not None

    def test_health_checker_instantiable(self) -> None:
        """HealthChecker must be instantiable with no required arguments."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()
        assert checker is not None


# ---------------------------------------------------------------------------
# AC-060: register_check and check_health basic flow
# ---------------------------------------------------------------------------


class TestHealthCheckerRegistration:
    """HealthChecker.register_check allows registering async check functions."""

    def test_register_check(self) -> None:
        """register_check should accept a name and async callable without error."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()

        async def _ok() -> bool:
            return True

        checker.register_check("database", _ok)

    def test_register_multiple_checks(self) -> None:
        """Multiple checks can be registered under different names."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()

        async def _ok() -> bool:
            return True

        checker.register_check("database", _ok)
        checker.register_check("redis", _ok)
        checker.register_check("celery", _ok)


# ---------------------------------------------------------------------------
# AC-060: check_health returns HealthResult with correct structure
# ---------------------------------------------------------------------------


class TestHealthCheckerAllHealthy:
    """When all components are healthy, check_health returns status='healthy'."""

    @pytest.mark.asyncio
    async def test_all_healthy_status(self) -> None:
        """status must be 'healthy' when every registered check returns True."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()

        async def _healthy() -> bool:
            return True

        checker.register_check("database", _healthy)
        checker.register_check("redis", _healthy)
        checker.register_check("celery", _healthy)

        result = await checker.check_health()
        assert result.status == "healthy", f"Expected 'healthy', got '{result.status}'"

    @pytest.mark.asyncio
    async def test_all_healthy_checks_dict(self) -> None:
        """checks dict must map each component name to 'healthy'."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()

        async def _healthy() -> bool:
            return True

        checker.register_check("database", _healthy)
        checker.register_check("redis", _healthy)
        checker.register_check("celery", _healthy)

        result = await checker.check_health()
        assert result.checks["database"] == "healthy"
        assert result.checks["redis"] == "healthy"
        assert result.checks["celery"] == "healthy"

    @pytest.mark.asyncio
    async def test_result_has_version(self) -> None:
        """HealthResult must include a version string."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()
        result = await checker.check_health()
        assert isinstance(result.version, str)
        assert len(result.version) > 0

    @pytest.mark.asyncio
    async def test_result_has_uptime_seconds(self) -> None:
        """HealthResult must include uptime_seconds as a non-negative integer."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()
        result = await checker.check_health()
        assert isinstance(result.uptime_seconds, (int, float))
        assert result.uptime_seconds >= 0

    @pytest.mark.asyncio
    async def test_result_has_timestamp(self) -> None:
        """HealthResult must include a timestamp (datetime)."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()
        result = await checker.check_health()
        assert isinstance(result.timestamp, datetime)


# ---------------------------------------------------------------------------
# AC-T007-2: Degraded / unhealthy status when components fail
# ---------------------------------------------------------------------------


class TestHealthCheckerDegraded:
    """When one or more components are unhealthy, status must reflect degradation."""

    @pytest.mark.asyncio
    async def test_one_unhealthy_component(self) -> None:
        """If one component is unhealthy, overall status must not be 'healthy'."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()

        async def _healthy() -> bool:
            return True

        async def _unhealthy() -> bool:
            return False

        checker.register_check("database", _healthy)
        checker.register_check("redis", _unhealthy)
        checker.register_check("celery", _healthy)

        result = await checker.check_health()
        assert result.status in ("degraded", "unhealthy"), (
            f"Expected degraded/unhealthy, got '{result.status}'"
        )

    @pytest.mark.asyncio
    async def test_unhealthy_component_marked_in_checks(self) -> None:
        """The failing component must be marked 'unhealthy' in checks dict."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()

        async def _healthy() -> bool:
            return True

        async def _unhealthy() -> bool:
            return False

        checker.register_check("database", _healthy)
        checker.register_check("redis", _unhealthy)
        checker.register_check("celery", _healthy)

        result = await checker.check_health()
        assert result.checks["redis"] == "unhealthy"
        assert result.checks["database"] == "healthy"
        assert result.checks["celery"] == "healthy"

    @pytest.mark.asyncio
    async def test_all_unhealthy(self) -> None:
        """If all components are unhealthy, status must be 'unhealthy'."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()

        async def _unhealthy() -> bool:
            return False

        checker.register_check("database", _unhealthy)
        checker.register_check("redis", _unhealthy)
        checker.register_check("celery", _unhealthy)

        result = await checker.check_health()
        assert result.status == "unhealthy", (
            f"Expected 'unhealthy' when all components fail, got '{result.status}'"
        )

    @pytest.mark.asyncio
    async def test_check_function_raises_exception(self) -> None:
        """If a check function raises, that component should be treated as unhealthy."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()

        async def _raises() -> bool:
            raise ConnectionError("cannot connect")

        async def _healthy() -> bool:
            return True

        checker.register_check("database", _raises)
        checker.register_check("redis", _healthy)

        result = await checker.check_health()
        assert result.checks["database"] == "unhealthy"
        assert result.status in ("degraded", "unhealthy")


# ---------------------------------------------------------------------------
# AC-T007-1: HealthChecker has no auth dependency
# ---------------------------------------------------------------------------


class TestHealthCheckerNoAuthDependency:
    """HealthChecker must not require any authentication or credentials to operate."""

    def test_no_auth_parameter_in_init(self) -> None:
        """HealthChecker __init__ must not require auth-related parameters."""
        import inspect

        from intellisource.observability.health import HealthChecker

        sig = inspect.signature(HealthChecker.__init__)
        param_names = [p for p in sig.parameters if p != "self"]
        auth_keywords = {
            "token",
            "api_key",
            "secret",
            "password",
            "credentials",
            "auth",
        }
        found = auth_keywords & set(param_names)
        assert not found, (
            f"HealthChecker.__init__ should not require auth params, found: {found}"
        )

    @pytest.mark.asyncio
    async def test_check_health_no_auth_required(self) -> None:
        """check_health() must be callable without any auth context."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()

        async def _healthy() -> bool:
            return True

        checker.register_check("database", _healthy)
        # Should not raise any auth-related error
        result = await checker.check_health()
        assert result.status == "healthy"


# ---------------------------------------------------------------------------
# AC-060: No registered checks edge case
# ---------------------------------------------------------------------------


class TestHealthCheckerNoChecks:
    """Edge case: HealthChecker with no registered checks."""

    @pytest.mark.asyncio
    async def test_no_checks_returns_healthy(self) -> None:
        """With no checks registered, status should default to 'healthy'."""
        from intellisource.observability.health import HealthChecker

        checker = HealthChecker()
        result = await checker.check_health()
        assert result.status == "healthy"
        assert result.checks == {} or len(result.checks) == 0


# ---------------------------------------------------------------------------
# F-20 / F-21: concurrent checks + per-check timeout + last_error detail
# ---------------------------------------------------------------------------


class TestHealthCheckerTimeout:
    """A stuck dependency must not block the whole endpoint."""

    @pytest.mark.asyncio
    async def test_timeout_marks_check_unhealthy(self) -> None:
        """A check that exceeds the timeout is reported unhealthy with last_error."""
        import asyncio

        from intellisource.observability.health import HealthChecker

        async def _slow() -> bool:
            await asyncio.sleep(5)
            return True

        async def _fast() -> bool:
            return True

        checker = HealthChecker(check_timeout_seconds=0.05)
        checker.register_check("slow_dep", _slow)
        checker.register_check("fast_dep", _fast)

        result = await checker.check_health()

        assert result.checks["slow_dep"] == "unhealthy"
        assert result.checks["fast_dep"] == "healthy"
        assert "timeout" in (result.details["slow_dep"].get("last_error") or "")
        assert "failed_at" in result.details["slow_dep"]

    @pytest.mark.asyncio
    async def test_checks_run_concurrently(self) -> None:
        """Two 0.3s checks finish near ~0.3s, not ~0.6s, when run in parallel."""
        import asyncio
        import time

        from intellisource.observability.health import HealthChecker

        async def _slow() -> bool:
            await asyncio.sleep(0.3)
            return True

        checker = HealthChecker(check_timeout_seconds=2.0)
        checker.register_check("a", _slow)
        checker.register_check("b", _slow)

        start = time.monotonic()
        result = await checker.check_health()
        elapsed = time.monotonic() - start

        assert result.status == "healthy"
        assert elapsed < 0.55, (
            f"check_health must run checks concurrently; took {elapsed:.2f}s"
        )


class TestHealthCheckerLastError:
    """Exceptions surface as details[*].last_error so /health is self-diagnosing."""

    @pytest.mark.asyncio
    async def test_exception_captured_in_last_error(self) -> None:
        from intellisource.observability.health import HealthChecker

        async def _raises() -> bool:
            raise ConnectionRefusedError("redis down at 127.0.0.1:6379")

        async def _ok() -> bool:
            return True

        checker = HealthChecker()
        checker.register_check("redis", _raises)
        checker.register_check("db", _ok)

        result = await checker.check_health()

        assert result.checks["redis"] == "unhealthy"
        last_error = result.details["redis"].get("last_error")
        assert last_error is not None
        assert "ConnectionRefusedError" in last_error
        assert "redis down" in last_error
        assert "failed_at" in result.details["redis"]
        # Healthy checks must not carry last_error keys
        assert "last_error" not in result.details["db"]

    @pytest.mark.asyncio
    async def test_healthy_check_has_no_failure_metadata(self) -> None:
        from intellisource.observability.health import HealthChecker

        async def _ok() -> bool:
            return True

        checker = HealthChecker()
        checker.register_check("redis", _ok)

        result = await checker.check_health()

        entry = result.details["redis"]
        assert entry == {"status": "healthy"}
