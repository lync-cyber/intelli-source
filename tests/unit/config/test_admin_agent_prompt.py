"""The admin-agent system prompt must mandate tool use before state queries."""

from __future__ import annotations

from intellisource.pipeline.definition_service import load_pipeline_config


class TestAdminAgentSystemPrompt:
    """admin-agent forbids answering 'what exists' queries from memory."""

    def test_mandates_list_get_before_state_query(self) -> None:
        config = load_pipeline_config("admin-agent")
        prompt = config.system_prompt or ""
        assert "凭记忆" in prompt, (
            "admin-agent system_prompt must forbid answering state queries "
            "from memory and mandate calling list_/get_ tools first"
        )
