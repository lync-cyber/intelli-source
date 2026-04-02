# Development Plan 分卷 -- Sprint 3: IntelliSource
<!-- required_sections: ["## 3. 任务卡详细"] -->
<!-- volume_type: sprint -->
<!-- id: dev-plan-intellisource-v1-s3 | author: tech-lead | status: draft -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: sprint | split-from: dev-plan-intellisource-v1 -->

[NAV]

- §3 任务卡详细 → T-024..T-036 (Sprint 3: 内置Agent与LLM服务 + 分发渠道)
[/NAV]

## 3. 任务卡详细

### T-024: LLM统一网关(litellm封装)

- **目标**: 基于 litellm 封装统一的 LLM 调用接口（LLMGateway），屏蔽不同模型提供商差异，支持 JSON Mode/Function Calling 输出格式
- **模块**: M-005
- **接口**: 无（内部接口，被 M-004 内置 Agent 调用）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-023 映射: LLMGateway.complete() 统一调用接口，支持配置不同 provider/model
  - [ ] AC-025 映射: SchemaEnforcer 强制 LLM 输出符合预定义 JSON Schema
  - [ ] AC-T024-1: 支持通过环境变量配置多个 LLM 提供商的 API Key
  - [ ] AC-T024-2: 请求参数标准化（temperature/max_tokens/system_prompt）跨提供商一致
  - [ ] AC-T024-3: 调用结果包含 input_tokens/output_tokens/latency_ms 元数据
  - [ ] AC-T024-4: 支持 function calling 模式（用于 Agent 调用原子操作）
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/gateway.py` -- LLM 统一网关
  - [ ] `src/intellisource/llm/__init__.py` -- 模块导出
  - [ ] `tests/unit/llm/test_gateway.py` -- 网关测试（使用 Mock LLM）
- **context_load**:
  - arch#§2.M-005
  - arch#§1.4（litellm 选型）
- **实现提示**: litellm.completion() 作为底层调用；使用 pydantic 校验 LLM 输出；测试使用 unittest.mock 模拟 litellm 响应

### T-025: 熔断器与成本追踪

- **目标**: 实现 LLM 调用的熔断器（Circuit Breaker）和成本追踪器（CostTracker）
- **模块**: M-005
- **接口**: API-017（LLM 用量统计的数据来源）
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-024 映射: 连续失败 5 次触发熔断（Open），60s 后半开（Half-Open）探测，成功则关闭
  - [ ] AC-026 映射: 每次 LLM 调用记录 model/input_tokens/output_tokens/latency_ms
  - [ ] AC-T025-1: 熔断状态持久化到 Redis，多 Worker 共享状态
  - [ ] AC-T025-2: 熔断器支持按 model/provider 独立跟踪
  - [ ] AC-T025-3: CostTracker 支持按 day/week/month 聚合统计
  - [ ] AC-T025-4: CostTracker 数据持久化到 LLMCallLog 表（E-007）
  - [ ] AC-T025-5: 半开状态试探成功后自动恢复正常调用
  - [ ] AC-T025-6: 熔断触发时通知 M-004 Agent 降级到 Playbook 模式
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/circuit_breaker.py` -- 熔断器实现
  - [ ] `src/intellisource/llm/cost_tracker.py` -- 成本追踪器
  - [ ] `tests/unit/llm/test_circuit_breaker.py` -- 熔断器测试
  - [ ] `tests/unit/llm/test_cost_tracker.py` -- 追踪器测试
- **context_load**:
  - arch#§2.M-005
  - arch#§5.3（熔断机制）
  - arch-intellisource-v1-data#§4.E-007

### T-026: 敏感词过滤

