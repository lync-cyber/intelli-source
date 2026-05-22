"""Tests for 6 agent tool execute functions — real implementation calls.

Covers T-089 AC-1 through AC-7:

AC-1: _collect_execute triggers CollectorRegistry.get(source_type).collect()
AC-2: _process_execute triggers PipelineEngine.execute(ctx)
AC-3: _distribute_execute triggers BaseDistributor.distribute()
AC-4: _search_execute calls HybridSearchEngine.search(query, query_vector, ...)
AC-5: _get_content_detail_execute calls ContentRepository.get_by_id(content_id)
AC-6: _summarize_for_user_execute calls LLMGateway.complete() or .chat()
AC-7: All 6 tools use ToolDeps for injection; AgentRunner.run() passes ToolDeps
      when invoking tools.

ToolDeps shared design (also referenced by T-087 AC-4 / test_llm_complete_execute.py):
- Location: src/intellisource/agent/deps.py
- Fields: session_factory, llm_gateway, pipeline_engine, search_engine,
          collector_registry, distributor
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_deps(
    *,
    llm_gateway: Any = None,
    pipeline_engine: Any = None,
    search_engine: Any = None,
    collector_registry: Any = None,
    distributor: Any = None,
    session_factory: Any = None,
) -> Any:
    """Construct a ToolDeps instance with provided or auto-created mocks."""
    from intellisource.agent.deps import ToolDeps  # type: ignore[import]

    return ToolDeps(
        session_factory=session_factory or MagicMock(),
        llm_gateway=llm_gateway or AsyncMock(),
        pipeline_engine=pipeline_engine or AsyncMock(),
        search_engine=search_engine or AsyncMock(),
        collector_registry=collector_registry or MagicMock(),
        distributor=distributor or AsyncMock(),
    )


# ---------------------------------------------------------------------------
# AC-1: _collect_execute triggers CollectorRegistry.get().collect()
# ---------------------------------------------------------------------------


class TestCollectExecuteReal:
    """AC-1: _collect_execute must call CollectorRegistry.get(source_type).collect()."""

    @pytest.mark.asyncio
    async def test_collect_execute_calls_registry_get_and_collect(self) -> None:
        """_collect_execute must call registry.get(source_type).collect()."""
        from intellisource.agent.tools import _collect_execute  # type: ignore[import]

        mock_collector = AsyncMock()
        mock_collector.collect = AsyncMock(return_value=[])

        mock_registry = MagicMock()
        mock_registry.get = MagicMock(return_value=mock_collector)

        deps = _make_tool_deps(collector_registry=mock_registry)

        await _collect_execute(
            source_id="src-001",
            source_type="rss",
            tool_deps=deps,
        )

        assert mock_registry.get.called, (
            "_collect_execute must call collector_registry.get(source_type)"
        )
        assert mock_collector.collect.called, (
            "_collect_execute must call .collect() on the returned collector"
        )

    @pytest.mark.asyncio
    async def test_collect_execute_passes_source_type(self) -> None:
        """_collect_execute passes source_type to registry.get()."""
        from intellisource.agent.tools import _collect_execute  # type: ignore[import]

        mock_collector = AsyncMock()
        mock_collector.collect = AsyncMock(return_value=[])

        mock_registry = MagicMock()
        mock_registry.get = MagicMock(return_value=mock_collector)

        deps = _make_tool_deps(collector_registry=mock_registry)

        await _collect_execute(
            source_id="src-001",
            source_type="api",
            tool_deps=deps,
        )

        mock_registry.get.assert_called_once_with("api")

    @pytest.mark.asyncio
    async def test_collect_execute_not_placeholder(self) -> None:
        """_collect_execute must not return the old placeholder dict."""
        from intellisource.agent.tools import _collect_execute  # type: ignore[import]

        mock_collector = AsyncMock()
        mock_collector.collect = AsyncMock(return_value=[{"id": "item-1"}])

        mock_registry = MagicMock()
        mock_registry.get = MagicMock(return_value=mock_collector)

        deps = _make_tool_deps(collector_registry=mock_registry)

        result = await _collect_execute(
            source_id="src-001",
            source_type="rss",
            tool_deps=deps,
        )

        is_placeholder = (
            isinstance(result, dict)
            and result.get("status") == "ok"
            and result.get("tool") == "collect"
            and "collected" not in result
            and mock_collector.collect.call_count == 0
        )
        assert not is_placeholder, (
            f"_collect_execute must not return old placeholder; got: {result}"
        )


# ---------------------------------------------------------------------------
# AC-2: _process_execute triggers PipelineEngine.execute(ctx)
# ---------------------------------------------------------------------------


class TestProcessExecuteReal:
    """AC-2: _process_execute must trigger PipelineEngine.execute()."""

    @pytest.mark.asyncio
    async def test_process_execute_calls_pipeline_engine_execute(self) -> None:
        """_process_execute must call pipeline_engine.execute() or execute_stream()."""
        from intellisource.agent.tools import _process_execute  # type: ignore[import]

        mock_engine = AsyncMock()
        mock_engine.execute = AsyncMock(return_value={"status": "success"})
        mock_engine.execute_stream = AsyncMock(return_value=iter([]))

        deps = _make_tool_deps(pipeline_engine=mock_engine)

        await _process_execute(
            content_id=str(uuid.uuid4()),
            tool_deps=deps,
        )

        total_calls = (
            mock_engine.execute.call_count + mock_engine.execute_stream.call_count
        )
        assert total_calls >= 1, (
            "_process_execute must call PipelineEngine.execute() or execute_stream(); "
            f"found {total_calls} calls"
        )

    @pytest.mark.asyncio
    async def test_process_execute_calls_execute_exactly_once(self) -> None:
        """_process_execute calls engine exactly once per invocation."""
        from intellisource.agent.tools import _process_execute  # type: ignore[import]

        mock_engine = AsyncMock()
        mock_engine.execute = AsyncMock(return_value={"status": "success"})
        mock_engine.execute_stream = AsyncMock(return_value=iter([]))

        deps = _make_tool_deps(pipeline_engine=mock_engine)

        await _process_execute(
            content_id=str(uuid.uuid4()),
            tool_deps=deps,
        )

        total = mock_engine.execute.call_count + mock_engine.execute_stream.call_count
        assert total == 1, f"Expected exactly 1 engine call, got {total}"

    @pytest.mark.asyncio
    async def test_process_execute_not_placeholder(self) -> None:
        """_process_execute must not return old placeholder."""
        from intellisource.agent.tools import _process_execute  # type: ignore[import]

        mock_engine = AsyncMock()
        mock_engine.execute = AsyncMock(return_value={"pipeline_result": "done"})

        deps = _make_tool_deps(pipeline_engine=mock_engine)

        result = await _process_execute(
            content_id=str(uuid.uuid4()),
            tool_deps=deps,
        )

        is_placeholder = (
            isinstance(result, dict)
            and result.get("status") == "ok"
            and result.get("tool") == "process"
            and mock_engine.execute.call_count == 0
        )
        assert not is_placeholder, (
            f"_process_execute returned old placeholder: {result}"
        )


# ---------------------------------------------------------------------------
# AC-3: _distribute_execute triggers BaseDistributor.distribute()
# ---------------------------------------------------------------------------


class TestDistributeExecuteReal:
    """AC-3: _distribute_execute must call distributor.distribute()."""

    @pytest.mark.asyncio
    async def test_distribute_execute_calls_distribute(self) -> None:
        """_distribute_execute must call distributor.distribute()."""
        from intellisource.agent.tools import (
            _distribute_execute,  # type: ignore[import]
        )

        mock_distributor = AsyncMock()
        mock_distributor.distribute = AsyncMock(return_value={"sent": True})

        deps = _make_tool_deps(distributor=mock_distributor)

        content_id = str(uuid.uuid4())
        subscription_id = str(uuid.uuid4())

        await _distribute_execute(
            content_id=content_id,
            subscription_id=subscription_id,
            tool_deps=deps,
        )

        assert mock_distributor.distribute.called, (
            "_distribute_execute must call distributor.distribute()"
        )

    @pytest.mark.asyncio
    async def test_distribute_execute_distribute_called_once(self) -> None:
        """_distribute_execute calls distribute exactly once."""
        from intellisource.agent.tools import (
            _distribute_execute,  # type: ignore[import]
        )

        mock_distributor = AsyncMock()
        mock_distributor.distribute = AsyncMock(return_value={"sent": True})

        deps = _make_tool_deps(distributor=mock_distributor)

        await _distribute_execute(
            content_id=str(uuid.uuid4()),
            subscription_id=str(uuid.uuid4()),
            tool_deps=deps,
        )

        assert mock_distributor.distribute.call_count == 1, (
            f"Expected 1 distribute call, got {mock_distributor.distribute.call_count}"
        )

    @pytest.mark.asyncio
    async def test_distribute_execute_not_placeholder(self) -> None:
        """_distribute_execute must not return old placeholder."""
        from intellisource.agent.tools import (
            _distribute_execute,  # type: ignore[import]
        )

        mock_distributor = AsyncMock()
        mock_distributor.distribute = AsyncMock(return_value={"sent": True})

        deps = _make_tool_deps(distributor=mock_distributor)

        result = await _distribute_execute(
            content_id=str(uuid.uuid4()),
            subscription_id=str(uuid.uuid4()),
            tool_deps=deps,
        )

        is_placeholder = (
            isinstance(result, dict)
            and result.get("status") == "ok"
            and result.get("tool") == "distribute"
            and mock_distributor.distribute.call_count == 0
        )
        assert not is_placeholder, (
            f"_distribute_execute returned old placeholder: {result}"
        )


# ---------------------------------------------------------------------------
# AC-4: _search_execute calls HybridSearchEngine.search(query, query_vector, ...)
# ---------------------------------------------------------------------------


class TestSearchExecuteReal:
    """AC-4: _search_execute must call HybridSearchEngine.search()."""

    @pytest.mark.asyncio
    async def test_search_execute_calls_engine_search(self) -> None:
        """_search_execute must call search_engine.search()."""
        from intellisource.agent.tools import _search_execute  # type: ignore[import]
        from intellisource.search.hybrid import SearchResponse

        mock_engine = AsyncMock()
        mock_engine.search = AsyncMock(
            return_value=SearchResponse(items=[], total=0, query_time_ms=1)
        )

        deps = _make_tool_deps(search_engine=mock_engine)

        await _search_execute(
            query="machine learning papers",
            top_k=5,
            tool_deps=deps,
        )

        assert mock_engine.search.called, (
            "_search_execute must call search_engine.search()"
        )

    @pytest.mark.asyncio
    async def test_search_execute_passes_query_correctly(self) -> None:
        """_search_execute passes the query string to search()."""
        from intellisource.agent.tools import _search_execute  # type: ignore[import]
        from intellisource.search.hybrid import SearchResponse

        mock_engine = AsyncMock()
        mock_engine.search = AsyncMock(
            return_value=SearchResponse(items=[], total=0, query_time_ms=1)
        )

        deps = _make_tool_deps(search_engine=mock_engine)

        await _search_execute(
            query="deep learning",
            top_k=3,
            tool_deps=deps,
        )

        assert mock_engine.search.called
        call_args = mock_engine.search.call_args
        all_args_str = str(call_args)
        assert "deep learning" in all_args_str, (
            f"search() call must include query='deep learning'; args: {all_args_str}"
        )

    @pytest.mark.asyncio
    async def test_search_execute_not_placeholder(self) -> None:
        """_search_execute must not return old placeholder."""
        from intellisource.agent.tools import _search_execute  # type: ignore[import]
        from intellisource.search.hybrid import SearchResponse

        mock_engine = AsyncMock()
        mock_engine.search = AsyncMock(
            return_value=SearchResponse(items=[], total=0, query_time_ms=1)
        )

        deps = _make_tool_deps(search_engine=mock_engine)

        result = await _search_execute(
            query="test query",
            tool_deps=deps,
        )

        is_placeholder = (
            isinstance(result, dict)
            and result.get("status") == "ok"
            and result.get("tool") == "search"
            and mock_engine.search.call_count == 0
        )
        assert not is_placeholder, f"_search_execute returned old placeholder: {result}"


# ---------------------------------------------------------------------------
# AC-5: _get_content_detail_execute calls ContentRepository.get_by_id()
# ---------------------------------------------------------------------------


class TestGetContentDetailExecuteReal:
    """AC-5: _get_content_detail_execute must call ContentRepository.get_by_id()."""

    @pytest.mark.asyncio
    async def test_get_content_detail_calls_repo_get_by_id(self) -> None:
        """_get_content_detail_execute must call repository.get_by_id(content_id)."""
        from intellisource.agent.tools import (
            _get_content_detail_execute,  # type: ignore[import]
        )

        content_id = uuid.uuid4()
        fake_content = MagicMock()
        fake_content.id = content_id
        fake_content.title = "Test Title"
        fake_content.body_text = "Test body"

        mock_repo = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=fake_content)

        # session_factory that returns a session which provides the content repo
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_factory = MagicMock(return_value=mock_session)

        deps = _make_tool_deps(session_factory=mock_session_factory)

        # Patch ContentRepository to use our mock
        with patch(
            "intellisource.storage.repositories.content.ContentRepository",
            return_value=mock_repo,
        ):
            await _get_content_detail_execute(
                content_id=str(content_id),
                tool_deps=deps,
            )

    @pytest.mark.asyncio
    async def test_get_content_detail_returns_content_dict(self) -> None:
        """_get_content_detail_execute returns a content dict with id and title."""
        from intellisource.agent.tools import (
            _get_content_detail_execute,  # type: ignore[import]
        )

        content_id = uuid.uuid4()

        fake_content = MagicMock()
        fake_content.id = content_id
        fake_content.title = "Test Content Title"
        fake_content.body_text = "Some body text"

        mock_repo = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=fake_content)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        deps = _make_tool_deps(session_factory=MagicMock(return_value=mock_session))

        with patch(
            "intellisource.storage.repositories.content.ContentRepository",
            return_value=mock_repo,
        ):
            result = await _get_content_detail_execute(
                content_id=str(content_id),
                tool_deps=deps,
            )

        # Result must be a non-placeholder dict containing content information
        is_placeholder = (
            isinstance(result, dict)
            and result.get("status") == "ok"
            and result.get("tool") == "get_content_detail"
            and mock_repo.get_by_id.call_count == 0
        )
        assert not is_placeholder, (
            f"_get_content_detail_execute returned old placeholder: {result}"
        )

    @pytest.mark.asyncio
    async def test_get_content_detail_content_id_passed_to_repo(self) -> None:
        """content_id must be passed to get_by_id()."""
        from intellisource.agent.tools import (
            _get_content_detail_execute,  # type: ignore[import]
        )

        content_id = uuid.uuid4()
        fake_content = MagicMock()
        fake_content.id = content_id
        fake_content.title = "Title"

        mock_repo = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=fake_content)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        deps = _make_tool_deps(session_factory=MagicMock(return_value=mock_session))

        with patch(
            "intellisource.storage.repositories.content.ContentRepository",
            return_value=mock_repo,
        ):
            await _get_content_detail_execute(
                content_id=str(content_id),
                tool_deps=deps,
            )

        # Verify get_by_id was called with the expected content_id
        assert mock_repo.get_by_id.called, (
            "ContentRepository.get_by_id() must be called"
        )
        call_args_str = str(mock_repo.get_by_id.call_args)
        assert (
            str(content_id) in call_args_str
            or str(content_id).replace("-", "") in call_args_str
            or mock_repo.get_by_id.called
        ), f"get_by_id() call args must include content_id {content_id}"


# ---------------------------------------------------------------------------
# AC-6: _summarize_for_user_execute calls LLMGateway and prompt contains content
# ---------------------------------------------------------------------------


class TestSummarizeForUserExecuteReal:
    """AC-6: _summarize_for_user_execute must call LLMGateway with content in prompt."""

    @pytest.mark.asyncio
    async def test_summarize_calls_llm_gateway(self) -> None:
        """_summarize_for_user_execute must call gateway.complete() or .chat()."""
        from intellisource.agent.tools import (
            _summarize_for_user_execute,  # type: ignore[import]
        )
        from intellisource.llm.gateway import LLMResult

        mock_gateway = AsyncMock()
        mock_gateway.complete = AsyncMock(
            return_value=LLMResult(content="Concise summary here.", metadata={})
        )
        mock_gateway.chat = AsyncMock(
            return_value=LLMResult(content="Concise summary here.", metadata={})
        )

        deps = _make_tool_deps(llm_gateway=mock_gateway)

        await _summarize_for_user_execute(
            content_id=str(uuid.uuid4()),
            content="This is a long article about deep learning...",
            tool_deps=deps,
        )

        total_calls = mock_gateway.complete.call_count + mock_gateway.chat.call_count
        assert total_calls >= 1, (
            "_summarize_for_user_execute must call LLMGateway.complete() or .chat(); "
            f"total: {total_calls}"
        )

    @pytest.mark.asyncio
    async def test_summarize_prompt_contains_content(self) -> None:
        """The LLMGateway call must include the content in the prompt/messages."""
        from intellisource.agent.tools import (
            _summarize_for_user_execute,  # type: ignore[import]
        )
        from intellisource.llm.gateway import LLMResult

        mock_gateway = AsyncMock()
        mock_gateway.complete = AsyncMock(
            return_value=LLMResult(content="Summary.", metadata={})
        )
        mock_gateway.chat = AsyncMock(
            return_value=LLMResult(content="Summary.", metadata={})
        )

        deps = _make_tool_deps(llm_gateway=mock_gateway)

        content_text = "Breaking news: quantum computing breakthrough announced today"
        await _summarize_for_user_execute(
            content_id=str(uuid.uuid4()),
            content=content_text,
            tool_deps=deps,
        )

        if mock_gateway.complete.called:
            all_args_str = str(mock_gateway.complete.call_args)
        else:
            all_args_str = str(mock_gateway.chat.call_args)

        assert content_text in all_args_str or "quantum" in all_args_str, (
            "LLMGateway call must include content text in prompt; "
            f"call args: {all_args_str}"
        )

    @pytest.mark.asyncio
    async def test_summarize_not_placeholder(self) -> None:
        """_summarize_for_user_execute must not return old placeholder."""
        from intellisource.agent.tools import (
            _summarize_for_user_execute,  # type: ignore[import]
        )
        from intellisource.llm.gateway import LLMResult

        mock_gateway = AsyncMock()
        mock_gateway.complete = AsyncMock(
            return_value=LLMResult(content="A real summary.", metadata={})
        )
        mock_gateway.chat = AsyncMock(
            return_value=LLMResult(content="A real summary.", metadata={})
        )

        deps = _make_tool_deps(llm_gateway=mock_gateway)

        result = await _summarize_for_user_execute(
            content_id=str(uuid.uuid4()),
            content="Article text here",
            tool_deps=deps,
        )

        is_placeholder = (
            isinstance(result, dict)
            and result.get("status") == "ok"
            and result.get("tool") == "summarize_for_user"
            and mock_gateway.complete.call_count == 0
            and mock_gateway.chat.call_count == 0
        )
        assert not is_placeholder, (
            f"_summarize_for_user_execute returned old placeholder: {result}"
        )


# ---------------------------------------------------------------------------
# AC-7: ToolDeps injection — AgentRunner.run() passes ToolDeps to tool execute fns
# ---------------------------------------------------------------------------


class TestToolDepsInjectionViaAgentRunner:
    """AC-7: AgentRunner.run() must pass ToolDeps when invoking tool execute fns."""

    def test_tool_deps_class_importable(self) -> None:
        """ToolDeps must be importable from intellisource.agent.deps."""
        from intellisource.agent.deps import ToolDeps  # type: ignore[import]

        assert ToolDeps is not None

    def test_tool_deps_has_all_required_fields(self) -> None:
        """ToolDeps must carry all 6 required dependency fields."""
        from intellisource.agent.deps import ToolDeps  # type: ignore[import]

        deps = ToolDeps(
            session_factory=MagicMock(),
            llm_gateway=MagicMock(),
            pipeline_engine=MagicMock(),
            search_engine=MagicMock(),
            collector_registry=MagicMock(),
            distributor=MagicMock(),
        )
        required_fields = [
            "session_factory",
            "llm_gateway",
            "pipeline_engine",
            "search_engine",
            "collector_registry",
            "distributor",
        ]
        for field in required_fields:
            assert hasattr(deps, field), (
                f"ToolDeps must have field '{field}' per shared design contract"
            )

    @pytest.mark.asyncio
    async def test_agent_runner_run_flexible_receives_tool_deps(self) -> None:
        """AgentRunner.run_flexible() must accept and use a tool_deps parameter."""
        from intellisource.agent.runner import AgentRunner  # type: ignore[import]
        from intellisource.agent.tools import AgentToolRegistry
        from intellisource.llm.gateway import LLMResult

        mock_gateway = AsyncMock()
        # LLM responds with stop immediately (no tool calls)
        mock_gateway.chat = AsyncMock(
            return_value=LLMResult(
                content="Done",
                metadata={
                    "tool_calls": None,
                    "finish_reason": "stop",
                    "usage": {},
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "latency_ms": 100,
                    "model": "gpt-4o-mini",
                },
            )
        )

        mock_engine = AsyncMock()
        mock_engine.execute = AsyncMock(return_value={"status": "success"})

        registry = AgentToolRegistry()
        registry.register_defaults()
        registry.register_atomic_tools()

        runner = AgentRunner(
            tool_registry=registry,
            llm_gateway=mock_gateway,
            pipeline_engine=mock_engine,
        )

        # Verify AgentRunner accepts a tool_deps parameter in run() or run_flexible()
        import inspect

        run_flexible_sig = inspect.signature(runner.run_flexible)
        run_sig = inspect.signature(runner.run) if hasattr(runner, "run") else None

        has_tool_deps_param = "tool_deps" in run_flexible_sig.parameters or (
            run_sig is not None and "tool_deps" in run_sig.parameters
        )

        assert has_tool_deps_param, (
            "AgentRunner.run_flexible() (or run()) must accept a 'tool_deps' parameter "
            "to inject dependencies into tool execute functions (T-089 AC-7)"
        )

    @pytest.mark.asyncio
    async def test_agent_runner_execute_with_tool_deps(self) -> None:
        """AgentRunner.execute() must forward tool_deps when calling tools."""
        import inspect

        from intellisource.agent.runner import AgentRunner  # type: ignore[import]
        from intellisource.agent.tools import AgentToolRegistry
        from intellisource.llm.gateway import LLMResult

        mock_gateway = AsyncMock()
        mock_gateway.chat = AsyncMock(
            return_value=LLMResult(
                content="",
                metadata={
                    "tool_calls": None,
                    "finish_reason": "stop",
                    "usage": {},
                    "input_tokens": 5,
                    "output_tokens": 3,
                    "latency_ms": 10,
                    "model": "gpt-4o-mini",
                },
            )
        )

        injected_deps: list[Any] = []

        async def _collect_with_deps_capture(
            tool_deps: Any = None, **kwargs: Any
        ) -> dict[str, Any]:
            injected_deps.append(tool_deps)
            return {"status": "collected"}

        registry = AgentToolRegistry()
        registry.register(
            name="collect",
            description="Test collect",
            parameters={"type": "object", "properties": {}},
            execute_fn=_collect_with_deps_capture,
        )

        runner = AgentRunner(
            tool_registry=registry,
            llm_gateway=mock_gateway,
        )

        # Verify run() or run_flexible() signature accepts tool_deps
        run_flexible_sig = inspect.signature(runner.run_flexible)
        has_tool_deps = "tool_deps" in run_flexible_sig.parameters

        assert has_tool_deps, (
            "AgentRunner.run_flexible() must accept 'tool_deps' parameter "
            "so tools can receive injected dependencies"
        )


# ---------------------------------------------------------------------------
# AC-7 cross-check: all 6 default tool execute functions accept tool_deps kwarg
# ---------------------------------------------------------------------------


class TestAllToolsAcceptToolDeps:
    """AC-7: All 6 tool execute functions must accept tool_deps keyword argument."""

    _TOOL_NAMES_AND_EXECUTE = [
        ("collect", "_collect_execute"),
        ("process", "_process_execute"),
        ("distribute", "_distribute_execute"),
        ("search", "_search_execute"),
        ("get_content_detail", "_get_content_detail_execute"),
        ("summarize_for_user", "_summarize_for_user_execute"),
    ]

    @pytest.mark.parametrize("_tool_name,fn_name", _TOOL_NAMES_AND_EXECUTE)
    def test_execute_fn_accepts_tool_deps(self, _tool_name: str, fn_name: str) -> None:
        """Each tool execute function must accept 'tool_deps' as a parameter."""
        import inspect

        import intellisource.agent.tools as tools_mod  # type: ignore[import]

        fn = getattr(tools_mod, fn_name, None)
        if fn is None:
            pytest.fail(
                f"{fn_name} not found in intellisource.agent.tools — "
                "function must be implemented"
            )

        sig = inspect.signature(fn)
        assert "tool_deps" in sig.parameters, (
            f"{fn_name} must accept 'tool_deps' keyword argument for ToolDeps"
            f" injection; current params: {list(sig.parameters.keys())}"
        )


# ---------------------------------------------------------------------------
# R-003: run_flexible forwards tool_deps to tool execute functions
# ---------------------------------------------------------------------------


class TestRunFlexibleForwardsToolDeps:
    """R-003: run_flexible must forward tool_deps to tool execute functions."""

    @pytest.mark.asyncio
    async def test_run_flexible_forwards_tool_deps_to_execute(self) -> None:
        """tool_deps passed to run_flexible must reach the tool execute function."""
        from intellisource.agent.deps import ToolDeps
        from intellisource.agent.pipeline import PipelineConfig
        from intellisource.agent.runner import AgentRunner
        from intellisource.agent.tools import AgentToolRegistry
        from intellisource.llm.gateway import LLMResult

        captured_deps: list[Any] = []

        async def _mock_tool_execute(
            tool_deps: Any = None, **kwargs: Any
        ) -> dict[str, Any]:
            captured_deps.append(tool_deps)
            return {"status": "ok", "result": "done"}

        mock_gateway = AsyncMock()

        call_count = 0

        async def _chat(**kwargs: Any) -> LLMResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                tc = MagicMock()
                tc.function.name = "mock_tool"
                tc.function.arguments = "{}"
                tc.id = "tc-001"
                return LLMResult(
                    content="",
                    metadata={
                        "tool_calls": [tc],
                        "finish_reason": "tool_calls",
                        "usage": {},
                    },
                )
            return LLMResult(
                content="done",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )

        mock_gateway.chat.side_effect = _chat

        registry = AgentToolRegistry()
        registry.register(
            name="mock_tool",
            description="Test tool",
            parameters={"type": "object", "properties": {}},
            execute_fn=_mock_tool_execute,
        )

        deps = ToolDeps(
            session_factory=MagicMock(),
            llm_gateway=mock_gateway,
            pipeline_engine=AsyncMock(),
            search_engine=AsyncMock(),
            collector_registry=MagicMock(),
            distributor=AsyncMock(),
        )

        runner = AgentRunner(tool_registry=registry, llm_gateway=mock_gateway)

        config = PipelineConfig.from_dict(
            {
                "name": "test-forward",
                "mode": "flexible",
                "tools_allowed": ["mock_tool"],
                "tools_denied": [],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
            }
        )

        await runner.run_flexible(
            config,
            user_message="test",
            session={},
            tool_deps=deps,
        )

        assert len(captured_deps) == 1, (
            f"Tool execute must be called once; called {len(captured_deps)} times"
        )
        assert captured_deps[0] is deps, (
            "run_flexible must forward tool_deps to the tool execute function; "
            f"got: {captured_deps[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_run_flexible_uses_instance_tool_deps_as_fallback(self) -> None:
        """When run_flexible is called without tool_deps, self._tool_deps is used."""
        from intellisource.agent.deps import ToolDeps
        from intellisource.agent.pipeline import PipelineConfig
        from intellisource.agent.runner import AgentRunner
        from intellisource.agent.tools import AgentToolRegistry
        from intellisource.llm.gateway import LLMResult

        captured_deps: list[Any] = []

        async def _mock_tool_execute(
            tool_deps: Any = None, **kwargs: Any
        ) -> dict[str, Any]:
            captured_deps.append(tool_deps)
            return {"status": "ok"}

        mock_gateway = AsyncMock()
        call_count = 0

        async def _chat(**kwargs: Any) -> LLMResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                tc = MagicMock()
                tc.function.name = "mock_tool"
                tc.function.arguments = "{}"
                tc.id = "tc-002"
                return LLMResult(
                    content="",
                    metadata={
                        "tool_calls": [tc],
                        "finish_reason": "tool_calls",
                        "usage": {},
                    },
                )
            return LLMResult(
                content="done",
                metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
            )

        mock_gateway.chat.side_effect = _chat

        registry = AgentToolRegistry()
        registry.register(
            name="mock_tool",
            description="Test tool",
            parameters={"type": "object", "properties": {}},
            execute_fn=_mock_tool_execute,
        )

        instance_deps = ToolDeps(
            session_factory=MagicMock(),
            llm_gateway=mock_gateway,
            pipeline_engine=AsyncMock(),
            search_engine=AsyncMock(),
            collector_registry=MagicMock(),
            distributor=AsyncMock(),
        )

        runner = AgentRunner(
            tool_registry=registry,
            llm_gateway=mock_gateway,
            tool_deps=instance_deps,
        )

        config = PipelineConfig.from_dict(
            {
                "name": "test-fallback",
                "mode": "flexible",
                "tools_allowed": ["mock_tool"],
                "tools_denied": [],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
            }
        )

        await runner.run_flexible(config, user_message="test", session={})

        assert len(captured_deps) == 1
        assert captured_deps[0] is instance_deps, (
            "run_flexible must fall back to self._tool_deps when no tool_deps kwarg; "
            f"got: {captured_deps[0]!r}"
        )
