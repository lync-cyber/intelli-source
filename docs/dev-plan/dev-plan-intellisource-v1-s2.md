# Development Plan 分卷 -- Sprint 2: IntelliSource
<!-- required_sections: ["## 3. 任务卡详细"] -->
<!-- volume_type: sprint -->
<!-- id: dev-plan-intellisource-v1-s2 | author: tech-lead | status: draft -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: sprint | split-from: dev-plan-intellisource-v1 -->

[NAV]

- §3 任务卡详细 → T-010..T-023 (Sprint 2: 采集引擎与原子操作层)
[/NAV]

## 3. 任务卡详细

### T-010: ToolSpec基类与工具注册中心

- **目标**: 定义原子操作的统一描述协议（ToolSpec）和工具注册中心（ToolRegistry），支持启动时自动注册、运行时查询
- **模块**: M-003
- **接口**: 无（内部框架，被 M-004/M-011/M-012 消费）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-013 映射: ToolSpec 定义 name/description/parameters(JSON Schema)/returns(JSON Schema)/idempotent/side_effects
  - [ ] AC-015 映射: ToolRegistry.register(tool_spec) 注册工具，ToolRegistry.get(name) 查询工具
  - [ ] AC-T010-1: ToolSpec 参数和返回值使用 JSON Schema 定义，支持 Pydantic 模型自动转换
  - [ ] AC-T010-2: ToolRegistry.list_tools() 返回所有已注册工具的 Schema 描述（供 MCP/API 消费）
  - [ ] AC-T010-3: ToolSpec.execute(**params) 执行原子操作前自动校验参数
  - [ ] AC-T010-4: 重复注册同名工具抛出异常
- **deliverables** (交付物):
  - [ ] `src/intellisource/tools/base.py` -- ToolSpec 基类定义
  - [ ] `src/intellisource/tools/registry.py` -- 工具注册中心
  - [ ] `src/intellisource/tools/__init__.py` -- 模块导出
  - [ ] `tests/unit/tools/test_base.py` -- ToolSpec 测试
  - [ ] `tests/unit/tools/test_registry.py` -- 注册中心测试
- **context_load**:
  - arch#§2.M-003
  - prd#§2.F-004

### T-011: 采集器抽象基类与注册中心

- **目标**: 定义统一的采集器接口（BaseCollector）和插件化注册机制（CollectorRegistry），支持按信源类型自动匹配采集器
- **模块**: M-002
- **接口**: 无（内部接口，由原子操作 collect 调用）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-005 映射: BaseCollector 定义 collect(source_config) -> list[RawContent] 统一接口
  - [ ] AC-T011-1: CollectorRegistry.register(type, collector_cls) 注册新采集器
  - [ ] AC-T011-2: CollectorRegistry.get(type) 按信源类型返回对应采集器实例
  - [ ] AC-T011-3: 未注册类型抛出明确异常（IS-COL-001）
  - [ ] AC-T011-4: 采集输出符合统一数据模型（title/author/body_html/body_text/source_url/published_at/metadata）
- **deliverables** (交付物):
  - [ ] `src/intellisource/collector/base.py` -- 采集器抽象基类
  - [ ] `src/intellisource/collector/registry.py` -- 采集器注册中心
  - [ ] `src/intellisource/collector/__init__.py` -- 模块导出
  - [ ] `tests/unit/collector/test_base.py` -- 基类测试
  - [ ] `tests/unit/collector/test_registry.py` -- 注册中心测试
- **context_load**:
  - arch#§2.M-002
  - arch-intellisource-v1-data#§4.E-003

### T-012: RSS采集适配器

- **目标**: 实现 RSS/Atom Feed 的采集适配器，支持标准 RSS 2.0、Atom 1.0 格式解析和第三方桥接（RSSHub）
- **模块**: M-002
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-006 映射: RSSCollector 正确解析 RSS 2.0 和 Atom 1.0 格式
  - [ ] AC-007 映射: 输出 RawContent 包含 title/author/body_html/body_text/source_url/published_at
  - [ ] AC-008 映射: 通过 RSSHub URL 作为信源可正常采集
  - [ ] AC-T012-1: 解析失败记录错误日志并返回空列表，不抛异常
  - [ ] AC-T012-2: 为每条内容生成 fingerprint（基于 source_url + title + published_at 的 SHA-256）
