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

### T-027: Celery任务定义与调度触发

- **目标**: 定义 Celery 任务作为调度触发层，负责定时/手动/消息触发后调用 AgentRunner 执行对应管道配置
- **模块**: M-006
- **接口**: 无（内部基础设施）
- **复杂度**: M
- **status**: done
- **tdd_acceptance**:
  - [x] AC-034 映射: Celery 任务触发 AgentRunner 执行管道配置，单步失败可独立重试
  - [x] AC-035 映射: 定时任务与手动触发任务通过独立队列并行处理
  - [x] AC-T027-1: CeleryTasks.run_pipeline(pipeline_name, params) 加载管道配置并调用 AgentRunner
  - [x] AC-T027-2: 单步失败时记录错误到 CollectTask.error_message
  - [x] AC-T027-3: 任务链执行状态持久化到 TaskChain 表（E-008），包含 pipeline_name 和 execution_mode
  - [x] AC-T027-4: 支持 low/normal/high 三级优先级队列
- **deliverables** (交付物):
  - [x] `src/intellisource/scheduler/tasks.py` -- Celery 任务定义（触发层）
  - [x] `src/intellisource/scheduler/__init__.py` -- 模块导出
  - [x] `tests/unit/scheduler/test_tasks.py` -- 任务定义测试
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
- **status**: done
- **tdd_acceptance**:
  - [x] AC-038 映射: 状态机支持 pending/running/success/failed/paused/cancelled 状态转换
  - [x] AC-039 映射: 支持 Celery Beat 定时调度、手动触发、消息触发三种模式
  - [x] AC-T028-1: pause 操作暂停正在执行的任务链（revoke pending subtasks）
  - [x] AC-T028-2: resume 操作从暂停点恢复执行
  - [x] AC-T028-3: 任务超时（可配置）自动标记为 failed
  - [x] AC-T028-4: SchedulerManager 管理 Celery Beat 定时任务的注册和取消
- **deliverables** (交付物):
  - [x] `src/intellisource/scheduler/state_machine.py` -- 任务状态机
  - [x] `tests/unit/scheduler/test_state_machine.py` -- 状态机测试
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
- **status**: done
- **tdd_acceptance**:
  - [x] AC-036 映射: 多工作节点并发执行任务时不产生重复处理
  - [x] AC-037 映射: 幂等设计覆盖文档指纹去重 + 推送记录 + 分布式锁三层
  - [x] AC-T029-1: IdempotencyGuard.acquire(source_id) 获取分布式锁，防止同一信源并发采集
  - [x] AC-T029-2: 锁超时自动释放（默认 5 分钟），防止死锁
  - [x] AC-T029-3: 内容指纹去重在入库前检查 RawContent.fingerprint 唯一约束
  - [x] AC-T029-4: 推送去重通过 PushRecord 的 (subscription_id, content_id, channel) 唯一约束
- **deliverables** (交付物):
  - [x] `src/intellisource/scheduler/idempotency.py` -- 幂等保护器
  - [x] `tests/unit/scheduler/test_idempotency.py` -- 幂等测试
- **context_load**:
  - arch#§2.M-006
  - arch#§5.1（并发控制）
  - arch-intellisource-v1-data#§4.E-010（去重约束）
- **实现提示**: Redis SET NX EX 实现分布式锁；内容指纹唯一约束由数据库层保证

### T-030: AgentRunner双模式执行引擎

- **目标**: 实现双模式 Agent 执行引擎。strict 模式按管道配置步骤顺序直接调用工具函数（零 LLM 开销，用于定时任务）；flexible 模式运行 LLM Agent Loop，LLM 自主选择工具调用（用于即时检索）
- **模块**: M-006
- **接口**: 无（内部引擎，被 CeleryTasks 和 Webhook 处理调用）
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-066 映射: PipelineConfig 正确解析 YAML 管道配置文件（mode, tools_allowed/denied, steps, max_steps）
  - [ ] AC-067 映射: strict 模式按 steps 顺序直接调用工具函数，不经过 LLM；flexible 模式通过 LLM Agent Loop 自主编排工具调用
  - [ ] AC-T030-1: AgentRunner.run_strict(pipeline_config, params) 按步骤顺序执行，返回执行结果
  - [ ] AC-T030-2: AgentRunner.run_flexible(pipeline_config, user_message, session) 运行 LLM Agent Loop
  - [ ] AC-T030-3: flexible 模式下 max_steps 超限时强制终止并返回当前结果
  - [ ] AC-T030-4: flexible 模式下 tools_denied 中的工具不出现在 LLM 可用工具列表中
  - [ ] AC-T030-5: strict 模式执行失败时按管道配置的 on_failure 策略处理（retry/skip/abort）
  - [ ] AC-T030-6: 两种模式的执行结果均持久化到 TaskChain 表（E-008）
