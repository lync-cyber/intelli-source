# CODE-REVIEW-sprint5-r1

- **Sprint**: Sprint 5
- **审查轮次**: r1
- **审查范围**: 14 source files, 10 test files (T-037 ~ T-046)
- **审查日期**: 2026-04-09
- **测试结果**: 1563 passed, 0 failed, 18 warnings
- **mypy --strict**: Success, no issues found in 14 source files

---

## 审查结论: needs_revision

存在 1 个 HIGH 问题，需修复后重新审查。

---

## 问题列表

### [R-001] HIGH: CLI 认证头与 AuthMiddleware 不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `cli/main.py` 的 `_get_headers()` 发送 `Authorization: Bearer {api_key}` 头（第39-41行），但 `api/middleware.py` 的 `AuthMiddleware` 检查的是 `x-api-key` 头（第28行）。架构文档 arch#§5.2 明确规定使用 `X-API-Key` 请求头进行认证。CLI 发送的认证头永远无法通过 middleware 验证，导致 CLI 在对接真实服务时所有需认证的请求都会被拒绝。
- **建议**: 将 `cli/main.py` 的 `_get_headers()` 修改为发送 `X-API-Key` 头而非 `Authorization: Bearer`，与 arch 规范和 middleware 实现保持一致。

### [R-002] MEDIUM: CLI task trigger 使用错误的 API 路径

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `cli/main.py` 的 `task_trigger` 命令向 `/api/v1/tasks` 发送 POST 请求（第177行），但 `api/routers/tasks.py` 定义的采集触发端点路径为 `POST /api/v1/tasks/collect`（第96行）。CLI 发出的请求会得到 405 Method Not Allowed 响应。
- **建议**: 将 `cli/main.py` 第177行的 URL 从 `/api/v1/tasks` 改为 `/api/v1/tasks/collect`。同时 CLI 发送的 payload 缺少 `trigger_type` 字段（`CollectRequest` 模型要求 `source_id` 和 `trigger_type` 两个字段）。

### [R-003] MEDIUM: TracingMiddleware 未注入 trace_id 到日志上下文

- **category**: completeness
- **root_cause**: self-caused
- **描述**: AC-T043-5 要求 "TracingMiddleware 为每个请求注入 trace_id 到日志上下文和响应头"。当前实现（`middleware.py` 第68-77行）仅将 trace_id 添加到响应头 `X-Trace-ID`，但未注入到 Python logging 上下文（如 `logging.LoggerAdapter` 或 `contextvars`）。这意味着日志中无法自动关联 trace_id，降低了可观测性价值。
- **建议**: 使用 `contextvars.ContextVar` 存储 trace_id，或通过 `logging.LoggerAdapter` / `structlog` 绑定上下文变量，使同一请求的所有日志条目自动携带 trace_id。

### [R-004] MEDIUM: chat_session.py 上下文压缩使用字符串截断而非 LLM 压缩

- **category**: completeness
- **root_cause**: self-caused
- **描述**: AC-T038-3 要求 "当 total_tokens_estimate 超过管道配置的 token 上限时，调用 LLM 将旧消息压缩为 compacted_summary"。当前 `chat_session.py` 的 `compact_context()` 方法（第61-79行）使用简单的字符串拼接和截断（`joined[:max_chars]`），而非调用 LLM 进行语义压缩。虽然作为 v1 的简化实现可以接受，但与 AC 描述存在偏差。
- **建议**: 至少在代码注释中标注 `[ASSUMPTION]` 说明当前为简化实现，后续版本将接入 LLM 压缩。或者添加一个 `compactor` 协议/接口参数，为 LLM 压缩预留扩展点。

### [R-005] MEDIUM: system.py 健康端点路径与 AC-T042-6 不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: AC-T042-6 要求 `GET /api/v1/health`，但 `system.py` 的 health 端点定义为 `@router.get("/health")`，且 `main.py` 将其挂载在 `prefix="/api/v1/system"`，实际路径为 `/api/v1/system/health`。虽然 `main.py` 还定义了根级别的 `/health` 端点，但 AC 要求的 `/api/v1/health` 路径不存在。
- **建议**: 在 `main.py` 中额外注册一个 `/api/v1/health` 端点，或将 system router 的 health 端点单独挂载到 `/api/v1` 前缀下，使 AC-T042-6 要求的路径可达。