- **deliverables** (交付物):
  - [ ] `src/intellisource/collector/adapters/rss.py` -- RSS 采集适配器
  - [ ] `tests/unit/collector/test_rss.py` -- RSS 采集测试
- **context_load**:
  - arch#§2.M-002
- **实现提示**: 使用 feedparser 库解析；httpx AsyncClient 获取 Feed 内容

### T-013: Web爬虫采集适配器

- **目标**: 实现网页爬虫采集适配器，支持 HTML 页面抓取、正文提取和元数据解析
- **模块**: M-002
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-006 映射: WebCollector 正确抓取网页并提取正文内容
  - [ ] AC-007 映射: 输出 RawContent 包含 title/author/body_html/body_text/source_url
  - [ ] AC-T013-1: 使用 BeautifulSoup4 + lxml 解析 HTML
  - [ ] AC-T013-2: 正文提取能过滤导航栏、广告等非内容区域
  - [ ] AC-T013-3: 支持通过 CSS 选择器配置自定义正文提取规则
  - [ ] AC-T013-4: 请求超时（默认 30s）和连接错误正确处理
- **deliverables** (交付物):
  - [ ] `src/intellisource/collector/adapters/web.py` -- Web 爬虫适配器
  - [ ] `tests/unit/collector/test_web.py` -- Web 采集测试
- **context_load**:
  - arch#§2.M-002

### T-014: API采集适配器

- **目标**: 实现通用 API 采集适配器，支持通过配置定义 REST API 的请求方式和响应映射
- **模块**: M-002
- **接口**: 无
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-006 映射: APICollector 按配置发送 HTTP 请求并解析 JSON 响应
  - [ ] AC-007 映射: 通过字段映射配置将 API 响应转换为统一 RawContent 格式
  - [ ] AC-008 映射: 支持通过通用 API 配置接入第三方数据接口
  - [ ] AC-T014-1: 支持 GET/POST 方法，可配置 headers/params/body
  - [ ] AC-T014-2: 支持 JSONPath 表达式配置响应字段映射
- **deliverables** (交付物):
  - [ ] `src/intellisource/collector/adapters/api.py` -- API 采集适配器
  - [ ] `tests/unit/collector/test_api.py` -- API 采集测试
- **context_load**:
  - arch#§2.M-002

### T-015: 速率限制与代理管理

- **目标**: 实现基于 Redis 令牌桶的请求速率限制器和 HTTP 代理管理器，支持按信源独立配置
- **模块**: M-002
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-010 映射: ProxyManager 按信源配置返回对应的 HTTP 代理地址
  - [ ] AC-011 映射: RateLimiter 基于 Redis 令牌桶限制请求频率
  - [ ] AC-T015-1: 超出速率限制时请求等待而非直接拒绝
  - [ ] AC-T015-2: 多个 Worker 共享 Redis 中的速率限制状态
  - [ ] AC-T015-3: 信源未配置速率限制时使用全局默认值
- **deliverables** (交付物):
  - [ ] `src/intellisource/collector/rate_limiter.py` -- 速率限制器
  - [ ] `src/intellisource/collector/proxy.py` -- 代理管理器
  - [ ] `tests/unit/collector/test_rate_limiter.py` -- 速率限制测试
- **context_load**:
  - arch#§2.M-002
  - arch#§5.1（并发控制）

### T-016: 频率自适应调度

- **目标**: 实现采集频率自适应算法，根据信源历史更新频率动态调整采集间隔
- **模块**: M-002
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-009 映射: 根据历史更新频率动态计算下次采集时间
  - [ ] AC-012 映射: 采集失败时自动重试（3 次指数退避），最终失败记录日志不阻塞其他任务
  - [ ] AC-T016-1: 新增信源使用配置的默认间隔，采集 5 次后开始自适应调整
  - [ ] AC-T016-2: 自适应间隔有上下限（最短 5 分钟，最长 24 小时）
  - [ ] AC-T016-3: 连续错误累计后自动延长间隔，成功后恢复
- **deliverables** (交付物):
  - [ ] `src/intellisource/collector/adaptive.py` -- 频率自适应调度器
  - [ ] `tests/unit/collector/test_adaptive.py` -- 自适应调度测试
- **context_load**:
  - arch#§2.M-002
  - arch-intellisource-v1-data#§4.E-001（avg_update_interval, error_count 字段）

### T-017: 采集类原子操作(collect/parse)