- **deliverables** (交付物):
  - [ ] `src/intellisource/agent/__init__.py` -- 模块导出
  - [ ] `src/intellisource/agent/runner.py` -- AgentRunner 双模式执行引擎
  - [ ] `src/intellisource/agent/pipeline.py` -- PipelineConfig 管道配置加载与校验
  - [ ] `src/intellisource/agent/prompts/base.txt` -- Agent 基础系统提示词
  - [ ] `config/pipelines/scheduled-collect.yaml` -- 定时采集管道配置示例
  - [ ] `config/pipelines/instant-search.yaml` -- 即时检索管道配置示例
  - [ ] `tests/unit/agent/test_runner.py` -- AgentRunner 测试
  - [ ] `tests/unit/agent/test_pipeline.py` -- 管道配置测试
- **context_load**:
  - arch#§2.M-006
  - arch#§1.2（双模式 Agent 调度）
  - prd#§2.F-008（AC-066, AC-067）
- **实现提示**: strict 模式本质上是配置驱动的函数调用序列；flexible 模式使用 litellm 的 function calling 能力，将工具定义传给 LLM 并循环处理 tool_calls 直到 LLM 返回文本响应或达到 max_steps

### T-031: 分发器基类与订阅规则匹配（含高级关键词/权重评分）

- **目标**: 定义分发器统一接口（BaseDistributor）、实现支持高级关键词语法的订阅规则匹配引擎、内容权重评分器和推送去重/历史记录
- **模块**: M-007
- **接口**: 无（内部框架）
- **复杂度**: M
- **status**: done
- **tdd_acceptance**:
  - [x] AC-043 映射: SubscriptionMatcher 基于关键词/标签匹配推送内容到对应订阅
  - [x] AC-043a: SubscriptionMatcher 结合 ContentScorer 权重评分进行推送排序和阈值过滤
  - [x] AC-T031-1: BaseDistributor 定义 distribute(content, subscription) -> PushRecord 统一接口
  - [x] AC-T031-2: SubscriptionMatcher.match(content) 返回匹配的 Subscription 列表
  - [x] AC-T031-3: 匹配规则支持 keywords（OR 逻辑）、tags（OR 逻辑）
  - [x] AC-T031-4: 关键词高级语法：普通词（包含即匹配）、`+`前缀必选词（必须包含）、`!`前缀排除词（排除匹配）、`/pattern/`正则匹配
  - [x] AC-T031-5: ContentScorer.score(content, subscription) 综合计算权重分（源可信度 × 时间衰减 × 关键词匹配度），推送时按权重降序排列
  - [x] AC-T031-6: Subscription.match_rules.min_score 阈值过滤，权重低于阈值的内容不推送（默认 0 表示不过滤）
  - [x] AC-T031-7: DeliveryTracker 记录推送历史并检查去重
- **deliverables** (交付物):
  - [x] `src/intellisource/distributor/base.py` -- 分发器抽象基类
  - [x] `src/intellisource/distributor/matcher.py` -- 订阅规则匹配引擎（含高级关键词语法解析）
  - [x] `src/intellisource/distributor/scorer.py` -- 内容权重评分器
  - [x] `src/intellisource/distributor/__init__.py` -- 模块导出
  - [x] `tests/unit/distributor/test_matcher.py` -- 匹配器测试（含高级关键词语法）
  - [x] `tests/unit/distributor/test_scorer.py` -- 权重评分测试
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

### T-036: Agent工具注册与管道配置

- **目标**: 将各模块的核心功能包装为 Agent 可调用的工具函数，注册到 AgentToolRegistry；创建各场景的管道配置文件
- **模块**: M-006
- **接口**: 无（内部基础设施）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-066 映射: 管道配置文件正确定义各场景的工具集和步骤约束
  - [ ] AC-T036-1: AgentToolRegistry 注册 collect 工具（调用 M-002 采集引擎）
  - [ ] AC-T036-2: AgentToolRegistry 注册 process 工具（调用 M-003 处理管道）
  - [ ] AC-T036-3: AgentToolRegistry 注册 distribute 工具（调用 M-007 分发）
  - [ ] AC-T036-4: AgentToolRegistry 注册 search 工具（调用 M-008 混合检索引擎）
  - [ ] AC-T036-5: AgentToolRegistry 注册 get_content_detail 工具（调用 M-009 内容详情）
  - [ ] AC-T036-6: 工具定义包含 name/description/parameters(JSON Schema)/execute 函数
  - [ ] AC-T036-7: scheduled-collect.yaml 管道配置：mode=strict, tools_allowed=[collect,process,distribute]
  - [ ] AC-T036-8: instant-search.yaml 管道配置：mode=flexible, tools_allowed=[search,get_content_detail,summarize_for_user]
- **deliverables** (交付物):
  - [ ] `src/intellisource/agent/tools.py` -- Agent 工具定义与注册
  - [ ] `config/pipelines/scheduled-collect.yaml` -- 定时采集管道配置
  - [ ] `config/pipelines/manual-collect.yaml` -- 手动触发管道配置
  - [ ] `config/pipelines/instant-search.yaml` -- 即时检索管道配置
  - [ ] `tests/unit/agent/test_tools.py` -- 工具注册测试
- **context_load**:
  - arch#§2.M-006（AgentToolRegistry）
  - arch#§2.M-002, M-003, M-007, M-008（各模块作为工具来源）
