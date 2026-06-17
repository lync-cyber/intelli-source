"""WF-4.1: load_prompt supports .prompt.md (front-matter + Jinja + required_vars).

The ``.txt`` + ``format_map`` path is covered by the other prompt tests;
these cover the ``.prompt.md`` behaviour.
"""

from __future__ import annotations

import pytest

from intellisource.llm.prompts import load_prompt


class TestPromptMd:
    def test_renders_jinja_variables(self) -> None:
        out = load_prompt("digest_intro", title="AI 周刊", items="- 头条\n- 次条")
        assert "AI 周刊" in out
        assert "- 头条" in out
        # Jinja placeholders fully substituted — no raw delimiters leak through.
        assert "{{" not in out and "}}" not in out

    def test_front_matter_stripped_from_body(self) -> None:
        out = load_prompt("digest_intro", title="t", items="- x")
        assert "description:" not in out
        assert "required_vars" not in out
        assert not out.lstrip().startswith("---")

    def test_missing_required_var_raises(self) -> None:
        with pytest.raises(ValueError, match="required"):
            load_prompt("digest_intro", title="only-title")

    def test_why_prompt_renders_both_vars(self) -> None:
        out = load_prompt("digest_why", title="标题X", summary="摘要Y")
        assert "标题X" in out
        assert "摘要Y" in out
