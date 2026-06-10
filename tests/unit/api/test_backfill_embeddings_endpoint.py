"""Tests for POST /api/v1/content/backfill-embeddings endpoint (T-BF-2 AC-1/2/3/6)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Import router under test — fail-fast with clear message when not implemented
# ---------------------------------------------------------------------------

try:
    from intellisource.api.routers.contents import (
        router as contents_router,
    )
except ImportError:
    contents_router = None  # type: ignore[assignment]

_ROUTER_MISSING = contents_router is None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_CELERY_TASK_ID = "b1e2a3d4-c5f6-7890-abcd-ef1234567890"


def _make_mock_celery(task_id: str = FAKE_CELERY_TASK_ID) -> MagicMock:
    """Return a mock Celery app whose send_task returns an AsyncResult-like object."""
    mock_async_result = MagicMock()
    mock_async_result.id = task_id
    mock_celery = MagicMock()
    mock_celery.send_task = MagicMock(return_value=mock_async_result)
    return mock_celery


def _make_backfill_app(celery_task_id: str = FAKE_CELERY_TASK_ID) -> FastAPI:
    """Build a minimal FastAPI app with contents router + celery_app in app.state."""
    if _ROUTER_MISSING:
        pytest.fail(
            "intellisource.api.routers.contents not implemented: "
            "cannot import 'router'. "
            "POST /api/v1/content/backfill-embeddings endpoint does not exist."
        )
    application = FastAPI()
    application.include_router(contents_router, prefix="/api/v1")
    application.state.celery_app = _make_mock_celery(celery_task_id)
    return application


# ---------------------------------------------------------------------------
# AC-1: Route is truly registered — TestClient reaches it (non-404)
# ---------------------------------------------------------------------------


class TestRouteRegistered:
    """AC-1 [生产路径 AC]: The route must be registered in the production router."""

    @pytest.mark.asyncio
    async def test_post_backfill_embeddings_is_not_404(self) -> None:
        """POST /api/v1/content/backfill-embeddings resolves to a real handler."""
        app = _make_backfill_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/content/backfill-embeddings",
                json={},
            )
        # Any status other than 404 proves the route is registered.
        assert resp.status_code != 404, (
            "Route returned 404 — "
            "'POST /api/v1/content/backfill-embeddings' is not "
            "registered in intellisource.api.routers.contents "
            f"(status={resp.status_code})"
        )

    @pytest.mark.asyncio
    async def test_post_backfill_route_in_openapi_paths(self) -> None:
        """POST /api/v1/content/backfill-embeddings in the OpenAPI path listing."""
        app = _make_backfill_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        paths = resp.json().get("paths", {})
        assert "/api/v1/content/backfill-embeddings" in paths, (
            "POST /api/v1/content/backfill-embeddings is not present in "
            "OpenAPI paths. The route must be registered in the production router."
        )


# ---------------------------------------------------------------------------
# AC-2: HTTP 202 + response body shape {status, task_id}
# ---------------------------------------------------------------------------


class TestBackfillResponseShape:
    """AC-2: Successful call returns 202, status=='accepted', task_id non-empty."""

    @pytest.mark.asyncio
    async def test_returns_202(self) -> None:
        """POST returns HTTP 202 Accepted."""
        app = _make_backfill_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/content/backfill-embeddings",
                json={},
            )
        assert resp.status_code == 202, (
            f"Expected 202 Accepted, got {resp.status_code}. Body: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_response_body_has_status_accepted(self) -> None:
        """Response body contains status == 'accepted'."""
        app = _make_backfill_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/content/backfill-embeddings",
                json={},
            )
        body = resp.json()
        assert body.get("status") == "accepted", (
            f"Expected body['status'] == 'accepted', "
            f"got {body.get('status')!r}. Full body: {body}"
        )

    @pytest.mark.asyncio
    async def test_response_body_has_nonempty_task_id(self) -> None:
        """Response body contains a non-empty task_id string."""
        app = _make_backfill_app(celery_task_id=FAKE_CELERY_TASK_ID)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/content/backfill-embeddings",
                json={},
            )
        body = resp.json()
        task_id = body.get("task_id")
        assert isinstance(task_id, str) and len(task_id) > 0, (
            "Expected body['task_id'] to be a non-empty string, "
            f"got {task_id!r}. Full body: {body}"
        )


# ---------------------------------------------------------------------------
# AC-3: Celery enqueue — send_task called with "backfill_embeddings";
#        response task_id == mock AsyncResult.id
# ---------------------------------------------------------------------------


class TestCeleryEnqueue:
    """AC-3: Endpoint enqueues 'backfill_embeddings' via app.state.celery_app."""

    @pytest.mark.asyncio
    async def test_send_task_called_once(self) -> None:
        """send_task is called exactly once per request."""
        app = _make_backfill_app()
        mock_celery = app.state.celery_app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post("/api/v1/content/backfill-embeddings", json={})
        assert mock_celery.send_task.call_count == 1, (
            "Expected send_task to be called once, "
            f"got {mock_celery.send_task.call_count}. "
            "Endpoint must use app.state.celery_app.send_task."
        )

    @pytest.mark.asyncio
    async def test_send_task_first_arg_is_backfill_embeddings(self) -> None:
        """send_task positional arg[0] is exactly 'backfill_embeddings'."""
        app = _make_backfill_app()
        mock_celery = app.state.celery_app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post("/api/v1/content/backfill-embeddings", json={})
        call_args = mock_celery.send_task.call_args
        task_name = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("name")
        )
        assert task_name == "backfill_embeddings", (
            "Expected send_task first arg == 'backfill_embeddings', "
            f"got {task_name!r}. "
            "AC-3 contract: task name literal must be 'backfill_embeddings'."
        )

    @pytest.mark.asyncio
    async def test_response_task_id_equals_mock_async_result_id(self) -> None:
        """Response body task_id equals the .id attribute of the mock AsyncResult."""
        sentinel_id = "deadbeef-dead-beef-dead-beefdeadbeef"
        app = _make_backfill_app(celery_task_id=sentinel_id)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/v1/content/backfill-embeddings", json={})
        body = resp.json()
        assert body.get("task_id") == sentinel_id, (
            f"Expected body['task_id'] == {sentinel_id!r} (mock AsyncResult.id), "
            f"got {body.get('task_id')!r}. "
            "Endpoint must return the .id of the Celery AsyncResult from send_task."
        )

    @pytest.mark.asyncio
    async def test_celery_injected_via_app_state_not_module_import(self) -> None:
        """Replacing app.state.celery_app at request time is the instance invoked.

        Verifies the endpoint uses getattr(request.app.state, 'celery_app') rather
        than a bare module-level import of celery_app.
        """
        app = _make_backfill_app()
        different_sentinel = "cafecafe-cafe-cafe-cafe-cafecafecafe"
        replacement_mock = _make_mock_celery(different_sentinel)
        app.state.celery_app = replacement_mock

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/v1/content/backfill-embeddings", json={})

        body = resp.json()
        assert replacement_mock.send_task.call_count == 1, (
            "Endpoint did not use the injected app.state.celery_app. "
            "It must call getattr(request.app.state, 'celery_app') at request time."
        )
        assert body.get("task_id") == different_sentinel, (
            f"task_id should come from the replaced mock, got {body.get('task_id')!r}"
        )


# ---------------------------------------------------------------------------
# AC-6: BackfillEmbeddingsResponse schema — response_model enforces status+task_id
# ---------------------------------------------------------------------------


class TestBackfillEmbeddingsResponseSchema:
    """AC-6: BackfillEmbeddingsResponse has status: str + task_id: str fields."""

    def test_schema_importable_with_correct_fields(self) -> None:
        """BackfillEmbeddingsResponse can be imported and has status + task_id."""
        schema_cls = None
        import_errors: list[str] = []

        try:
            from intellisource.api.schemas.contents import (  # type: ignore[import-untyped]
                BackfillEmbeddingsResponse,
            )

            schema_cls = BackfillEmbeddingsResponse
        except ImportError as e:
            import_errors.append(f"schemas.contents: {e}")

        if schema_cls is None:
            try:
                from intellisource.api.schemas import (  # type: ignore[import-untyped]
                    BackfillEmbeddingsResponse,
                )

                schema_cls = BackfillEmbeddingsResponse
            except ImportError as e:
                import_errors.append(f"api.schemas: {e}")

        assert schema_cls is not None, (
            "BackfillEmbeddingsResponse not found. Tried: " + "; ".join(import_errors)
        )

        instance = schema_cls(status="accepted", task_id="some-task-id-123")
        assert instance.status == "accepted", (
            "BackfillEmbeddingsResponse.status should be 'accepted', "
            f"got {instance.status!r}"
        )
        assert instance.task_id == "some-task-id-123", (
            "BackfillEmbeddingsResponse.task_id should be 'some-task-id-123', "
            f"got {instance.task_id!r}"
        )

    @pytest.mark.asyncio
    async def test_response_model_enforced_by_fastapi(self) -> None:
        """FastAPI validates the response against BackfillEmbeddingsResponse.

        Both fields must be present as strings in the serialized response.
        """
        app = _make_backfill_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/v1/content/backfill-embeddings", json={})
        assert resp.status_code == 202
        body = resp.json()
        assert isinstance(body.get("status"), str), (
            "body['status'] must be a str, "
            f"got {type(body.get('status'))}: {body.get('status')!r}"
        )
        assert isinstance(body.get("task_id"), str), (
            "body['task_id'] must be a str, "
            f"got {type(body.get('task_id'))}: {body.get('task_id')!r}"
        )


# ---------------------------------------------------------------------------
# R-002: BrokerUnavailableError -> HTTP 503 (not 500)
# ---------------------------------------------------------------------------


class TestBrokerUnavailable503:
    """R-002: BrokerUnavailableError from send_task must map to HTTP 503."""

    @pytest.mark.asyncio
    async def test_broker_unavailable_returns_503(self) -> None:
        """BrokerUnavailableError must map to HTTP 503, not 500."""
        from intellisource.scheduler.dispatch import BrokerUnavailableError

        app = _make_backfill_app()
        with patch(
            "intellisource.api.routers.contents.send_task_with_trace",
            side_effect=BrokerUnavailableError("connection refused"),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/content/backfill-embeddings",
                    json={},
                )
        assert resp.status_code == 503, (
            f"Expected 503 when broker unavailable, got {resp.status_code}. "
            "Endpoint must catch BrokerUnavailableError and return HTTPException(503)."
        )

    @pytest.mark.asyncio
    async def test_broker_unavailable_detail_contains_broker(self) -> None:
        """503 response body detail must contain useful error context."""
        from intellisource.scheduler.dispatch import BrokerUnavailableError

        app = _make_backfill_app()
        with patch(
            "intellisource.api.routers.contents.send_task_with_trace",
            side_effect=BrokerUnavailableError("connection refused"),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/content/backfill-embeddings",
                    json={},
                )
        assert resp.status_code == 503
        detail = resp.json().get("detail", "")
        assert "broker" in detail.lower(), (
            f"503 detail should mention 'broker', got: {detail!r}"
        )
