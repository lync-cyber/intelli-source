"""Execute-function implementations for agent tools.

Boundary convention: the leading underscore on ``_*_execute`` here does **not**
mean "module-private". It marks "not a stable cross-layer public API — only the
registry (which assembles them into ``ToolDefinition``s), same-layer agent
callers (runner / factory) and tests should import them directly". The hard
boundary is enforced by importlinter Contract 10 (``api.routers`` ✗→ ``executes``)
and Contract 11 (``mcp_server`` ✗→ ``executes``); downstream transport adapters
obtain tools through ``AgentToolRegistry`` instead.
"""
