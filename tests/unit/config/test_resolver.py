"""T-059: 配置分层合并机制测试。

覆盖:
- AC-T059-1: config/defaults.yaml 作为全局默认值层
- AC-T059-2: config/llm_models.yaml 作为项目覆盖层
- AC-T059-3: IS_* 前缀环境变量作为最高优先级覆盖
- AC-T059-4: 深度合并策略 — nested dict recursive merge，list 覆盖不合并
- AC-T059-5: ConfigResolver.resolve() 返回最终合并后的 config dict
- AC-T059-6: 合并结果通过 Pydantic model 验证
- AC-T059-7: 缺少 defaults.yaml 时仅使用 project config + env vars
- AC-T059-8: mypy --strict 零错误（通过静态类型检查保证）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from intellisource.config.resolver import ConfigResolver

# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

DEFAULTS_CONFIG: dict[str, Any] = {
    "default_model": {
        "model": "gpt-4o-mini",
        "provider": "openai",
    },
    "models": {
        "extract": {
            "model": "gpt-4o-mini",
            "provider": "openai",
            "temperature": 0.1,
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

PROJECT_CONFIG: dict[str, Any] = {
    "default_model": {
        "model": "claude-3-haiku-20240307",
        "provider": "anthropic",
    },
    "models": {
        "extract": {
            "model": "claude-3-haiku-20240307",
            "provider": "anthropic",
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
}


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.dump(data), encoding="utf-8")


# ===========================================================================
# AC-T059-1: defaults.yaml 作为全局默认值层
# ===========================================================================


class TestDefaultsLayer:
    """AC-T059-1: defaults.yaml 提供所有配置项的合理默认值。"""

    def test_resolver_uses_defaults_when_no_project_config(
        self, tmp_path: Path
    ) -> None:
        """无 project config 时 resolve() 使用 defaults.yaml 中的值。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        result = resolver.resolve()

        assert result["default_model"]["model"] == "gpt-4o-mini"

    def test_resolver_loads_defaults_models_section(self, tmp_path: Path) -> None:
        """defaults.yaml 中的 models 配置可被 resolve() 读取。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        result = resolver.resolve()

        assert "models" in result
        assert "extract" in result["models"]


# ===========================================================================
# AC-T059-2: project config 覆盖 defaults
# ===========================================================================


class TestProjectOverride:
    """AC-T059-2: llm_models.yaml 覆盖 defaults.yaml 中的同名配置。"""

    def test_project_config_overrides_default_model(self, tmp_path: Path) -> None:
        """project config 的 default_model 覆盖 defaults.yaml 中的值。"""
        defaults_path = tmp_path / "defaults.yaml"
        project_path = tmp_path / "llm_models.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        write_yaml(project_path, PROJECT_CONFIG)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(project_path),
        )
        result = resolver.resolve()

        assert result["default_model"]["model"] == "claude-3-haiku-20240307"
        assert result["default_model"]["provider"] == "anthropic"

    def test_project_config_adds_new_task_types(self, tmp_path: Path) -> None:
        """project config 新增的 task_types 合并到结果中。"""
        defaults_path = tmp_path / "defaults.yaml"
        project_path = tmp_path / "llm_models.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        write_yaml(project_path, PROJECT_CONFIG)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(project_path),
        )
        result = resolver.resolve()

        assert "summarize" in result["models"]

    def test_project_config_overrides_existing_task_type(self, tmp_path: Path) -> None:
        """project config 中已存在 task_type 覆盖 defaults 中的同名配置。"""
        defaults_path = tmp_path / "defaults.yaml"
        project_path = tmp_path / "llm_models.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        write_yaml(project_path, PROJECT_CONFIG)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(project_path),
        )
        result = resolver.resolve()

        assert result["models"]["extract"]["model"] == "claude-3-haiku-20240307"


# ===========================================================================
# AC-T059-3: 环境变量作为最高优先级覆盖
# ===========================================================================


class TestEnvVarOverride:
    """AC-T059-3: IS_* 前缀环境变量作为最高优先级覆盖。"""

    def test_env_var_overrides_default_model_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """IS_DEFAULT_MODEL_MODEL 覆盖 default_model.model。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        monkeypatch.setenv("IS_DEFAULT_MODEL_MODEL", "gpt-4-turbo")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        result = resolver.resolve()

        assert result["default_model"]["model"] == "gpt-4-turbo"

    def test_env_var_overrides_project_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """环境变量优先级高于 project config。"""
        defaults_path = tmp_path / "defaults.yaml"
        project_path = tmp_path / "llm_models.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        write_yaml(project_path, PROJECT_CONFIG)
        monkeypatch.setenv("IS_DEFAULT_MODEL_PROVIDER", "custom_provider")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(project_path),
        )
        result = resolver.resolve()

        assert result["default_model"]["provider"] == "custom_provider"

    def test_env_var_not_prefixed_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """不以 IS_ 开头的环境变量不影响配置。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        monkeypatch.setenv("DEFAULT_MODEL_MODEL", "should_not_apply")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        result = resolver.resolve()

        assert result["default_model"]["model"] != "should_not_apply"

    def test_env_var_custom_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env_prefix 参数允许自定义前缀。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        monkeypatch.setenv("APP_DEFAULT_MODEL_MODEL", "custom-model")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
            env_prefix="APP_",
        )
        result = resolver.resolve()

        assert result["default_model"]["model"] == "custom-model"


# ===========================================================================
# AC-T059-4: 深度合并策略
# ===========================================================================


class TestDeepMerge:
    """AC-T059-4: nested dict recursive merge，list 覆盖不合并。"""

    def test_nested_dict_recursive_merge(self, tmp_path: Path) -> None:
        """nested dict 采用递归合并，不会丢失 defaults 中未被覆盖的子键。"""
        defaults: dict[str, Any] = {
            "default_model": {
                "model": "gpt-4o-mini",
                "provider": "openai",
                "extra_key": "keep_me",
            },
            "models": {},
        }
        project: dict[str, Any] = {
            "default_model": {
                "model": "gpt-4-turbo",
            },
        }
        defaults_path = tmp_path / "defaults.yaml"
        project_path = tmp_path / "project.yaml"
        write_yaml(defaults_path, defaults)
        write_yaml(project_path, project)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(project_path),
        )
        result = resolver.resolve()

        assert result["default_model"]["model"] == "gpt-4-turbo"
        assert result["default_model"]["provider"] == "openai"
        assert result["default_model"]["extra_key"] == "keep_me"

    def test_list_override_not_merge(self, tmp_path: Path) -> None:
        """list 类型的值直接覆盖，不做 extend 合并。"""
        defaults: dict[str, Any] = {
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
            "models": {},
            "tags": ["default_tag_1", "default_tag_2"],
        }
        project: dict[str, Any] = {
            "tags": ["project_tag"],
        }
        defaults_path = tmp_path / "defaults.yaml"
        project_path = tmp_path / "project.yaml"
        write_yaml(defaults_path, defaults)
        write_yaml(project_path, project)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(project_path),
        )
        result = resolver.resolve()

        assert result["tags"] == ["project_tag"]

    def test_models_dict_recursive_merge(self, tmp_path: Path) -> None:
        """models 下的 task_type 配置做嵌套合并。"""
        defaults: dict[str, Any] = {
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
            "models": {
                "extract": {
                    "model": "gpt-4o-mini",
                    "provider": "openai",
                    "temperature": 0.1,
                    "max_tokens": 2048,
                }
            },
        }
        project: dict[str, Any] = {
            "models": {
                "extract": {
                    "temperature": 0.5,
                }
            }
        }
        defaults_path = tmp_path / "defaults.yaml"
        project_path = tmp_path / "project.yaml"
        write_yaml(defaults_path, defaults)
        write_yaml(project_path, project)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(project_path),
        )
        result = resolver.resolve()

        assert result["models"]["extract"]["temperature"] == 0.5
        assert result["models"]["extract"]["model"] == "gpt-4o-mini"
        assert result["models"]["extract"]["max_tokens"] == 2048


# ===========================================================================
# AC-T059-5: ConfigResolver.resolve() 返回 dict
# ===========================================================================


class TestResolveReturnType:
    """AC-T059-5: ConfigResolver.resolve() 返回最终合并后的 config dict。"""

    def test_resolve_returns_dict(self, tmp_path: Path) -> None:
        """resolve() 返回 dict[str, Any] 类型。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        result = resolver.resolve()

        assert isinstance(result, dict)

    def test_resolve_contains_default_model_key(self, tmp_path: Path) -> None:
        """resolve() 返回的 dict 包含 default_model 键。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        result = resolver.resolve()

        assert "default_model" in result


# ===========================================================================
# AC-T059-6: 合并结果通过 Pydantic model 验证
# ===========================================================================


class TestPydanticValidation:
    """AC-T059-6: 合并结果通过 Pydantic LLMModelsConfig 验证。"""

    def test_resolve_result_validates_with_pydantic(self, tmp_path: Path) -> None:
        """resolve() 返回的 dict 可通过 LLMModelsConfig.model_validate() 验证。"""
        from intellisource.config.llm_schema import LLMModelsConfig

        defaults_path = tmp_path / "defaults.yaml"
        project_path = tmp_path / "project.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        write_yaml(project_path, PROJECT_CONFIG)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(project_path),
        )
        result = resolver.resolve()

        validated = LLMModelsConfig.model_validate(result)
        assert validated.default_model.model == "claude-3-haiku-20240307"


# ===========================================================================
# AC-T059-7: 缺少 defaults.yaml 时不报错
# ===========================================================================


class TestMissingDefaults:
    """AC-T059-7: 缺少 defaults.yaml 时仅使用 project config + env vars。"""

    def test_missing_defaults_does_not_raise(self, tmp_path: Path) -> None:
        """defaults.yaml 缺失时 resolve() 不抛出异常。"""
        project_path = tmp_path / "llm_models.yaml"
        write_yaml(project_path, PROJECT_CONFIG)

        resolver = ConfigResolver(
            defaults_path=str(tmp_path / "nonexistent_defaults.yaml"),
            project_path=str(project_path),
        )
        result = resolver.resolve()

        assert isinstance(result, dict)

    def test_missing_defaults_uses_project_config(self, tmp_path: Path) -> None:
        """defaults.yaml 缺失时 resolve() 使用 project config 中的值。"""
        project_path = tmp_path / "llm_models.yaml"
        write_yaml(project_path, PROJECT_CONFIG)

        resolver = ConfigResolver(
            defaults_path=str(tmp_path / "nonexistent_defaults.yaml"),
            project_path=str(project_path),
        )
        result = resolver.resolve()

        assert result["default_model"]["model"] == "claude-3-haiku-20240307"

    def test_missing_both_defaults_and_project_returns_empty_or_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """defaults.yaml 和 project config 均缺失时，仅 env vars 影响结果。"""
        monkeypatch.setenv("IS_DEFAULT_MODEL_MODEL", "env-only-model")

        resolver = ConfigResolver(
            defaults_path=str(tmp_path / "nonexistent_defaults.yaml"),
            project_path=str(tmp_path / "nonexistent_project.yaml"),
        )
        result = resolver.resolve()

        assert result.get("default_model", {}).get("model") == "env-only-model"


# ===========================================================================
# R-001 回归: IS_LLM_* 前缀支持 (AC-T059-3 原文路径)
# ===========================================================================


class TestEnvVarLLMPrefixSupport:
    """R-001: IS_LLM_* 前缀与 IS_* 前缀均可映射到同一配置路径。"""

    def test_is_llm_default_model_maps_to_default_model_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """IS_LLM_DEFAULT_MODEL=foo → config['default_model']['model'] == 'foo'。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        monkeypatch.setenv("IS_LLM_DEFAULT_MODEL", "foo")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        result = resolver.resolve()

        assert result["default_model"]["model"] == "foo"

    def test_is_default_model_model_maps_to_default_model_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """IS_DEFAULT_MODEL_MODEL=bar → default_model.model（既有路径）。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        monkeypatch.setenv("IS_DEFAULT_MODEL_MODEL", "bar")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        result = resolver.resolve()

        assert result["default_model"]["model"] == "bar"

    def test_is_llm_models_extract_model_maps_to_models_extract_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """IS_LLM_MODELS_EXTRACT_MODEL=baz → models.extract.model。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        monkeypatch.setenv("IS_LLM_MODELS_EXTRACT_MODEL", "baz")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        result = resolver.resolve()

        assert result["models"]["extract"]["model"] == "baz"

    def test_is_llm_default_model_provider_maps_to_provider_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """IS_LLM_DEFAULT_MODEL_PROVIDER=anthropic maps to default_model.provider。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        monkeypatch.setenv("IS_LLM_DEFAULT_MODEL_PROVIDER", "anthropic")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        result = resolver.resolve()

        assert result["default_model"]["provider"] == "anthropic"


# ===========================================================================
# R-002 回归: 非 dict leaf 覆盖防护（env var 白名单 + 安全拒绝）
# ===========================================================================


class TestEnvVarOverwriteProtection:
    """R-002: 贪婪前缀匹配碰撞到非 dict leaf 时拒绝覆盖并记录 warning。"""

    def test_env_var_collision_does_not_overwrite_non_dict_leaf(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """IS_DEFAULT_MODEL_PROVIDER_API_KEY 不修改 default_model.provider。"""
        from structlog.testing import capture_logs

        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        monkeypatch.setenv("IS_DEFAULT_MODEL_PROVIDER_API_KEY", "sk-secret")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        with capture_logs() as logs:
            result = resolver.resolve()

        # provider 字段不被覆盖
        assert result["default_model"]["provider"] == "openai"
        # 记录了 warning
        assert any("skipped" in e["event"].lower() for e in logs)

    def test_unknown_is_prefix_env_var_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """不以已知顶层 key 开头的 IS_* 变量被静默忽略，不写入 config。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        monkeypatch.setenv("IS_UNKNOWN_SECTION_VALUE", "should_not_appear")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        result = resolver.resolve()

        assert "unknown_section" not in result


