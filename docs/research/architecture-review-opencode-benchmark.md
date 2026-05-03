---
id: "architecture-review-opencode-benchmark"
doc_type: research
author: user
status: approved
deps: []
---
# IntelliSource 深度架构评审报告 — 以 OpenCode 为对标

> 评审范围: src/intellisource/, .claude/, config/, docs/, tests/
> 对标对象: OpenCode (github.com/anomalyco/opencode) — TypeScript/Bun, 141k+ stars
> 日期: 2026-04-10
> 类型: research-note
> 前置文档: docs/research/prompt-management-analysis.md

---

## 1. 执行摘要

### 1.1 IntelliSource 当前架构成熟度判断

IntelliSource 是一个**中等成熟度的领域特定 AI 信息平台**，在以下方面表现良好：

**已确认优势：**
- **错误分类体系**（`core/errors.py`）：4 级错误分类 + 恢复策略映射，优于 OpenCode 的简单 try-catch 模式
- **降级优先设计**（`llm/fallback.py`）：每个 LLM 任务都有对应的传统算法降级路径，这在 OpenCode 中不存在
- **任务型模型路由**（`llm/model_config.py`）：按 task_type 自动选择最优模型+参数，比 OpenCode 的手动 model 指定更自动化
- **结构化输出校验**（`llm/gateway.py:SchemaEnforcer`）：JSON Schema 强制校验，比 OpenCode 的自由文本输出更可靠
- **Pipeline/Processor 模式**（`pipeline/`）：清晰的 BaseProcessor → PipelineEngine 抽象，适合批处理场景
- **CataForge 框架集成**（`.claude/`）：14 个 Agent 角色定义 + 7 阶段开发生命周期，工程化程度高

**已确认不足：**
- Agent 系统仅支持单一执行模式（无 plan/build/explore 等模式区分）
- 缺少分层配置体系（无全局/项目/本地覆盖机制）
- 缺少声明式权限模型（权限散落在代码和 YAML 中）
- 上下文压缩机制原始（`compaction.py` 仅做简单截断+LLM摘要）
- 工具注册表中的工具实现均为占位符（`tools.py:92-119` 全部返回 `{"status": "ok"}`）
- 缺少插件/扩展机制
- 缺少会话回放和审计日志的结构化查询能力

### 1.2 OpenCode 关键设计模式提炼

| 设计模式 | 解决的问题 | 适合 IntelliSource? | 理由 |
|----------|-----------|-------------------|------|
| **主代理+子代理+系统代理** | 任务分解、职责隔离、上下文保护 | **部分适合** | IS 的 Agent 不需要交互式 TUI，但 "处理Agent+压缩Agent+分析Agent" 的分层有价值 |
| **Provider-agnostic 模型抽象** | 75+ provider 统一接入 | **已有** | IS 已通过 litellm 实现，但缺少模型特化 prompt |
| **分层配置合并** | 组织级→用户级→项目级配置治理 | **适合** | IS 当前配置扁平，缺少覆盖机制 |
| **AGENTS.md 项目指令** | 项目级 AI 行为定制 | **不适合** | IS 是服务端平台，不是交互式编码工具，CLAUDE.md 已满足需求 |
| **声明式工具权限** | allow/ask/deny 细粒度控制 | **适合** | IS 的 pipeline 工具需要权限分级（如 distribute 应比 search 更严格） |
| **Build/Plan 模式切换** | 只读分析 vs 全权执行 | **部分适合** | IS 可借鉴为 "preview(dry-run)/execute" 双模式 |
| **自动上下文压缩** | 长会话 token 溢出 | **适合** | IS 的 `compact_messages()` 过于简单 |
| **插件系统+事件总线** | 第三方扩展、自定义工具 | **长期适合** | 当前优先级低，但架构应预留扩展点 |
| **Git-based Undo/Redo** | 操作可逆性 | **不适合** | IS 是服务端批处理系统，不需要文件级撤销 |
| **Budget/深度限制** | 防止无限循环 | **适合** | IS 的 `max_steps` 是粗粒度限制，缺少 token 预算和嵌套深度控制 |

---

## 2. 差距分析（Gap Analysis）与改进建议

### 2.1 架构层改进

#### GAP-A1: Agent 分层与模式系统

