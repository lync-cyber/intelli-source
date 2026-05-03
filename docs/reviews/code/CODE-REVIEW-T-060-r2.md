---
id: "code-review-T-060-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-060"]
---

# CODE-REVIEW T-060: LLM 统计仪表盘 API — r2

**Layer 1**: PASS（ruff check + ruff format 零 finding，由 orchestrator 运行时验证）
**Layer 2**: AI 语义审查（聚焦 R-001 / R-002 闭环验证 + 新引入问题评估；R-003~R-006 延续）
**verdict**: approved_with_notes

---

## r1 → r2 修订闭环验证

### R-001（HIGH, error-handling）— 已闭环

**修复验证**: `llm.py` 路由层新增 `try/except ValueError as exc` 块，捕获 repository 抛出的 `ValueError` 并以 `JSONResponse(status_code=400, content={"detail": str(exc)})` 返回。

- 修复形式与项目既有惯例完全一致（`sources.py:180`、`tasks.py:108`、`subscriptions.py:112` 同模式）
- 新增测试 `TestInvalidPeriod.test_invalid_period_returns_400`：mock repo 抛 `ValueError`，断言 `status_code=400` 且 `body["detail"]` 含错误关键词 — 断言有效，逻辑正确
- 运行时验证：15/15 target tests PASSED（含新增测试），1735 全量回归 PASSED，mypy --strict 0 errors
- **结论**: R-001 闭环，不再以 HIGH 重报

### R-002（HIGH, completeness）— 已闭环

**修复验证**: 路由签名移除 `date_from: str | None = None` 和 `date_to: str | None = None` 两个查询参数；repository `get_stats()` 签名同步移除同名参数；`base_filters` 构建逻辑不再引用这两个参数。两处均已对齐，不再存在"接受参数但静默忽略"的情形。

- 路由现仅接受 `period`、`model`、`call_type` 三个查询参数，与实际 SQL 过滤逻辑一致
- **结论**: R-002 闭环，不再以 HIGH 重报

---

## 残留问题（MEDIUM / LOW，本轮不强制修复）

### [R-003] MEDIUM: repository SQL 聚合逻辑缺乏 SQL-level 测试
- **category**: test-quality
- **root_cause**: self-caused
- **描述**: 本轮修订未涉及 repository 层测试。15 个测试全部为路由层 mock 测试（patch `LLMCallLogRepository`），repository 内的 SQL 聚合路径（CASE WHEN error_rate、GROUP BY model/date、`func.coalesce` 空数据兜底、`result.one()` 在全空表场景下的行为）仍未经真实数据库执行验证。对比项目惯例：`SourceRepository`、`ContentRepository`、`TaskRepository` 等均在 `tests/unit/storage/test_repositories.py` 有 SQLite in-memory 测试覆盖。
- **建议**: 在 `tests/unit/storage/` 新增 `test_llm_call_log_repository.py`，复用现有 SQLite fixture（`SQLITE_TEST_URL` + `create_async_engine`），至少覆盖：全空表 `get_stats()` 不报错且 `total_calls=0`；`_get_by_model` 正确分组计数；`_get_by_date` 正确按日期排序；`error_rate` 在有/无 error 记录时均返回预期浮点数。

---

### [R-004] MEDIUM: error_rate AVG(CASE WHEN) 整数除法风险
- **category**: consistency
- **root_cause**: self-caused
- **描述**: `func.avg(case((LLMCallLog.status == "error", 1), else_=0))` 中 CASE WHEN 返回整数，在 SQLite 某些版本下 AVG 对全整数列可能返回整数类型，导致 `error_rate=0` 而非 `0.0`。代码中的 `float(r.error_rate) if r.error_rate is not None else 0.0` 可缓解，但 repository 层无真实 SQL 测试（见 R-003），此路径在项目切换 SQLite 测试场景时存在隐性风险。
- **建议**: 将表达式改为 `func.avg(case((LLMCallLog.status == "error", 1.0), else_=0.0))` 强制浮点输入；或在 R-003 建议的 repository 测试中显式断言 `error_rate` 类型为 `float` 且值在 `[0.0, 1.0]` 范围内。

---

### [R-005] LOW: arch#API-017 字段命名偏差（已知，upstream-caused）
- **category**: consistency
- **root_cause**: upstream-caused
- **描述**: arch#API-017 定义 `by_model[].calls`（整型）、`by_model[].tokens`（整型），实现使用 `call_count`、`input_tokens`、`output_tokens`（对齐 AC testable contract）；`by_date[].calls` vs 实现的 `call_count`，`by_date[].tokens` vs 实现的 `total_tokens`。本轮修订未改变此偏差。
- **建议**: 在 sprint-7 末尾或 Sprint 8 启动前，对 `arch-intellisource-v1-api#§3.API-017` 的 `by_model.item_fields` 和 `by_date.item_fields` 做 amendment，与实现对齐。

---

### [R-006] LOW: implementer self-report 轻微失真（历史记录，已纳入 retrospective 监控）
- **category**: convention
- **root_cause**: self-caused
- **描述**: r1 报告已记录此问题，属于过程纪律，不要求代码修改。本轮修订未再现同类问题，延续作为 soft 信号留存于报告中。
- **建议**: 无需额外操作，已纳入项目 retrospective 监控（soft 计数，不计入 RETRO hard+review 阈值）。

---

## 三态判定

CRITICAL 和 HIGH 问题已全部闭环（R-001 和 R-002 经修订验证通过），仅存在 MEDIUM 和 LOW 级别问题，判定为 **approved_with_notes**。

| 严重等级 | 数量 | 问题编号 |
|---------|-----|--------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 2 | R-003（test-quality）, R-004（consistency） |
| LOW | 2 | R-005（consistency/upstream-caused）, R-006（convention/self-caused） |

## 归因统计

| root_cause | 数量 |
|-----------|-----|
| self-caused | 3 (R-003, R-004, R-006) |
| upstream-caused | 1 (R-005) |

## 运行时质量指标（orchestrator 已验证）

| 指标 | 结果 |
|-----|------|
| target tests | 15/15 PASSED（14 原有 + 1 新增 `test_invalid_period_returns_400`）|
| 全量回归 | 1735/1735 PASSED（baseline 1734 + 1 new）|
| mypy --strict | 0 errors |
| ruff check + format | clean |
