---
id: "code-review-T-084-r2"
doc_type: code-review
author: reviewer
status: approved
deps: [T-084]
---

# CODE-REVIEW T-084 r2 — r1 复检 + df7b24d delta 扫描

Layer 1 delegated to hook（`PostToolUse Edit` 绑定 `lint_format`；ruff check + mypy --strict 3 文件全部 clean）。

**审查范围**: commit `df7b24d` delta — `pipeline/engine.py` / `agent/factory.py` / `agent/runner.py` / `tests/unit/agent/test_factory.py` / `tests/unit/pipeline/test_engine_middleware.py`

---

## §0 r1 复检

| ID | 等级 | 复检结论 | 说明 |
|----|------|----------|------|
| R-001 | MEDIUM | RESOLVED | `execute_stream` 加入 per-processor try/except；`fail_fast=False` 捕获并累积到 `ctx["errors"]`，`fail_fast=True` re-raise；`TestExecuteStreamFailFastParity` 三个测试覆盖两分支（含后继处理器仍运行、错误字段结构、异常传播）|
| R-002 | MEDIUM | RESOLVED | `factory.py` 加载 `content-process.yaml`（`PipelineConfig.from_yaml`），调用 `_build_processors_from_config`，构造 `PipelineEngine(processors=processors)` 并以 `pipeline_engine=` 传入 `AgentRunner`；`[ASSUMPTION]` 注释到位，指向 T-094；`AgentRunner.__init__` 增加 `pipeline_engine: PipelineEngine | None = None` kwarg，存为 `self._pipeline_engine`；`pipeline_config` 参数现在实际驱动 yaml 路径 |
| R-003 | LOW | RESOLVED | `TestAC5FactoryInstantiatesPipelineEngine` docstring 由"AC-5: build_agent_runner instantiates PipelineEngine **from yaml**"改为"AC-5: build_agent_runner calls PipelineEngine() constructor internally"，不再误称 yaml 加载 |

---

## §1 净增问题扫描（df7b24d delta）

### [R-001] MEDIUM: execute() 与 execute_stream() 的 ctx["errors"] schema 不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `_run_processors`（execute 路径）将错误存为 `list[str]`（`errors.append(str(exc))`），`execute_stream`（流式路径）将错误存为 `list[dict[str, str]]`（`{"processor": ..., "error": ...}`）。同一字段名 `ctx["errors"]` 在两条执行路径下携带不同的 schema，任何读取 `ctx["errors"]` 的下游代码（T-094 集成阶段必然会出现）无法在两条路径之间复用，且当前测试不覆盖跨路径消费场景。
- **建议**: 统一 schema——推荐两条路径均使用 `list[dict[str, str]]`（含 `processor` 和 `error` 字段），`_run_processors` 相应调整（同时更新 `test_engine.py` 中依赖原 `list[str]` 格式的断言）。或者在文档/注释中显式声明两条路径的 schema 差异并在 T-094 前锁定接口契约，但这会给集成阶段埋坑。

### [R-002] LOW: _DEFAULT_PIPELINE_YAML 路径通过 `parent.parent.parent.parent` 硬计算，文件移动即静默失效

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `_DEFAULT_PIPELINE_YAML = Path(__file__).parent.parent.parent.parent / "config" / "pipelines" / "content-process.yaml"` 依赖 `factory.py` 在 `src/intellisource/agent/` 下的固定层级（向上4层到仓库根）。若包结构变更（如模块重命名、目录移动），`_DEFAULT_PIPELINE_YAML` 会指向错误路径；`PipelineConfig.from_yaml` 随即抛出裸 `FileNotFoundError`，错误信息不包含"期望路径"以外的上下文，调试成本高。
- **建议**: 低成本修法：在 `build_agent_runner` 中加断言 `assert _DEFAULT_PIPELINE_YAML.exists(), f"Default pipeline yaml not found: {_DEFAULT_PIPELINE_YAML}"`，让失败在调用点即时可见而非在 `open()` 内部。长远建议通过项目配置（如 `Settings` 类读取环境变量）提供 yaml 路径，使其与物理布局解耦。

