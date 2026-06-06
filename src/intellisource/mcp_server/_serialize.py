"""Plain-dict serializers shared by the MCP tool modules.

The MCP transport returns JSON-able dicts; these helpers project domain
objects / configs into exactly the shape each tool advertises.
"""

from __future__ import annotations

from typing import Any

from intellisource.config.pipeline_models import PipelineConfig


def pipeline_dict(cfg: PipelineConfig) -> dict[str, Any]:
    return {
        "name": cfg.name,
        "mode": cfg.mode,
        "max_steps": cfg.max_steps,
        "on_failure": cfg.on_failure,
        "steps": cfg.steps,
        "tools_allowed": cfg.tools_allowed,
        "tools_denied": cfg.tools_denied,
        "system_prompt": cfg.system_prompt,
    }


def source_dict(s: Any) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "type": s.type,
        "url": s.url,
        "status": s.status,
        "tags": list(getattr(s, "tags", None) or []),
        "discipline_tags": list(getattr(s, "discipline_tags", None) or []),
        "schedule_interval": getattr(s, "schedule_interval", None),
    }


def subscription_dict(s: Any) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "channel": s.channel,
        "status": s.status,
        "frequency": getattr(s, "frequency", None),
        "match_rules": dict(getattr(s, "match_rules", None) or {}),
    }


def search_response_dict(response: Any) -> dict[str, Any]:
    from dataclasses import asdict, is_dataclass

    if is_dataclass(response) and not isinstance(response, type):
        payload = asdict(response)
        items = []
        for item in payload.get("items") or []:
            row = dict(item) if isinstance(item, dict) else item
            cid = row.get("content_id") if isinstance(row, dict) else None
            if isinstance(row, dict) and cid is not None:
                row["content_id"] = str(cid)
            items.append(row)
        payload["items"] = items
        return payload
    if isinstance(response, dict):
        return response
    return {"items": [], "total": 0, "query_time_ms": 0}


def only_set(**maybe: Any) -> dict[str, Any]:
    """Return only the keyword args that were supplied a non-None value.

    Lets a patch tool accept every editable field as an optional parameter and
    forward exactly the ones the caller set, so an unspecified field is left
    untouched rather than reset to a default.
    """
    return {k: v for k, v in maybe.items() if v is not None}