| 维度 | IntelliSource 现状 | OpenCode 最佳实践 | 差距 | 改进建议 | 风险 |
|------|-------------------|------------------|------|---------|------|
| Agent 分层 | `AgentRunner` 单一类，`run_strict()` 和 `run_flexible()` 两种执行模式（`runner.py:33-146`） | 4 层 Agent 体系：Primary(Build/Plan) + Subagent(General/Explore) + System(Compaction/Title/Summary) + Custom | AgentRunner 职责过重——既是调度器又是执行器，没有 "分析型Agent" 和 "系统Agent" 的概念分离 | 引入 `AgentMode` 枚举（`process` / `analyze` / `preview`），在 PipelineConfig 中声明模式，AgentRunner 根据模式限制工具访问范围。将 `compaction.py` 的逻辑封装为隐式 "系统Agent" 而非独立函数 | 低风险：不改变现有接口，仅扩展 |
| 模式切换 | 仅 strict/flexible 硬编码在 `config.mode`（`runner.py:40-46`） | Build/Plan/Custom modes，通过 JSON/Markdown 声明，Tab 键动态切换 | IS 缺少 "只分析不执行" 的 preview/dry-run 模式 | 新增 `preview` 模式：执行 Agent 循环但跳过有副作用的工具（distribute、process），仅返回计划步骤 | 低风险 |
| 子任务委派 | 无嵌套 Agent 调用能力 | `TaskTool` 实现子 Agent 调用，最多 5 层嵌套，独立 budget 跟踪 | IS 不需要交互式子任务，但缺少 "处理子流程" 的隔离能力 | 在 `run_flexible()` 中支持 `delegate` 工具，允许 Agent 将部分内容委派给独立的 mini-pipeline 执行 | 中等风险：需要上下文隔离机制 |

**代码证据：**
- `runner.py:94-146`：`run_flexible()` 直接在主循环中执行所有工具调用，没有隔离
- `runner.py:122-139`：工具调用失败时仅 log warning 并继续，缺少降级策略选择
- `compaction.py:20-51`：`compact_messages()` 是独立函数而非 Agent 组件

---

#### GAP-A2: Provider 抽象与模型特化

| 维度 | IntelliSource 现状 | OpenCode 最佳实践 | 差距 | 改进建议 | 风险 |
|------|-------------------|------------------|------|---------|------|
| Provider 抽象 | litellm 统一封装（`gateway.py:103-258`），`_CONTEXT_WINDOWS` 手动维护 4 个模型（`gateway.py:106-111`） | Vercel AI SDK + 75 providers，BaseProvider 包装层处理消息格式转换、错误重试 | IS 的 litellm 封装已足够（litellm 本身支持 100+ providers），但上下文窗口硬编码不可维护 | 将 `_CONTEXT_WINDOWS` 迁移到 `config/llm_models.yaml` 的 `profiles` 区段（T-053 已规划），增加 `litellm.get_model_info()` 作为动态查询 fallback | 低风险 |
| 模型特化 prompt | 无模型特化（所有模型用同一 prompt） | `session/system.ts` 按 model ID 匹配不同 prompt 文件（Anthropic/Beast/Gemini/Default） | **IS 缺少模型特化 prompt** — 不同模型对 prompt 格式有不同偏好（如 Claude 偏好结构化 XML、GPT 偏好简洁直接指令） | 在 `PromptBuilder` 中增加 `prompt_style` 参数（从 `ModelProfile.prompt_style` 获取），按模型家族选择 prompt 变体 | 低风险：可增量引入 |
| 流式输出 | 未实现（`gateway.py:206` 使用 `acompletion` 非流式） | 完整流式支持 + chunk 级事件追踪 | IS 是后台批处理系统，流式需求较低，但 chat API（`/api/v1/chat`）理应支持流式 | 为 chat API 增加 SSE 流式端点，使用 `litellm.acompletion(stream=True)` | 中等风险：需要前端适配 |
| 重试/fallback | `FallbackManager`（`fallback.py:13-68`）— 按 task_type 注册降级函数 | BaseProvider 内置重试 + 错误处理 | **IS 的降级设计优于 OpenCode**（有显式降级路径），但缺少指数退避重试 | 在 `LLMGateway.complete()` 中增加 `tenacity` 重试装饰器，配合 `ErrorCategory.RECOVERABLE_TRANSIENT` 自动触发 | 低风险 |

**代码证据：**
- `gateway.py:106-111`：仅 4 个模型的上下文窗口硬编码
- `gateway.py:206-215`：`litellm.acompletion()` 无 stream 参数
- `fallback.py:40-68`：`execute_fallback()` 有完整的降级记录机制，这是 OpenCode 不具备的

---

#### GAP-A3: 配置体系

