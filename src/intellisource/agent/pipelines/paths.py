"""Shared filesystem paths for pipeline YAML configs."""

from __future__ import annotations

from pathlib import Path

PIPELINES_DIR: Path = Path(__file__).resolve().parents[4] / "config" / "pipelines"
