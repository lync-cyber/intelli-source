"""Health check module for IntelliSource observability."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

DEFAULT_CHECK_TIMEOUT_SECONDS: float = 2.0


@dataclass
class HealthResult:
    """Result of a health check run."""

    status: str
    version: str
    uptime_seconds: float
    checks: dict[str, str]
    timestamp: datetime
    details: dict[str, dict[str, Any]] = field(default_factory=dict)


class HealthChecker:
    """Executes registered async health checks and aggregates results.

    Each check runs under ``asyncio.wait_for(timeout=DEFAULT_CHECK_TIMEOUT_SECONDS)``
    and all checks run concurrently via ``asyncio.gather`` so a single stuck
    dependency cannot block the entire endpoint. Per-check ``last_error`` is
    captured (timeout message or exception repr) and surfaced in
    ``HealthResult.details`` so operators can diagnose without scraping logs.
    """

    def __init__(
        self,
        *,
        check_timeout_seconds: float = DEFAULT_CHECK_TIMEOUT_SECONDS,
    ) -> None:
        self._checks: dict[str, Callable[[], Coroutine[Any, Any, bool]]] = {}
        self._start_time: float = time.monotonic()
        self._check_timeout_seconds: float = check_timeout_seconds

    def register_check(
        self, name: str, check_fn: Callable[[], Coroutine[Any, Any, bool]]
    ) -> None:
        """Register an async health check function under *name*."""
        self._checks[name] = check_fn

    async def _run_single(
        self,
        name: str,
        fn: Callable[[], Coroutine[Any, Any, bool]],
    ) -> tuple[str, bool, str | None]:
        """Run *fn* with a timeout, returning (name, ok, last_error)."""
        try:
            ok = await asyncio.wait_for(fn(), timeout=self._check_timeout_seconds)
            return name, bool(ok), None
        except asyncio.TimeoutError:
            return (
                name,
                False,
                f"check exceeded timeout {self._check_timeout_seconds:.1f}s",
            )
        except Exception as exc:  # noqa: BLE001 — surface any failure as last_error
            return name, False, repr(exc)

    async def check_health(self) -> HealthResult:
        """Run all registered checks concurrently and aggregate."""
        now = datetime.now(tz=timezone.utc)
        if not self._checks:
            return HealthResult(
                status="healthy",
                version="0.3.0",
                uptime_seconds=time.monotonic() - self._start_time,
                checks={},
                timestamp=now,
                details={},
            )

        names = list(self._checks.keys())
        results = await asyncio.gather(
            *(self._run_single(name, self._checks[name]) for name in names)
        )

        checks: dict[str, str] = {}
        details: dict[str, dict[str, Any]] = {}
        for name, healthy, last_error in results:
            status_word = "healthy" if healthy else "unhealthy"
            checks[name] = status_word
            entry: dict[str, Any] = {"status": status_word}
            if last_error is not None:
                entry["last_error"] = last_error
                entry["failed_at"] = now.isoformat()
            details[name] = entry

        statuses = list(checks.values())
        if all(s == "healthy" for s in statuses):
            status = "healthy"
        elif all(s == "unhealthy" for s in statuses):
            status = "unhealthy"
        else:
            status = "degraded"

        return HealthResult(
            status=status,
            version="0.3.0",
            uptime_seconds=time.monotonic() - self._start_time,
            checks=checks,
            timestamp=now,
            details=details,
        )
