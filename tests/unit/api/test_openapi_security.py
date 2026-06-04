"""Inc2 P0-2: X-API-Key surfaced as an OpenAPI security scheme.

Enforcement stays in AuthMiddleware; this verifies the schema mirrors it so
clients (and Swagger UI) see which endpoints need the key.
"""

from __future__ import annotations

from typing import Any


def test_security_scheme_declared(main_openapi: dict[str, Any]) -> None:
    """components.securitySchemes carries an apiKey header scheme."""
    schemes = main_openapi.get("components", {}).get("securitySchemes", {})
    assert "ApiKeyAuth" in schemes
    assert schemes["ApiKeyAuth"] == {
        "type": "apiKey",
        "in": "header",
        "name": "x-api-key",
    }


def test_protected_endpoint_requires_api_key(
    main_openapi_paths: dict[str, Any],
) -> None:
    """A business endpoint requires the API-key scheme."""
    op = main_openapi_paths["/api/v1/sources"]["get"]
    assert op.get("security") == [{"ApiKeyAuth": []}]


def test_probe_endpoint_is_public(main_openapi_paths: dict[str, Any]) -> None:
    """An exempt probe endpoint declares empty security (public)."""
    op = main_openapi_paths["/api/v1/metrics"]["get"]
    assert op.get("security") == []
