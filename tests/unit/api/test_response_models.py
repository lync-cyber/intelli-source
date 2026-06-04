"""Inc2 P0-1: every JSON endpoint exposes a named response_model in OpenAPI.

Endpoints returning raw Response / PlainText / StreamingResponse (webhooks,
/metrics, /search/chat/stream) are intentionally excluded — response_model does
not apply to a Response return value.
"""

from __future__ import annotations

from typing import Any

import pytest

# Representative endpoints that must carry a named ($ref) response schema rather
# than the untyped object/empty schema FastAPI emits for dict[str, Any] / Any.
_TYPED_ENDPOINTS = [
    ("/api/v1/sources", "get"),
    ("/api/v1/sources/{id}", "get"),
    ("/api/v1/sources", "post"),
    ("/api/v1/subscriptions", "get"),
    ("/api/v1/tasks", "get"),
    ("/api/v1/tasks/{id}", "get"),
    ("/api/v1/contents", "get"),
    ("/api/v1/clusters", "get"),
    ("/api/v1/topics", "get"),
    ("/api/v1/pipelines", "get"),
    ("/api/v1/pipelines/{name}", "get"),
    ("/api/v1/llm/status", "get"),
    ("/api/v1/channels", "get"),
    ("/api/v1/templates", "get"),
    ("/api/v1/push-records", "get"),
    ("/api/v1/tasks/chains/{id}", "get"),
    ("/api/v1/distributions/assemble", "post"),
]


def _success_schema(operation: dict[str, Any]) -> dict[str, Any]:
    responses = operation.get("responses", {})
    success = next(
        (responses[code] for code in sorted(responses) if code.startswith("2")),
        {},
    )
    return success.get("content", {}).get("application/json", {}).get("schema", {})


@pytest.mark.parametrize("path,method", _TYPED_ENDPOINTS)
def test_endpoint_has_named_response_model(
    main_openapi_paths: dict[str, Any], path: str, method: str
) -> None:
    """The 200 response references a named component (directly or as list items)."""
    operation = main_openapi_paths[path][method]
    schema = _success_schema(operation)
    ref = schema.get("$ref") or schema.get("items", {}).get("$ref")
    assert ref, f"{method.upper()} {path} lacks a typed response_model: {schema}"