| 维度 | IntelliSource 现状 | OpenCode 最佳实践 | 差距 | 改进建议 | 风险 |
|------|-------------------|------------------|------|---------|------|
| 配置分层 | 仅 `config/llm_models.yaml`（一层）+ `.claude/settings.json`（框架层）+ `pydantic-settings` 环境变量 | 8 层合并：remote → global → env → project → .opencode/ → inline → managed → MDM | IS 缺少 "全局默认 → 项目覆盖" 的分层机制 | 引入 `ConfigResolver` 类：加载顺序为 `config/defaults.yaml` → `config/llm_models.yaml` → 环境变量，使用 `dict.update()` 深度合并 | 低风险：渐进式引入 |
| 配置热更新 | `ConfigWatcher` 存在（`config/loader.py:108-120+`）但仅监控 source configs | 无特别的热更新机制 | **IS 在配置热更新方面优于 OpenCode** | 扩展 `ConfigWatcher` 范围到 `config/llm_models.yaml`，使 LLM 配置变更无需重启 | 低风险 |
| Schema 验证 | `SourceConfig` 用 Pydantic 验证（`config/models.py`），但 LLM config 无 schema | `opencode.json` 有完整 JSON Schema + JSONC 支持 | LLM 配置缺少 schema 验证 | 为 `config/llm_models.yaml` 创建 Pydantic model `LLMModelsConfig`，在 `load_model_config()` 中验证 | 低风险 |

**代码证据：**
- `config/loader.py:64-106`：`ConfigLoader` 仅处理 source config
- `llm/model_config.py`：`load_model_config()` 直接 YAML → dict，无验证
- `config/models.py:1-31`：`SourceConfig` 有完善的 Pydantic 验证

---

#### GAP-A4: 权限模型

| 维度 | IntelliSource 现状 | OpenCode 最佳实践 | 差距 | 改进建议 | 风险 |
|------|-------------------|------------------|------|---------|------|
| 工具权限 | `AgentToolRegistry.filter()` 基于 `allowed/denied` 名单（`tools.py:64-78`），PipelineConfig YAML 中声明 `tools_allowed/tools_denied` | 声明式 3 级权限（allow/ask/deny）+ glob 模式匹配 + 按 Agent 模式自动继承 | IS 的权限模型是二值的（有/无），缺少 "需确认" 中间态 | 扩展 `ToolDefinition` 增加 `permission_level` 字段（`auto` / `confirm` / `deny`），在 `run_flexible()` 工具调用前检查权限级别 | 低风险 |
| 文件写保护 | API 层 `AuthMiddleware`（`api/middleware.py:23-50`），框架层 `allowed_paths` | `.env` 默认拒绝 + 外部目录访问拦截 + 精细 glob 模式 | IS 的运行时（非框架层）缺少文件写保护 | 为 `distribute` 和写操作类工具增加输出路径白名单验证 | 低风险 |
| 命令执行安全 | 框架层 `settings.json` 白名单（`.claude/settings.json:6-54`） | 内置 bash 命令解析 + doom-loop 检测 + 命令级 glob 权限 | IS 是服务端应用，不直接暴露 shell（与 OpenCode 场景不同） | **不需要引入** — IS 的安全模型应聚焦在 API 认证和数据隔离 | N/A |

**代码证据：**
- `tools.py:64-78`：`filter()` 方法仅支持 include/exclude，无中间确认态
- `api/middleware.py:23-50`：`AuthMiddleware` 仅做 API Key 校验
- Pipeline YAML 示例（`config/pipelines/instant-search.yaml`）：`tools_allowed` / `tools_denied` 列表

---

### 2.2 实现层改进

#### GAP-B1: 工具注册与实现

| 维度 | IntelliSource 现状 | OpenCode 最佳实践 | 差距 | 改进建议 | 风险 |
|------|-------------------|------------------|------|---------|------|
| 工具实现状态 | 6 个内置工具全部为占位符（`tools.py:92-119`，每个返回 `{"status": "ok"}`） | 20+ 完整实现的内置工具 | **关键差距**：工具系统是 Agent 的核心能力，占位符实现意味着 Agent 实际无法执行任何有意义的操作 | Sprint 6 的 T-048/T-050 已规划原子工具 + 工具注册增强，需确保工具实际连接到业务模块 | 高优先级：Sprint 6 正在解决 |
| 工具自发现 | 无动态发现（`register_defaults()` 硬编码 6 个工具） | `Tool.define()` + 目录扫描 `.opencode/tools/` | IS 的 `CollectorRegistry.auto_discover()` 已有类似模式（`collector/registry.py:44-76`），但 Agent 工具未使用 | 将 CollectorRegistry 的 auto-discover 模式推广到 AgentToolRegistry，支持从 `src/intellisource/agent/tools/` 目录自动加载工具定义 | 低风险 |
| 工具参数校验 | `parameters` 字段为 dict（JSON Schema 格式），但未在执行前校验 | 内置参数校验 + 类型转换 | 工具调用可能因参数不合法而失败，但错误信息不明确 | 在 `AgentRunner._call_tool()` 中增加 `jsonschema.validate()` 前置校验 | 低风险 |

**代码证据：**
- `tools.py:92-119`：所有 `_*_execute()` 函数体为 `return {"status": "ok", "tool": "...", **kwargs}`
- `collector/registry.py:44-76`：`auto_discover()` 使用 `importlib` 动态加载，可复用此模式

---

