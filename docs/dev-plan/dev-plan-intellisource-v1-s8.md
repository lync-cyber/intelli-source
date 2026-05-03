---
id: dev-plan-intellisource-v1-s8
doc_type: dev-plan
author: tech-lead
status: draft
deps: [arch-intellisource-v1]
consumers: [developer, qa-engineer]
volume: s8
---
# Development Plan: IntelliSource — Sprint 8
<!-- id: dev-plan-intellisource-v1-s8 | author: tech-lead | status: draft -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: s8 -->

> **Sprint 主题**: Agent 模式系统、工具治理与运行时增强（P2 改进项，源自 OpenCode 对标架构评审）
> **前置依赖**: Sprint 7 全部完成（T-057~T-063）
> **参考**: docs/research/architecture-review-opencode-benchmark.md

## 3. 任务卡详细

### T-064: Agent 模式系统

- **目标**: 为 AgentRunner 引入 `AgentMode` 枚举（`process` / `analyze` / `preview`），在 PipelineConfig 中声明模式，根据模式限制工具访问范围
- **模块**: M-006
- **接口**: internal
- **复杂度**: M
- **依赖**: T-054（AgentRunner run_flexible 增强）
- **tdd_acceptance**:
  - [ ] AC-T064-1: `AgentMode` 枚举定义 3 种模式: `process`（全权执行）、`analyze`（只读分析，禁止 distribute/process 工具）、`preview`（执行但跳过副作用工具，返回计划步骤）
  - [ ] AC-T064-2: PipelineConfig YAML 新增可选 `agent_mode` 字段（默认 `process`）
  - [ ] AC-T064-3: `analyze` 模式下 `distribute` 和 `process` 工具被自动加入 denied 列表
  - [ ] AC-T064-4: `preview` 模式下所有工具调用记录到 plan 列表但不实际执行，返回 `{"status": "preview", "plan": [...]}`
  - [ ] AC-T064-5: `process` 模式行为与现有 flexible 模式完全一致（向后兼容）
  - [ ] AC-T064-6: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/agent/runner.py` — AgentMode 枚举 + 模式分支逻辑
  - [ ] `src/intellisource/agent/pipeline.py` — agent_mode 字段解析
  - [ ] `tests/unit/agent/test_agent_mode.py` — 模式测试（≥10 tests）
- **context_load**:
  - src/intellisource/agent/runner.py (AgentRunner)
  - src/intellisource/agent/pipeline.py (PipelineConfig)
  - docs/research/architecture-review-opencode-benchmark.md §GAP-A1

---

### T-065: 工具权限分级

- **目标**: 扩展 `ToolDefinition` 增加 `permission_level` 字段（`auto` / `confirm` / `deny`），在 `run_flexible()` 工具调用前检查权限级别
- **模块**: M-006
- **接口**: internal
- **复杂度**: M
- **依赖**: T-050（AgentToolRegistry）
- **tdd_acceptance**:
  - [ ] AC-T065-1: `ToolDefinition` 新增 `permission_level` 字段（枚举: `auto` / `confirm` / `deny`，默认 `auto`）
  - [ ] AC-T065-2: `auto` 权限工具自动执行（与现有行为一致）
  - [ ] AC-T065-3: `confirm` 权限工具在 `run_flexible()` 中调用前记录 pending_confirmation 事件，Agent 必须在 prompt 中声明确认意图
  - [ ] AC-T065-4: `deny` 权限工具不出现在 Agent 可用工具列表中
  - [ ] AC-T065-5: PipelineConfig YAML 支持 `tool_permissions` 区段覆盖默认权限级别
  - [ ] AC-T065-6: `distribute` 工具默认 permission_level=`confirm`
  - [ ] AC-T065-7: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/agent/tools.py` — permission_level 字段 + 过滤逻辑
  - [ ] `src/intellisource/agent/runner.py` — 权限检查逻辑
  - [ ] `tests/unit/agent/test_tool_permissions.py` — 权限测试（≥8 tests）
- **context_load**:
  - src/intellisource/agent/tools.py (ToolDefinition, AgentToolRegistry)
  - docs/research/architecture-review-opencode-benchmark.md §GAP-A4

---

### T-066: 工具自动发现机制

