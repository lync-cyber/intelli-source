---
id: dev-plan-intellisource-v1-s8
doc_type: dev-plan
author: tech-lead
status: draft
deps: [arch-intellisource-v1]
consumers: [developer, qa-engineer]
volume: s8
split_from: dev-plan-intellisource-v1
---
# Development Plan: IntelliSource — Sprint 8
<!-- id: dev-plan-intellisource-v1-s8 | author: tech-lead | status: draft -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: s8 -->

> **Sprint 主题**: Agent 模式系统、工具治理与运行时增强（P2 改进项，源自 OpenCode 对标架构评审；新增 T-075~T-079 修复 CODE-SCAN HIGH/MEDIUM 问题）
> **前置依赖**: Sprint 7 全部完成（T-057~T-063, T-072~T-074）
> **参考**: docs/research/architecture-review-opencode-benchmark.md；docs/reviews/code/CODE-SCAN-20260503-r1.md（R-002/R-008/R-010/R-011/R-012）；docs/reviews/code/CODE-SCAN-20260503-r2.md（R2-001 应用组合根 / R2-002 压缩策略统一）

[NAV]

- §3 任务卡详细
  - T-064 Agent 模式系统
  - T-065 工具权限分级
  - T-066 工具自动发现机制
  - T-067 Pipeline 执行事件日志
  - T-068 外部 API 熔断器实现
  - T-069 Prompt 版本自动计算
  - T-070 Chat API SSE 流式输出
  - T-075 Agent 工具层接驳真实模块（源自 CODE-SCAN-r1 R-002）
  - T-076 健康检查与指标端点完善（源自 CODE-SCAN-r1 R-008/R-010）
  - T-077 信源重载与代码质量清理（源自 CODE-SCAN-r1 R-011/R-012 + r2 R2-005）
  - T-078 应用组合根 — Celery app + Agent 工厂 + Lifespan 真实化（新增，源自 CODE-SCAN-r2 R2-001）
  - T-079 上下文压缩策略统一（新增，源自 CODE-SCAN-r2 R2-002）
  - T-071 Sprint 8 集成测试与回归

[/NAV]

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

### T-075: Agent 工具层接驳真实模块

> **来源**: CODE-SCAN-20260503-r1 R-002（HIGH）

