"""Standardised JSON error envelope for every API error.

All errors — domain (:class:`IntelliSourceError`), framework 4xx
(:class:`HTTPException` / request validation) and uncaught exceptions — render
as a single shape::

    {"error": {"code": str, "message": str, "category"?: str,
               "recovery_hint"?: str, "detail"?: any}}

so a client (or the CLI) parses one envelope regardless of status. Routers and
middleware that build responses directly use :func:`error_json` to stay on the
same shape as the exception-handler path.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from intellisource.core.errors import ErrorCategory, IntelliSourceError
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)


class ErrorBody(BaseModel):
    """The inner payload of the standard error envelope."""

    code: str
    message: str
    category: str | None = None
    recovery_hint: str | None = None
    detail: Any = None


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


def _http_code_name(status_code: int) -> str:
    """Return a CamelCase code for an HTTP status (404 -> ``NotFound``)."""
    try:
        return HTTPStatus(status_code).phrase.replace(" ", "")
    except ValueError:
        return "Error"


def error_json(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    detail: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the standard ``{"error": {...}}`` envelope for any status.

    Used by routers/middleware that return a response directly so their bodies
    match the exception-handler envelope.
    """
    body: dict[str, Any] = {
        "code": code or _http_code_name(status_code),
        "message": message,
    }
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(
        status_code=status_code, content={"error": body}, headers=headers
    )


def _render(body: ErrorBody, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": body.model_dump(exclude_none=True)}
    )


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


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """Render an HTTPException in the unified error envelope."""
    status_code = getattr(exc, "status_code", 500)
    raw_detail = getattr(exc, "detail", None)
    if isinstance(raw_detail, str):
        message, structured = raw_detail, None
    else:
        message, structured = _http_code_name(status_code), raw_detail
    return error_json(
        status_code,
        message,
        detail=structured,
        headers=getattr(exc, "headers", None),
    )


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Render request-validation failures in the unified envelope."""
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    return error_json(
        422,
        "request validation failed",
        code="ValidationError",
        detail=jsonable_encoder(errors),
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: never leak internals, always return the envelope."""
    logger.exception("unhandled error at %s", request.url.path)
    body = ErrorBody(code="InternalServerError", message="Internal Server Error")
    return _render(body, 500)


def install_exception_handlers(app: FastAPI) -> None:
    """Register the unified envelope handlers for every error class."""
    app.add_exception_handler(IntelliSourceError, _handle_domain_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
