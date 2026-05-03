---
id: "code-review-T-060-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-060"]
---

# CODE-REVIEW T-060: LLM 统计仪表盘 API — r1

**Layer 1**: PASS（ruff check + ruff format 零 finding）
**Layer 2**: AI 语义审查（全维度）
**verdict**: needs_revision

---

## 问题列表

### [R-001] HIGH: invalid period 值触发 500 而非 400
- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `LLMCallLogRepository.get_stats()` 对无效 `period` 值（如 `period=hour`）抛出原始 `ValueError`。路由层 `llm_stats()` 没有 `try/except` 捕获该异常，FastAPI 会将未捕获的 `ValueError` 转化为 HTTP 500 而非客户端期望的 400。项目内其他路由（`sources.py:179`、`tasks.py:107`）均以 `try/except ValueError → JSONResponse(400)` 模式处理，本路由是孤例。arch#§5.3 统一错误响应格式要求返回 `{"error": {"code": ..., "message": ...}}`，而 FastAPI 的 500 响应体不符合该格式。测试套件中无任何测试覆盖 `period=invalid` 路径（grep `invalid|400|422` 无命中）。

- **建议**: 在路由层捕获 `ValueError` 并返回 `HTTPException(status_code=400, detail=...)` 或 `JSONResponse(status_code=400, ...)`，格式对齐 arch#§5.3 统一错误响应。同时在 `test_llm_routes.py` 补充一个测试用例验证 `period=invalid` 返回 HTTP 400。

---

### [R-002] HIGH: date_from / date_to 参数静默无效
- **category**: completeness
- **root_cause**: self-caused
- **描述**: 路由声明了 `date_from: str | None = None` 和 `date_to: str | None = None` 查询参数，repository `get_stats()` 也接受同名参数，但两处均未将其转换为 SQL 过滤条件——`base_filters` 列表构建逻辑（llm_call_log.py 第 47–51 行）完全没有 `date_from`/`date_to` 的分支。arch#API-017 将 `date_from` / `date_to` 定义为 `query: datetime, required: false`，用户传入后会被静默忽略，得到的响应与不传时完全相同，且无任何错误或警告提示。这违反"最小惊奇原则"，并且是与 API 契约的功能性缺失（非仅命名偏差）。

- **建议**: 若本 Sprint 范围内不实现 `date_from`/`date_to` 过滤，应在路由和 repository 签名中**移除**这两个参数（避免对调用方撒谎），或者将其实现为实际过滤条件（解析 ISO 字符串为 `datetime` 后追加 `LLMCallLog.created_at >= date_from` 等条件）。如选择移除，需同步更新 arch#API-017 注记（可在 sprint-7 末 amendment 时一并处理）。

---

### [R-003] MEDIUM: repository SQL 聚合逻辑缺乏 SQL-level 测试
- **category**: test-quality
- **root_cause**: self-caused
- **描述**: 14 个测试全部为路由层 mock 测试（patch `LLMCallLogRepository`），repository 内的 SQL 聚合逻辑（CASE WHEN status='error'、GROUP BY model、GROUP BY date、func.coalesce 空数据兜底、`_get_by_model` / `_get_by_date` 的拼装逻辑）从未被实际数据库执行验证过。对比项目惯例：其他所有 repository（`SourceRepository`、`ContentRepository`、`TaskRepository`、`PushRepository`、`SubscriptionRepository`）均在 `tests/unit/storage/test_repositories.py` 中以 SQLite in-memory + `aiosqlite` 执行真实 SQL。AC-T060-6（无数据时返回空聚合）在 repository 层从未以实际空表跑过 `result.one()` 路径，若 SQLAlchemy 结果集行为不符预期（如 `one()` 在全空表 `func.count()=0` 时返回 None 而非含零值的行），会在生产运行时才暴露。

- **建议**: 在 `tests/unit/storage/` 新增 `test_llm_call_log_repository.py`，复用现有 SQLite fixture（`SQLITE_TEST_URL` + `create_async_engine`），至少覆盖：全空表 `get_stats()` 不报错且返回 `total_calls=0`；`_get_by_model` 正确分组计数；`_get_by_date` 正确按日期排序；`error_rate` 计算在有/无 error 记录时均返回预期浮点数。

---