- **目标**: 将 `agent/tools.py` 中 6 个默认工具的占位 `execute` 函数替换为对真实模块的调用，使 AgentRunner flexible 模式具备真实编排能力
- **模块**: M-006
- **接口**: internal
- **复杂度**: L
- **依赖**: T-064（Agent 模式系统，提供工具访问控制框架）、T-072（DB session DI，工具需通过 session 访问数据）
- **扫描背景**: CODE-SCAN R-002 — 6 个默认工具均返回 `{"status": "ok", "tool": "<name>", **kwargs}`；`llm_complete` 元工具不调用 `LLMGateway`；flexible 模式等效于"空转"
- **tdd_acceptance**:
  - [ ] AC-T075-1: `collect` 工具调用 `CollectorRegistry.run_collector()` 执行真实采集
  - [ ] AC-T075-2: `process` 工具调用 `PipelineEngine.run()` 执行真实处理管道
  - [ ] AC-T075-3: `distribute` 工具调用 `DistributorBase.dispatch()` 执行真实分发
  - [ ] AC-T075-4: `search` 工具调用 `HybridIndex.search()` 执行真实检索
  - [ ] AC-T075-5: `get_content_detail` 工具调用 `ContentRepository.get_by_id()` 查询真实内容
  - [ ] AC-T075-6: `llm_complete` 元工具调用 `LLMGateway.complete()`，gateway 实例从 `AgentRunner._llm_gateway` 取得
  - [ ] AC-T075-7: 工具依赖（CollectorRegistry/PipelineEngine 等）通过工厂函数或构造时注入，不使用全局单例
  - [ ] AC-T075-8: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/agent/tools.py` — 6 个默认工具替换为真实实现
  - [ ] `src/intellisource/agent/runner.py` — 工具工厂注入逻辑
  - [ ] `tests/unit/agent/test_tools_integration.py` — 工具接驳测试（≥10 tests，mock 上游模块边界）
- **context_load**:
  - src/intellisource/agent/tools.py (默认工具占位)
  - src/intellisource/collector/registry.py (CollectorRegistry)
  - src/intellisource/processing/pipeline.py (PipelineEngine)
  - src/intellisource/distributor/base.py (DistributorBase)
  - src/intellisource/search/hybrid.py (HybridIndex)

---

### T-076: 健康检查与指标端点完善

> **来源**: CODE-SCAN-20260503-r1 R-008/R-010（MEDIUM）

- **目标**: 将 `system.py` 的 `check_health()` 和 `get_metrics()` 从硬编码 stub 替换为真实检查逻辑，对齐 API-018/019 规范
- **模块**: M-010, M-011
- **接口**: API-018（健康检查）、API-019（指标）
- **复杂度**: M
- **依赖**: T-007（现有健康检查/指标模块）、T-072（DB session DI，健康检查需 ping DB）
- **tdd_acceptance**:
  - [ ] AC-T076-1: `check_health()` 响应包含 `status`（healthy/degraded/unhealthy）、`version`、`uptime_seconds`、`checks`（db/redis/celery 三子项）
  - [ ] AC-T076-2: `checks.db` 通过 `app.state.db` ping 数据库得出状态
  - [ ] AC-T076-3: `checks.redis` ping Redis 连接得出状态；任一组件不可达时整体 `status=degraded`
  - [ ] AC-T076-4: `uptime_seconds` 以启动时间戳计算（lifespan startup 时记录）
  - [ ] AC-T076-5: `get_metrics()` 调用 `observability/metrics.py` 导出 Prometheus 格式文本（`text/plain; version=0.0.4`）
  - [ ] AC-T076-6: 移除 `# pragma: no cover` 并补充单元测试（mock ping 调用）
  - [ ] AC-T076-7: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/api/routers/system.py` — check_health / get_metrics 替换为真实逻辑
  - [ ] `src/intellisource/main.py` — startup 时记录 `app.state.start_time`
  - [ ] `tests/unit/api/test_system_routes.py` — ≥8 tests（含组件 degraded 场景）
- **context_load**:
  - src/intellisource/api/routers/system.py (现有 stub)
  - src/intellisource/observability/health.py
  - src/intellisource/observability/metrics.py
  - docs/arch/arch-intellisource-v1-api.md#API-018 #API-019

---

### T-077: 信源重载与代码质量清理

> **来源**: CODE-SCAN-20260503-r1 R-011/R-012（LOW）

- **目标**: 修复 `reload_source_configs()` stub 使其返回真实结果；将 `agent/runner.py` 中循环体内的 `import json` 移至顶层；合并 `import json` 分散引用
- **模块**: M-001, M-006, M-011
- **接口**: API-005（信源配置重载）
- **复杂度**: S
- **依赖**: T-072（DB session DI）
- **tdd_acceptance**:
  - [ ] AC-T077-1: `POST /api/v1/sources/reload` 调用 `ConfigLoader.reload()`，返回真实 `{"loaded_count": N, "errors": [...]}`
  - [ ] AC-T077-2: `agent/runner.py` 文件顶层统一 `import json`，循环体内的 `import json as _json` 删除
  - [ ] AC-T077-3: mypy --strict 零错误，ruff check 无新 warning
  - [ ] AC-T077-4 (R2-005): `pyproject.toml` 增加 `[tool.vulture]` 配置（`ignore_names = ["names", "a", "kw"]` 或将 `circuit_breaker.py:19` / `database.py:75` 的参数加 `_` 前缀），消除 vulture 假阳性
- **deliverables**:
  - [ ] `src/intellisource/api/routers/sources.py` — `reload_source_configs()` 接入 `ConfigLoader`
  - [ ] `src/intellisource/agent/runner.py` — 顶层 `import json`
  - [ ] `pyproject.toml` — vulture 白名单配置（或对应源文件参数前缀化）
  - [ ] `tests/unit/api/test_sources_routes.py` — reload 端点测试更新（≥2 tests）
- **context_load**:
  - src/intellisource/api/routers/sources.py (reload_source_configs stub)
  - src/intellisource/config/loader.py (ConfigLoader)
  - src/intellisource/agent/runner.py (import json at line 155)
  - src/intellisource/llm/circuit_breaker.py (Protocol 方法 `*names` 参数)
  - src/intellisource/storage/database.py (`_closed_creator(*a, **kw)` 闭包)

---

### T-078: 应用组合根 (composition root) — Celery app + Agent 工厂 + Lifespan 真实化

> **来源**: CODE-SCAN-20260503-r2 R2-001（HIGH）

- **目标**: 在 `src/` 内首次构造 Celery app singleton 与 AgentRunner 工厂，使整套 `M-006 编排 → M-002 采集 → M-003 处理 → M-007 分发` 链路在生产部署时可冷启动；与 T-072（DB session DI）、T-074（TaskChainRepository）、T-075（Agent 工具接驳真实模块）一同收口"系统可端到端运行"目标
- **模块**: M-006, M-011
- **接口**: internal（启动链路）
- **复杂度**: M
- **依赖**: T-072（DB session DI）、T-074（TaskChainRepository）、T-075（Agent 工具接驳）
- **扫描背景**: CODE-SCAN R2-001 — 全仓 `grep` 验证 `Celery(` / `celery_app` / `AgentRunner(` / `AgentToolRegistry()` 在 `src/` 内零命中；`CeleryTasks` 类仅由测试 fixture 实例化；`main.py:init_celery()` 函数体为空。即便 T-075 把 6 个工具替换为真实实现，也没有任何代码会构造 `AgentToolRegistry → AgentRunner → CeleryTasks` 调用链
- **tdd_acceptance**:
  - [ ] AC-T078-1: 新增 `src/intellisource/scheduler/celery_app.py`，按 `config/defaults.yaml` 的 `celery.broker_url` / `celery.result_backend` 配置创建模块级 `celery_app: Celery` 实例
  - [ ] AC-T078-2: 新增 `src/intellisource/agent/factory.py:build_agent_runner(session_factory, llm_gateway) -> AgentRunner`，内部构造 `AgentToolRegistry`、调用 `register_defaults() + register_atomic_tools()`、注入 LLM gateway 与工具依赖
  - [ ] AC-T078-3: `CeleryTasks.run_pipeline` 改为 `@celery_app.task(name="run_pipeline")` 装饰的具名任务；从 `current_app.state.agent_runner`（或 lazy module-level singleton）取实例
  - [ ] AC-T078-4: `main.py:init_celery()` import `scheduler.celery_app` 并在 lifespan 中存入 `app.state.celery_app`；`init_redis()` 使用 `aioredis.from_url(config.redis.url)` 创建连接并存入 `app.state.redis`（与 T-072 AC-T072-4 协同）
  - [ ] AC-T078-5: 新增端到端冷启动集成测试：FastAPI lifespan startup 完成后，`celery_app.send_task("run_pipeline", ["test_pipeline", {}])` 能跑通一个 stub pipeline（in-memory eager 模式即可，不要求真实 broker）
  - [ ] AC-T078-6: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/scheduler/celery_app.py` — Celery app singleton + `@celery_app.task` 装饰的 run_pipeline
  - [ ] `src/intellisource/agent/factory.py` — `build_agent_runner` 工厂函数
  - [ ] `src/intellisource/scheduler/tasks.py` — 移除 `TaskChainRepository: Any = None` 全局占位（与 T-074 同步），改为 factory 返回的真实 repository
  - [ ] `src/intellisource/main.py` — `init_celery / init_redis` 真实化，`app.state.celery_app / redis / agent_runner` 在 lifespan 中赋值
  - [ ] `config/defaults.yaml` — 新增 `celery` 与 `redis` 顶层段
  - [ ] `tests/integration/test_cold_start.py` — 端到端冷启动测试（≥4 tests，含 lifespan startup/shutdown、Celery eager 任务调度）
- **context_load**:
  - src/intellisource/main.py (init_celery / init_redis 空实现)
  - src/intellisource/scheduler/tasks.py (CeleryTasks 类，TaskChainRepository 占位)
  - src/intellisource/agent/runner.py (AgentRunner 构造签名)
  - src/intellisource/agent/tools.py (AgentToolRegistry, register_defaults / register_atomic_tools)
  - src/intellisource/llm/gateway.py (LLMGateway 构造签名)

---

### T-079: 上下文压缩策略统一 — `search/chat_session.py` 委托 `agent/compaction.py`

> **来源**: CODE-SCAN-20260503-r2 R2-002（MEDIUM）

- **目标**: 消除 chat 会话与 Agent 流之间两套压缩逻辑的质量差距，使 `search/chat_session.py:compact_context()` 委托 T-058 已升级的 `agent/compaction.py`（token-based 保留 + 结构化 LLM 摘要 + 失败回退 truncation）
- **模块**: M-005, M-006, M-008
- **接口**: internal
- **复杂度**: S
- **依赖**: T-058（compact_messages token-based 升级，已 done）
- **扫描背景**: CODE-SCAN R2-002 — `search/chat_session.py:67 compact_context()` 仍是 string-concat 摘要 + "消息数量除以 10"保留窗口，与 T-058 AC-T058-1 显式禁止的"消息数量百分比"策略一致；docstring 自承 `[ASSUMPTION] Future versions should integrate an LLM-based compactor`
- **tdd_acceptance**:
  - [ ] AC-T079-1: 在 `agent/compaction.py` 暴露 `compact_messages_for_chat(messages, max_tokens, gateway) -> list[dict]` 不依赖 PipelineConfig 的纯函数（或 `CompactionService` 类），保持原有 `compact_messages` 签名兼容
  - [ ] AC-T079-2: `search/chat_session.py:compact_context()` 改为委托 AC-T079-1 暴露的接口；删除本地 `summary_parts` / `summary_text` string-concat 路径与 `[ASSUMPTION]` docstring
  - [ ] AC-T079-3: 保留窗口策略对齐 T-058（token-based，role=tool 优先裁剪）；删除 `keep_count = min(max(2, len(messages) // 10), len(messages))` 计算
  - [ ] AC-T079-4: LLM 摘要失败时回退 truncation（与 T-058 AC-T058-6 一致）
  - [ ] AC-T079-5: `tests/unit/search/test_chat_session.py` 增加压缩回归用例（≥4 tests，含 LLM 摘要失败回退、role=tool 优先裁剪）
  - [ ] AC-T079-6: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/agent/compaction.py` — 暴露 chat 友好接口
  - [ ] `src/intellisource/search/chat_session.py` — 删除本地实现，委托上述接口
  - [ ] `tests/unit/search/test_chat_session.py` — 压缩回归用例
- **context_load**:
  - src/intellisource/search/chat_session.py (compact_context 现有实现，line 67)
  - src/intellisource/agent/compaction.py (compact_messages T-058 升级版本)
  - src/intellisource/llm/prompts/compaction_summary.txt (T-058 模板)

---

### T-071: Sprint 8 集成测试与回归

- **目标**: 验证 Sprint 8 所有改进（含 T-075~T-079 基础设施修复）在集成场景下正常工作，全量 pytest + mypy 通过
- **模块**: 全模块
- **接口**: internal
- **复杂度**: M
- **依赖**: T-064~T-070, T-075~T-079
- **tdd_acceptance**:
  - [ ] AC-T071-1: Agent 模式系统 + 工具权限分级联合测试（analyze 模式 + confirm 权限）
  - [ ] AC-T071-2: 工具自动发现 + 手动注册优先级测试
  - [ ] AC-T071-3: Pipeline 事件日志在 flexible 模式执行中完整记录
  - [ ] AC-T071-4: 熔断器 + 重试 + 降级端到端链路测试
  - [ ] AC-T071-5: SSE 流式输出 + token 统计集成测试
  - [ ] AC-T071-6: Agent 工具接驳真实模块的端到端编排测试（collect → process → distribute 链路）
  - [ ] AC-T071-7: 健康检查 degraded 场景集成测试（模拟 DB/Redis 不可达）
  - [ ] AC-T071-8 (R2-001): 应用冷启动 e2e — FastAPI lifespan startup 后，`celery_app.send_task("run_pipeline", ...)` 完成 stub pipeline 全流程并写入 TaskChain
  - [ ] AC-T071-9 (R2-002): chat_session 与 agent flexible 模式压缩策略行为一致性测试（同一对话历史在两端压缩后的保留窗口应等价）
  - [ ] AC-T071-10: 全量 `pytest` 通过
  - [ ] AC-T071-11: `mypy --strict src/` 零错误
- **deliverables**:
  - [ ] `tests/integration/test_sprint8_integration.py` — 集成测试（含 T-075~T-079 场景）
  - [ ] 全量 pytest + mypy 通过报告
- **context_load**:
  - 所有 T-064 ~ T-070, T-075 ~ T-079 deliverables
