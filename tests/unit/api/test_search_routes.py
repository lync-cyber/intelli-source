"""Stream-endpoint contract tests migrated to test_search_chat_stream_uses_rag.

The original AC-T070 suite asserted the pre-B-001 SSE shape
({content, done}) and mocked `app.state.llm_gateway.stream_complete`.
B-001 routed `/search/chat/stream` through `AgentRunner.run_flexible_stream`
so the SSE event shape is now {type: step|sources|token|done|error, ...}.

Current coverage:
- ``tests/integration/test_search_chat_stream_uses_rag.py`` — full B-001
  contract incl. 503 / RAG plumbing / event shape.
- ``tests/unit/agent/test_runner_run_flexible_stream.py`` — runner-level
  unit coverage of the streaming generator.
"""

from __future__ import annotations