#### GAP-B2: 上下文与会话管理

| 维度 | IntelliSource 现状 | OpenCode 最佳实践 | 差距 | 改进建议 | 风险 |
|------|-------------------|------------------|------|---------|------|
| 上下文压缩 | `compaction.py:20-51`：保留最近 10% 消息 + LLM 摘要旧消息，`_MAX_SUMMARY_PARTS=20`，每条截断 200 字符 | 95% 窗口阈值自动触发 + 工具输出选择性裁剪（保护最近 40k tokens）+ compaction agent 结构化摘要模板 | IS 的压缩策略过于粗糙：(1) 10% 保留比例可能丢失关键信息；(2) 200 字符截断破坏语义完整性；(3) 无工具输出选择性裁剪 | 重构 `compact_messages()`：(1) 基于 token 计数而非消息数量决定保留比例；(2) 使用结构化摘要模板（Goal/Context/Changes/State/Next Steps）；(3) 增加工具输出 pruning（先裁剪旧工具输出，再压缩对话） | 中等风险：改变现有行为 |
| 会话持久化 | `ChatSession`/`ChatMessage` ORM（`storage/models.py`） | Session 本地文件存储 + git-aware 项目隔离 | IS 使用 PostgreSQL 持久化，这对服务端应用是正确选择 | **IS 的方案更适合服务端场景** — 保持数据库持久化，无需改变 | N/A |
| Token 预算 | 仅 `max_steps` 限制（`runner.py:112`） | per-session token budget + cost tracking + hierarchical limits + max 5 depth | IS 缺少 token 级别的预算控制，可能导致 LLM 成本失控 | 在 `AgentRunner` 中增加 `max_tokens_budget` 参数，每次 LLM 调用后累计 token 消耗，超预算时中止并返回已有结果 | 低风险 |

**代码证据：**
- `compaction.py:39`：`keep_count = min(max(2, len(messages) // 10), len(messages))` — 固定 10% 比例
- `compaction.py:61-62`：200 字符截断 + 最多 20 条消息摘要
- `runner.py:112`：`while steps_executed < config.max_steps` — 仅步骤数限制

---

#### GAP-B3: Prompt 工程

| 维度 | IntelliSource 现状 | OpenCode 最佳实践 | 差距 | 改进建议 | 风险 |
|------|-------------------|------------------|------|---------|------|
| Prompt 分层 | Sprint 6 正在引入 `PromptBuilder`（T-051），模板已外置到 `llm/prompts/*.txt` | 5 层 prompt 组装：Provider → Environment → Skills → Instructions → Reminders | IS 目前 2 层（system_prompt + user prompt），缺少环境信息注入和指令文件层 | PromptBuilder 增加 `add_environment()` 方法，注入运行时上下文（当前日期、模型名、pipeline 名称等） | 低风险 |
| 模型特化 prompt | 无（所有模型用同一 prompt） | 按模型家族匹配不同 prompt 风格（Anthropic/GPT/Gemini/Default） | 不同模型对 prompt 格式有不同偏好 | `ModelProfile` 增加 `prompt_style` 字段（`structured` / `concise` / `default`），PromptBuilder 根据 style 选择模板变体 | 低风险 |
| Prompt 版本化 | cache key 包含 `prompt_version`（`cache.py` 设计），但无自动版本计算 | 无显式版本化 | IS 的设计思路正确但未实现 | 使用模板文件 hash 作为自动 `prompt_version`，在 `PromptBuilder.build()` 时计算 | 低风险 |

**代码证据：**
- `llm/prompts/__init__.py:16-20`：`_read_template()` 有 LRU cache 但无版本追踪
- `gateway.py:150-157`：cache_key_parts 需要显式传入 `prompt_version`

---

#### GAP-B4: 可观测性增强

| 维度 | IntelliSource 现状 | OpenCode 最佳实践 | 差距 | 改进建议 | 风险 |
|------|-------------------|------------------|------|---------|------|
| 结构化日志 | structlog JSON Lines（`observability/logging.py`）+ trace ID 传播（`tracing.py`） | 文件日志 + 保留最近 10 个 + session 级日志 | **IS 的日志系统优于 OpenCode** — structlog 的结构化日志 + contextvars 的 trace 传播更专业 | 保持现有设计，增加 per-pipeline-execution 的日志聚合查询 | N/A |
| LLM 调用日志 | `E-011 LLMCallLog` ORM 实体（`storage/models.py`） | 插件级 token/cost 追踪 | **IS 的设计优于 OpenCode** — 数据库级 LLM 调用日志支持聚合分析和报表 | 增加仪表盘查询端点（`/api/v1/system/llm-stats`），提供按时间/模型/任务类型的 token 消耗和成本统计 | 低风险 |
| 事件日志 | `docs/EVENT-LOG.jsonl` + schema（`.claude/schemas/event-log.schema.json`）— 13 种事件类型 | OpenTelemetry 实验性集成 | 事件日志是开发框架层（CataForge），而非运行时应用层 | 在运行时增加 `pipeline_execution` 事件：start/tool_call/llm_call/complete/error，写入独立的 `pipeline-events.jsonl` | 中等风险：需要设计事件 schema |
| 成本控制 | `CostTracker` 存在（研究报告提及），LLMCallLog 记录 token 数 | 插件级 budget alert + 消费预测 | IS 有数据但缺少主动告警 | 在 `LLMGateway.complete()` 后检查累计 token 消耗，超阈值时 log.warning 并可配置中止 | 低风险 |

