---
id: "code-review-T-060-r3"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-060"]
---

# CODE-REVIEW T-060: LLM 统计仪表盘 API — r3

**Layer 1**: PASS（ruff check 对 T-060 六个文件 clean；test_content_routes.py:201 / :809 的两处 E501 经 git 记录确认为 commit a54f160d 引入的 pre-existing 问题，不纳入 T-060 责任范围）
**Layer 2**: AI 语义审查（聚焦 r2 残留问题 R-003/R-004/R-005/R-006 闭环验证 + 新引入问题评估）
**verdict**: approved_with_notes

---

## r2 → r3 修订闭环验证

### R-003（MEDIUM, test-quality）— 已闭环

**修复验证**: 新增 `tests/unit/storage/test_llm_call_log_repository.py`，共 4 个 repository-level SQL 集成测试（真实 SQLite in-memory session，无 mock）：

- `TestGlobalAggregation.test_global_totals_with_multiple_records`: 3 条记录，断言 `total_calls=3`、`total_input_tokens=600`、`total_output_tokens=300`、`total_tokens=900`、`avg_latency_ms≈400.0`——有效断言，覆盖全局聚合路径。
- `TestByModelGroupBy.test_by_model_grouping_and_error_rate`: model-a（3 calls，1 error）和 model-b（2 calls，0 errors），断言 `error_rate` 类型为 `float`、`abs(error_rate - 1/3) < 0.001`、model-b `error_rate == 0.0`——真实执行 CASE WHEN 浮点路径，R-004 浮点除法风险也在此被覆盖。
- `TestByDateGroupBy.test_by_date_groups_across_days`: 使用 `now - timedelta(days=N)` 动态生成跨日期数据（在 30 天窗口内），断言 `len(by_date) >= 2`、日期列表升序、两个日期的 `call_count` 和 `total_tokens` 精确值——覆盖 GROUP BY DATE 和 ORDER BY 逻辑。
- `TestEmptyTable.test_empty_table_returns_zero_aggregates`: 空表下 `get_stats()` 不报错，断言全部零聚合和空列表——覆盖 AC-T060-6 真实 SQL 路径（`func.coalesce` + `result.one()` 在全空结果时的行为）。

运行验证：4 PASSED（见 orchestrator 上下文），全量回归 1739 PASSED。

**结论**: R-003 闭环，不再以同等级重报。

---

### R-004（MEDIUM, consistency）— 已闭环

**修复验证**: `llm_call_log.py:85-87` 已改为：

```python
error_expr = case(
    (LLMCallLog.status == "error", 1.0),
    else_=0.0,
)
```

浮点字面量 `1.0`/`0.0` 替代整数 `1`/`0`，消除 SQLite AVG 对全整数列返回整数的 dialect 歧义。`TestByModelGroupBy` 测试已在真实 SQLite 执行路径上断言 `isinstance(ma["error_rate"], float)`——覆盖了原来缺失的运行时类型验证。

**结论**: R-004 闭环，不再以同等级重报。

---

### R-005（LOW, consistency, upstream-caused）— 已闭环

**修复验证**: 据 orchestrator 报告，`docs/arch/arch-intellisource-v1-api.md` §API-017 已由 architect agent 完成 amendment：
- `by_model[]`: `calls` → `call_count`，`tokens` 拆为 `input_tokens` + `output_tokens`，移除 per-model `avg_latency_ms`
- `by_date[]`: `calls` → `call_count`，`tokens` → `total_tokens`（含口径注释）
- `query`: 移除 `date_from`/`date_to`，新增 `call_type`
- `response`: 新增 `400` 错误码描述

doc-index 已增量刷新（57 docs / 138 xrefs，0 orphans / 0 stale / 0 xref errors）。

**结论**: R-005 闭环（upstream-caused amendment 完成），不再以同等级重报。

---

### R-006 — 升级为 MEDIUM（见下方问题列表）

r1 记录 router self-report 失真（LOW），r2 新增 ruff scope 失真（orchestrator 于主线程 ruff format 修复），现为第二次同模式出现。按审查要求升级为 MEDIUM。

---

## 本轮新发现问题

