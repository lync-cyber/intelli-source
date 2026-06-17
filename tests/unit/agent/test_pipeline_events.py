"""Tests for PipelineEventLogger + AgentRunner integration.

Covers:
- AC-T067-1: events written to a JSONL file.
- AC-T067-2: 5 event types (pipeline_start/tool_call/llm_call/
              pipeline_complete/pipeline_error).
- AC-T067-3: every record carries ts/event/pipeline_name/task_chain_id/detail.
- AC-T067-4: tool_call detail contains tool_name/duration_ms/status.
- AC-T067-5: llm_call detail contains model/input_tokens/output_tokens/
              latency_ms.
- AC-T067-6: write failures log warning, do not abort the pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from intellisource.agent.events import PipelineEventLogger
from intellisource.agent.runner import AgentRunner
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.llm.gateway import LLMResult


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _make_tool_registry(*tool_names: str) -> MagicMock:
    registry = MagicMock()
    tool_map = {name: AsyncMock(return_value={"result": name}) for name in tool_names}

    def _get(name: str) -> object:
        return tool_map.get(name)

    registry.get = MagicMock(side_effect=_get)
    registry.list_tools = MagicMock(return_value=list(tool_map.keys()))
    return registry


def _strict_config(name: str, tool_name: str) -> PipelineConfig:
    return PipelineConfig.from_dict(
        {
            "name": name,
            "mode": "strict",
            "steps": [{"tool": tool_name, "params": {}}],
            "max_steps": 3,
            "on_failure": "abort",
        }
    )


def _flexible_config(name: str, tools_allowed: list[str]) -> PipelineConfig:
    return PipelineConfig.from_dict(
        {
            "name": name,
            "mode": "flexible",
            "tools_allowed": tools_allowed,
            "tools_denied": [],
            "steps": [],
            "max_steps": 3,
            "on_failure": "skip",
        }
    )


# -------------------------------------------------------- AC-T067-1 + AC-T067-3


class TestJSONLOutputAndSchema:
    async def test_writes_jsonl_records_to_path(self, tmp_path: Path) -> None:
        events_path = tmp_path / "pipeline-events.jsonl"
        logger = PipelineEventLogger(events_path)

        await logger.pipeline_start(
            pipeline_name="p1", task_chain_id="chain-1", mode="strict"
        )

        records = _read_jsonl(events_path)
        assert len(records) == 1
        record = records[0]
        assert set(record.keys()) >= {
            "ts",
            "event",
            "pipeline_name",
            "task_chain_id",
            "detail",
        }
        assert record["event"] == "pipeline_start"
        assert record["pipeline_name"] == "p1"
        assert record["task_chain_id"] == "chain-1"

    async def test_default_path_when_none_passed(self) -> None:
        logger = PipelineEventLogger()
        assert logger.path == Path("pipeline-events.jsonl")


# -------------------------------------------------------- AC-T067-2


class TestAllFiveEventTypes:
    async def test_all_event_types_round_trip(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        logger = PipelineEventLogger(events_path)

        await logger.pipeline_start(
            pipeline_name="p", task_chain_id="c1", mode="flexible"
        )
        await logger.tool_call(
            pipeline_name="p",
            task_chain_id="c1",
            tool_name="search",
            duration_ms=12.5,
            status="success",
        )
        await logger.llm_call(
            pipeline_name="p",
            task_chain_id="c1",
            model="gpt-4o",
            input_tokens=10,
            output_tokens=20,
            latency_ms=345.6,
        )
        await logger.pipeline_complete(
            pipeline_name="p",
            task_chain_id="c1",
            status="success",
            steps_executed=3,
        )
        await logger.pipeline_error(pipeline_name="p", task_chain_id="c1", error="boom")

        events = [r["event"] for r in _read_jsonl(events_path)]
        assert events == [
            "pipeline_start",
            "tool_call",
            "llm_call",
            "pipeline_complete",
            "pipeline_error",
        ]


# -------------------------------------------------------- AC-T067-4


class TestToolCallDetailFields:
    async def test_tool_call_detail_has_required_keys(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        logger = PipelineEventLogger(events_path)

        await logger.tool_call(
            pipeline_name="p",
            task_chain_id="c1",
            tool_name="distribute",
            duration_ms=42.0,
            status="success",
        )

        rec = _read_jsonl(events_path)[0]
        assert rec["detail"]["tool_name"] == "distribute"
        assert rec["detail"]["duration_ms"] == 42.0
        assert rec["detail"]["status"] == "success"

    async def test_tool_call_error_status_carries_error_field(
        self, tmp_path: Path
    ) -> None:
        events_path = tmp_path / "events.jsonl"
        logger = PipelineEventLogger(events_path)

        await logger.tool_call(
            pipeline_name="p",
            task_chain_id="c1",
            tool_name="fail",
            duration_ms=3.0,
            status="error",
            error="ValueError: bad",
        )

        rec = _read_jsonl(events_path)[0]
        assert rec["detail"]["status"] == "error"
        assert rec["detail"]["error"] == "ValueError: bad"


# -------------------------------------------------------- AC-T067-5


class TestLLMCallDetailFields:
    async def test_llm_call_detail_has_required_keys(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        logger = PipelineEventLogger(events_path)

        await logger.llm_call(
            pipeline_name="p",
            task_chain_id="c1",
            model="claude-opus-4-7",
            input_tokens=100,
            output_tokens=250,
            latency_ms=789.0,
        )

        rec = _read_jsonl(events_path)[0]
        assert rec["detail"]["model"] == "claude-opus-4-7"
        assert rec["detail"]["input_tokens"] == 100
        assert rec["detail"]["output_tokens"] == 250
        assert rec["detail"]["latency_ms"] == 789.0


# -------------------------------------------------------- AC-T067-6


class TestWriteFailureTolerance:
    async def test_write_failure_logs_warning_and_returns(self, tmp_path: Path) -> None:
        from structlog.testing import capture_logs

        # Pass a path that points at an *existing* directory so opening
        # in append mode raises (a directory cannot be opened as a file).
        bad_path = tmp_path  # the tmp_path *directory* itself
        logger = PipelineEventLogger(bad_path)

        with capture_logs() as logs:
            await logger.pipeline_start(
                pipeline_name="p", task_chain_id="c1", mode="strict"
            )

        assert any("write failed" in e["event"] for e in logs)


# -------------------------------------------------------- Runner integration


class TestRunnerEmitsEvents:
    async def test_run_strict_emits_start_tool_complete(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        event_logger = PipelineEventLogger(events_path)
        registry = _make_tool_registry("collect")
        runner = AgentRunner(tool_registry=registry, event_logger=event_logger)
        config = _strict_config("strict-events", "collect")

        result = await runner.run_strict(config, params={})

        records = _read_jsonl(events_path)
        events = [r["event"] for r in records]
        assert events[0] == "pipeline_start"
        assert "tool_call" in events
        assert events[-1] == "pipeline_complete"

        # task_chain_id is consistent across all records and matches result
        chain_ids = {r["task_chain_id"] for r in records}
        assert len(chain_ids) == 1
        assert result["task_chain_id"] in chain_ids

        tool_records = [r for r in records if r["event"] == "tool_call"]
        assert tool_records[0]["detail"]["tool_name"] == "collect"
        assert tool_records[0]["detail"]["status"] == "success"
        assert isinstance(tool_records[0]["detail"]["duration_ms"], (int, float))

    async def test_run_flexible_emits_llm_call_with_usage(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        event_logger = PipelineEventLogger(events_path)

        llm_gw = AsyncMock()
        llm_gw.chat.return_value = LLMResult(
            content="done",
            metadata={
                "tool_calls": None,
                "finish_reason": "stop",
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 22,
                    "total_tokens": 33,
                },
                "model": "claude-opus-4-7",
            },
        )

        registry = _make_tool_registry("search")
        runner = AgentRunner(
            tool_registry=registry,
            llm_gateway=llm_gw,
            event_logger=event_logger,
        )
        config = _flexible_config("flex-events", tools_allowed=["search"])

        await runner.run_flexible(config, user_message="hi", session={})

        records = _read_jsonl(events_path)
        llm_records = [r for r in records if r["event"] == "llm_call"]
        assert len(llm_records) == 1
        detail = llm_records[0]["detail"]
        assert detail["model"] == "claude-opus-4-7"
        assert detail["input_tokens"] == 11
        assert detail["output_tokens"] == 22
        assert isinstance(detail["latency_ms"], (int, float))

    async def test_no_event_logger_runs_without_writes(self, tmp_path: Path) -> None:
        """AgentRunner is fully functional without an event_logger configured."""
        events_path = tmp_path / "events.jsonl"
        registry = _make_tool_registry("collect")
        runner = AgentRunner(tool_registry=registry, event_logger=None)
        config = _strict_config("no-logger", "collect")

        result = await runner.run_strict(config, params={})

        assert result["status"] == "success"
        assert not events_path.exists()
