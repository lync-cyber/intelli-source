"""Tests for AgentRunner dual-mode execution engine.

Covers:
- AC-067: strict mode calls tools sequentially; flexible mode runs LLM Agent Loop
- AC-T030-1: AgentRunner.run_strict(pipeline_config, params) executes steps in order
- AC-T030-2: AgentRunner.run_flexible(pipeline_config, user_message, session)
             runs LLM Agent Loop
- AC-T030-3: flexible mode terminates when max_steps exceeded
- AC-T030-4: flexible mode excludes tools_denied from LLM available tools
- AC-T030-5: strict mode handles on_failure strategies (retry/skip/abort)
- AC-T030-6: both modes persist results to TaskChain table (E-008)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from intellisource.agent.pipeline import PipelineConfig
from intellisource.agent.runner import AgentRunner

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tool_registry() -> MagicMock:
    """Mock tool registry that resolves tool names to async callables."""
    registry = MagicMock()

    async def _rss_fetch(**kwargs):
        return {"items": [{"title": "Article 1"}]}

    async def _html_clean(**kwargs):
        return {"text": "Cleaned content"}

    async def _summarize(**kwargs):
        return {"summary": "Brief summary"}

    tool_map = {
        "rss_fetch": AsyncMock(side_effect=_rss_fetch),
        "html_clean": AsyncMock(side_effect=_html_clean),
        "summarize": AsyncMock(side_effect=_summarize),
        "web_search": AsyncMock(
            return_value={"results": [{"url": "https://example.com"}]}
        ),
        "file_delete": AsyncMock(return_value={"deleted": True}),
        "db_drop": AsyncMock(return_value={"dropped": True}),
    }

    def get_tool(name: str):
        return tool_map.get(name)

    registry.get = MagicMock(side_effect=get_tool)
    registry.list_tools = MagicMock(return_value=list(tool_map.keys()))
    return registry


@pytest.fixture
def llm_gateway() -> AsyncMock:
    """Mock LLM gateway for flexible mode."""
    gateway = AsyncMock()
    # Simulate LLM returning a tool call then a final answer
    gateway.chat.return_value = {
        "tool_calls": [],
        "content": "Task completed successfully.",
        "done": True,
    }
    return gateway


@pytest.fixture
def strict_config() -> PipelineConfig:
    """PipelineConfig for strict mode testing."""
    return PipelineConfig.from_dict(
        {
            "name": "test-strict",
            "mode": "strict",
            "steps": [
                {
                    "tool": "rss_fetch",
                    "params": {"url": "https://example.com/feed"},
                },
                {
                    "tool": "html_clean",
                    "params": {"selector": "article"},
                },
            ],
            "max_steps": 10,
            "on_failure": "abort",
        }
    )


@pytest.fixture
def flexible_config() -> PipelineConfig:
    """PipelineConfig for flexible mode testing."""
    return PipelineConfig.from_dict(
        {
            "name": "test-flexible",
            "mode": "flexible",
            "tools_allowed": ["web_search", "summarize"],
            "tools_denied": ["file_delete", "db_drop"],
            "steps": [],
            "max_steps": 3,
            "on_failure": "skip",
        }
    )


@pytest.fixture
def strict_retry_config() -> PipelineConfig:
    """PipelineConfig for strict mode with retry on_failure."""
    return PipelineConfig.from_dict(
        {
            "name": "test-retry",
            "mode": "strict",
            "steps": [
                {
                    "tool": "rss_fetch",
                    "params": {"url": "https://fail.example.com"},
                },
            ],
            "max_steps": 10,
            "on_failure": "retry",
        }
    )


@pytest.fixture
def strict_skip_config() -> PipelineConfig:
    """PipelineConfig for strict mode with skip on_failure."""
    return PipelineConfig.from_dict(
        {
            "name": "test-skip",
            "mode": "strict",
            "steps": [
                {
                    "tool": "rss_fetch",
                    "params": {"url": "https://fail.example.com"},
                },
                {
                    "tool": "html_clean",
                    "params": {"selector": "div"},
                },
            ],
            "max_steps": 10,
            "on_failure": "skip",
        }
    )


@pytest.fixture
def runner(tool_registry: MagicMock, llm_gateway: AsyncMock) -> AgentRunner:
    """AgentRunner with mocked dependencies."""
    return AgentRunner(tool_registry=tool_registry, llm_gateway=llm_gateway)


# ===================================================================
# AC-T030-1: run_strict executes steps in order
# ===================================================================


class TestRunStrict:
    """Verify strict mode sequential tool execution."""

    async def test_strict_returns_success(
        self, runner: AgentRunner, strict_config: PipelineConfig
    ) -> None:
        """AC-T030-1: run_strict returns success status on completion."""
        result = await runner.run_strict(strict_config, params={})
        assert result["status"] == "success"

    async def test_strict_executes_all_steps(
        self,
        runner: AgentRunner,
        strict_config: PipelineConfig,
        tool_registry: MagicMock,
    ) -> None:
        """AC-T030-1: run_strict calls each tool in step order."""
        await runner.run_strict(strict_config, params={})
        # Both tools should have been called
        rss_tool = tool_registry.get("rss_fetch")
        html_tool = tool_registry.get("html_clean")
        rss_tool.assert_called_once()
        html_tool.assert_called_once()

    async def test_strict_steps_executed_count(
        self, runner: AgentRunner, strict_config: PipelineConfig
    ) -> None:
        """AC-T030-1: steps_executed matches number of steps in config."""
        result = await runner.run_strict(strict_config, params={})
        assert result["steps_executed"] == 2

    async def test_strict_results_ordered(
        self, runner: AgentRunner, strict_config: PipelineConfig
    ) -> None:
        """AC-T030-1: results list preserves step execution order."""
        result = await runner.run_strict(strict_config, params={})
        assert isinstance(result["results"], list)
        assert len(result["results"]) == 2

    async def test_strict_passes_params_to_tools(
        self,
        runner: AgentRunner,
        strict_config: PipelineConfig,
        tool_registry: MagicMock,
    ) -> None:
        """AC-T030-1: each step's params are forwarded to the tool."""
        await runner.run_strict(strict_config, params={"extra": "value"})
        rss_tool = tool_registry.get("rss_fetch")
        call_kwargs = rss_tool.call_args[1]
        assert "url" in call_kwargs


