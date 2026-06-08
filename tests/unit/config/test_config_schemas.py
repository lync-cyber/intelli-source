"""Guard config/schema/*.json against drift from the Pydantic models/constants.

Two contracts:
- every committed schema equals what scripts/gen_config_schemas.py produces, so
  editing a config model without regenerating fails here, not silently in an
  editor;
- the shipped example + pipeline YAML files validate against those schemas, so a
  schema that contradicts the real config shape is caught.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_DIR = _ROOT / "config" / "schema"
_GEN_PATH = _ROOT / "scripts" / "gen_config_schemas.py"


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location("gen_config_schemas", _GEN_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_gen = _load_generator()


@pytest.mark.parametrize(
    "filename,builder",
    [
        ("llm_models.schema.json", "build_llm_models_schema"),
        ("sources.schema.json", "build_sources_schema"),
        ("subscriptions.schema.json", "build_subscriptions_schema"),
        ("pipeline.schema.json", "build_pipeline_schema"),
    ],
)
def test_committed_schema_matches_generator(filename: str, builder: str) -> None:
    committed = json.loads((_SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    generated = getattr(_gen, builder)()
    assert committed == generated, (
        f"config/schema/{filename} is stale — "
        f"run: uv run python scripts/gen_config_schemas.py"
    )


@pytest.mark.parametrize(
    "filename",
    [
        "llm_models.schema.json",
        "sources.schema.json",
        "subscriptions.schema.json",
        "pipeline.schema.json",
    ],
)
def test_schema_is_well_formed(filename: str) -> None:
    schema = json.loads((_SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


def _validate(schema_name: str, yaml_path: Path) -> None:
    schema = json.loads(
        (_SCHEMA_DIR / f"{schema_name}.schema.json").read_text(encoding="utf-8")
    )
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path)
    )
    assert not errors, f"{yaml_path.name}: " + "; ".join(
        f"{list(e.path)} {e.message}" for e in errors[:3]
    )


def test_example_sources_conform() -> None:
    _validate("sources", _ROOT / "config" / "examples" / "sources.example.yaml")


def test_example_subscriptions_conform() -> None:
    _validate(
        "subscriptions",
        _ROOT / "config" / "examples" / "subscriptions.example.yaml",
    )


def test_example_llm_models_conform() -> None:
    _validate("llm_models", _ROOT / "config" / "examples" / "llm_models.example.yaml")


@pytest.mark.parametrize(
    "pipeline_file",
    sorted(p.name for p in (_ROOT / "config" / "pipelines").glob("*.yaml")),
)
def test_pipeline_files_conform(pipeline_file: str) -> None:
    _validate("pipeline", _ROOT / "config" / "pipelines" / pipeline_file)