- **目标**: 将采集引擎能力封装为 ToolSpec 原子操作：collect（执行采集）和 parse（HTML 解析清洗）
- **模块**: M-003
- **接口**: 无（通过 ToolRegistry 暴露）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-013 映射: collect 和 parse 注册到 ToolRegistry，Schema 定义完整
  - [ ] AC-016 映射: 输入输出通过显式参数传递，无隐式状态
  - [ ] AC-T017-1: collect(source_id, force) → {raw_content_ids, items_count}
  - [ ] AC-T017-2: parse(raw_content_id) → {title, body_text, author, published_at, source_url}
  - [ ] AC-T017-3: collect 标记 idempotent=true（指纹去重保证）
  - [ ] AC-T017-4: collect 的 side_effects 包含 writes_raw_content
- **deliverables** (交付物):
  - [ ] `src/intellisource/tools/collect.py` -- 采集类原子操作
  - [ ] `tests/unit/tools/test_collect.py` -- 采集操作测试
- **context_load**:
  - arch#§2.M-003
  - arch#§2.M-002

### T-018: 处理类原子操作(fingerprint/dedup/tag/sentiment)

- **目标**: 封装内容处理相关的原子操作：指纹生成、指纹去重、向量相似度查找、打标签、设置情感标签
- **模块**: M-003
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-013 映射: 全部操作注册到 ToolRegistry
  - [ ] AC-016 映射: 显式参数传递
  - [ ] AC-017 映射: dedup_by_fingerprint 支持批量调用模式
  - [ ] AC-022 映射: fingerprint 原子操作为每条内容生成唯一指纹，全链路基于指纹幂等处理
  - [ ] AC-T018-1: fingerprint(text) → {fingerprint} (SHA-256)
  - [ ] AC-T018-2: dedup_by_fingerprint(text) → {is_duplicate, fingerprint, existing_content_id}
  - [ ] AC-T018-3: find_similar(embedding, threshold, limit) → {results: [{content_id, similarity, title}]}
  - [ ] AC-T018-4: tag_content(content_id, tags) → {updated} — 调用方决定标签内容
  - [ ] AC-T018-5: set_sentiment(content_id, sentiment) → {updated} — 调用方决定情感值
- **deliverables** (交付物):
  - [ ] `src/intellisource/tools/process.py` -- 处理类原子操作
  - [ ] `tests/unit/tools/test_process.py` -- 处理操作测试
- **context_load**:
  - arch#§2.M-003
  - arch-intellisource-v1-data#§4.E-004

### T-019: 存储类原子操作(store_processed/store_embedding)

- **目标**: 封装内容存储相关的原子操作，embedding 和 summary/tags/sentiment 均由调用方传入
- **模块**: M-003
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-013 映射: 操作注册到 ToolRegistry
  - [ ] AC-016 映射: 所有字段由调用方显式传入
  - [ ] AC-069 映射: embedding 向量由调用方（内置Agent或外部Agent）生成并通过 store_processed 传入
  - [ ] AC-T019-1: store_processed(raw_content_id, summary?, tags?, sentiment?, embedding?, structured_data?) → {processed_content_id}
  - [ ] AC-T019-2: store_embedding(content_id, embedding) → {updated} — 单独存入/更新向量
  - [ ] AC-T019-3: store_processed 为 upsert 语义（idempotent=true）
  - [ ] AC-T019-4: embedding 字段可为空（外部 Agent 可后续通过 store_embedding 补充）
- **deliverables** (交付物):
  - [ ] `src/intellisource/tools/store.py` -- 存储类原子操作
  - [ ] `tests/unit/tools/test_store.py` -- 存储操作测试
- **context_load**:
  - arch#§2.M-003
  - arch-intellisource-v1-data#§4.E-004

### T-020: 检索类原子操作(search_fulltext/vector/hybrid)

- **目标**: 封装检索引擎能力为原子操作，包含全文检索、向量检索和混合检索三种模式
- **模块**: M-003, M-008
- **接口**: 无（通过 ToolRegistry 暴露，同时被 API-012 路由层调用）
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-051 映射: search_hybrid 支持关键词 + 向量语义联合查询
  - [ ] AC-056 映射: 混合检索结果按相关性排序
  - [ ] AC-T020-1: search_fulltext(keywords, tags_filter?, time_range_days?, limit?) → {results, total_count}
  - [ ] AC-T020-2: search_vector(embedding, threshold?, limit?) → {results: [{content_id, similarity, title}]}
  - [ ] AC-T020-3: search_hybrid(keywords?, embedding?, tags_filter?, time_range_days?, limit?) → {results, total_count}
  - [ ] AC-T020-4: hybrid 模式融合 ts_rank 和 cosine similarity 两个得分（可配置权重）
  - [ ] AC-T020-5: 全部检索操作 idempotent=true, side_effects=[]