# ===========================================================================
# R-003 回归: 畸形 YAML 抛出 ValueError
# ===========================================================================


class TestMalformedYamlError:
    """R-003: 畸形 YAML 文件使 resolve() 抛出 ValueError。"""

    def test_malformed_defaults_yaml_raises_value_error(self, tmp_path: Path) -> None:
        """defaults.yaml 内容格式错误时 resolve() 抛出 ValueError。"""
        defaults_path = tmp_path / "defaults.yaml"
        defaults_path.write_text("key: [unclosed")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
        )
        with pytest.raises(ValueError, match="Malformed YAML"):
            resolver.resolve()

    def test_malformed_project_yaml_raises_value_error(self, tmp_path: Path) -> None:
        """project config YAML 内容格式错误时 resolve() 抛出 ValueError。"""
        defaults_path = tmp_path / "defaults.yaml"
        project_path = tmp_path / "project.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        project_path.write_text("models: {bad: [unclosed")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(project_path),
        )
        with pytest.raises(ValueError, match="Malformed YAML"):
            resolver.resolve()


# ===========================================================================
# R-005 回归: ConfigResolver validator 参数
# ===========================================================================


class TestResolverValidatorParameter:
    """R-005: ConfigResolver.validator 参数允许调用方注入 Pydantic 验证。"""

    def test_validator_none_returns_dict_unchanged(self, tmp_path: Path) -> None:
        """validator=None 时 resolve() 正常返回合并 dict。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
            validator=None,
        )
        result = resolver.resolve()

        assert isinstance(result, dict)

    def test_validator_called_with_merged_dict(self, tmp_path: Path) -> None:
        """提供 validator 时，resolve() 在返回前调用 validator(merged_dict)。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)

        captured: list[Any] = []
        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
            validator=lambda d: captured.append(d),
        )
        result = resolver.resolve()

        assert len(captured) == 1
        assert captured[0] == result

    def test_validator_exception_propagates(self, tmp_path: Path) -> None:
        """validator 抛出的异常从 resolve() 透传给调用方。"""
        defaults_path = tmp_path / "defaults.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)

        def failing_validator(d: Any) -> None:
            raise ValueError("schema invalid")

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(tmp_path / "nonexistent.yaml"),
            validator=failing_validator,
        )
        with pytest.raises(ValueError, match="schema invalid"):
            resolver.resolve()

    def test_validator_with_pydantic_llm_schema(self, tmp_path: Path) -> None:
        """validator 注入 LLMModelsConfig 的集成场景（T-061 AC-T059-6）。"""
        from intellisource.config.llm_schema import LLMModelsConfig

        defaults_path = tmp_path / "defaults.yaml"
        project_path = tmp_path / "project.yaml"
        write_yaml(defaults_path, DEFAULTS_CONFIG)
        write_yaml(project_path, PROJECT_CONFIG)

        resolver = ConfigResolver(
            defaults_path=str(defaults_path),
            project_path=str(project_path),
            validator=lambda d: LLMModelsConfig.model_validate(d),
        )
        result = resolver.resolve()

        assert result["default_model"]["model"] == "claude-3-haiku-20240307"