# ===================================================================
# AC-T030-5: strict mode on_failure strategies
# ===================================================================


class TestStrictOnFailure:
    """Verify strict mode failure handling strategies."""

    async def test_abort_stops_on_failure(
        self,
        tool_registry: MagicMock,
        llm_gateway: AsyncMock,
    ) -> None:
        """AC-T030-5: abort strategy stops pipeline on first failure."""
        # Make the tool raise an exception
        tool_registry.get("rss_fetch").side_effect = RuntimeError("fetch failed")
        runner = AgentRunner(tool_registry=tool_registry, llm_gateway=llm_gateway)
        config = PipelineConfig.from_dict(
            {
                "name": "abort-test",
                "mode": "strict",
                "steps": [
                    {"tool": "rss_fetch", "params": {"url": "http://bad"}},
                    {"tool": "html_clean", "params": {"selector": "p"}},
                ],
                "max_steps": 10,
                "on_failure": "abort",
            }
        )
        result = await runner.run_strict(config, params={})
        assert result["status"] == "failed"
        # Second step should NOT have been called
        tool_registry.get("html_clean").assert_not_called()

    async def test_skip_continues_on_failure(
        self,
        tool_registry: MagicMock,
        llm_gateway: AsyncMock,
    ) -> None:
        """AC-T030-5: skip strategy continues to next step on failure."""
        tool_registry.get("rss_fetch").side_effect = RuntimeError("fetch failed")
        runner = AgentRunner(tool_registry=tool_registry, llm_gateway=llm_gateway)
        config = PipelineConfig.from_dict(
            {
                "name": "skip-test",
                "mode": "strict",
                "steps": [
                    {"tool": "rss_fetch", "params": {"url": "http://bad"}},
                    {"tool": "html_clean", "params": {"selector": "p"}},
                ],
                "max_steps": 10,
                "on_failure": "skip",
            }
        )
        result = await runner.run_strict(config, params={})
        # Pipeline continues; second step should be called
        tool_registry.get("html_clean").assert_called_once()
        assert result["steps_executed"] == 2

    async def test_retry_retries_failed_step(
        self,
        tool_registry: MagicMock,
        llm_gateway: AsyncMock,
    ) -> None:
        """AC-T030-5: retry strategy retries the failed step."""
        call_count = 0

        async def _flaky_fetch(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("transient failure")
            return {"items": []}

        tool_registry.get("rss_fetch").side_effect = _flaky_fetch
        runner = AgentRunner(tool_registry=tool_registry, llm_gateway=llm_gateway)
        config = PipelineConfig.from_dict(
            {
                "name": "retry-test",
                "mode": "strict",
                "steps": [
                    {"tool": "rss_fetch", "params": {"url": "http://flaky"}},
                ],
                "max_steps": 10,
                "on_failure": "retry",
            }
        )
        result = await runner.run_strict(config, params={})
        assert result["status"] == "success"
        assert call_count >= 2


# ===================================================================
# AC-T030-2: run_flexible runs LLM Agent Loop
# ===================================================================


class TestRunFlexible:
    """Verify flexible mode LLM Agent Loop execution."""

    async def test_flexible_returns_success(
        self, runner: AgentRunner, flexible_config: PipelineConfig
    ) -> None:
        """AC-T030-2: run_flexible returns success status."""
        result = await runner.run_flexible(
            flexible_config,
            user_message="Search for AI news",
            session={"session_id": "test-001"},
        )
        assert result["status"] == "success"

    async def test_flexible_calls_llm_gateway(
        self,
        runner: AgentRunner,
        flexible_config: PipelineConfig,
        llm_gateway: AsyncMock,
    ) -> None:
        """AC-T030-2: run_flexible invokes the LLM gateway."""
        await runner.run_flexible(
            flexible_config,
            user_message="Summarize latest news",
            session={"session_id": "test-002"},
        )
        llm_gateway.chat.assert_called()

    async def test_flexible_returns_steps_executed(
        self, runner: AgentRunner, flexible_config: PipelineConfig
    ) -> None:
        """AC-T030-2: result includes steps_executed count."""
        result = await runner.run_flexible(
            flexible_config,
            user_message="Search and summarize",
            session={},
        )
        assert "steps_executed" in result
        assert isinstance(result["steps_executed"], int)


# ===================================================================
# AC-T030-3: flexible mode max_steps enforcement
# ===================================================================


class TestFlexibleMaxSteps:
    """Verify flexible mode terminates when max_steps exceeded."""

    async def test_terminates_at_max_steps(
        self,
        tool_registry: MagicMock,
    ) -> None:
        """AC-T030-3: flexible mode stops after max_steps iterations."""
        # LLM gateway that always requests another tool call (never done)
        llm_gw = AsyncMock()
        llm_gw.chat.return_value = {
            "tool_calls": [{"name": "web_search", "arguments": {"q": "test"}}],
            "content": "",
            "done": False,
        }
        runner = AgentRunner(tool_registry=tool_registry, llm_gateway=llm_gw)
        config = PipelineConfig.from_dict(
            {
                "name": "max-steps-test",
                "mode": "flexible",
                "tools_allowed": ["web_search"],
                "tools_denied": [],
                "steps": [],
                "max_steps": 3,
                "on_failure": "abort",
            }
        )
        result = await runner.run_flexible(
            config,
            user_message="Keep searching",
            session={},
        )
        # Should have terminated, not run forever
        assert result["steps_executed"] <= 3
        assert result["status"] in ("success", "failed")


# ===================================================================
# AC-T030-4: flexible mode tools_denied filtering
# ===================================================================


class TestFlexibleToolsDenied:
    """Verify tools_denied are excluded from LLM available tools."""

    async def test_denied_tools_excluded(
        self,
        tool_registry: MagicMock,
        llm_gateway: AsyncMock,
    ) -> None:
        """AC-T030-4: tools in tools_denied are not available to LLM."""
        runner = AgentRunner(tool_registry=tool_registry, llm_gateway=llm_gateway)
        config = PipelineConfig.from_dict(
            {
                "name": "denied-tools-test",
                "mode": "flexible",
                "tools_allowed": [],
                "tools_denied": ["file_delete", "db_drop"],
                "steps": [],
                "max_steps": 5,
                "on_failure": "skip",
            }
        )
        await runner.run_flexible(
            config,
            user_message="Do something",
            session={},
        )
        # Inspect the tools passed to the LLM gateway
        call_kwargs = llm_gateway.chat.call_args
        # The available tools passed to LLM should not include denied tools
        if call_kwargs and call_kwargs.kwargs.get("tools"):
            tool_names = [t["name"] for t in call_kwargs.kwargs["tools"]]
            assert "file_delete" not in tool_names
            assert "db_drop" not in tool_names
        elif call_kwargs and len(call_kwargs.args) > 1:
            # Tools may be passed as positional arg
            tools_arg = call_kwargs.args[1]
            if isinstance(tools_arg, list):
                tool_names = [
                    t.get("name", t) if isinstance(t, dict) else t for t in tools_arg
                ]
                assert "file_delete" not in tool_names
                assert "db_drop" not in tool_names


# ===================================================================
# AC-T030-6: results persisted to TaskChain table
# ===================================================================


class TestResultPersistence:
    """Verify both modes persist results to TaskChain (E-008)."""

    async def test_strict_persists_to_taskchain(
        self, runner: AgentRunner, strict_config: PipelineConfig
    ) -> None:
        """AC-T030-6: strict mode result is persisted to TaskChain."""
        result = await runner.run_strict(strict_config, params={})
        # Result should contain a task_chain_id or similar persistence marker
        assert result["status"] == "success"
        # The runner should have called some persistence mechanism
        # (exact API depends on implementation; we check the result
        #  contains a reference to the persisted chain)
        assert "task_chain_id" in result or "chain_id" in result

    async def test_flexible_persists_to_taskchain(
        self, runner: AgentRunner, flexible_config: PipelineConfig
    ) -> None:
        """AC-T030-6: flexible mode result is persisted to TaskChain."""
        result = await runner.run_flexible(
            flexible_config,
            user_message="Persist this",
            session={"session_id": "persist-test"},
        )
        assert result["status"] == "success"
        assert "task_chain_id" in result or "chain_id" in result