- **目标**: 将 CollectorRegistry 的 auto-discover 模式推广到 AgentToolRegistry，支持从 `agent/tools/` 目录自动加载工具定义
- **模块**: M-006
- **接口**: internal
- **复杂度**: S
- **依赖**: T-050（AgentToolRegistry）
- **tdd_acceptance**:
  - [ ] AC-T066-1: `AgentToolRegistry.auto_discover()` 扫描 `src/intellisource/agent/tools/` 目录
  - [ ] AC-T066-2: 工具文件需导出 `TOOL_DEFINITION: ToolDefinition` 常量
  - [ ] AC-T066-3: 自动发现的工具与手动注册的工具在 `list_tools()` 中统一返回
  - [ ] AC-T066-4: 重复名称的工具手动注册优先于自动发现
  - [ ] AC-T066-5: 自动发现失败（import error）时 log warning 但不阻止启动
  - [ ] AC-T066-6: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/agent/tools.py` — auto_discover() 方法
  - [ ] `src/intellisource/agent/tools/` — 工具目录（初始含 __init__.py）
  - [ ] `tests/unit/agent/test_tool_discovery.py` — 自动发现测试（≥6 tests）
- **context_load**:
  - src/intellisource/collector/registry.py (auto_discover 参考实现)
  - src/intellisource/agent/tools.py (AgentToolRegistry)

---

### T-067: Pipeline 执行事件日志

- **目标**: 在 AgentRunner 执行过程中记录结构化事件（pipeline_start/tool_call/llm_call/pipeline_complete/pipeline_error），供运行时审计和故障排查
- **模块**: M-006, M-010
- **接口**: internal
- **复杂度**: M
- **依赖**: T-054（AgentRunner 增强）
- **tdd_acceptance**:
  - [ ] AC-T067-1: 事件写入独立文件 `pipeline-events.jsonl`（JSONL 格式）
  - [ ] AC-T067-2: 事件类型: `pipeline_start` / `tool_call` / `llm_call` / `pipeline_complete` / `pipeline_error`
  - [ ] AC-T067-3: 每个事件包含 `ts`, `event`, `pipeline_name`, `task_chain_id`, `detail` 字段
  - [ ] AC-T067-4: `tool_call` 事件包含 `tool_name`, `duration_ms`, `status`（success/error）
  - [ ] AC-T067-5: `llm_call` 事件包含 `model`, `input_tokens`, `output_tokens`, `latency_ms`
  - [ ] AC-T067-6: 事件记录不影响主流程性能（async write，失败时 log warning 不中断）
  - [ ] AC-T067-7: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/agent/events.py` — PipelineEventLogger 类
  - [ ] `src/intellisource/agent/runner.py` — 事件记录集成
  - [ ] `tests/unit/agent/test_pipeline_events.py` — 事件记录测试（≥8 tests）
- **context_load**:
  - src/intellisource/agent/runner.py (AgentRunner)
  - .claude/schemas/event-log.schema.json (参考事件 schema 设计)

---

### T-068: 外部 API 熔断器实现

- **目标**: 实现 `CircuitBreaker` 类，为 LLM 调用和外部 API 调用提供熔断保护（架构已设计但未实现）
- **模块**: M-005
- **接口**: internal
- **复杂度**: M
- **依赖**: T-057（RetryPolicy）
- **tdd_acceptance**:
  - [ ] AC-T068-1: `CircuitBreaker` 类支持 Closed → Open → HalfOpen → Closed 状态机
  - [ ] AC-T068-2: 连续失败 `failure_threshold` 次（默认 5）触发 Open 状态
  - [ ] AC-T068-3: Open 状态持续 `recovery_timeout` 秒（默认 60）后进入 HalfOpen
  - [ ] AC-T068-4: HalfOpen 状态允许 1 次试探调用，成功则 Closed，失败则回到 Open
  - [ ] AC-T068-5: Open 状态下调用直接返回 `CircuitBreakerOpenError`（继承 LLMError, EXTERNAL）
  - [ ] AC-T068-6: `LLMGateway` 集成 CircuitBreaker，在 retry 耗尽后触发熔断计数
  - [ ] AC-T068-7: 熔断状态变化记录到日志（log.warning）
  - [ ] AC-T068-8: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/llm/circuit_breaker.py` — CircuitBreaker 类（替代现有占位文件）
  - [ ] `src/intellisource/llm/gateway.py` — 熔断集成
  - [ ] `tests/unit/llm/test_circuit_breaker.py` — 熔断状态机测试（≥10 tests）
- **context_load**:
  - src/intellisource/llm/circuit_breaker.py (现有文件)
  - docs/arch/arch-intellisource-v1.md §5.3 熔断机制规格

---

### T-069: Prompt 版本自动计算

- **目标**: 使用模板文件 hash 作为自动 `prompt_version`，在 PromptBuilder.build() 时计算，用于 LLMCache key 自动失效
- **模块**: M-005
- **接口**: internal
- **复杂度**: S
- **依赖**: T-051（PromptBuilder）, T-052（LLMCache）
- **tdd_acceptance**:
  - [ ] AC-T069-1: `PromptBuilder.prompt_version` 属性返回当前模板文件的 SHA-256 前 8 位 hex
  - [ ] AC-T069-2: 模板文件内容变化时 prompt_version 自动变化
  - [ ] AC-T069-3: `LLMGateway.complete()` 在有 PromptBuilder 时自动使用其 prompt_version（无需调用方手动传入）
  - [ ] AC-T069-4: 模板文件不存在时 prompt_version 为 `"unknown"`
  - [ ] AC-T069-5: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/llm/prompt_builder.py` — prompt_version 属性
  - [ ] `src/intellisource/llm/gateway.py` — 自动 version 集成
  - [ ] `tests/unit/llm/test_prompt_version.py` — 版本计算测试（≥5 tests）
