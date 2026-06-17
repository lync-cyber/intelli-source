"""Stream-endpoint contract tests migrated to test_search_chat_stream_uses_rag.

`/search/chat/stream` routes through `AgentRunner.run_flexible_stream`, so the
SSE event shape is {type: step|sources|token|done|error, ...}. AC-T070 stream
coverage now lives in:

- ``tests/integration/test_search_chat_stream_uses_rag.py`` — full stream
  contract incl. 503 / RAG plumbing / event shape.
- ``tests/unit/agent/test_runner_run_flexible_stream.py`` — runner-level
  unit coverage of the streaming generator.
"""

from __future__ import annotations
