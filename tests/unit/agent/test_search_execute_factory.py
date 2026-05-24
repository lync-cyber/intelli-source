"""Unit tests for _search_execute factory wiring (E-02/E-04)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.agent.deps import ToolDeps
from intellisource.agent.tools import _search_execute
from intellisource.search.hybrid import SearchResponse


@asynccontextmanager
async def _session_cm() -> Any:
    session = MagicMock(name="db_session")
    yield session


class TestSearchExecuteFactoryWiring:
    @pytest.mark.asyncio
    async def test_search_execute_uses_factory_with_session(self) -> None:
        mock_engine = AsyncMock()
        mock_engine.search = AsyncMock(
            return_value=SearchResponse(items=[], total=0, query_time_ms=3)
        )
        mock_factory = MagicMock(return_value=mock_engine)
        session_factory = MagicMock(return_value=_session_cm())

        deps = ToolDeps(
            session_factory=session_factory,
            llm_gateway=None,
            pipeline_engine=None,
            search_engine_factory=mock_factory,
            collector_registry=None,
            distributor=None,
        )

        result = await _search_execute(query="vector db", top_k=7, tool_deps=deps)

        session_factory.assert_called_once()
        mock_factory.assert_called_once()
        mock_engine.search.assert_awaited_once()
        assert mock_engine.search.await_args.kwargs["query"] == "vector db"
        assert mock_engine.search.await_args.kwargs["limit"] == 7
        assert result["status"] == "ok"
        assert result["tool"] == "search"
        assert isinstance(result["response"], dict)
        assert result["response"]["items"] == []