- **context_load**:
  - src/intellisource/llm/prompt_builder.py (PromptBuilder)
  - src/intellisource/llm/cache.py (LLMCache key 结构)

---

### T-070: Chat API SSE 流式输出

- **目标**: 为 chat API 端点增加 SSE 流式响应支持，使用 `litellm.acompletion(stream=True)`
- **模块**: M-011, M-005
- **接口**: API-013 增强
- **复杂度**: M
- **依赖**: T-057（LLMGateway timeout 集成）
- **tdd_acceptance**:
  - [ ] AC-T070-1: GET/POST `/api/v1/chat/stream` 端点返回 `text/event-stream` SSE 响应
  - [ ] AC-T070-2: `LLMGateway.stream_complete()` 方法使用 `litellm.acompletion(stream=True)` 返回 AsyncGenerator
  - [ ] AC-T070-3: 每个 SSE event 包含 `data: {"content": "...", "done": false}` 格式
  - [ ] AC-T070-4: 流结束时发送 `data: {"content": "", "done": true, "metadata": {...}}` 包含 token 统计
  - [ ] AC-T070-5: 流式调用仍记录到 LLMCallLog（在流结束时）
  - [ ] AC-T070-6: 客户端断开连接时优雅关闭流
  - [ ] AC-T070-7: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/llm/gateway.py` — stream_complete() 方法
  - [ ] `src/intellisource/api/routers/search.py` — SSE 流式端点
  - [ ] `tests/unit/llm/test_gateway_stream.py` — 流式测试（≥6 tests）
  - [ ] `tests/unit/api/test_search_routes.py` — SSE 端点测试（≥4 tests）
- **context_load**:
  - src/intellisource/llm/gateway.py (LLMGateway)
  - src/intellisource/api/routers/search.py (现有 chat 端点)

---

### T-071: Sprint 8 集成测试与回归

- **目标**: 验证 Sprint 8 所有改进在集成场景下正常工作，全量 pytest + mypy 通过
- **模块**: 全模块
- **接口**: internal
- **复杂度**: M
- **依赖**: T-064~T-070
- **tdd_acceptance**:
  - [ ] AC-T071-1: Agent 模式系统 + 工具权限分级联合测试（analyze 模式 + confirm 权限）
  - [ ] AC-T071-2: 工具自动发现 + 手动注册优先级测试
  - [ ] AC-T071-3: Pipeline 事件日志在 flexible 模式执行中完整记录
  - [ ] AC-T071-4: 熔断器 + 重试 + 降级端到端链路测试
  - [ ] AC-T071-5: SSE 流式输出 + token 统计集成测试
  - [ ] AC-T071-6: 全量 `pytest` 通过
  - [ ] AC-T071-7: `mypy --strict src/` 零错误
- **deliverables**:
  - [ ] `tests/unit/integration/test_sprint8_integration.py` — 集成测试
  - [ ] 全量 pytest + mypy 通过报告
- **context_load**:
  - 所有 T-064 ~ T-070 deliverables
