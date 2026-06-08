"""Management (CRUD) tools: sources / subscriptions / pipelines / templates.

Split per entity for readability. The execute functions and the per-entity
``ToolDefinition`` lists are re-exported here so the historical import surface
(``from intellisource.agent.tools.executes.manage import _create_source_execute``
and ``MANAGEMENT_TOOL_DEFS``) is preserved.

The services are injected via ``ToolDeps`` factories (constructed in the
composition root); these modules import only the cross-cutting config value
objects, never a domain service package, so the agent layer gains no static edge
to those services.
"""

from __future__ import annotations

from intellisource.agent.tools._spec import ToolDefinition
from intellisource.agent.tools.executes.manage.pipeline import (
    PIPELINE_TOOL_DEFS,
    _create_pipeline_execute,
    _delete_pipeline_execute,
    _get_pipeline_execute,
    _list_pipelines_execute,
    _update_pipeline_execute,
)
from intellisource.agent.tools.executes.manage.source import (
    SOURCE_TOOL_DEFS,
    _create_source_execute,
    _delete_source_execute,
    _get_source_execute,
    _list_sources_execute,
    _update_source_execute,
)
from intellisource.agent.tools.executes.manage.subscription import (
    SUBSCRIPTION_TOOL_DEFS,
    _create_subscription_execute,
    _delete_subscription_execute,
    _get_subscription_execute,
    _list_subscriptions_execute,
    _update_subscription_execute,
)
from intellisource.agent.tools.executes.manage.template import (
    TEMPLATE_TOOL_DEFS,
    _create_template_execute,
    _delete_template_execute,
    _get_template_execute,
    _list_templates_execute,
    _update_template_execute,
)

MANAGEMENT_TOOL_DEFS: list[ToolDefinition] = [
    *SOURCE_TOOL_DEFS,
    *SUBSCRIPTION_TOOL_DEFS,
    *PIPELINE_TOOL_DEFS,
    *TEMPLATE_TOOL_DEFS,
]

__all__ = [
    "MANAGEMENT_TOOL_DEFS",
    "_create_pipeline_execute",
    "_create_source_execute",
    "_create_subscription_execute",
    "_create_template_execute",
    "_delete_pipeline_execute",
    "_delete_source_execute",
    "_delete_subscription_execute",
    "_delete_template_execute",
    "_get_pipeline_execute",
    "_get_source_execute",
    "_get_subscription_execute",
    "_get_template_execute",
    "_list_pipelines_execute",
    "_list_sources_execute",
    "_list_subscriptions_execute",
    "_list_templates_execute",
    "_update_pipeline_execute",
    "_update_source_execute",
    "_update_subscription_execute",
    "_update_template_execute",
]