---

### 2.3 安全与可运维改进

#### GAP-C1: 运行时安全

| 维度 | IntelliSource 现状 | OpenCode 最佳实践 | 差距 | 改进建议 | 风险 |
|------|-------------------|------------------|------|---------|------|
| API 认证 | `AuthMiddleware` X-API-Key（`api/middleware.py:23-50`） | 无（本地运行，不暴露网络） | IS 作为服务端应用，API 认证是正确的 | **IS 现状适合其场景** — 考虑增加 rate limiting 中间件防止滥用 | 低风险 |
| 数据隔离 | 多租户数据全在同一 PostgreSQL 库中 | 完全本地，无多租户问题 | IS 缺少租户级数据隔离 | 引入 `tenant_id` 字段到核心实体（Source、Content），查询时自动过滤 | 中等风险：涉及数据模型变更 |
| 敏感内容保护 | `ContentFilter`（`filter.py`）+ 敏感词过滤工具（T-048 规划的 `filter_sensitive()`） | `.env` 文件默认拒绝 | IS 的敏感内容过滤更全面（面向内容处理场景） | **IS 现状优于 OpenCode** 在此维度 | N/A |

#### GAP-C2: 错误恢复与韧性

| 维度 | IntelliSource 现状 | OpenCode 最佳实践 | 差距 | 改进建议 | 风险 |
|------|-------------------|------------------|------|---------|------|
| 重试策略 | `AgentRunner._retry_step()`（`runner.py:150-163`）：固定 3 次重试，无退避 | BaseProvider 内置重试 | IS 的重试是固定次数无退避（线性重试），可能加重下游压力 | 使用 `tenacity` 库：`retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(3))` | 低风险 |
| 熔断机制 | `ErrorCategory.EXTERNAL` 定义了"触发熔断"（`errors.py:30-31`），但无实现 | 无 | 架构设计了但未实现 | 实现 `CircuitBreaker` 类：跟踪连续失败数，超阈值后进入 open 状态，定期半开探测 | 中等风险 |
| 超时控制 | `TaskStateMachine` 有 3600s 默认超时（`scheduler/state_machine.py`），但 LLM 调用无超时 | `chunkTimeout` stream 级超时 | LLM 调用可能无限挂起 | 在 `litellm.acompletion()` 调用中增加 `timeout` 参数（默认 60s），从 ModelProfile 中读取 | 低风险 |

---

## 3. 优先级路线图

### P0: 关键路径（Sprint 6 必须完成，不做则 Agent 系统不可用）

| 编号 | 改进项 | 对应 Sprint 6 任务 | 状态 |
|------|-------|-------------------|------|
| P0-1 | 原子工具函数实现（替代占位符） | T-048 | Sprint 6 已规划 |
| P0-2 | 工具注册增强 + llm_complete 元工具 | T-050 | Sprint 6 已规划 |
| P0-3 | Agent 编排引擎增强（run_flexible system_prompt） | T-054 | Sprint 6 已规划 |
| P0-4 | PromptBuilder + Token 截断 | T-051 | Sprint 6 已规划 |
| P0-5 | LLM 调用结果缓存 | T-052 | Sprint 6 已规划 |
| P0-6 | 模型参数配置增强（ModelProfile） | T-053 | Sprint 6 已规划 |

**评估**：Sprint 6 的 T-047~T-056 已覆盖 P0 级改进。本评审确认这些任务的优先级是正确的。

### P1: 高价值改进（Sprint 7 建议，显著提升系统韧性和可维护性）

| 编号 | 改进项 | 收益 | 成本 | 复杂度 |
|------|-------|------|------|--------|
| P1-1 | **LLM 调用超时 + 指数退避重试** | 防止 LLM 调用挂起，减少雪崩风险 | 0.5d | S |
| P1-2 | **Token 预算控制**（AgentRunner 级） | 防止单次执行 token 成本失控 | 1d | S |
| P1-3 | **上下文压缩增强**（结构化摘要模板 + token-based 保留策略） | 长会话质量显著提升 | 2d | M |
| P1-4 | **模型特化 prompt**（prompt_style in ModelProfile） | 不同模型发挥最优性能 | 1d | S |
| P1-5 | **配置分层合并**（defaults.yaml → llm_models.yaml → env vars） | 部署灵活性，环境间配置管理 | 1.5d | M |
| P1-6 | **LLM 统计仪表盘 API**（/api/v1/system/llm-stats） | 成本可见性，运营决策支持 | 1d | S |
| P1-7 | **LLM 配置 Pydantic Schema 验证** | 配置错误提前发现 | 0.5d | S |