### [R-006] MEDIUM: _AutoLifespanApp 在每次请求后触发 shutdown

- **category**: structure
- **root_cause**: self-caused
- **描述**: `main.py` 的 `_AutoLifespanApp.__call__` 方法（第108-113行）在每次非 lifespan 请求处理完毕后都会调用 `cm.__aexit__`（shutdown），然后重置 `_auto_started = False`。这意味着在测试场景中如果发送多个请求，每次请求都会触发一次 startup+shutdown 循环，与真实服务器行为不一致。虽然当前测试都只发送一个请求所以未暴露问题，但设计上存在缺陷。
- **建议**: 将 auto-lifespan 的 shutdown 从请求级别移到 `AsyncClient` 上下文退出时触发，或使用 `atexit` / `weakref.finalize` 机制延迟清理。

### [R-007] LOW: MetricsCollector 单例在测试间共享状态

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `metrics.py` 使用模块级 `_instance` 单例模式（第18-23行）。测试文件 `test_metrics.py` 虽然通过 `MetricsCollector._instance = None` 重置（第14-16行的 fixture），但单例模式在并发测试运行时可能导致状态污染。
- **建议**: 已有 fixture 处理，风险较低。可考虑提供 `reset()` 类方法使测试重置更规范。

### [R-008] LOW: webhooks.py XML 解析使用 xml.etree.ElementTree

- **category**: security
- **root_cause**: self-caused
- **描述**: `webhooks.py` 第38行使用 `ET.fromstring(xml_body)` 解析 XML，该方法已知存在 XML 外部实体注入（XXE）和 Billion Laughs 攻击风险。代码通过 `# noqa: S314` 抑制了安全警告，但未使用 `defusedxml` 库。
- **建议**: 对于微信回调这一受控场景，风险可控。但建议在注释中记录风险评估理由，或在后续版本中替换为 `defusedxml.ElementTree`。

### [R-009] LOW: CLI task_trigger payload 缺少 trigger_type 字段

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `cli/main.py` 的 `task_trigger` 命令构建 payload 为 `{"source_id": source_id}`（第178行），缺少 `trigger_type` 字段。而 `tasks.py` 的 `CollectRequest` 模型要求 `source_id` 和 `trigger_type` 两个字段都是必填项，请求将被 Pydantic 验证拒绝。此问题与 R-002 相关但属于不同层面（路径 vs 请求体）。
- **建议**: 在 `task_trigger` 命令中添加 `--trigger-type` 选项（默认值如 `"manual"`），并将其包含在 payload 中。

### [R-010] LOW: 源代码文件路径与 dev-plan 交付物不一致

- **category**: convention
- **root_cause**: self-caused
- **描述**: dev-plan T-038 交付物声明文件为 `src/intellisource/search/session.py`，但实际文件为 `src/intellisource/search/chat_session.py`。虽然功能完整且测试通过，但文档与实际存在偏差。
- **建议**: 更新 dev-plan 中的交付物路径，或添加备注说明重命名原因。

---

## 统计摘要

| 严重等级 | 数量 |
|---------|------|
| CRITICAL | 0 |
| HIGH | 1 |
| MEDIUM | 5 |
| LOW | 4 |
| **合计** | **10** |

| 分类 | 数量 |
|------|------|
| consistency | 3 |
| completeness | 3 |
| structure | 1 |
| security | 1 |
| test-quality | 1 |
| convention | 1 |

---

## 正面发现

- 全部 1563 个单元测试通过，零失败
- mypy --strict 对 14 个源文件零错误
- 所有 API router 正确使用 cursor-based 分页（limit capped at 100, next_cursor + has_more 响应格式）
- SourceRepository、TaskRepository 等仓储层实现规范，过滤和分页逻辑清晰
- Webhook 签名验证逻辑正确，异步超时处理合理
- 中间件分层清晰（Auth → Logger → Tracing），职责分离良好
- MetricsCollector 的 counter/gauge/histogram 三种指标类型实现完整
- 测试覆盖了主要的正常路径和异常路径，断言有效性良好
