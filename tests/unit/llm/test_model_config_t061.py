"""T-061: LLM 配置 Pydantic Schema 验证测试。

覆盖:
- AC-T061-1: LLMModelsConfig Pydantic model 覆盖所有 YAML 字段
- AC-T061-2: ModelTaskConfig 子模型验证 model/provider/temperature/max_tokens
- AC-T061-3: load_model_config() 自动通过 LLMModelsConfig 验证
- AC-T061-4: 无效配置抛出 ValidationError 并指明具体字段
- AC-T061-5: 缺少可选字段时使用 Pydantic 默认值
- AC-T061-6: mypy --strict 零错误（通过静态类型检查保证）
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from intellisource.llm.model_config import (
    LLMModelsConfig,
    ModelTaskConfig,
    load_model_config,
)

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

VALID_CONFIG: dict = {
    "default_model": {
        "model": "gpt-4o-mini",
        "provider": "openai",
    },
    "models": {
        "extract": {
            "model": "gpt-4o-mini",
            "provider": "openai",
            "temperature": 0.0,
            "max_tokens": 4096,
        },
        "summarize": {
            "model": "claude-3-haiku-20240307",
            "provider": "anthropic",
            "temperature": 0.3,
            "max_tokens": 2048,
        },
    },
    "profiles": {
        "gpt-4o-mini": {
            "temperature": 0.1,
            "max_tokens": 4096,
            "context_window": 128000,
            "prompt_style": "default",
            "timeout_seconds": 60,
        },
    },
}


# ===========================================================================
# AC-T061-1: LLMModelsConfig 覆盖所有 YAML 字段
# ===========================================================================


class TestLLMModelsConfig:
    """AC-T061-1: LLMModelsConfig Pydantic model 覆盖所有 YAML 字段。"""

    def test_llm_models_config_accepts_valid_config(self) -> None:
        """LLMModelsConfig 可从完整有效配置构建。"""
        config = LLMModelsConfig.model_validate(VALID_CONFIG)

        assert config.default_model.model == "gpt-4o-mini"
        assert config.default_model.provider == "openai"

    def test_llm_models_config_has_models_field(self) -> None:
        """LLMModelsConfig.models 包含 task_type 到 ModelTaskConfig 的映射。"""
        config = LLMModelsConfig.model_validate(VALID_CONFIG)

        assert "extract" in config.models
        assert "summarize" in config.models

    def test_llm_models_config_has_profiles_field(self) -> None:
        """LLMModelsConfig.profiles 包含 model_id 到 profile 的映射。"""
        config = LLMModelsConfig.model_validate(VALID_CONFIG)

        assert "gpt-4o-mini" in config.profiles

    def test_llm_models_config_profiles_optional(self) -> None:
        """AC-T061-5: profiles 字段可选，缺失时使用空 dict 默认值。"""
        config_no_profiles = {
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
            "models": {},
        }
        config = LLMModelsConfig.model_validate(config_no_profiles)

        assert config.profiles == {}


# ===========================================================================
# AC-T061-2: ModelTaskConfig 子模型验证
# ===========================================================================


class TestModelTaskConfig:
    """AC-T061-2: ModelTaskConfig 子模型验证 model/provider/temperature/max_tokens。"""

    def test_model_task_config_required_fields(self) -> None:
        """ModelTaskConfig 需要 model 和 provider 字段。"""
        task = ModelTaskConfig(model="gpt-4o-mini", provider="openai")

        assert task.model == "gpt-4o-mini"
        assert task.provider == "openai"

    def test_model_task_config_optional_temperature(self) -> None:
        """AC-T061-5: temperature 字段可选，缺失时为 None。"""
        task = ModelTaskConfig(model="gpt-4o-mini", provider="openai")

        assert task.temperature is None

    def test_model_task_config_optional_max_tokens(self) -> None:
        """AC-T061-5: max_tokens 字段可选，缺失时为 None。"""
        task = ModelTaskConfig(model="gpt-4o-mini", provider="openai")

        assert task.max_tokens is None

    def test_model_task_config_temperature_validation_too_high(self) -> None:
        """AC-T061-4: temperature > 2.0 抛出 ValidationError 指明字段。"""
        with pytest.raises(ValidationError) as exc_info:
            ModelTaskConfig(model="gpt-4o-mini", provider="openai", temperature=3.0)

        errors = exc_info.value.errors()
        assert any("temperature" in str(e["loc"]) for e in errors)

    def test_model_task_config_temperature_validation_negative(self) -> None:
        """AC-T061-4: temperature < 0.0 抛出 ValidationError 指明字段。"""
        with pytest.raises(ValidationError) as exc_info:
            ModelTaskConfig(model="gpt-4o-mini", provider="openai", temperature=-0.1)

        errors = exc_info.value.errors()
        assert any("temperature" in str(e["loc"]) for e in errors)

    def test_model_task_config_max_tokens_validation_zero(self) -> None:
        """AC-T061-4: max_tokens <= 0 抛出 ValidationError 指明字段。"""
        with pytest.raises(ValidationError) as exc_info:
            ModelTaskConfig(model="gpt-4o-mini", provider="openai", max_tokens=0)

        errors = exc_info.value.errors()
        assert any("max_tokens" in str(e["loc"]) for e in errors)

    def test_model_task_config_max_tokens_validation_negative(self) -> None:
        """AC-T061-4: max_tokens < 0 抛出 ValidationError 指明字段。"""
        with pytest.raises(ValidationError) as exc_info:
            ModelTaskConfig(model="gpt-4o-mini", provider="openai", max_tokens=-100)

        errors = exc_info.value.errors()
        assert any("max_tokens" in str(e["loc"]) for e in errors)

    def test_model_task_config_temperature_boundary_zero(self) -> None:
        """temperature = 0.0 是有效边界值。"""
        task = ModelTaskConfig(model="gpt-4o-mini", provider="openai", temperature=0.0)
        assert task.temperature == 0.0

    def test_model_task_config_temperature_boundary_two(self) -> None:
        """temperature = 2.0 是有效边界值。"""
        task = ModelTaskConfig(model="gpt-4o-mini", provider="openai", temperature=2.0)
        assert task.temperature == 2.0


# ===========================================================================
# AC-T061-3: load_model_config() 通过 LLMModelsConfig 验证
# ===========================================================================


class TestLoadModelConfigValidation:
    """AC-T061-3: load_model_config() 加载后自动通过 LLMModelsConfig 验证。"""

    def test_load_model_config_returns_validated_dict(self, tmp_path: Path) -> None:
        """load_model_config() 成功加载有效配置并返回 dict。"""
        config_file = tmp_path / "llm_models.yaml"
        config_file.write_text(yaml.dump(VALID_CONFIG))

        result = load_model_config(str(config_file))

        assert isinstance(result, dict)
        assert "default_model" in result

    def test_load_model_config_invalid_temperature_raises(self, tmp_path: Path) -> None:
        """AC-T061-4: 无效 temperature 使 load_model_config() 抛出 ValidationError。"""
        invalid_config = {
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
            "models": {
                "extract": {
                    "model": "gpt-4o-mini",
                    "provider": "openai",
                    "temperature": 5.0,  # 超过 2.0 上限
                    "max_tokens": 4096,
                }
            },
        }
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text(yaml.dump(invalid_config))

        with pytest.raises(ValidationError):
            load_model_config(str(config_file))

    def test_load_model_config_invalid_max_tokens_raises(self, tmp_path: Path) -> None:
        """AC-T061-4: 无效 max_tokens 使 load_model_config() 抛出 ValidationError。"""
        invalid_config = {
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
            "models": {
                "extract": {
                    "model": "gpt-4o-mini",
                    "provider": "openai",
                    "temperature": 0.0,
                    "max_tokens": -1,  # 不合法
                }
            },
        }
        config_file = tmp_path / "invalid_tokens.yaml"
        config_file.write_text(yaml.dump(invalid_config))

        with pytest.raises(ValidationError):
            load_model_config(str(config_file))