### P2: 中等价值改进（Sprint 8+，增强架构扩展性）

| 编号 | 改进项 | 收益 | 成本 | 复杂度 |
|------|-------|------|------|--------|
| P2-1 | **Agent 模式系统**（process/analyze/preview 三模式） | 支持 dry-run 预览，安全性提升 | 2d | M |
| P2-2 | **工具权限分级**（auto/confirm/deny 三级） | 高风险工具（distribute）需确认 | 1.5d | M |
| P2-3 | **工具自动发现**（从目录自动加载 ToolDefinition） | 新工具无需修改注册代码 | 1d | S |
| P2-4 | **Pipeline 执行事件日志** | 运行时可观测性，故障排查 | 1.5d | M |
| P2-5 | **熔断器实现**（CircuitBreaker for external APIs） | 外部服务故障隔离 | 2d | M |
| P2-6 | **Prompt 版本自动计算**（模板文件 hash） | 缓存失效自动化 | 0.5d | S |
| P2-7 | **Chat API SSE 流式输出** | 用户体验提升 | 2d | M |

### P3: 长期演进（当业务需求驱动时引入）

| 编号 | 改进项 | 适用前提 | 收益 |
|------|-------|---------|------|
| P3-1 | 插件系统 + 事件总线 | 第三方集成需求出现 | 生态扩展性 |
| P3-2 | 多租户数据隔离（tenant_id） | SaaS 化部署需求 | 数据安全 |
| P3-3 | 子任务委派（delegate 工具） | 复杂多阶段处理流程 | 任务分解能力 |
| P3-4 | 配置热更新扩展（LLM config） | 不停机调整模型参数 | 运维便捷性 |
| P3-5 | API Rate Limiting 中间件 | 公网暴露或高并发场景 | 安全防护 |

---

## 4. 修改变更计划

### 4.1 Sprint 6 调整建议（对现有 T-047~T-056 的增补）

Sprint 6 的现有任务设计合理，以下为建议增补项（可视工作量决定是否纳入 Sprint 6 或推到 Sprint 7）：

#### 增补-1: 在 T-053（ModelProfile）中增加 prompt_style 和 timeout 字段

**变更范围**：`src/intellisource/llm/model_config.py`

```python
@dataclass
class ModelProfile:
    temperature: float = 0.7
    max_tokens: int = 4096
    context_window: int = 128000
    prompt_style: str = "default"  # "default" | "structured" | "concise"
    timeout_seconds: int = 60      # LLM 调用超时
```

**影响**：T-053 的 AC 增加 2 个验收标准
- AC-T053-6: `ModelProfile.prompt_style` 可配置，默认 "default"
- AC-T053-7: `ModelProfile.timeout_seconds` 可配置，默认 60

#### 增补-2: 在 T-054（AgentRunner 增强）中增加 token 预算

**变更范围**：`src/intellisource/agent/runner.py`

```python
async def run_flexible(
    self,
    config: Any,
    user_message: str,
    session: dict[str, Any],
    max_tokens_budget: int | None = None,  # 新增
) -> dict[str, Any]:
    ...
    tokens_consumed = 0
    while steps_executed < config.max_steps:
        if max_tokens_budget and tokens_consumed >= max_tokens_budget:
            logger.warning("Token budget exhausted: %d/%d", tokens_consumed, max_tokens_budget)
            break
        response = await self._llm_gateway.chat(...)
        tokens_consumed += response.get("usage", {}).get("total_tokens", 0)
        ...
```

**影响**：T-054 的 AC 增加 1 个验收标准
- AC-T054-8: `max_tokens_budget` 超预算时中止循环并返回已有结果

#### 增补-3: 在 LLMGateway.complete() 中增加超时

**变更范围**：`src/intellisource/llm/gateway.py`

在 `litellm.acompletion()` 调用中增加 `timeout` 参数：

```python
response = await litellm.acompletion(
    model=resolved_model,
    messages=messages,
    temperature=...,
    max_tokens=...,
    timeout=timeout_seconds,  # 从 ModelProfile 获取，默认 60s
)
```

**影响**：可作为 T-053 的附属变更，无需单独任务卡

### 4.2 Sprint 7 规划草案（P1 改进项）