- **deliverables** (交付物):
  - [ ] `src/intellisource/tools/search.py` -- 检索类原子操作
  - [ ] `src/intellisource/search/hybrid.py` -- 混合检索引擎实现
  - [ ] `tests/unit/tools/test_search.py` -- 检索操作测试
- **context_load**:
  - arch#§2.M-003
  - arch#§2.M-008
  - arch-intellisource-v1-data#§4.E-004（embedding, 全文检索索引）

### T-021: 聚类类原子操作(cluster_create/assign)

- **目标**: 封装聚类管理为原子操作，聚类的语义决策（归属判断）由编排层负责
- **模块**: M-003
- **接口**: 无
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-013 映射: 操作注册到 ToolRegistry
  - [ ] AC-T021-1: cluster_create(topic, tags?, centroid?) → {cluster_id}
  - [ ] AC-T021-2: cluster_assign(content_id, cluster_id) → {updated, new_content_count}
  - [ ] AC-T021-3: cluster_assign 更新聚类中心向量（如提供了新内容的 embedding）
- **deliverables** (交付物):
  - [ ] `src/intellisource/tools/cluster.py` -- 聚类类原子操作
  - [ ] `tests/unit/tools/test_cluster.py` -- 聚类操作测试
- **context_load**:
  - arch#§2.M-003
  - arch-intellisource-v1-data#§4.E-005

### T-022: 分发类原子操作(match_subscriptions/push)

- **目标**: 封装订阅匹配和推送为原子操作，内置推送去重
- **模块**: M-003, M-007
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-013 映射: 操作注册到 ToolRegistry
  - [ ] AC-043 映射: match_subscriptions 基于关键词/标签匹配
  - [ ] AC-T022-1: match_subscriptions(content_id) → {matched: [{subscription_id, channel, channel_config}]}
  - [ ] AC-T022-2: push(subscription_id, content_id, title_override?, body_override?) → {status, push_record_id}
  - [ ] AC-T022-3: push 内置去重（重复推送返回 status=already_sent），idempotent=true
  - [ ] AC-T022-4: push 的 side_effects 包含 [writes_push_record, sends_external_message]
  - [ ] AC-T022-5: get_push_history(subscription_id?, content_id?, limit?) → {records}
- **deliverables** (交付物):
  - [ ] `src/intellisource/tools/distribute.py` -- 分发类原子操作
  - [ ] `tests/unit/tools/test_distribute.py` -- 分发操作测试
- **context_load**:
  - arch#§2.M-003
  - arch#§2.M-007
  - arch-intellisource-v1-data#§4.E-010

### T-023: 分发器基类与订阅规则匹配

- **目标**: 定义分发器统一接口（BaseDistributor）、实现订阅规则匹配引擎和推送去重/历史记录
- **模块**: M-007
- **接口**: 无（内部框架，被 T-022 分发类原子操作调用）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-043 映射: SubscriptionMatcher 基于关键词/标签匹配推送内容到对应订阅
  - [ ] AC-T023-1: BaseDistributor 定义 distribute(content, subscription) -> PushRecord 统一接口
  - [ ] AC-T023-2: SubscriptionMatcher.match(content) 返回匹配的 Subscription 列表
  - [ ] AC-T023-3: 匹配规则支持 keywords（OR 逻辑）、tags（OR 逻辑）、sentiment 过滤
  - [ ] AC-T023-4: DeliveryTracker 记录推送历史并检查去重
- **deliverables** (交付物):
  - [ ] `src/intellisource/distributor/base.py` -- 分发器抽象基类
  - [ ] `src/intellisource/distributor/matcher.py` -- 订阅规则匹配引擎
  - [ ] `src/intellisource/distributor/__init__.py` -- 模块导出
  - [ ] `tests/unit/distributor/test_matcher.py` -- 匹配器测试
- **context_load**:
  - arch#§2.M-007
  - arch-intellisource-v1-data#§4.E-009
  - arch-intellisource-v1-data#§4.E-010
