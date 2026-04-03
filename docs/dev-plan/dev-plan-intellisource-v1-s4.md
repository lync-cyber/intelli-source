# Development Plan 分卷 -- Sprint 4: IntelliSource
<!-- required_sections: ["## 3. 任务卡详细"] -->
<!-- volume_type: sprint -->
<!-- id: dev-plan-intellisource-v1-s4 | author: tech-lead | status: approved -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: sprint | split-from: dev-plan-intellisource-v1 -->

[NAV]

- §3 任务卡详细 → T-027..T-036 (Sprint 4: 任务编排与分发)
[/NAV]

## 3. 任务卡详细

### T-027: Celery任务定义与任务链构建

- **目标**: 定义 Celery 任务（采集/处理/分发），实现任务链构建器将多个阶段串联为原子任务链
- **模块**: M-006
- **接口**: 无（内部基础设施）
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-034 映射: 采集->处理->存储->分发串联为原子任务链，单步失败可独立重试
  - [ ] AC-035 映射: 定时任务与手动触发任务通过独立队列并行处理
  - [ ] AC-T027-1: TaskChainBuilder.build(source_ids, pipeline_config, distribute_config) 返回 Celery chain
  - [ ] AC-T027-2: 单步失败时记录错误到 CollectTask.error_message，不中断后续步骤（可配置）
  - [ ] AC-T027-3: 任务链执行状态持久化到 TaskChain 表（E-008）
  - [ ] AC-T027-4: 支持 low/normal/high 三级优先级队列
- **deliverables** (交付物):
  - [ ] `src/intellisource/scheduler/tasks.py` -- Celery 任务定义
  - [ ] `src/intellisource/scheduler/chains.py` -- 任务链构建器
  - [ ] `src/intellisource/scheduler/__init__.py` -- 模块导出
  - [ ] `tests/unit/scheduler/test_tasks.py` -- 任务定义测试
  - [ ] `tests/unit/scheduler/test_chains.py` -- 任务链测试
- **context_load**:
  - arch#§2.M-006
  - arch-intellisource-v1-data#§4.E-002
  - arch-intellisource-v1-data#§4.E-008
  - arch#§5.3（重试策略）

### T-028: 任务状态机与调度管理

- **目标**: 实现统一任务状态机（pending->running->success/failed + pause/resume/timeout）和定时调度管理
- **模块**: M-006
- **接口**: API-008, API-009 的业务逻辑层
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-038 映射: 状态机支持 pending/running/success/failed/paused/cancelled 状态转换
  - [ ] AC-039 映射: 支持 Celery Beat 定时调度、手动触发、消息触发三种模式
  - [ ] AC-T028-1: pause 操作暂停正在执行的任务链（revoke pending subtasks）
  - [ ] AC-T028-2: resume 操作从暂停点恢复执行
  - [ ] AC-T028-3: 任务超时（可配置）自动标记为 failed
  - [ ] AC-T028-4: SchedulerManager 管理 Celery Beat 定时任务的注册和取消
- **deliverables** (交付物):
  - [ ] `src/intellisource/scheduler/state_machine.py` -- 任务状态机
  - [ ] `tests/unit/scheduler/test_state_machine.py` -- 状态机测试
- **context_load**:
  - arch#§2.M-006
  - arch-intellisource-v1-data#§4.E-002（status 字段）
  - arch-intellisource-v1-api#API-008
  - arch-intellisource-v1-api#API-009

### T-029: 幂等保护与分布式锁

- **目标**: 实现基于内容指纹、推送记录和 Redis 分布式锁的幂等保护机制，防止重复处理和推送
- **模块**: M-006
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-036 映射: 多工作节点并发执行任务时不产生重复处理
  - [ ] AC-037 映射: 幂等设计覆盖文档指纹去重 + 推送记录 + 分布式锁三层
  - [ ] AC-T029-1: IdempotencyGuard.acquire(source_id) 获取分布式锁，防止同一信源并发采集
  - [ ] AC-T029-2: 锁超时自动释放（默认 5 分钟），防止死锁
  - [ ] AC-T029-3: 内容指纹去重在入库前检查 RawContent.fingerprint 唯一约束
  - [ ] AC-T029-4: 推送去重通过 PushRecord 的 (subscription_id, content_id, channel) 唯一约束
