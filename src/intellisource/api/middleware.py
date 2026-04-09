"""API middleware: authentication, request logging, and tracing."""

from __future__ import annotations

import contextvars
import logging
import os
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)

trace_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate X-API-Key header against IS_API_KEY environment variable."""

    _EXEMPT_EXACT = {"/health"}
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


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """Log method, path, status_code, and duration_ms for each request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "method=%s path=%s status_code=%s duration_ms=%d",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
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
