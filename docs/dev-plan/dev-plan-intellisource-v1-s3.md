# Development Plan 分卷 -- Sprint 3: IntelliSource
<!-- required_sections: ["## 3. 任务卡详细"] -->
<!-- volume_type: sprint -->
<!-- id: dev-plan-intellisource-v1-s3 | author: tech-lead | status: draft -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: sprint | split-from: dev-plan-intellisource-v1 -->

[NAV]

- §3 任务卡详细 → T-019..T-026, T-019a (Sprint 3: LLM智能处理)
[/NAV]

## 3. 任务卡详细

### T-019: LLM统一网关(litellm封装)

- **目标**: 基于 litellm 封装统一的 LLM 调用接口（LLMGateway），屏蔽不同模型提供商差异，支持 JSON Mode/Function Calling 输出格式
- **模块**: M-005
- **接口**: 无（内部接口，被 M-004/M-008 调用）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-028 映射: LLMGateway.complete() 统一调用接口，支持配置不同 provider/model
  - [ ] AC-031 映射: SchemaEnforcer 强制 LLM 输出符合预定义 JSON Schema
  - [ ] AC-T019-1: 支持通过环境变量配置多个 LLM 提供商的 API Key
  - [ ] AC-T019-2: 请求参数标准化（temperature/max_tokens/system_prompt）跨提供商一致
  - [ ] AC-T019-3: 调用结果包含 input_tokens/output_tokens/latency_ms 元数据
  - [ ] AC-T019-4: JSON Schema 校验失败时抛出 SchemaValidationError
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/gateway.py` -- LLM 统一网关
  - [ ] `src/intellisource/llm/__init__.py` -- 模块导出
  - [ ] `src/intellisource/llm/schemas/` -- LLM 输入输出 JSON Schema 目录
  - [ ] `tests/unit/llm/test_gateway.py` -- 网关测试（使用 Mock LLM）
- **context_load**:
  - arch#§2.M-005
  - arch#§1.4（litellm 选型）
- **实现提示**: litellm.completion() 作为底层调用；使用 pydantic 校验 LLM 输出；测试使用 unittest.mock 模拟 litellm 响应

### T-019a: LLM模型能力声明与智能路由

- **目标**: 实现模型能力注册表（ModelRegistry）和智能路由器（SmartRouter），通过 YAML 配置声明每个模型的能力维度，根据 LLM 任务类型自动选择最优模型
- **模块**: M-005
- **接口**: 无（内部接口，被 LLMGateway 调用）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-T019a-1: ModelRegistry 从 `config/llm_models.yaml` 加载模型能力声明（context_window、supports_json_mode、supports_function_calling、cost_per_1k_tokens、best_for 列表），支持热加载更新
  - [ ] AC-T019a-2: SmartRouter.select_model(task_type, constraints) 根据任务类型（extraction/summarization/embedding/sentiment/tagging）+ 模型能力 + 可选成本约束返回最优模型标识
  - [ ] AC-T019a-3: 无匹配模型时降级到配置的 default_model 并记录 WARNING 日志
  - [ ] AC-T019a-4: LLMGateway 集成 SmartRouter，调用时可传入 task_type 参数自动路由（也可手动指定 model 覆盖路由）
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/models.py` -- 模型能力注册表（ModelRegistry）
  - [ ] `src/intellisource/llm/router.py` -- 智能路由器（SmartRouter）
  - [ ] `config/llm_models.example.yaml` -- 模型能力配置示例
  - [ ] `tests/unit/llm/test_models.py` -- 模型注册表测试
  - [ ] `tests/unit/llm/test_router.py` -- 智能路由器测试
- **context_load**:
  - arch#§2.M-005（ModelRegistry、SmartRouter 组件定义）
  - arch#§5.3（降级策略）
- **实现提示**: YAML 配置示例应包含至少 3 个模型声明（如 gpt-4o、claude-sonnet、embedding-ada-002）；SmartRouter 优先匹配 best_for 列表，其次按 cost_per_1k_tokens 升序排列

### T-020: 熔断器与降级管理器

