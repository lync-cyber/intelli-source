"""Unit tests for strict pipeline step param merging (S-01/S-02)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.agent.runner import AgentRunner
from intellisource.agent.step_params import build_step_params, merge_step_output
from intellisource.config.pipeline_models import PipelineConfig


class TestStepParamsHelpers:
    def test_build_step_params_merges_runtime_and_context(self) -> None:
        step = {"tool": "process", "params": {"pipeline": "default"}}
        params = build_step_params(
            step,
            runtime_params={"source_id": "src-1", "task_id": "t-1"},
            step_context={"content_id": "raw-123"},
            tool_deps=None,
        )
        assert params["pipeline"] == "default"
        assert params["source_id"] == "src-1"
        assert params["content_id"] == "raw-123"

    def test_merge_step_output_process_sets_processed_content_id(self) -> None:
        ctx: dict[str, str] = {"content_id": "raw-old"}
        merge_step_output(
            "process",
            {
                "result": {
                    "content_id": "processed-999",
                    "raw_content_id": "raw-old",
                }
            },
            ctx,
        )
        assert ctx["content_id"] == "processed-999"
        assert ctx["raw_content_id"] == "raw-old"

    def test_merge_step_output_process_multi_fans_out_processed_ids(self) -> None:
        # When process handles several contents ``result`` is a list, so the
        # processed ids must be read from the top-level keys — otherwise the
        # stale collect-stage raw id leaks into distribute (content_not_found).
        ctx: dict[str, object] = {
            "content_id": "raw-old",
            "raw_content_ids": ["raw-old", "raw-2"],
        }
        merge_step_output(
            "process",
            {
                "status": "ok",
                "result": [
                    {"content_id": "pc-1", "raw_content_id": "raw-old"},
                    {"content_id": "pc-2", "raw_content_id": "raw-2"},
                ],
                "processed_content_ids": ["pc-1", "pc-2"],
                "content_id": "pc-1",
            },
            ctx,
        )
        assert ctx["content_id"] == "pc-1"
        assert ctx["processed_content_ids"] == ["pc-1", "pc-2"]


class TestRunStrictRuntimeParams:
    @pytest.mark.asyncio
    async def test_runtime_params_reach_collect_tool(self) -> None:
        registry = MagicMock()
        collect_fn = AsyncMock(
            return_value={
                "status": "ok",
                "raw_content_ids": ["raw-1"],
                "content_id": "raw-1",
            }
        )
        process_fn = AsyncMock(
            return_value={
                "status": "ok",
                "result": {"content_id": "pc-1", "raw_content_id": "raw-1"},
            }
        )
        distribute_fn = AsyncMock(return_value={"status": "ok", "result": {}})

        registry.get = MagicMock(
            side_effect=lambda name: {
                "collect": collect_fn,
                "process": process_fn,
                "distribute": distribute_fn,
            }[name]
        )

        runner = AgentRunner(tool_registry=registry, llm_gateway=None)
        config = PipelineConfig.from_dict(
            {
                "name": "chain-test",
                "mode": "strict",
                "steps": [
                    {"tool": "collect", "params": {}},
                    {"tool": "process", "params": {}},
                    {"tool": "distribute", "params": {}},
                ],
                "max_steps": 10,
                "on_failure": "abort",
            }
        )

        await runner.run_strict(
            config,
            params={
                "source_id": "11111111-1111-1111-1111-111111111111",
                "source_type": "rss",
                "task_id": "22222222-2222-2222-2222-222222222222",
            },
        )

        collect_kwargs = collect_fn.await_args.kwargs
        assert collect_kwargs["source_id"] == "11111111-1111-1111-1111-111111111111"
        assert collect_kwargs["source_type"] == "rss"
        assert collect_kwargs["task_id"] == "22222222-2222-2222-2222-222222222222"

        process_kwargs = process_fn.await_args.kwargs
        assert process_kwargs["content_id"] == "raw-1"

        distribute_kwargs = distribute_fn.await_args.kwargs
        assert distribute_kwargs["content_id"] == "pc-1"

    @pytest.mark.asyncio
    async def test_multi_process_fans_out_processed_ids_to_distribute(self) -> None:
        registry = MagicMock()
        collect_fn = AsyncMock(
            return_value={
                "status": "ok",
                "raw_content_ids": ["raw-1", "raw-2"],
                "content_id": "raw-1",
            }
        )
        # multi-content process: result is a list, processed ids at top level
        process_fn = AsyncMock(
            return_value={
                "status": "ok",
                "result": [
                    {"content_id": "pc-1", "raw_content_id": "raw-1"},
                    {"content_id": "pc-2", "raw_content_id": "raw-2"},
                ],
                "processed_content_ids": ["pc-1", "pc-2"],
                "content_id": "pc-1",
            }
        )
        distribute_fn = AsyncMock(return_value={"status": "ok", "result": {}})

        registry.get = MagicMock(
            side_effect=lambda name: {
                "collect": collect_fn,
                "process": process_fn,
                "distribute": distribute_fn,
            }[name]
        )

        runner = AgentRunner(tool_registry=registry, llm_gateway=None)
        config = PipelineConfig.from_dict(
            {
                "name": "chain-test",
                "mode": "strict",
                "steps": [
                    {"tool": "collect", "params": {}},
                    {"tool": "process", "params": {}},
                    {"tool": "distribute", "params": {}},
                ],
                "max_steps": 10,
                "on_failure": "abort",
            }
        )

        await runner.run_strict(
            config,
            params={
                "source_id": "11111111-1111-1111-1111-111111111111",
                "source_type": "rss",
            },
        )

        # distribute must receive the full processed-id list (fan-out), not the
        # stale raw content_id from the collect stage.
        distribute_kwargs = distribute_fn.await_args.kwargs
        assert distribute_kwargs["processed_content_ids"] == ["pc-1", "pc-2"]
        assert distribute_kwargs["content_id"] == "pc-1"
