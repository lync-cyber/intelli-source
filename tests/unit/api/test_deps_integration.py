"""Tests for T-072 AC-T072-2 and AC-T072-3: get_db_session DI wiring and
router migration away from local get_session stubs.

RED phase — all tests in this file are expected to FAIL until the
implementation is complete.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Depends, Request
from fastapi.routing import APIRoute


# ---------------------------------------------------------------------------
# AC-T072-2: get_db_session() yields a real session from app.state.db
# ---------------------------------------------------------------------------


class TestGetDbSessionYieldsRealSession:
    """get_db_session() must delegate to request.app.state.db.get_session()."""

    @pytest.mark.asyncio
    async def test_get_db_session_accepts_request_parameter(self) -> None:
        """AC-T072-2: get_db_session() accepts a Request parameter (not zero-arg)."""
        import inspect
        from intellisource.api.deps import get_db_session

        sig = inspect.signature(get_db_session)
        params = list(sig.parameters.keys())
        assert "request" in params, (
            "get_db_session must accept a 'request' parameter to access app.state.db; "
            f"current parameters: {params}"
        )

    @pytest.mark.asyncio
    async def test_get_db_session_yields_session_from_state_db(self) -> None:
        """AC-T072-2: get_db_session() yields the session from request.app.state.db.get_session()."""
        from intellisource.api.deps import get_db_session
        from intellisource.storage.database import DatabaseManager

        sentinel_session = MagicMock(name="async_session")

        @asynccontextmanager
        async def _fake_get_session() -> AsyncIterator[Any]:
            yield sentinel_session

        mock_db = MagicMock(spec=DatabaseManager)
        mock_db.get_session = _fake_get_session

        mock_app = MagicMock()
        mock_app.state.db = mock_db

        mock_request = MagicMock(spec=Request)
        mock_request.app = mock_app

        gen = get_db_session(mock_request)
        yielded = await gen.__anext__()

        assert yielded is sentinel_session, (
            f"get_db_session() must yield the session from app.state.db.get_session(); "
            f"got {yielded!r} instead"
        )

    @pytest.mark.asyncio
    async def test_get_db_session_does_not_yield_none(self) -> None:
        """AC-T072-2: get_db_session() must not yield None (old placeholder behaviour)."""
        from intellisource.api.deps import get_db_session
        from intellisource.storage.database import DatabaseManager

        real_session = MagicMock(name="real_async_session")

        @asynccontextmanager
        async def _fake_get_session() -> AsyncIterator[Any]:
            yield real_session

        mock_db = MagicMock(spec=DatabaseManager)
        mock_db.get_session = _fake_get_session

        mock_app = MagicMock()
        mock_app.state.db = mock_db

        mock_request = MagicMock(spec=Request)
        mock_request.app = mock_app

        gen = get_db_session(mock_request)
        yielded = await gen.__anext__()

        assert yielded is not None, (
            "get_db_session() must yield a real AsyncSession, not None"
        )


# ---------------------------------------------------------------------------
# AC-T072-3: 5 router modules no longer define a local get_session
# ---------------------------------------------------------------------------


class TestRoutersNoLocalGetSession:
    """sources/contents/tasks/subscriptions/search must not define local get_session."""

    def test_sources_router_has_no_local_get_session(self) -> None:
        """AC-T072-3: intellisource.api.routers.sources defines no local get_session."""
        from intellisource.api.routers import sources
        assert not hasattr(sources, "get_session"), (
            "sources.py must not define a local get_session; "
            "use Depends(get_db_session) from intellisource.api.deps instead"
        )

    def test_contents_router_has_no_local_get_session(self) -> None:
        """AC-T072-3: intellisource.api.routers.contents defines no local get_session."""
        from intellisource.api.routers import contents
        assert not hasattr(contents, "get_session"), (
            "contents.py must not define a local get_session"
        )

    def test_tasks_router_has_no_local_get_session(self) -> None:
        """AC-T072-3: intellisource.api.routers.tasks defines no local get_session."""
        from intellisource.api.routers import tasks
        assert not hasattr(tasks, "get_session"), (
            "tasks.py must not define a local get_session"
        )

    def test_subscriptions_router_has_no_local_get_session(self) -> None:
        """AC-T072-3: intellisource.api.routers.subscriptions defines no local get_session."""
        from intellisource.api.routers import subscriptions
        assert not hasattr(subscriptions, "get_session"), (
            "subscriptions.py must not define a local get_session"
        )

    def test_search_router_has_no_local_get_session(self) -> None:
        """AC-T072-3: intellisource.api.routers.search defines no local get_session."""
        from intellisource.api.routers import search
        assert not hasattr(search, "get_session"), (
            "search.py must not define a local get_session"
        )


# ---------------------------------------------------------------------------
# AC-T072-3: All 6 routers reference get_db_session from api.deps
# ---------------------------------------------------------------------------


def _collect_depends_callables(router: Any) -> list[Any]:
    """Walk all routes in an APIRouter and collect Depends callables."""
    callables: list[Any] = []
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        # FastAPI stores the dependency list in route.dependant.dependencies
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for dep in dependant.dependencies:
            callables.append(dep.call)
    return callables


class TestRoutersUseDepsGetDbSession:
    """All 6 routers must wire Depends(get_db_session) from api.deps."""

    def test_sources_router_uses_deps_get_db_session(self) -> None:
        """AC-T072-3: sources router uses intellisource.api.deps.get_db_session."""
        from intellisource.api.deps import get_db_session
        from intellisource.api.routers.sources import router

        dep_callables = _collect_depends_callables(router)
        assert get_db_session in dep_callables, (
            "sources router must reference api.deps.get_db_session via Depends; "
            f"found callables: {dep_callables}"
        )

    def test_contents_router_uses_deps_get_db_session(self) -> None:
        """AC-T072-3: contents router uses intellisource.api.deps.get_db_session."""
        from intellisource.api.deps import get_db_session
        from intellisource.api.routers.contents import router

        dep_callables = _collect_depends_callables(router)
        assert get_db_session in dep_callables, (
            "contents router must reference api.deps.get_db_session via Depends"
        )

    def test_tasks_router_uses_deps_get_db_session(self) -> None:
        """AC-T072-3: tasks router uses intellisource.api.deps.get_db_session."""
        from intellisource.api.deps import get_db_session
        from intellisource.api.routers.tasks import router

        dep_callables = _collect_depends_callables(router)
        assert get_db_session in dep_callables, (
            "tasks router must reference api.deps.get_db_session via Depends"
        )

    def test_subscriptions_router_uses_deps_get_db_session(self) -> None:
        """AC-T072-3: subscriptions router uses intellisource.api.deps.get_db_session."""
        from intellisource.api.deps import get_db_session
        from intellisource.api.routers.subscriptions import router

        dep_callables = _collect_depends_callables(router)
        assert get_db_session in dep_callables, (
            "subscriptions router must reference api.deps.get_db_session via Depends"
        )

    def test_search_router_uses_deps_get_db_session(self) -> None:
        """AC-T072-3: search router uses intellisource.api.deps.get_db_session."""
        from intellisource.api.deps import get_db_session
        from intellisource.api.routers.search import router

        dep_callables = _collect_depends_callables(router)
        assert get_db_session in dep_callables, (
            "search router must reference api.deps.get_db_session via Depends"
        )

    def test_llm_router_uses_deps_get_db_session(self) -> None:
        """AC-T072-3: llm router (reference shape) uses intellisource.api.deps.get_db_session."""
        from intellisource.api.deps import get_db_session
        from intellisource.api.routers.llm import router

        dep_callables = _collect_depends_callables(router)
        assert get_db_session in dep_callables, (
            "llm router must reference api.deps.get_db_session via Depends"
        )
