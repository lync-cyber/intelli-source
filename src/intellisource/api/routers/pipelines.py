"""Pipelines API router (AC-T099-1/2/3): list, detail, run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from intellisource.agent.pipeline import PipelineConfig
from intellisource.agent.tools import load_pipeline_config

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


_PIPELINES_DIR = (
    Path(__file__).parent.parent.parent.parent.parent / "config" / "pipelines"
)


class PipelineRunRequest(BaseModel):
    """POST body for /pipelines/{name}/run."""

    params: dict[str, Any] | None = None


def _config_summary(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "mode": raw.get("mode", "strict"),
        "max_steps": raw.get("max_steps", 0),
        "tools_allowed": raw.get("tools_allowed", []),
    }


def _list_pipeline_files() -> list[Path]:
    if not _PIPELINES_DIR.is_dir():
        return []
    return sorted(_PIPELINES_DIR.glob("*.yaml"))


@router.get("")
async def list_pipelines() -> list[dict[str, Any]]:
    """Return summary of every YAML in config/pipelines/."""
    summaries: list[dict[str, Any]] = []
    for path in _list_pipeline_files():
        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(raw, dict):
            continue
        summaries.append(_config_summary(path.stem, raw))
    return summaries


def _pipeline_to_dict(config: PipelineConfig) -> dict[str, Any]:
    return {
        "name": config.name,
        "mode": config.mode,
        "max_steps": config.max_steps,
        "on_failure": config.on_failure,
        "steps": config.steps,
        "tools_allowed": config.tools_allowed,
        "tools_denied": config.tools_denied,
        "system_prompt": config.system_prompt,
    }


@router.get("/{name}")
async def get_pipeline(name: str) -> dict[str, Any]:
    """Return the parsed PipelineConfig for *name* or 404 if absent."""
    path = _PIPELINES_DIR / f"{name}.yaml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"pipeline '{name}' not found")
    config = load_pipeline_config(name)
    return _pipeline_to_dict(config)


@router.post("/{name}/run")
async def run_pipeline(
    name: str, body: PipelineRunRequest, request: Request
) -> dict[str, Any]:
    """Trigger a Celery `run_pipeline` task for the named pipeline."""
    path = _PIPELINES_DIR / f"{name}.yaml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"pipeline '{name}' not found")

    celery_app = getattr(request.app.state, "celery_app", None)
    if celery_app is None:
        raise HTTPException(status_code=503, detail="celery_app not initialised")

    result = celery_app.send_task(
        "run_pipeline",
        kwargs={"pipeline_name": name, "params": body.params or {}},
    )
    return {"task_id": str(getattr(result, "id", result))}
