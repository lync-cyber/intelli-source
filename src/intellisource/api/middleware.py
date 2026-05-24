"""API middleware: authentication, request logging, and tracing."""

from __future__ import annotations

import logging
import os
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from intellisource.observability.trace_context import trace_id_ctx

logger = logging.getLogger(__name__)

__all__ = [
    "AuthMiddleware",
    "RequestLoggerMiddleware",
    "TracingMiddleware",
    "trace_id_ctx",
]


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate X-API-Key header against IS_API_KEY environment variable.

    Probe / observability endpoints are exempt so external uptime monitors,
    container orchestrators (k8s liveness/readiness), and Prometheus scrapers
    can reach them without holding a shared production API key.
    """

    _EXEMPT_EXACT = {
        "/health",
        "/api/v1/health",
        "/api/v1/system/health",
        "/api/v1/metrics",
        "/api/v1/system/metrics",
        "/metrics",
    }
    _EXEMPT_PREFIXES = ("/api/v1/webhooks",)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        api_key = os.environ.get("IS_API_KEY", "")

        if not api_key:
            return await call_next(request)

        path = request.url.path
        if path in self._EXEMPT_EXACT:
            return await call_next(request)
        for prefix in self._EXEMPT_PREFIXES:
            if path.startswith(prefix):
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
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response
