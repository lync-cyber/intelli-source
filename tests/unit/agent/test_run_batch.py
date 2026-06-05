"""Unit tests for AgentRunner.run_batch (S-06)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.agent.runner import AgentRunner
from intellisource.config.pipeline_models import PipelineConfig


class TestRunBatchMode:
    @pytest.mark.asyncio
    async def test_execute_dispatches_batch_mode(self) -> None:
        runner = AgentRunner(tool_registry=MagicMock(), llm_gateway=None)
        config = PipelineConfig.from_dict(
            {
                "name": "content-process",
                "mode": "batch",
                "steps": [{"processor": "HTMLParser"}],
                "max_steps": 10,
                "on_failure": "skip",
            }
        )
        runner.run_batch = AsyncMock(  # type: ignore[method-assign]
            return_value={"status": "success", "content_id": "raw-1"}
        )

        result = await runner.execute(
            config, params={"content_id": "raw-1", "task_id": "t-1"}
        )

        runner.run_batch.assert_awaited_once()
        assert result["content_id"] == "raw-1"

    @pytest.mark.asyncio
    async def test_run_batch_delegates_to_process_execute(self) -> None:
        runner = AgentRunner(tool_registry=MagicMock(), llm_gateway=None)
        config = PipelineConfig.from_dict(
            {
                "name": "content-process",
                "mode": "batch",
                "steps": [{"processor": "HTMLParser"}],
                "max_steps": 10,
                "on_failure": "skip",
            }
        )
        process_output = {
            "status": "ok",
            "results": [
                {
                    "content_id": "processed-1",
                    "raw_content_id": "raw-1",
                }
            ],
        }

        with patch(
            "intellisource.agent.tools._process_execute",
            new=AsyncMock(return_value=process_output),
        ) as mock_process:
            result = await runner.run_batch(
                config, params={"content_id": "raw-1"}, tool_deps=MagicMock()
            )

        mock_process.assert_awaited_once()
        assert result["content_id"] == "raw-1"
        assert result["processed_content_id"] == "processed-1"
        assert result["status"] == "success"
