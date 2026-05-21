---
id: "code-review-T-084-r3"
doc_type: code-review
author: reviewer
status: approved
deps: [T-084]
---

# CODE-REVIEW T-084 r3 — r2 复检 + c7a9ed9 delta 扫描

Layer 1 delegated to hook（`PostToolUse Edit` 绑定 `lint_format`；ruff check + mypy --strict 全部 clean）。

**审查范围**: commit `c7a9ed9` delta — `pipeline/engine.py` / `agent/factory.py` / `tests/unit/pipeline/test_engine_middleware.py`

---

## §0 r2 复检

| ID | 等级 | 复检结论 | 说明 |
|----|------|----------|------|
| R-001 | MEDIUM | RESOLVED | `_run_processors` 改为 `list[dict[str, str]]`，存 `{"processor": type(processor).__name__, "error": str(exc)}`；两条路径 schema 对齐。`TestCtxErrorsSchemaConsistency` 三个测试存在并全部 PASS。 |
| R-002 | LOW | RESOLVED | `build_agent_runner` 将 `pipeline_config` 先解析为 `Path`，调用 `resolved_yaml.exists()` 检查，不存在时 `raise FileNotFoundError(f"Pipeline yaml not found: {resolved_yaml.resolve()}")`，错误信息包含 resolved 绝对路径。 |
| R-003 | LOW | RESOLVED | `_PassThroughProcessor` docstring 和 `_build_processors_from_config` docstring 均已改为 `[ASSUMPTION] yaml step → processor class mapping deferred to T-094`，无 `#` 前缀，与 `search/hybrid.py` 风格一致。 |

---

## §1 net-new 扫描

### consistency：旧 `list[str]` 测试未被改动，与新 schema 兼容

`tests/unit/pipeline/test_engine.py` 中两处 `ctx.get("errors")` 断言仅检查 `errors is not None` 和 `len(errors) >= 2`，未对元素类型做假设，与 `list[dict]` 兼容。全量 351 测试 PASS，无回归。

### error-handling：`from_yaml` parse 错误独立关注点

`build_agent_runner` 的 `exists()` 检查覆盖"文件不存在"场景，报错信息可读。`from_yaml` 内部的 yaml 解析错误（如 yaml 格式损坏）仍作为裸异常向上传播，调用方会收到 `yaml.YAMLError`，不附带额外上下文。这属于独立的改善空间，不属于 r2 R-002 修复范畴，且 T-094 集成层更适合决定是否包装该异常。此条不计为新问题。

### test-quality：三个 schema 一致性测试质量验证

- `test_execute_errors_are_list_of_dicts`：用 `_RaisingProcessor("p", "oops")` 触发真实异常；断言 `isinstance(entry, dict)`、`"processor" in entry`、`"error" in entry`、`entry["processor"] == "_RaisingProcessor"`、`"oops" in entry["error"]`。断言有效，非平凡。
- `test_execute_stream_errors_are_list_of_dicts`：镜像 execute() 测试，采用 async for 收集所有 yield，读取第一个 context 的 errors。断言结构与 execute 路径测试完全对称，跨路径 schema 对比有效。
- `test_execute_multiple_errors_all_dicts`：用 2 个 `_RaisingProcessor` 验证多错误场景；遍历所有 entry 断言 `isinstance(entry, dict)` 和 `{"processor", "error"} <= entry.keys()`。覆盖了 r2 R-001 中"下游无法统一消费"的核心风险。

三个测试全部 PASS。无空断言、无自我验证式断言。

### convention / comment style：`_build_processors_from_config` docstring 语句结构

`_build_processors_from_config` docstring 末行 `[ASSUMPTION] yaml step → processor class mapping deferred to T-094` 跟在散文句子 `Uses _PassThroughProcessor for each step; concrete class lookup is` 之后，形成语法上不完整的悬挂结构（"lookup is [ASSUMPTION]..."）。语义清晰但句式略显中断。属于 LOW 级别的可读性改善，不阻塞交付。鉴于 r2 已要求修复 `#` 前缀问题且已正确完成，此处建议在下一自然修改机会中将两行改为独立段落（如加空行后写 `[ASSUMPTION] processor class lookup deferred to T-094`），不需额外审查轮次。

---

## §2 通过维度

**consistency（跨路径 schema）**: `_run_processors`（execute 路径）与 `execute_stream` 路径的 `ctx["errors"]` 现在均产出 `list[dict[str, str]]`，`processor` 和 `error` 字段名一致。现有消费测试兼容，无破坏性回归。

**error-handling（yaml 路径检查）**: `resolved_yaml.exists()` + `FileNotFoundError` 携带 resolved 绝对路径，调试可读性大幅提升。

**test-quality（新增 3 测试）**: 见 §1，断言有效，跨路径对比覆盖正确。

**convention（ASSUMPTION 标记）**: 两处 docstring 的 `[ASSUMPTION]` 已对齐项目约定，无 `#` 前缀。

**test-quality（test_engine.py 兼容性）**: 旧测试 `test_error_recorded_in_context` 与 `test_multiple_errors_all_recorded` 仅断言长度，与新 `list[dict]` schema 完全兼容。

---

## §3 问题汇总

| ID | 严重等级 | category | 描述摘要 |
|----|----------|----------|----------|
| — | — | — | 无新增 CRITICAL / HIGH / MEDIUM 问题 |

（docstring 悬挂语句见 §1，LOW 级别，建议下次顺手改，不计入问题列表）

---

## 最终判定

r2 三个问题（R-001 MEDIUM ctx errors schema 分叉、R-002 LOW yaml 路径无 exists 检查、R-003 LOW ASSUMPTION 标记格式）全部 RESOLVED。净增扫描无 CRITICAL / HIGH / MEDIUM 问题。351 个目标测试全部 PASS。

**verdict: approved**

---

> 注：本轮为第三次审查。如后续仍有遗留 LOW 级别项（如上述 docstring 悬挂语句），建议 orchestrator 接受当前 approved 状态，在下一次自然修改时顺带修复，避免为纯粹风格问题开启新的 revision 轮次。
