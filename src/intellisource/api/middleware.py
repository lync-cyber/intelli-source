"""API middleware: authentication, request logging, and tracing."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from intellisource.core.settings import get_settings
from intellisource.observability.trace_context import trace_id_ctx

logger = logging.getLogger(__name__)

# Probe / observability / webhook endpoints reachable without the production API
# key. Module-level so the OpenAPI security-scheme builder can mark exactly the
# same paths public (single source of truth shared with api.openapi).
PUBLIC_EXACT_PATHS = frozenset(
    {
        "/health",
        "/api/v1/health",
        "/api/v1/system/health",
        "/api/v1/metrics",
        "/api/v1/system/metrics",
        "/metrics",
        # Interactive API docs: the schema lists the surface but every operation
        # still requires X-API-Key, so exposing the docs aids integration without
        # weakening enforcement.
        "/docs",
        "/redoc",
        "/openapi.json",
    }
)
PUBLIC_PATH_PREFIXES = ("/api/v1/webhooks",)

__all__ = [
    "AuthMiddleware",
    "PUBLIC_EXACT_PATHS",
    "PUBLIC_PATH_PREFIXES",
    "RequestLoggerMiddleware",
    "TracingMiddleware",
    "trace_id_ctx",
]


_PRODUCTION_ENVS = frozenset({"production", "prod"})


def _is_production() -> bool:
    """True when the deployment env is production (rejects an unset API key)."""
    return get_settings().env.strip().lower() in _PRODUCTION_ENVS


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate X-API-Key header against IS_API_KEY environment variable.

    Probe / observability endpoints are exempt so external uptime monitors,
    container orchestrators (k8s liveness/readiness), and Prometheus scrapers
    can reach them without holding a shared production API key.

    When ``IS_API_KEY`` is unset the behaviour depends on ``ENV``: in production
    every authenticated path is rejected with 503 (fail closed — never silently
    serve an unauthenticated control plane), while in non-production it is
    allowed through with a one-time WARN so local development stays frictionless.
    """

    _EXEMPT_EXACT = PUBLIC_EXACT_PATHS
    _EXEMPT_PREFIXES = PUBLIC_PATH_PREFIXES

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._warned_missing_key = False

    def _is_exempt(self, path: str) -> bool:
        if path in self._EXEMPT_EXACT:
            return True
        return any(path.startswith(prefix) for prefix in self._EXEMPT_PREFIXES)

    def _warn_missing_key_once(self, production: bool) -> None:
        if self._warned_missing_key:
            return
        self._warned_missing_key = True
        if production:
            logger.warning(
                "IS_API_KEY is not set while ENV is production — rejecting all"
                " authenticated requests with 503 until a key is configured"
            )
        else:
            logger.warning(
                "IS_API_KEY is not set — API authentication is DISABLED (dev only);"
                " set IS_API_KEY to enforce X-API-Key"
            )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        if self._is_exempt(path):
            return await call_next(request)

        api_key = get_settings().api_key
        if not api_key:
            production = _is_production()
            self._warn_missing_key_once(production)
            if production:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "server API key not configured"},
                )
            return await call_next(request)

        request_key = request.headers.get("x-api-key", "")
        if request_key != api_key:
            return JSONResponse(
                status_code=401, content={"detail": "Invalid or missing API key"}
            )

        return await call_next(request)


_METRIC_HTTP_REQUESTS_TOTAL = "http_requests_total"
_METRIC_HTTP_REQUEST_DURATION = "http_request_duration_seconds"


def _ensure_http_metrics_registered() -> None:
    """Idempotently register the HTTP-side metrics on the singleton collector."""
    from intellisource.observability.metrics import MetricsCollector

    mc = MetricsCollector.get_instance()
    if _METRIC_HTTP_REQUESTS_TOTAL not in mc._counters:
        mc.register_counter(
            _METRIC_HTTP_REQUESTS_TOTAL,
            "Total HTTP requests served (any method/status)",
        )
    if _METRIC_HTTP_REQUEST_DURATION not in mc._histograms:
        mc.register_histogram(
            _METRIC_HTTP_REQUEST_DURATION,
            "Wall-clock duration (seconds) of HTTP request handling",
        )


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """Log method, path, status_code, duration_ms and record per-request metrics.

    Metrics emitted on every request (F-22):
    - ``http_requests_total`` counter increments once per response, regardless
      of status code, so error rate is computed as deltas against another
      labelled counter at scrape time.
    - ``http_request_duration_seconds`` histogram records wall-clock seconds.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        # Register the HTTP families at startup (when the middleware stack is
        # built) so the very first /metrics scrape already lists them, rather
        # than only after the first non-metrics request.
        _ensure_http_metrics_registered()

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - start
        duration_ms = int(elapsed * 1000)
        logger.info(
            "method=%s path=%s status_code=%s duration_ms=%d",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        try:
            from intellisource.observability.metrics import MetricsCollector

            _ensure_http_metrics_registered()
            mc = MetricsCollector.get_instance()
            mc.increment_counter(_METRIC_HTTP_REQUESTS_TOTAL)
            mc.observe_histogram(_METRIC_HTTP_REQUEST_DURATION, elapsed)
        except Exception:  # noqa: BLE001 — metric failures must not break responses
            logger.exception("failed to record http request metrics")
        return response


class TracingMiddleware(BaseHTTPMiddleware):
    """Inject or propagate X-Trace-ID header."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
        trace_id_ctx.set(trace_id)
        # Carrier line emitted while trace_id_ctx is freshly bound so the
        # TraceIdFormatter renders trace_id= on at least one api-side row.
        logger.info(
            "http request inbound method=%s path=%s",
            request.method,
            request.url.path,
        )
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response