- **deliverables** (交付物):
  - [ ] `src/intellisource/scheduler/idempotency.py` -- 幂等保护器
  - [ ] `tests/unit/scheduler/test_idempotency.py` -- 幂等测试
- **context_load**:
  - arch#§2.M-006
  - arch#§5.1（并发控制）
  - arch-intellisource-v1-data#§4.E-010（去重约束）
- **实现提示**: Redis SET NX EX 实现分布式锁；内容指纹唯一约束由数据库层保证

### T-030: 工作流引擎

- **目标**: 实现用户自定义工作流引擎，支持灵活组合采集-处理-分发步骤
- **模块**: M-006
- **接口**: API-010, API-011 的业务逻辑层
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-063 映射: 工作流支持自定义步骤组合（collect/process/distribute 的灵活编排）
  - [ ] AC-T030-1: WorkflowEngine.create(name, steps, schedule) 创建工作流定义并持久化
  - [ ] AC-T030-2: WorkflowEngine.run(workflow_id, override_params) 实例化工作流为 TaskChain 执行
  - [ ] AC-T030-3: 每个步骤支持 on_failure 策略（retry/skip/abort）
  - [ ] AC-T030-4: 支持 Cron 表达式定时执行（注册到 Celery Beat）
  - [ ] AC-T030-5: 工作流 CRUD 操作与 Workflow 表（E-012）正确交互
- **deliverables** (交付物):
  - [ ] `src/intellisource/scheduler/workflow.py` -- 工作流引擎
  - [ ] `tests/unit/scheduler/test_workflow.py` -- 工作流测试
- **context_load**:
  - arch#§2.M-006
  - arch-intellisource-v1-data#§4.E-012
  - arch-intellisource-v1-api#API-010
  - arch-intellisource-v1-api#API-011

### T-031: 分发器基类与订阅规则匹配

- **目标**: 定义分发器统一接口（BaseDistributor）、实现订阅规则匹配引擎和推送去重/历史记录
- **模块**: M-007
- **接口**: 无（内部框架）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-043 映射: SubscriptionMatcher 基于关键词/标签匹配推送内容到对应订阅
  - [ ] AC-T031-1: BaseDistributor 定义 distribute(content, subscription) -> PushRecord 统一接口
  - [ ] AC-T031-2: SubscriptionMatcher.match(content) 返回匹配的 Subscription 列表
  - [ ] AC-T031-3: 匹配规则支持 keywords（OR 逻辑）、tags（OR 逻辑）过滤
  - [ ] AC-T031-4: DeliveryTracker 记录推送历史并检查去重
- **deliverables** (交付物):
  - [ ] `src/intellisource/distributor/base.py` -- 分发器抽象基类
  - [ ] `src/intellisource/distributor/matcher.py` -- 订阅规则匹配引擎
  - [ ] `src/intellisource/distributor/__init__.py` -- 模块导出
  - [ ] `tests/unit/distributor/test_matcher.py` -- 匹配器测试
- **context_load**:
  - arch#§2.M-007
  - arch-intellisource-v1-data#§4.E-009
  - arch-intellisource-v1-data#§4.E-010

### T-032: 微信公众号分发渠道

- **目标**: 实现微信公众号推送（模板消息/图文消息），包含 Access Token 管理和推送结果追踪
- **模块**: M-007
- **接口**: 无（由 M-006 任务链触发）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-040 映射: WeChatDistributor 支持通过微信公众号发送模板消息和图文消息
  - [ ] AC-044 映射: 同一内容对同一用户同一渠道不重复推送
  - [ ] AC-045 映射: 推送失败自动重试（3次，固定间隔5s），记录推送历史
  - [ ] AC-T032-1: Access Token 缓存到 Redis，过期前自动刷新
  - [ ] AC-T032-2: 推送内容格式化为微信支持的消息格式
  - [ ] AC-T032-3: 推送结果（成功/失败/错误码）记录到 PushRecord
- **deliverables** (交付物):
  - [ ] `src/intellisource/distributor/channels/wechat.py` -- 微信公众号分发
  - [ ] `tests/unit/distributor/test_wechat.py` -- 微信推送测试（Mock 微信 API）
