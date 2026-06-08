"""Generate config/schema/*.json from the config Pydantic models / constants.

Single source of truth for the editor-facing JSON Schemas referenced by the
``# yaml-language-server: $schema=`` modelines in config/**. Run after changing
any config model:

    uv run python scripts/gen_config_schemas.py

``tests/unit/config/test_config_schemas.py`` fails if a committed schema drifts
from what these builders produce, so regeneration stays enforced.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from intellisource.config.llm_schema import LLMModelsConfig
from intellisource.config.models import SourceConfig
from intellisource.config.pipeline_models import (
    _VALID_AGENT_MODES,
    _VALID_MODES,
    _VALID_ON_FAILURE,
    _VALID_PERMISSION_LEVELS,
)
from intellisource.config.subscription_models import SubscriptionConfig

_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "config" / "schema"


def build_llm_models_schema() -> dict[str, Any]:
    """Full llm_models.yaml schema (single object, no list wrapper)."""
    schema = LLMModelsConfig.model_json_schema()
    schema["title"] = "IntelliSource LLM models routing config"
    schema["$schema"] = _DRAFT
    return schema


def _list_wrapper(
    key: str, item_model: type[Any], title: str, description: str
) -> dict[str, Any]:
    """Schema for a YAML file shaped ``{<key>: [<item_model>, ...]}``."""
    item = item_model.model_json_schema()
    item.pop("$schema", None)
    return {
        "$schema": _DRAFT,
        "title": title,
        "description": description,
        "type": "object",
        "additionalProperties": False,
        "properties": {key: {"type": "array", "items": item}},
        "required": [key],
    }


def build_sources_schema() -> dict[str, Any]:
    return _list_wrapper(
        "sources",
        SourceConfig,
        "IntelliSource sources config",
        "Schema for config/sources/*.yaml — a mapping with a 'sources' list.",
    )


def build_subscriptions_schema() -> dict[str, Any]:
    return _list_wrapper(
        "subscriptions",
        SubscriptionConfig,
        "IntelliSource subscriptions config",
        "Schema for config/subscriptions/*.yaml — a mapping with a "
        "'subscriptions' list.",
    )


def build_pipeline_schema() -> dict[str, Any]:
    """Schema for a single pipeline file. PipelineConfig is a hand-validated
    value object, so enums are pulled from its module constants to stay in sync.
    """
    step = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tool": {"type": "string"},
            "processor": {"type": "string"},
            "name": {"type": "string"},
            "params": {"type": "object"},
            "condition": {"type": "object"},
        },
    }
    return {
        "$schema": _DRAFT,
        "title": "IntelliSource pipeline config",
        "description": "Schema for config/pipelines/*.yaml — one pipeline per file.",
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "mode", "steps"],
        "properties": {
            "name": {"type": "string"},
            "mode": {"enum": list(_VALID_MODES)},
            "steps": {"type": "array", "items": step},
            "max_steps": {"type": "integer", "minimum": 1, "default": 50},
            "on_failure": {"enum": list(_VALID_ON_FAILURE), "default": "abort"},
            "agent_mode": {"enum": list(_VALID_AGENT_MODES), "default": "process"},
            "tools_allowed": {"type": "array", "items": {"type": "string"}},
            "tools_denied": {"type": "array", "items": {"type": "string"}},
            "system_prompt": {"type": "string"},
            "max_tokens_budget": {"type": "integer", "minimum": 1},
            "tool_permissions": {
                "type": "object",
                "additionalProperties": {"enum": list(_VALID_PERMISSION_LEVELS)},
            },
        },
    }


BUILDERS: dict[str, Any] = {
    "llm_models.schema.json": build_llm_models_schema,
    "sources.schema.json": build_sources_schema,
    "subscriptions.schema.json": build_subscriptions_schema,
    "pipeline.schema.json": build_pipeline_schema,
}


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    _SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for filename, builder in BUILDERS.items():
        (_SCHEMA_DIR / filename).write_text(render(builder()), encoding="utf-8")
        print(f"wrote config/schema/{filename}")


if __name__ == "__main__":
    main()
