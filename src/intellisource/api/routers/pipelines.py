"""Pipelines API router (AC-T099-1/2/3): list, detail, run."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from intellisource.agent.pipeline import PipelineConfig
from intellisource.agent.tools import _PIPELINES_DIR as _SHARED_PIPELINES_DIR
from intellisource.agent.tools import load_pipeline_config
from intellisource.scheduler.dispatch import send_task_with_trace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipelines", tags=["pipelines"])

_PIPELINES_DIR: Path = _SHARED_PIPELINES_DIR
_PIPELINES_ROOT: Path = _PIPELINES_DIR.resolve()
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _resolve_pipeline_path(name: str) -> Path:
    """Resolve a pipeline name to its YAML path or raise 404.

    Rejects any name containing path-traversal characters, then verifies
    the resolved path stays under `_PIPELINES_DIR`. The 404 response is
    intentionally indistinguishable from "file not found" so the endpoint
    does not leak whether a sibling directory exists.
    """
    if not _NAME_PATTERN.fullmatch(name):
        raise HTTPException(status_code=404, detail=f"pipeline '{name}' not found")
    candidate = (_PIPELINES_DIR / f"{name}.yaml").resolve()
    try:
        under_root = candidate.is_relative_to(_PIPELINES_ROOT)
    except AttributeError:
        # Python < 3.9 fallback (project requires 3.11+, kept for clarity)
        under_root = str(candidate).startswith(str(_PIPELINES_ROOT))
    if not candidate.is_file() or not under_root:
        raise HTTPException(status_code=404, detail=f"pipeline '{name}' not found")
    return candidate


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
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            logger.warning("Skipping malformed pipeline YAML: %s", path)
            continue
        if not isinstance(raw, dict):
            logger.warning("Skipping pipeline YAML with non-mapping root: %s", path)
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
    _resolve_pipeline_path(name)
    config = load_pipeline_config(name)
    return _pipeline_to_dict(config)


@router.post("/{name}/run")
async def run_pipeline(
    name: str, body: PipelineRunRequest, request: Request
) -> dict[str, Any]:
    """Trigger a Celery `run_pipeline` task for the named pipeline."""
    _resolve_pipeline_path(name)

    celery_instance = getattr(request.app.state, "celery_app", None)
    if celery_instance is None:
        raise HTTPException(status_code=503, detail="celery_app not initialised")

    result = send_task_with_trace(
        "run_pipeline",
        kwargs={"pipeline_name": name, "params": body.params or {}},
        celery_instance=celery_instance,
    )
    return {"task_id": str(getattr(result, "id", result))}