| 任务编号 | 标题 | 复杂度 | 依赖 |
|---------|------|--------|------|
| T-057 | LLM 调用指数退避重试（tenacity 集成） | S | T-053 |
| T-058 | 上下文压缩增强（结构化摘要 + token-based 保留） | M | T-051 |
| T-059 | 配置分层合并机制（ConfigResolver） | M | T-053 |
| T-060 | LLM 统计仪表盘 API 端点 | S | T-056 |
| T-061 | LLM 配置 Pydantic Schema 验证 | S | T-059 |
| T-062 | 模型特化 Prompt 变体（prompt_style 实现） | S | T-051, T-053 |

#### T-057: LLM 调用指数退避重试

- **目标**: 为 `LLMGateway.complete()` 增加 tenacity 重试，仅对 `RECOVERABLE_TRANSIENT` 错误重试
- **模块**: M-005
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-T057-1: RECOVERABLE_TRANSIENT 错误自动重试最多 3 次
  - [ ] AC-T057-2: 退避策略为 exponential(min=1s, max=30s)
  - [ ] AC-T057-3: UNRECOVERABLE/RECOVERABLE_DEGRADED 错误不重试
  - [ ] AC-T057-4: 重试耗尽后降级到 FallbackManager
  - [ ] AC-T057-5: 每次重试记录到 LLMCallLog（status=retry）
- **deliverables**:
  - [ ] `src/intellisource/llm/gateway.py` — retry 逻辑
  - [ ] `tests/unit/llm/test_gateway.py` — retry 测试

#### T-058: 上下文压缩增强

- **目标**: 重构 `compact_messages()` 为 token-based 保留策略 + 结构化摘要模板
- **模块**: M-006
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-T058-1: 保留策略基于 token 计数而非消息数量百分比
  - [ ] AC-T058-2: 摘要使用结构化模板（Goal/Context/Changes/State/Next Steps）
  - [ ] AC-T058-3: 工具输出优先裁剪（旧工具输出先压缩）
  - [ ] AC-T058-4: 自动触发阈值：当 estimated tokens > context_window * 0.8 时
  - [ ] AC-T058-5: 摘要质量测试：压缩后的上下文仍能回答关键问题
- **deliverables**:
  - [ ] `src/intellisource/agent/compaction.py` — 重构
  - [ ] `src/intellisource/llm/prompts/compaction_summary.txt` — 结构化摘要模板
  - [ ] `tests/unit/agent/test_compaction.py` — 更新

#### T-059: 配置分层合并机制

- **目标**: 实现 `ConfigResolver` 支持 defaults → project → env vars 三层配置合并
- **模块**: M-001 (config)
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-T059-1: `config/defaults.yaml` 作为全局默认值（版本控制内）
  - [ ] AC-T059-2: `config/llm_models.yaml` 覆盖默认值（项目级）
  - [ ] AC-T059-3: `IS_*` 环境变量覆盖 YAML 配置
  - [ ] AC-T059-4: 深度合并（nested dict recursive merge）
  - [ ] AC-T059-5: `ConfigResolver.resolve()` 返回最终合并后的 config dict
- **deliverables**:
  - [ ] `src/intellisource/config/resolver.py` — ConfigResolver 类
  - [ ] `config/defaults.yaml` — 全局默认值
  - [ ] `tests/unit/config/test_resolver.py`

#### T-060: LLM 统计仪表盘 API

- **目标**: 新增 `/api/v1/system/llm-stats` 端点，提供 token 消耗和成本统计
- **模块**: M-010 (api)
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-T060-1: 按时间范围查询 token 消耗（input/output tokens）
  - [ ] AC-T060-2: 按模型维度聚合
  - [ ] AC-T060-3: 按 task_type 维度聚合
  - [ ] AC-T060-4: 返回 cached vs non-cached 调用比例
- **deliverables**:
  - [ ] `src/intellisource/api/routers/system.py` — llm-stats 端点
  - [ ] `tests/unit/api/test_system_routes.py` — 更新

#### T-061: LLM 配置 Pydantic Schema 验证

- **目标**: 为 `config/llm_models.yaml` 创建 Pydantic 验证模型
- **模块**: M-001 (config)
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-T061-1: `LLMModelsConfig` Pydantic model 覆盖所有 YAML 字段
  - [ ] AC-T061-2: `load_model_config()` 加载后自动验证
  - [ ] AC-T061-3: 无效配置抛出 `ValidationError` 并指明具体字段
- **deliverables**:
  - [ ] `src/intellisource/llm/model_config.py` — LLMModelsConfig model
  - [ ] `tests/unit/llm/test_model_config.py` — 验证测试

#### T-062: 模型特化 Prompt 变体

