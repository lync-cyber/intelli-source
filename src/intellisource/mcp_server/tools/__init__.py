"""Per-domain MCP tool registrars.

Each module exposes a ``register_*_tools(mcp, session_cm[, search_factory])``
that attaches its ``@mcp.tool`` handlers to the shared ``FastMCP`` instance.
"""

from __future__ import annotations

from intellisource.mcp_server.tools.pipeline import register_pipeline_tools
from intellisource.mcp_server.tools.search import register_search_tools
from intellisource.mcp_server.tools.source import register_source_tools
from intellisource.mcp_server.tools.subscription import register_subscription_tools
from intellisource.mcp_server.tools.template import register_template_tools

__all__ = [
    "register_pipeline_tools",
    "register_search_tools",
    "register_source_tools",
    "register_subscription_tools",
    "register_template_tools",
]