- **context_load**:
  - arch#§2.M-007
  - arch#§5.3（重试策略 -- 推送失败）
- **实现提示**: 微信公众号 API 使用 httpx；测试使用 Mock 服务模拟微信接口响应

### T-033: 企业微信分发渠道

- **目标**: 实现企业微信应用消息推送，包含 Access Token 管理和消息格式化
- **模块**: M-007
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-041 映射: WeWorkDistributor 支持通过企业微信发送应用消息
  - [ ] AC-044 映射: 同一内容不重复推送
  - [ ] AC-045 映射: 推送失败自动重试
  - [ ] AC-T033-1: 企业微信 Access Token 缓存与刷新
  - [ ] AC-T033-2: 支持文本/Markdown/图文卡片消息格式
  - [ ] AC-T033-3: 推送结果追踪
- **deliverables** (交付物):
  - [ ] `src/intellisource/distributor/channels/wework.py` -- 企业微信分发
  - [ ] `tests/unit/distributor/test_wework.py` -- 企业微信推送测试
- **context_load**:
  - arch#§2.M-007
  - arch#§5.3（重试策略）

### T-034: 邮件分发渠道

- **目标**: 实现 HTML 格式邮件推送，支持 SMTP 配置和邮件模板
- **模块**: M-007
- **接口**: 无
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-042 映射: EmailDistributor 通过 SMTP 发送 HTML 格式邮件
  - [ ] AC-044 映射: 同一内容不重复推送
  - [ ] AC-045 映射: 推送失败自动重试
  - [ ] AC-T034-1: SMTP 配置通过环境变量读取（IS_SMTP_HOST/PORT/USER/PASSWORD）
  - [ ] AC-T034-2: 邮件内容使用 HTML 模板格式化（标题/摘要/来源链接）
  - [ ] AC-T034-3: 支持 TLS/SSL 加密连接
- **deliverables** (交付物):
  - [ ] `src/intellisource/distributor/channels/email.py` -- 邮件分发
  - [ ] `tests/unit/distributor/test_email.py` -- 邮件推送测试
- **context_load**:
  - arch#§2.M-007
- **实现提示**: 使用 Python 标准库 email + aiosmtplib 实现异步 SMTP 发送

### T-035: 推送频率控制与免打扰

- **目标**: 实现推送频率控制（realtime/hourly/daily/weekly）和免打扰时段功能
- **模块**: M-007
- **接口**: 无
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-046 映射: 支持推送频率控制和免打扰时段配置
  - [ ] AC-T035-1: FrequencyController 按订阅配置的频率批量/延迟推送
  - [ ] AC-T035-2: hourly/daily/weekly 模式下内容聚合后统一推送
  - [ ] AC-T035-3: 免打扰时段内的推送延迟到时段结束后发送
  - [ ] AC-T035-4: realtime 模式下内容立即推送（不受频率控制）
- **deliverables** (交付物):
  - [ ] `src/intellisource/distributor/frequency.py` -- 频率控制器
  - [ ] `tests/unit/distributor/test_frequency.py` -- 频率控制测试
- **context_load**:
  - arch#§2.M-007
  - arch-intellisource-v1-data#§4.E-009（frequency, quiet_hours 字段）

### T-036: 推送内容LLM优化

- **目标**: 实现推送前的 LLM 内容重排序和引导语生成处理器
- **模块**: M-004
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-047 映射: PushOptimizer 调用 LLM 对推送内容按相关性/重要性重排序
  - [ ] AC-048 映射: 为推送内容生成简短引导语/摘要
  - [ ] AC-049 映射: LLM 处理失败时降级为默认排序和无引导语格式
  - [ ] AC-T036-1: PushOptimizer 实现 BaseProcessor 接口
  - [ ] AC-T036-2: 降级逻辑使用默认时间排序 + 无引导语
  - [ ] AC-T036-3: 优化结果不修改原始内容，仅影响推送呈现
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/processors/optimizer.py` -- 推送优化处理器
  - [ ] `tests/unit/llm/test_optimizer.py` -- 优化器测试
- **context_load**:
  - arch#§2.M-004
  - arch#§5.3（降级策略）
  - prd#§2.F-010
