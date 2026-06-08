"""Inject the X-API-Key security scheme into the generated OpenAPI schema.

Enforcement lives in ``AuthMiddleware``; this only makes the requirement visible
in /openapi.json and the Swagger 'Authorize' box, mirroring the middleware's
exempt paths so probe / webhook endpoints are correctly shown as public.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from intellisource.api.middleware import is_exempt_path

SECURITY_SCHEME_NAME = "ApiKeyAuth"

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """Generate (and cache) the OpenAPI schema with the API-key scheme applied."""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    components = schema.setdefault("components", {})
    components.setdefault("securitySchemes", {})[SECURITY_SCHEME_NAME] = {
        "type": "apiKey",
        "in": "header",
        "name": "x-api-key",
    }

    requirement: list[dict[str, list[str]]] = [{SECURITY_SCHEME_NAME: []}]
    for path, operations in schema.get("paths", {}).items():
        public = is_exempt_path(path)
        for method, operation in operations.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation["security"] = [] if public else requirement

    app.openapi_schema = schema
    return schema


def install_openapi(app: FastAPI) -> None:
    """Override ``app.openapi`` to add the API-key security scheme."""
    app.openapi = lambda: build_openapi(app)  # type: ignore[method-assign]