### [R-003] LOW: [ASSUMPTION] 标签在 docstring 内混用 `#` 前缀，格式不规范

- **category**: convention
- **root_cause**: self-caused
- **描述**: `_PassThroughProcessor` 和 `_build_processors_from_config` 的 docstring 中，`[ASSUMPTION]` 注释以 `# [ASSUMPTION] yaml step → ...` 形式嵌入，在 Python docstring 散文文本中使用了代码注释的 `#` 前缀。按 COMMON-RULES 约定，docstring 中引用假设应写为 `[ASSUMPTION] yaml step → processor class mapping deferred to T-094`，不带 `#`。
- **建议**: 将两处 docstring 中的 `# [ASSUMPTION]` 改为 `[ASSUMPTION]`。

---

## §2 通过维度汇报

**structure（_PassThroughProcessor + _build_processors_from_config 设计）**: 合理的分阶段设计——`_PassThroughProcessor` 是显式占位符，`[ASSUMPTION]` 标注指向 T-094，不会静默吞掉真实处理器类型（逐步通过 `_PassThroughProcessor` 显式替代，不存在隐式 fallback）。`_build_processors_from_config` 为线性 O(n)，无嵌套复杂度。

**structure（循环依赖）**: factory → `agent.pipeline.PipelineConfig`（仅依赖 `yaml` 和 `typing`，无回头引用）→ 无循环。factory → `pipeline.engine`（已有路径，r1 即合规）。无新增循环依赖。

**test-quality（6 新测试）**: 三个流式 fail_fast 测试非平凡——`test_stream_fail_fast_false_continues_after_exception` 断言 `errors[0]["processor"] == "_RaisingProcessor"` 和 `"boom" in errors[0]["error"]`；`test_stream_fail_fast_false_ok_processor_still_runs` 断言后继处理器实际执行（`order == ["ok"]`）；`test_stream_fail_fast_true_raises_immediately` 用 `pytest.raises(RuntimeError, match="critical error")`。三个 wiring 测试断言 `_pipeline_engine is not None`、类型为 `PipelineEngine`、`len(processors) >= 3`，覆盖自定义 yaml 路径。断言均有效，无空断言。

**error-handling（from_yaml 失败处理）**: `from_yaml` 在文件不存在时传播裸 `FileNotFoundError`，`build_agent_runner` 不捕获，调用方直接收到 OS 层异常——见 R-002。

**complexity（_build_processors_from_config）**: 单层 for 循环，圈复杂度 2，符合要求。

**runner.py TYPE_CHECKING 引用**: `PipelineEngine` 仅在 `TYPE_CHECKING` 块导入，运行时用字符串注解（因有 `from __future__ import annotations`），避免在 runner.py 引入对 pipeline.engine 的运行时循环依赖风险，设计正确。

---

## §3 问题汇总

| ID | 严重等级 | category | 描述摘要 |
|----|----------|----------|----------|
| R-001 | MEDIUM | consistency | `execute()` 存 `list[str]`，`execute_stream()` 存 `list[dict]`，同字段 `ctx["errors"]` schema 分叉 |
| R-002 | LOW | error-handling | `_DEFAULT_PIPELINE_YAML` 层级硬算；文件不存在时抛裸 `FileNotFoundError`，无上下文 |
| R-003 | LOW | convention | docstring 中 `[ASSUMPTION]` 混用 `#` 前缀 |

---

## 最终判定

r1 三个问题（R-001 MEDIUM execute_stream fail_fast parity、R-002 MEDIUM PipelineEngine 接线缺口、R-003 LOW docstring 误导）全部 RESOLVED。净增 1 MEDIUM（ctx["errors"] schema 不一致）和 2 LOW。无 CRITICAL / HIGH。

**verdict: approved_with_notes**