- **目标**: PromptBuilder 根据 `ModelProfile.prompt_style` 选择 prompt 模板变体
- **模块**: M-005
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-T062-1: `llm/prompts/` 支持 `{name}.{style}.txt` 变体文件（如 `extraction.structured.txt`）
  - [ ] AC-T062-2: PromptBuilder 优先加载 style 匹配的模板，fallback 到默认
  - [ ] AC-T062-3: 至少为 `extraction` 和 `summarization` 提供 `structured` 和 `concise` 两个变体
- **deliverables**:
  - [ ] `src/intellisource/llm/prompts/__init__.py` — 变体加载逻辑
  - [ ] `src/intellisource/llm/prompts/extraction.structured.txt`
  - [ ] `src/intellisource/llm/prompts/extraction.concise.txt`
  - [ ] `tests/unit/llm/test_prompt_builder.py` — 变体测试

### 4.3 Sprint 8+ 规划草案（P2 改进项）

| 任务编号 | 标题 | 复杂度 | 依赖 |
|---------|------|--------|------|
| T-063 | Agent 模式系统（process/analyze/preview） | M | T-054 |
| T-064 | 工具权限分级（auto/confirm/deny） | M | T-050 |
| T-065 | 工具自动发现机制 | S | T-050 |
| T-066 | Pipeline 执行事件日志 | M | T-054 |
| T-067 | 外部 API 熔断器 | M | T-057 |
| T-068 | Prompt 版本自动计算（模板 hash） | S | T-051, T-052 |
| T-069 | Chat API SSE 流式输出 | M | T-054 |

---

## 5. IntelliSource 优于 OpenCode 的领域（重要：避免单向对标）

以下领域 IntelliSource 的设计**优于** OpenCode，应保持而非模仿：

| 领域 | IntelliSource 优势 | 原因 |
|------|-------------------|------|
| **错误分类与恢复** | 4 级 ErrorCategory + 恢复策略映射（`core/errors.py`） | OpenCode 使用简单 try-catch，无系统化错误分类 |
| **降级优先设计** | 每个 LLM 任务有对应的传统算法 fallback（`fallback.py`） | OpenCode 无降级路径——LLM 失败就是失败 |
| **结构化输出校验** | SchemaEnforcer + JSON Schema 验证（`gateway.py:70-100`） | OpenCode 依赖 LLM 自律生成结构化输出 |
| **任务型模型路由** | `ModelRoutingConfig` 按 task_type 自动选模型（`model_config.py`） | OpenCode 需手动在 config 中指定每个 agent 的模型 |
| **LLM 调用审计** | `LLMCallLog` 数据库级调用日志（E-011） | OpenCode 通过可选插件实现，非核心功能 |
| **结构化日志** | structlog + trace ID 传播（`observability/`） | OpenCode 使用文件级日志，无结构化查询能力 |
| **数据持久化** | PostgreSQL + SQLAlchemy 2.0 async ORM | OpenCode 使用本地文件，不适合服务端场景 |
| **Pipeline 处理** | BaseProcessor → PipelineEngine 模式（`pipeline/`） | OpenCode 无批处理 pipeline 概念 |
| **状态机调度** | `TaskStateMachine` FSM（`scheduler/state_machine.py`） | OpenCode 无任务调度，单次会话模式 |
| **配置热更新** | `ConfigWatcher` 文件变更监控（`config/loader.py`） | OpenCode 配置变更需重启 |

**结论**：IntelliSource 和 OpenCode 面向不同的使用场景（服务端 AI 平台 vs 交互式编码助手），不应盲目对齐。IntelliSource 应借鉴 OpenCode 在**Agent 分层、配置治理、上下文管理、权限模型**方面的设计理念，同时保持其在**错误处理、降级设计、可观测性、批处理**方面的优势。

---

## 附录：对标问题清单回答

| 问题 | 结论 | 理由 |
|------|------|------|
| 1. 是否需要引入"主代理+子代理+系统代理"体系？ | **部分引入** | 引入 "系统Agent"（compaction/analysis）概念，但不需要交互式子代理委派 |
| 2. 是否需要 provider-agnostic 统一模型抽象？ | **已有** | litellm 已提供。需增强模型特化 prompt 和上下文窗口动态查询 |
| 3. 是否需要分层配置？ | **需要** | 引入 defaults → project → env vars 三层合并 |
| 4. 是否需要项目级 Agent 指令文件（AGENTS.md）？ | **不需要** | IS 是服务端平台，CLAUDE.md + pipeline YAML 已满足需求 |
| 5. 是否需要声明式权限配置？ | **部分需要** | 工具增加 auto/confirm/deny 三级权限，通过 pipeline YAML 声明 |
| 6. 是否需要只读规划/执行/探索代理分离？ | **部分需要** | 引入 preview 模式（dry-run），但不需要 OpenCode 级别的模式系统 |
| 7. 是否需要增强上下文压缩、任务委派、会话摘要、审计日志？ | **上下文压缩和审计日志需要增强**，任务委派当前不需要，会话摘要已有基础实现 |