### [R-004] MEDIUM: error_rate AVG(CASE WHEN) 在 SQLite 中整数除法风险
- **category**: consistency
- **root_cause**: self-caused
- **描述**: `func.avg(case((LLMCallLog.status == "error", 1), else_=0))` 在 SQLite 中，`CASE WHEN` 返回整数 1 或 0，`AVG` 对全整数列在某些 SQLite 版本中返回整数类型，导致 `error_rate` 在错误率为 0 时可能返回整数 `0` 而非浮点 `0.0`。代码中的 `float(r.error_rate) if r.error_rate is not None else 0.0` 可以缓解此问题，但在单元测试中 repository 未用真实 SQL 跑过（见 R-003），所以此路径仅在生产 PostgreSQL 上验证过隐性路径（mypy 无法检测运行时类型）。当项目切换到 SQLite 开发测试场景或非 PostgreSQL 部署时，此处行为不确定。

- **建议**: 可将表达式改为 `func.avg(case((LLMCallLog.status == "error", 1.0), else_=0.0))` 强制浮点输入以消除 dialect 歧义；或在 repository-level 测试（R-003 建议）中显式断言 `error_rate` 类型为 `float` 且值在 `[0.0, 1.0]` 范围内。

---

### [R-005] LOW: arch#API-017 by_model / by_date 字段命名偏差（已知，需 amendment）
- **category**: consistency
- **root_cause**: upstream-caused
- **描述**: arch#API-017 定义 `by_model[].calls`（整型）和 `by_model[].tokens`（整型），但实现使用 `call_count`、`input_tokens`、`output_tokens`（对齐 AC 中的 testable contract）。同样，`by_date[].calls` vs 实现的 `call_count`，`by_date[].tokens` vs 实现的 `total_tokens`。任务上下文已明确此偏差由 AC 驱动（AC 为 testable contract 优先）。不阻断本任务，但 arch 文档与实现之间存在持续的查阅混淆风险。

- **建议**: 在 sprint-7 末尾或 Sprint 8 启动前，对 arch-intellisource-v1-api#§3.API-017 的 `by_model.item_fields` 和 `by_date.item_fields` 做 amendment，将 `calls` 改为 `call_count`，`tokens` 拆分为 `input_tokens`/`output_tokens`（by_model）和 `total_tokens`（by_date），与实现对齐。

---

### [R-006] LOW: implementer self-report 与 git diff 轻微失真
- **category**: convention
- **root_cause**: self-caused
- **描述**: implementer 在 summary 中表述"路由文件已是正确实现，无需变更"，但 git diff 显示 `src/intellisource/api/routers/llm.py` 确实被修改（删除内联 stub repository、删除 placeholder session、改为 `Depends(get_db_session)` + 真实 `LLMCallLogRepository`）。这是一次轻度 self-report 失真，不影响交付物质量，但在本项目 retrospective 阈值监控临近 `RETRO_TRIGGER_SELF_CAUSED=5` 的背景下需记录。该模式此前在 T-058 also self-report 中已出现。

- **建议**: implementer 在 summary 中应如实列出被改动的文件及改动性质，不遗漏实际发生的变更。此为过程纪律，无需代码修改，但纳入 retrospective 计数作为 soft 信号监控（本条 root_cause 为 self-caused，severity LOW，不计入 RETRO hard+review 计数）。

---

## 三态判定

存在 HIGH 级别问题（R-001、R-002），判定为 **needs_revision**。

| 严重等级 | 数量 | 问题编号 |
|---------|-----|--------|
| CRITICAL | 0 | — |
| HIGH | 2 | R-001（error-handling）, R-002（completeness） |
| MEDIUM | 2 | R-003（test-quality）, R-004（consistency） |
| LOW | 2 | R-005（consistency/upstream-caused）, R-006（convention/self-caused） |

## 归因统计

| root_cause | 数量 |
|-----------|-----|
| self-caused | 5 (R-001, R-002, R-003, R-004, R-006) |
| upstream-caused | 1 (R-005) |

## 修订重点（revision 时仅需修复 HIGH）

1. **R-001**: `llm.py` 路由层捕获 `ValueError` → HTTP 400 + 对应测试用例
2. **R-002**: 移除或实现 `date_from`/`date_to` 参数——二选一，不可维持当前"接受但忽略"状态

MEDIUM 问题（R-003、R-004）建议在 revision 周期内一并处理，但不构成阻断条件。