- **目标**: 实现内容敏感词过滤，在 LLM 调用前后双重检查
- **模块**: M-005
- **接口**: 无
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-027 映射: 支持敏感词过滤与合规检查
  - [ ] AC-T026-1: ContentFilter 在 LLM 调用前过滤输入中的敏感信息
  - [ ] AC-T026-2: ContentFilter 在 LLM 输出后二次检查
  - [ ] AC-T026-3: 敏感词库可通过配置文件加载和热更新
  - [ ] AC-T026-4: 命中敏感词的内容标记为需人工审核（不自动丢弃）
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/filter.py` -- 敏感词过滤
  - [ ] `tests/unit/llm/test_filter.py` -- 过滤器测试
- **context_load**:
  - arch#§2.M-005
  - arch#§5.2（数据安全）

### T-027: Playbook定义与确定性执行器

- **目标**: 定义预定义 Playbook（scheduled_collect/manual_collect/user_search）和 PlaybookRunner 确定性执行器，作为 Agent 的快速路径和降级兜底
- **模块**: M-004, M-006
- **接口**: 无（内部框架）
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-019 映射: 三个预定义 Playbook 完整定义
  - [ ] AC-035 映射: Playbook 为纯确定性步骤序列
  - [ ] AC-037 映射: Playbook 不依赖 LLM，作为降级兜底
  - [ ] AC-T027-1: PlaybookLibrary 定义 scheduled_collect Playbook: collect → parse → fingerprint → dedup_by_fingerprint → store_processed → match_subscriptions → push
  - [ ] AC-T027-2: PlaybookLibrary 定义 user_search Playbook: search_hybrid（纯关键词模式）→ 返回结果
  - [ ] AC-T027-3: PlaybookRunner.execute(playbook_name, params) 按步骤序列调用原子操作
  - [ ] AC-T027-4: PlaybookRunner 每步失败可配置 retry/skip/abort 策略
  - [ ] AC-T027-5: 执行过程记录到 E-013 AgentExecutionLog (mode=playbook_fallback)
- **deliverables** (交付物):
  - [ ] `src/intellisource/agent/playbooks.py` -- Playbook 定义
  - [ ] `src/intellisource/scheduler/playbook_runner.py` -- 确定性执行器
  - [ ] `tests/unit/agent/test_playbooks.py` -- Playbook 测试
  - [ ] `tests/unit/scheduler/test_playbook_runner.py` -- 执行器测试
- **context_load**:
  - arch#§2.M-004
  - arch#§2.M-006
  - arch#§5.3（Agent 降级策略）

### T-028: 内置编排Agent(ReAct主循环)

- **目标**: 实现内置编排 Agent 的 ReAct/Plan-Execute 主循环，通过 function calling 调用原子操作，支持 LLM 语义决策
- **模块**: M-004
- **接口**: 无（由 M-006 触发调用）
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-018 映射: BuiltinAgent 以 ReAct 模式运行，通过 function calling 调用原子操作
  - [ ] AC-020 映射: Agent 利用 LLM 进行语义判断（去重、聚类归属、摘要生成等）
  - [ ] AC-021 映射: LLM 不可用时自动降级到 PlaybookRunner
  - [ ] AC-T028-1: Agent System Prompt 包含可用工具列表（从 ToolRegistry 自动生成）和 Playbook 模板
  - [ ] AC-T028-2: Agent 优先匹配 Playbook 模板减少 LLM 推理（AC-038）
  - [ ] AC-T028-3: Agent 执行步数上限（MAX_STEPS=20），超限返回 max_steps_exceeded
  - [ ] AC-T028-4: Agent 工具调用前校验参数（ToolSpec.parameters Schema）
  - [ ] AC-T028-5: 完整执行链记录到 E-013 AgentExecutionLog (mode=agent)
  - [ ] AC-T028-6: 降级切换时间 < 500ms（从检测 LLM 故障到启动 PlaybookRunner）
- **deliverables** (交付物):
  - [ ] `src/intellisource/agent/orchestrator.py` -- Agent 主循环
  - [ ] `src/intellisource/agent/__init__.py` -- 模块导出
  - [ ] `tests/unit/agent/test_orchestrator.py` -- Agent 测试（Mock LLM）
- **context_load**:
  - arch#§2.M-004
  - arch#§5.3（Agent 降级策略）
- **实现提示**: LLM function calling 的工具定义从 ToolRegistry.list_tools() 自动生成；测试使用 Mock LLM 返回预定义的 tool_call 序列

### T-029: 多轮对话会话管理

- **目标**: 实现多轮对话会话管理器，保持最近 5 轮上下文，服务即时检索场景
- **模块**: M-004
- **接口**: API-013（session_id 支持）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-053 映射: 支持多轮对话上下文保持（最近 5 轮）
  - [ ] AC-T029-1: ChatSessionManager.get_or_create(channel, channel_user_id) 获取或创建会话
  - [ ] AC-T029-2: 对话上下文存储在 ChatSession.context JSONB 字段
  - [ ] AC-T029-3: 超过 5 轮时自动丢弃最早的对话
  - [ ] AC-T029-4: 超过 24 小时无活跃的会话自动清理
  - [ ] AC-T029-5: Agent 执行 user_search Playbook 时自动加载会话上下文
- **deliverables** (交付物):
  - [ ] `src/intellisource/agent/session.py` -- 对话会话管理器
  - [ ] `tests/unit/agent/test_session.py` -- 会话管理测试
- **context_load**:
  - arch#§2.M-004
  - arch-intellisource-v1-data#§4.E-011

### T-030: 任务触发管理与Celery任务定义

- **目标**: 实现任务触发管理器（TriggerManager），定义 Celery 任务封装 Agent 调用和 Playbook 执行
- **模块**: M-006
- **接口**: API-007 的业务逻辑层
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-028 映射: 支持 Celery Beat 定时触发、API 手动触发、消息触发三种模式
  - [ ] AC-029 映射: 定时任务与手动触发任务通过独立队列并行处理
  - [ ] AC-030 映射: 支持多工作节点并发执行
  - [ ] AC-T030-1: TriggerManager.trigger(trigger_type, params) 创建 TaskChain 并调度 Agent
  - [ ] AC-T030-2: Celery 任务定义: run_agent_task（调用 BuiltinAgent）、run_playbook_task（调用 PlaybookRunner）
  - [ ] AC-T030-3: 支持 low/normal/high 三级优先级队列
  - [ ] AC-T030-4: 任务链执行状态持久化到 TaskChain 表（E-008）
- **deliverables** (交付物):
  - [ ] `src/intellisource/scheduler/tasks.py` -- Celery 任务定义
  - [ ] `src/intellisource/scheduler/__init__.py` -- 模块导出
  - [ ] `tests/unit/scheduler/test_tasks.py` -- 任务定义测试
- **context_load**:
  - arch#§2.M-006
  - arch-intellisource-v1-data#§4.E-008

### T-031: 任务状态机与幂等保护

- **目标**: 实现统一任务状态机（pending->running->success/failed + pause/resume/timeout）和基于 Redis 的幂等保护
- **模块**: M-006
- **接口**: API-008, API-009 的业务逻辑层
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-031 映射: 幂等设计覆盖内容指纹去重 + 推送记录 + 分布式锁
  - [ ] AC-032 映射: 状态机支持 pending/running/success/failed/paused/cancelled 状态转换
  - [ ] AC-T031-1: IdempotencyGuard.acquire(source_id) 获取分布式锁
  - [ ] AC-T031-2: 锁超时自动释放（默认 5 分钟），防止死锁
  - [ ] AC-T031-3: pause 操作暂停正在执行的任务链
  - [ ] AC-T031-4: 任务超时（可配置）自动标记为 failed
- **deliverables** (交付物):
  - [ ] `src/intellisource/scheduler/state_machine.py` -- 任务状态机
  - [ ] `src/intellisource/scheduler/idempotency.py` -- 幂等保护器
  - [ ] `tests/unit/scheduler/test_state_machine.py` -- 状态机测试
  - [ ] `tests/unit/scheduler/test_idempotency.py` -- 幂等测试
- **context_load**:
  - arch#§2.M-006
  - arch#§5.1（并发控制）

### T-032: 工作流定义管理

- **目标**: 实现用户自定义工作流的 CRUD 管理，支持 Cron 定时执行
- **模块**: M-006
- **接口**: API-010, API-011, API-026~029 的业务逻辑层
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-034 映射: 工作流支持自定义步骤组合
  - [ ] AC-036 映射: 支持 Cron 定时执行或仅手动触发
  - [ ] AC-039 映射: 支持定时/手动/消息三种触发模式
  - [ ] AC-T032-1: WorkflowManager.create(name, steps, schedule) 创建工作流并持久化
  - [ ] AC-T032-2: WorkflowManager.run(workflow_id, override_params) 触发工作流执行
  - [ ] AC-T032-3: 支持 Cron 表达式注册到 Celery Beat
  - [ ] AC-T032-4: 工作流 CRUD 与 Workflow 表（E-012）正确交互
- **deliverables** (交付物):
  - [ ] `src/intellisource/scheduler/workflow.py` -- 工作流管理
  - [ ] `tests/unit/scheduler/test_workflow.py` -- 工作流测试
- **context_load**:
  - arch#§2.M-006
  - arch-intellisource-v1-data#§4.E-012

### T-033: 微信公众号分发渠道

- **目标**: 实现微信公众号推送（模板消息/图文消息），包含 Access Token 管理
- **模块**: M-007
- **接口**: 无（由分发类原子操作 push 调用）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-040 映射: WeChatDistributor 支持发送模板消息和图文消息
  - [ ] AC-044 映射: 同一内容对同一用户同一渠道不重复推送
  - [ ] AC-045 映射: 推送失败自动重试（3次，固定间隔5s）
  - [ ] AC-T033-1: Access Token 缓存到 Redis，过期前自动刷新
  - [ ] AC-T033-2: 推送结果记录到 PushRecord
- **deliverables** (交付物):
  - [ ] `src/intellisource/distributor/channels/wechat.py` -- 微信公众号分发
  - [ ] `tests/unit/distributor/test_wechat.py` -- 微信推送测试（Mock）
- **context_load**:
  - arch#§2.M-007

### T-034: 企业微信分发渠道

- **目标**: 实现企业微信应用消息推送
- **模块**: M-007
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-041 映射: WeWorkDistributor 支持发送应用消息
  - [ ] AC-044 映射: 不重复推送
  - [ ] AC-045 映射: 推送失败自动重试
  - [ ] AC-T034-1: 企业微信 Access Token 缓存与刷新
  - [ ] AC-T034-2: 支持文本/Markdown/图文卡片消息格式
- **deliverables** (交付物):
  - [ ] `src/intellisource/distributor/channels/wework.py` -- 企业微信分发
  - [ ] `tests/unit/distributor/test_wework.py` -- 企业微信推送测试
- **context_load**:
  - arch#§2.M-007

### T-035: 邮件分发渠道

- **目标**: 实现 HTML 格式邮件推送
- **模块**: M-007
- **接口**: 无
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-042 映射: EmailDistributor 通过 SMTP 发送 HTML 格式邮件
  - [ ] AC-044 映射: 不重复推送
  - [ ] AC-045 映射: 推送失败自动重试
  - [ ] AC-T035-1: SMTP 配置通过环境变量读取
  - [ ] AC-T035-2: 邮件内容使用 HTML 模板格式化
  - [ ] AC-T035-3: 支持 TLS/SSL 加密连接
- **deliverables** (交付物):
  - [ ] `src/intellisource/distributor/channels/email.py` -- 邮件分发
  - [ ] `tests/unit/distributor/test_email.py` -- 邮件推送测试
- **context_load**:
  - arch#§2.M-007

### T-036: 推送频率控制与免打扰

- **目标**: 实现推送频率控制（realtime/hourly/daily/weekly）和免打扰时段
- **模块**: M-007
- **接口**: 无
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-046 映射: 支持推送频率控制和免打扰时段
  - [ ] AC-T036-1: FrequencyController 按订阅配置的频率批量/延迟推送
  - [ ] AC-T036-2: hourly/daily/weekly 模式下内容聚合后统一推送
  - [ ] AC-T036-3: 免打扰时段内的推送延迟到时段结束后发送
  - [ ] AC-T036-4: realtime 模式下内容立即推送
- **deliverables** (交付物):
  - [ ] `src/intellisource/distributor/frequency.py` -- 频率控制器
  - [ ] `tests/unit/distributor/test_frequency.py` -- 频率控制测试
- **context_load**:
  - arch#§2.M-007
  - arch-intellisource-v1-data#§4.E-009（frequency, quiet_hours 字段）
