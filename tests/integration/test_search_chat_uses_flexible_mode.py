"""Integration tests for /search/chat via AgentRunner.run_flexible (AC-1/3/4).

AC-1: HybridSearchEngine.chat() method must not exist after deletion of echo stub.
AC-3: /search/chat endpoint uses app.state.agent_runner + run_flexible(); 503 if unset.
AC-4: POST /search/chat with mock AgentRunner returns steps_executed>=2 + answer!=msg.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# AC-1: HybridSearchEngine must NOT have a .chat() method
# ---------------------------------------------------------------------------


class TestHybridSearchEngineChatRemoved:
    """AC-1: The echo-stub chat() method must be deleted from HybridSearchEngine."""

    def test_hybrid_search_engine_has_no_chat_method(self) -> None:
        """HybridSearchEngine should not expose a .chat() method after AC-1 removal."""
        from intellisource.search.hybrid import HybridSearchEngine

        assert not hasattr(HybridSearchEngine, "chat"), (
            "HybridSearchEngine.chat() echo stub must be removed (AC-1). "
            "The /search/chat route should route through AgentRunner.run_flexible."
        )


# ---------------------------------------------------------------------------
# Helpers for AC-3 / AC-4
# ---------------------------------------------------------------------------


def _make_mock_agent_runner(
    steps_executed: int = 2,
    answer: str = "RAG 论文综述：近期研究重点是检索增强生成效率提升。",
) -> MagicMock:
    """Return a mock AgentRunner whose run_flexible returns a realistic payload."""
    runner = MagicMock()
    runner.run_flexible = AsyncMock(
        return_value={
            "status": "success",
            "steps_executed": steps_executed,
            "results": [
                {
                    "tool": "search",
                    "output": {
                        "response": {
                            "items": [{"title": "RAG Survey 2024"}],
                        }
                    },
                },
                {
                    "tool": "summarize_for_user",
                    "output": {"summary": answer},
                },
            ],
            "pipeline_name": "instant-search",
            "task_chain_id": "tc-test-001",
        }
    )
    return runner


def _make_search_chat_app(agent_runner: Any = None) -> FastAPI:
    """Build a minimal FastAPI app with /search/chat wired to the new impl."""
    from intellisource.api.routers.search import (
        router as search_router,
    )

    app = FastAPI()
    app.include_router(search_router, prefix="/api/v1")
    if agent_runner is not None:
        app.state.agent_runner = agent_runner
    return app


# ---------------------------------------------------------------------------
# AC-3: /search/chat uses app.state.agent_runner; 503 when missing
# ---------------------------------------------------------------------------


class TestSearchChatEndpointUsesAgentRunner:
    """AC-3: The /search/chat endpoint must delegate to app.state.agent_runner."""

    async def test_returns_503_when_agent_runner_not_initialized(self) -> None:
        """POST /search/chat returns 503 when app.state.agent_runner is not set."""
        app = _make_search_chat_app(agent_runner=None)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/search/chat",
                json={"message": "找最近的 RAG 论文并总结"},
            )

        assert resp.status_code == 503, (
            f"Expected 503 when agent_runner unset, got {resp.status_code}. "
            "Router must check app.state.agent_runner and return 503 if absent."
        )

    async def test_agent_runner_run_flexible_is_called(self) -> None:
        """run_flexible() on app.state.agent_runner is called for POST /search/chat."""
        mock_runner = _make_mock_agent_runner()
        app = _make_search_chat_app(agent_runner=mock_runner)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/search/chat",
                json={"message": "找最近的 RAG 论文并总结"},
            )

        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )
        mock_runner.run_flexible.assert_awaited_once()

    async def test_user_message_forwarded_to_run_flexible(self) -> None:
        """The user message from the request body reaches run_flexible kwarg."""
        mock_runner = _make_mock_agent_runner()
        app = _make_search_chat_app(agent_runner=mock_runner)

        user_msg = "找最近的 RAG 论文并总结"
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/v1/search/chat",
                json={"message": user_msg},
            )

        call_kwargs = mock_runner.run_flexible.call_args
        # user_message should be passed either as positional or keyword arg
        all_args = str(call_kwargs)
        assert user_msg in all_args, (
            f"user_message '{user_msg}' not found in run_flexible call args: {all_args}"
        )


# ---------------------------------------------------------------------------
# AC-4: steps_executed >= 2 + answer != body.message
# ---------------------------------------------------------------------------


class TestSearchChatResponseShape:
    """AC-4: /search/chat response carries steps_executed>=2 + non-echo answer."""

    async def test_response_steps_executed_at_least_two(self) -> None:
        """Response body steps_executed >= 2 for a real agent loop."""
        mock_runner = _make_mock_agent_runner(steps_executed=2)
        app = _make_search_chat_app(agent_runner=mock_runner)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/search/chat",
                json={"message": "找最近的 RAG 论文并总结"},
            )

        assert resp.status_code == 200
        body = resp.json()
        steps = body.get("steps_executed", 0)
        assert steps >= 2, (
            f"steps_executed must be >= 2, got {steps}. "
            "Agent should execute at least search + summarize steps."
        )

    async def test_response_answer_differs_from_input_message(self) -> None:
        """Response answer must not echo the user's input message back unchanged."""
        user_message = "找最近的 RAG 论文并总结"
        mock_runner = _make_mock_agent_runner(
            answer="RAG 论文综述：近期研究重点是检索增强生成效率提升。"
        )
        app = _make_search_chat_app(agent_runner=mock_runner)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/search/chat",
                json={"message": user_message},
            )

        assert resp.status_code == 200
        body = resp.json()
        answer = body.get("answer", "")
        assert answer != user_message, (
            "answer must not be an echo of the input message. "
            "The route must use AgentRunner.run_flexible, not HybridSearchEngine.chat."
        )
        assert answer, "answer must not be empty"

    async def test_response_contains_task_chain_id(self) -> None:
        """Response body includes task_chain_id from AgentRunner result."""
        mock_runner = _make_mock_agent_runner()
        app = _make_search_chat_app(agent_runner=mock_runner)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/search/chat",
                json={"message": "test query"},
            )

        body = resp.json()
        assert "task_chain_id" in body, (
            "Response must include task_chain_id from the AgentRunner persist result."
        )

    async def test_pipeline_config_instant_search_loaded(self) -> None:
        """The router loads 'instant-search' pipeline config before run_flexible."""
        mock_runner = _make_mock_agent_runner()
        app = _make_search_chat_app(agent_runner=mock_runner)

        # Spy on load_pipeline_config to confirm it's called with "instant-search"
        with patch(
            "intellisource.api.routers.search.load_pipeline_config",
            return_value=MagicMock(name="instant-search", mode="flexible"),
        ) as mock_load:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post(
                    "/api/v1/search/chat",
                    json={"message": "test"},
                )

        mock_load.assert_called_once_with("instant-search")