- **目标**: 实现 LLM 调用的熔断器（Circuit Breaker）和降级管理器（FallbackManager），确保 LLM 故障时主流程不中断
- **模块**: M-005
- **接口**: 无
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-029 映射: 连续失败 5 次触发熔断（Open），60s 后半开（Half-Open）探测，成功则关闭
  - [ ] AC-030 映射: 降级切换时间 < 500ms（从检测故障到执行降级逻辑的耗时）
  - [ ] AC-T020-1: 熔断状态持久化到 Redis，多 Worker 共享状态
  - [ ] AC-T020-2: 熔断器支持按 model/provider 独立跟踪
  - [ ] AC-T020-3: FallbackManager 维护降级映射表（LLM处理 -> 传统处理逻辑）
  - [ ] AC-T020-4: 降级事件记录到 LLMCallLog（status=fallback）
  - [ ] AC-T020-5: 半开状态试探成功后自动恢复正常调用
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/circuit_breaker.py` -- 熔断器实现
  - [ ] `src/intellisource/llm/fallback.py` -- 降级管理器
  - [ ] `tests/unit/llm/test_circuit_breaker.py` -- 熔断器测试
  - [ ] `tests/unit/llm/test_fallback.py` -- 降级测试
- **context_load**:
  - arch#§2.M-005
  - arch#§5.3（熔断机制、降级策略）
- **实现提示**: 熔断器状态机使用 Redis HASH 存储（failure_count, state, last_failure_at）；降级映射表见 arch#§5.3 降级策略表

### T-021: LLM优先级队列与成本追踪

- **目标**: 实现 LLM 调用的优先级队列（隔离用户交互和后台处理请求）和成本追踪器（记录 Token 消耗/延迟）
- **模块**: M-005
- **接口**: API-017（LLM 用量统计的数据来源）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-032 映射: 用户交互请求（priority=high）和后台处理请求（priority=normal/low）使用独立队列
  - [ ] AC-033 映射: 每次 LLM 调用记录 model/input_tokens/output_tokens/latency_ms/input_length/output_length
  - [ ] AC-T021-1: PriorityQueue 确保高优先级请求先执行
  - [ ] AC-T021-2: CostTracker 支持按 day/week/month 聚合统计
  - [ ] AC-T021-3: CostTracker 数据持久化到 LLMCallLog 表（E-007）
  - [ ] AC-T021-4: 支持按 model/call_type 维度查询统计
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/priority_queue.py` -- 优先级队列
  - [ ] `src/intellisource/llm/cost_tracker.py` -- 成本追踪器
  - [ ] `tests/unit/llm/test_priority_queue.py` -- 队列测试
  - [ ] `tests/unit/llm/test_cost_tracker.py` -- 追踪器测试
- **context_load**:
  - arch#§2.M-005
  - arch-intellisource-v1-data#§4.E-007
  - arch-intellisource-v1-api#API-017

### T-022: LLM结构化提取处理器

- **目标**: 实现 LLM 结构化数据提取处理器（作为管道处理器），支持按 JSON Schema 从文本中提取结构化信息
- **模块**: M-004
- **接口**: 无（管道处理器，由 M-003 调度）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-018 映射: 传统解析失败时调用 LLM 按 JSON Schema 提取结构化数据
  - [ ] AC-021 映射: LLM 输出不合规时降级到传统处理逻辑（正则/规则提取）
  - [ ] AC-T022-1: LLMExtractor 实现 BaseProcessor 接口
  - [ ] AC-T022-2: 提取结果写入 ProcessedContent.structured_data 字段
  - [ ] AC-T022-3: 降级逻辑使用规则引擎+正则提取（arch#§5.3 降级映射表）
  - [ ] AC-T022-4: 提取处理记录到 LLMCallLog（call_type=extract）
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/processors/extractor.py` -- 结构化提取处理器
  - [ ] `src/intellisource/llm/processors/__init__.py` -- 模块导出
  - [ ] `src/intellisource/llm/schemas/extraction.json` -- 提取 JSON Schema
  - [ ] `tests/unit/llm/test_extractor.py` -- 提取器测试
- **context_load**:
  - arch#§2.M-004
  - arch#§5.3（降级策略）
  - arch-intellisource-v1-data#§4.E-004（structured_data 字段）

### T-023: 语义去重处理器

- **目标**: 实现基于向量检索 + LLM 判定的语义级去重处理器，识别语义相同但表述不同的内容
- **模块**: M-004
- **接口**: 无
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-019 映射: 向量检索候选后调用 LLM 精确判定是否为重复内容
  - [ ] AC-022 映射: 每条内容生成唯一指纹，全链路基于指纹幂等处理
  - [ ] AC-T023-1: 相似度阈值可配置（默认 0.85）
  - [ ] AC-T023-2: 去重流程：(1) 生成 embedding -> (2) 向量检索候选 -> (3) LLM 判定 -> (4) 标记重复
  - [ ] AC-T023-3: 降级逻辑使用内容指纹 + SimHash 相似度
  - [ ] AC-T023-4: FingerprintGenerator 生成稳定的内容指纹（SHA-256，基于标题+正文归一化）
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/processors/dedup.py` -- 语义去重处理器
  - [ ] `src/intellisource/llm/processors/fingerprint.py` -- 内容指纹生成器
  - [ ] `tests/unit/llm/test_dedup.py` -- 语义去重测试
