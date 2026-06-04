"""Standardised JSON error envelope for domain and unhandled errors.

IntelliSourceError subclasses (previously surfaced as opaque 500s) and any
uncaught exception render as ``{"error": {code, message, category, recovery_hint}}``.
FastAPI's default ``{"detail": ...}`` rendering for HTTPException and request
validation is intentionally left untouched — it is the established 4xx contract.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from intellisource.core.errors import ErrorCategory, IntelliSourceError
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)


class ErrorBody(BaseModel):
    """The inner payload of the standard error envelope."""

    code: str
    message: str
    category: str | None = None
    recovery_hint: str | None = None


class ErrorResponse(BaseModel):
    """Top-level error envelope: ``{"error": {...}}``."""

    error: ErrorBody


# Domain category → HTTP status. Transient/degraded conditions are retryable
# (503); external dependency failures map to 502; everything else is a 500.
_CATEGORY_STATUS: dict[ErrorCategory, int] = {
    ErrorCategory.RECOVERABLE_TRANSIENT: 503,
    ErrorCategory.RECOVERABLE_DEGRADED: 503,
    ErrorCategory.UNRECOVERABLE: 500,
    ErrorCategory.EXTERNAL: 502,
}


def _render(body: ErrorBody, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": body.model_dump()})


async def _handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    """Map an IntelliSourceError to its category status + envelope."""
    category = (
        exc.category
        if isinstance(exc, IntelliSourceError)
        else ErrorCategory.UNRECOVERABLE
    )
    hint = exc.recovery_hint if isinstance(exc, IntelliSourceError) else ""
    status_code = _CATEGORY_STATUS.get(category, 500)
    body = ErrorBody(
        code=type(exc).__name__,
        message=str(exc),
        category=category.value,
        recovery_hint=hint or None,
    )
    logger.warning(
        "domain error: code=%s category=%s path=%s",
        body.code,
        category.value,
        request.url.path,
    )
    return _render(body, status_code)


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: never leak internals, always return the envelope."""
    logger.exception("unhandled error at %s", request.url.path)
    body = ErrorBody(code="InternalServerError", message="Internal Server Error")
    return _render(body, 500)


def install_exception_handlers(app: FastAPI) -> None:
    """Register envelope handlers for domain + unhandled errors.

    HTTPException / RequestValidationError keep FastAPI's default handlers so the
    existing ``{"detail": ...}`` 4xx contract is preserved.
    """
    app.add_exception_handler(IntelliSourceError, _handle_domain_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