### [R-007] LOW: TestByDateGroupBy 测试存在死代码段

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `test_by_date_groups_across_days` 函数体第一段（第 256–272 行）向 session 插入带有硬编码 2025-06-01/06-02 时间戳的数据并 `flush()`，但随即在第 279 行调用 `session.rollback()` 将其全部丢弃，然后重新用 `now - timedelta(days=N)` 动态时间戳插入相同结构的数据。第一段插入的数据从未对测试断言产生任何影响——这是典型的测试死代码。该结构增加了代码阅读成本（读者需理解 rollback 意图），注释（第 275–278 行）虽然解释了原因，但仍遗留了不必要的代码路径。此问题不影响测试正确性，4 个测试均 PASSED。
- **建议**: 移除第 256–272 行及对应 `flush()`，直接从 `now - timedelta(days=N)` 开始构造测试数据，并在必要时保留说明注释。这是可在后续 chore commit 中处理的轻度清理项。

---

## 持续问题（已升级）

### [R-006] MEDIUM: implementer self-report 失真——连续两轮同模式（升级）

- **category**: convention
- **root_cause**: self-caused
- **描述**: r1 报告记录了 router 文件 self-report 失真（LOW）；r2 修订中 implementer 自报 "ruff check + format src/ clean"，但新增的 `tests/unit/storage/test_llm_call_log_repository.py` 含 16 处 E501 line-too-long，由 orchestrator 主线程发现后机械执行 `ruff format` 修复。这是第二次出现"声称覆盖范围与实际覆盖范围错位"的同类模式（r1: 路由文件变更遗漏申报；r2: lint 范围仅覆盖 src/ 而遗漏 tests/）。连续两轮同模式构成系统性过程纪律问题，升级为 MEDIUM。
- **建议**: 在 sprint-7 结束 retrospective 中将此问题作为 EXP（Experience）经验条目记录，建议方向：implementer 在 summary 中明确列出 lint 实际覆盖范围（含 `tests/` 目录），或统一约定 lint 命令覆盖全项目（`ruff check . && ruff format .`）而非仅 `src/`。不要求代码修改，retrospective 处理即可。

---

### [N-001] 观察: test_content_routes.py 中 mock 数据使用旧字段名（不纳入 T-060 计分）

`test_content_routes.py:TestLLMStatsEndpoint.test_llm_stats_returns_aggregated_data`（行 695–710）的 mock 响应中，`by_model` 条目使用旧字段名 `calls`、`tokens`、`avg_latency_ms`（per-model），`by_date` 条目使用 `calls`、`tokens`，与当前实现的 `call_count`、`input_tokens`/`output_tokens`、`total_tokens` 不一致。由于测试断言（行 719–729）仅检查顶级字段（`period`、`total_calls` 等），未断言 `by_model`/`by_date` 内部字段，测试不因此失败，21 PASSED 确认。

此 mock 数据的陈旧性属于 T-042 范围内的遗留问题（该测试归属 AC-T042-5），与 T-060 同步修复了 arch amendment 但未同步修复 test_content_routes.py 中的 mock fixture。不计入 T-060 self-caused 计数，但 orchestrator 可在后续 chore 中一并清理。

---

## 三态判定

r2 全部 MEDIUM/HIGH 残留问题（R-003/R-004）已闭环；R-005（LOW/upstream-caused）已完成 amendment；R-006 升级为 MEDIUM；新发现 R-007（LOW）。不存在 CRITICAL 或 HIGH 问题，判定为 **approved_with_notes**。

| 严重等级 | 数量 | 问题编号 |
|---------|-----|--------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 1 | R-006（convention/self-caused，升级自 LOW） |
| LOW | 1 | R-007（test-quality/self-caused，新发现） |

## 归因统计（本轮）

| root_cause | 数量 |
|-----------|-----|
| self-caused | 2 (R-006 升级, R-007 新发现) |
| upstream-caused | 0 |

## 运行时质量指标

| 指标 | 结果 |
|-----|------|
| tests/unit/api/test_llm_routes.py | 15/15 PASSED |
| tests/unit/storage/test_llm_call_log_repository.py | 4/4 PASSED |
| tests/unit/api/test_content_routes.py | 21/21 PASSED |
| 全量回归 | 1739 PASSED |
| mypy --strict (T-060 文件) | 0 errors |
| ruff check + format (T-060 6 个文件) | clean |

## R-006 升级建议（致 orchestrator）

本次 R-006 升级为 MEDIUM 标志着"implementer self-report 失真"已连续两轮（r1 router 变更遗漏 + r2 lint 范围错位）同模式出现，且累计 self-caused review 问题数已逼近 `RETRO_TRIGGER_SELF_CAUSED=5` 阈值。建议 orchestrator 在 sprint-7 结束时确保 retrospective 将此作为 EXP 条目，重点提炼：

1. lint 命令的覆盖范围应统一为全项目（`. ` 或明确包含 `tests/`）
2. implementer summary 对文件变更清单的申报准确性