- **context_load**:
  - arch#§2.M-004
  - arch-intellisource-v1-data#§4.E-004（embedding, fingerprint 字段）
  - arch#§5.3（降级策略）
- **实现提示**: 向量检索调用 M-009 VectorStore；LLM 判定使用简短 prompt（给出两篇文章判断是否重复）；SimHash 降级可用 simhash 库

### T-024: 内容聚类处理器

- **目标**: 实现同主题多源内容的自动聚类处理器，将相关内容归组并生成聚类主题
- **模块**: M-004
- **接口**: 无
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-020 映射: 同一事件/主题的多源内容自动聚类为一组
  - [ ] AC-T024-1: 聚类基于内容向量的 cosine similarity，阈值可配置
  - [ ] AC-T024-2: 新内容优先尝试归入已有聚类，无匹配则创建新聚类
  - [ ] AC-T024-3: 聚类主题（topic）由 LLM 生成
  - [ ] AC-T024-4: 降级逻辑使用 TF-IDF + 余弦相似度聚类
  - [ ] AC-T024-5: 聚类中心向量（centroid）随新内容加入更新
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/processors/cluster.py` -- 内容聚类处理器
  - [ ] `tests/unit/llm/test_cluster.py` -- 聚类测试
- **context_load**:
  - arch#§2.M-004
  - arch-intellisource-v1-data#§4.E-005
  - arch#§5.3（降级策略）
- **实现提示**: 增量聚类策略：新内容到来时与现有聚类中心比较，超过阈值则归入，否则新建

### T-025: 摘要/打标处理器

- **目标**: 实现 LLM 驱动的综合简报生成和语义打标处理器
- **模块**: M-004
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-023 映射: DigestGenerator 对同聚类多篇文档生成综合简报（含时间线和要点）
  - [ ] AC-024 映射: SemanticTagger 基于语义为内容打标签，无法归类则进入"未分类"
  - [ ] AC-027 映射: 所有处理器均支持降级到传统逻辑
  - [ ] AC-T025-1: DigestGenerator 输出包含 title/summary/timeline/key_points
  - [ ] AC-T025-2: 打标降级使用关键词匹配 + 预定义标签库
  - [ ] AC-T025-3: 摘要降级使用截断式摘要（取前 N 句）
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/processors/summarizer.py` -- 摘要/简报生成处理器
  - [ ] `src/intellisource/llm/processors/tagger.py` -- 语义打标处理器
  - [ ] `tests/unit/llm/test_summarizer.py` -- 摘要测试
  - [ ] `tests/unit/llm/test_tagger.py` -- 打标测试
- **context_load**:
  - arch#§2.M-004
  - arch-intellisource-v1-data#§4.E-004（tags 字段）
  - arch-intellisource-v1-data#§4.E-006
  - arch#§5.3（降级策略）

### T-026: 敏感词过滤与合规检查

- **目标**: 实现内容敏感词过滤和合规检查处理器，在 LLM 调用前后双重检查
- **模块**: M-004
- **接口**: 无
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-026 映射: 支持敏感词过滤与合规检查
  - [ ] AC-T026-1: ContentFilter 实现 BaseProcessor 接口
  - [ ] AC-T026-2: 敏感词库可通过配置文件加载和热更新
  - [ ] AC-T026-3: LLM 调用前过滤输入中的敏感信息
  - [ ] AC-T026-4: LLM 输出后二次检查，过滤可能生成的敏感内容
  - [ ] AC-T026-5: 命中敏感词的内容标记为需人工审核（不自动丢弃）
- **deliverables** (交付物):
  - [ ] `src/intellisource/llm/processors/filter.py` -- 敏感词过滤处理器
  - [ ] `tests/unit/llm/test_filter.py` -- 过滤器测试
- **context_load**:
  - arch#§2.M-004
  - prd#§2.F-006（AC-026）
  - arch#§5.2（数据安全）
