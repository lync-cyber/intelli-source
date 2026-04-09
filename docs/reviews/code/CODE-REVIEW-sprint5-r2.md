# CODE-REVIEW-sprint5-r2

- **Sprint**: Sprint 5
- **审查轮次**: r2
- **审查范围**: 针对 r1 报告中 1 HIGH + 5 MEDIUM 问题的修复验证
- **审查日期**: 2026-04-09
- **测试结果**: 1563 passed, 0 failed, 18 warnings
- **mypy --strict**: Success, no issues found in 4 source files

---

## 审查结论: approved

所有 HIGH 和 MEDIUM 问题已正确修复，无新增问题。r1 中的 4 个 LOW 问题(R-007 ~ R-010)风险可控，不阻塞交付。

---

## r1 问题修复验证

### [R-001] HIGH: CLI 认证头与 AuthMiddleware 不一致 -- VERIFIED FIXED

- **修复内容**: `cli/main.py` 第40行 `_get_headers()` 现已发送 `X-API-Key` 头，与 `AuthMiddleware` 检查的 `x-api-key` 头和 arch#§5.2 规范一致。
- **验证**: 代码确认 `headers["X-API-Key"] = api_key`，认证链路完整。

### [R-002] MEDIUM: CLI task trigger 使用错误的 API 路径 -- VERIFIED FIXED

- **修复内容**: `cli/main.py` 第176行 URL 改为 `/api/v1/tasks/collect`，第177行 payload 添加 `trigger_type: "manual"` 字段。
- **验证**: URL 与 `tasks.py` 的 `POST /tasks/collect` 端点一致，payload 包含 `CollectRequest` 要求的 `source_id` 和 `trigger_type` 两个必填字段。

### [R-003] MEDIUM: TracingMiddleware 未注入 trace_id 到日志上下文 -- VERIFIED FIXED

- **修复内容**: `middleware.py` 第18-20行新增 `trace_id_ctx: contextvars.ContextVar[str]`，第79行在请求处理前调用 `trace_id_ctx.set(trace_id)` 注入日志上下文。
- **验证**: trace_id 现同时注入到响应头和 contextvars，满足 AC-T043-5 要求。

### [R-004] MEDIUM: chat_session.py 上下文压缩缺少 [ASSUMPTION] 标注 -- VERIFIED FIXED

- **修复内容**: `chat_session.py` 第72-73行 `compact_context` 方法 docstring 添加 `[ASSUMPTION]` 注释，说明当前为简化实现，未来版本将接入 LLM 压缩。
- **验证**: 标注清晰，符合 COMMON-RULES 约定。

### [R-005] MEDIUM: /api/v1/health 端点不存在 -- VERIFIED FIXED

- **修复内容**: `main.py` 第154-156行新增 `@app.get("/api/v1/health")` 端点，与根级 `/health` 并存。
- **验证**: AC-T042-6 要求的路径现已可达。

### [R-006] MEDIUM: _AutoLifespanApp 在每次请求后触发 shutdown -- VERIFIED FIXED

- **修复内容**: `main.py` 第91-114行重构 `_AutoLifespanApp`。`__call__` 方法仅在首次非 lifespan 请求时触发 startup（第98-104行），不再在请求后触发 shutdown。新增显式 `shutdown()` 方法（第108-114行）供测试客户端退出时调用。
- **验证**: 测试文件 `test_app_entry.py` 第249行调用 `await app.shutdown()` 显式触发清理，设计合理。

---

## r1 未修复的 LOW 问题（不影响判定）

以下 LOW 问题在 r1 中已识别，未要求修复，风险评估不变:

- **R-007 LOW**: MetricsCollector 单例测试间状态共享 -- 已有 fixture 重置，风险可控
- **R-008 LOW**: XML 解析使用 xml.etree.ElementTree -- 受控场景，已有 noqa 标注
- **R-009 LOW**: CLI trigger_type 字段 -- 已在 R-002 修复中一并解决
- **R-010 LOW**: 源代码文件路径与 dev-plan 交付物不一致 -- 文档层面偏差，不影响功能

注: R-009 在 r2 中确认已随 R-002 一并修复（payload 已包含 `trigger_type: "manual"`）。

---

## 统计摘要

| 严重等级 | r1 数量 | r2 已修复 | r2 残留 |
|---------|--------|----------|--------|
| CRITICAL | 0 | - | 0 |
| HIGH | 1 | 1 | 0 |
| MEDIUM | 5 | 5 | 0 |
| LOW | 4 | 1 (R-009) | 3 |
| **合计** | **10** | **7** | **3** |

---

## 正面发现

- 全部修复准确到位，无过度修复或引入新问题
- _AutoLifespanApp 重构设计合理，显式 shutdown() 方法比原 auto-shutdown 更可控
- TracingMiddleware 的 contextvars 注入实现简洁，模块级 ContextVar 声明便于其他模块消费
- 测试文件同步更新（test_app_entry.py 第249行调用 app.shutdown()），保持测试与实现一致
