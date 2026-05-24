"""Unit tests for /search/chat result parsing helpers (E-03)."""

from __future__ import annotations

from intellisource.api.routers.search import _extract_answer, _extract_sources


class TestSearchChatResponseParsing:
    def test_extract_answer_prefers_final_answer(self) -> None:
        flex_result = {
            "final_answer": "direct final answer",
            "results": [
                {
                    "tool": "summarize_for_user",
                    "output": {"text": "tool summary"},
                }
            ],
        }

        assert _extract_answer(flex_result) == "direct final answer"

    def test_extract_sources_reads_search_tool_response_items(self) -> None:
        flex_result = {
            "results": [
                {
                    "tool": "search",
                    "output": {
                        "response": {
                            "items": [
                                {
                                    "title": "RAG Survey",
                                    "content_id": (
                                        "11111111-1111-1111-1111-111111111111"
                                    ),
                                }
                            ]
                        }
                    },
                }
            ]
        }

        sources = _extract_sources(flex_result)

        assert len(sources) == 1
        assert sources[0].title == "RAG Survey"
        assert str(sources[0].content_id) == "11111111-1111-1111-1111-111111111111"

    def test_extract_answer_prefers_summary_from_summarize_tool(self) -> None:
        flex_result = {
            "results": [
                {
                    "tool": "search",
                    "output": {"response": {"items": []}},
                },
                {
                    "tool": "summarize_for_user",
                    "output": {"summary": "RAG 论文综述摘要"},
                },
            ]
        }

        assert _extract_answer(flex_result) == "RAG 论文综述摘要"

    def test_extract_answer_falls_back_to_text(self) -> None:
        flex_result = {
            "results": [
                {
                    "tool": "summarize_for_user",
                    "output": {"text": "legacy text answer"},
                }
            ]
        }

        assert _extract_answer(flex_result) == "legacy text answer"
