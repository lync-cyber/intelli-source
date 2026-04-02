# Development Plan 分卷 -- Sprint 2: IntelliSource
<!-- required_sections: ["## 3. 任务卡详细"] -->
<!-- volume_type: sprint -->
<!-- id: dev-plan-intellisource-v1-s2 | author: tech-lead | status: draft -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: sprint | split-from: dev-plan-intellisource-v1 -->

[NAV]
- §3 任务卡详细 → T-010..T-018 (Sprint 2: 采集引擎与处理管道)
[/NAV]

## 3. 任务卡详细

### T-010: 采集器抽象基类与注册中心
- **目标**: 定义统一的采集器接口（BaseCollector）和插件化注册机制（CollectorRegistry），支持按信源类型自动匹配采集器
- **模块**: M-002
- **接口**: 无（内部接口，由 M-006 调度）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-005 映射: BaseCollector 定义 collect(source_config) -> list[RawContent] 统一接口
  - [ ] AC-T010-1: CollectorRegistry.register(type, collector_cls) 注册新采集器
  - [ ] AC-T010-2: CollectorRegistry.get(type) 按信源类型返回对应采集器实例
  - [ ] AC-T010-3: 未注册类型抛出明确异常（IS-COL-001）
  - [ ] AC-T010-4: 采集输出符合统一数据模型（title/author/body_html/body_text/source_url/published_at/metadata）
- **deliverables** (交付物):
  - [ ] `src/intellisource/collector/base.py` -- 采集器抽象基类
  - [ ] `src/intellisource/collector/registry.py` -- 采集器注册中心
  - [ ] `src/intellisource/collector/__init__.py` -- 模块导出
  - [ ] `tests/unit/collector/test_base.py` -- 基类测试
  - [ ] `tests/unit/collector/test_registry.py` -- 注册中心测试
- **context_load**:
  - arch#§2.M-002
  - arch-intellisource-v1-data#§4.E-003
  - arch#§5.3（错误码体系）

### T-011: RSS采集适配器
- **目标**: 实现 RSS/Atom Feed 的采集适配器，支持标准 RSS 2.0、Atom 1.0 格式解析和第三方桥接（RSSHub）
- **模块**: M-002
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-006 映射: RSSCollector 正确解析 RSS 2.0 和 Atom 1.0 格式
  - [ ] AC-007 映射: 输出 RawContent 包含 title/author/body_html/body_text/source_url/published_at
  - [ ] AC-008 映射: 通过 RSSHub URL 作为信源可正常采集（与标准 RSS 逻辑一致）
  - [ ] AC-T011-1: 解析失败（格式错误）记录错误日志并返回空列表，不抛异常
  - [ ] AC-T011-2: 为每条内容生成 fingerprint（基于 source_url + title + published_at 的 SHA-256）
- **deliverables** (交付物):
  - [ ] `src/intellisource/collector/adapters/rss.py` -- RSS 采集适配器
  - [ ] `tests/unit/collector/test_rss.py` -- RSS 采集测试（含 RSS 2.0 / Atom fixture）
- **context_load**:
  - arch#§2.M-002
  - arch-intellisource-v1-data#§4.E-003
- **实现提示**: 使用 feedparser 库解析；httpx AsyncClient 获取 Feed 内容；注意处理编码和时区

### T-012: Web爬虫采集适配器
- **目标**: 实现网页爬虫采集适配器，支持 HTML 页面抓取、正文提取和元数据解析
- **模块**: M-002
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-006 映射: WebCollector 正确抓取网页并提取正文内容
  - [ ] AC-007 映射: 输出 RawContent 包含 title/author/body_html/body_text/source_url
  - [ ] AC-T012-1: 使用 BeautifulSoup4 + lxml 解析 HTML
  - [ ] AC-T012-2: 正文提取能过滤导航栏、广告等非内容区域（基于常见 HTML 结构启发式规则）
  - [ ] AC-T012-3: 支持通过 CSS 选择器配置自定义正文提取规则（在 source metadata 中配置）
  - [ ] AC-T012-4: 请求超时（默认 30s）和连接错误正确处理
- **deliverables** (交付物):
  - [ ] `src/intellisource/collector/adapters/web.py` -- Web 爬虫适配器
  - [ ] `tests/unit/collector/test_web.py` -- Web 采集测试
- **context_load**:
  - arch#§2.M-002
  - arch-intellisource-v1-data#§4.E-003
- **实现提示**: httpx AsyncClient 抓取；BeautifulSoup4 解析；可参考 readability 算法实现正文提取

### T-013: API采集适配器
- **目标**: 实现通用 API 采集适配器，支持通过配置定义 REST API 的请求方式和响应映射
- **模块**: M-002
- **接口**: 无
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-006 映射: APICollector 按配置发送 HTTP 请求并解析 JSON 响应
  - [ ] AC-007 映射: 通过字段映射配置将 API 响应转换为统一 RawContent 格式
  - [ ] AC-008 映射: 支持通过通用 API 配置接入第三方数据接口
  - [ ] AC-T013-1: 支持 GET/POST 方法，可配置 headers/params/body
  - [ ] AC-T013-2: 支持 JSONPath 表达式配置响应字段映射
- **deliverables** (交付物):
  - [ ] `src/intellisource/collector/adapters/api.py` -- API 采集适配器
  - [ ] `tests/unit/collector/test_api.py` -- API 采集测试
- **context_load**:
  - arch#§2.M-002
  - arch-intellisource-v1-data#§4.E-003

### T-014: 速率限制与代理管理
- **目标**: 实现基于 Redis 令牌桶的请求速率限制器和 HTTP 代理管理器，支持按信源独立配置
- **模块**: M-002
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-010 映射: ProxyManager 按信源配置返回对应的 HTTP 代理地址
  - [ ] AC-011 映射: RateLimiter 基于 Redis 令牌桶限制请求频率（QPS 和并发数）
  - [ ] AC-T014-1: 超出速率限制时请求等待而非直接拒绝（令牌桶补充后继续）
  - [ ] AC-T014-2: 多个 Worker 共享 Redis 中的速率限制状态
  - [ ] AC-T014-3: 信源未配置速率限制时使用全局默认值
- **deliverables** (交付物):
  - [ ] `src/intellisource/collector/rate_limiter.py` -- 速率限制器
  - [ ] `src/intellisource/collector/proxy.py` -- 代理管理器
  - [ ] `tests/unit/collector/test_rate_limiter.py` -- 速率限制测试
- **context_load**:
  - arch#§2.M-002
  - arch#§5.1（并发控制）
- **实现提示**: Redis 令牌桶实现参考经典算法；使用 Redis MULTI/EXEC 保证原子性

### T-015: 频率自适应调度
- **目标**: 实现采集频率自适应算法，根据信源历史更新频率动态调整采集间隔
- **模块**: M-002
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-009 映射: 根据历史更新频率动态计算下次采集时间（更新频繁缩短间隔，反之延长）
  - [ ] AC-012 映射: 采集失败时自动重试（3 次指数退避），最终失败记录日志不阻塞其他任务
  - [ ] AC-T015-1: 新增信源使用配置的默认间隔，采集 5 次后开始自适应调整
  - [ ] AC-T015-2: 自适应间隔有上下限（最短 5 分钟，最长 24 小时）
  - [ ] AC-T015-3: 连续错误累计后自动延长间隔（退避机制），成功后恢复
- **deliverables** (交付物):
  - [ ] `src/intellisource/collector/adaptive.py` -- 频率自适应调度器
  - [ ] `tests/unit/collector/test_adaptive.py` -- 自适应调度测试
- **context_load**:
  - arch#§2.M-002
  - arch-intellisource-v1-data#§4.E-001（avg_update_interval, error_count 字段）
  - arch#§5.3（重试策略）

### T-016: 处理管道引擎与处理器基类
- **目标**: 实现可编排的处理管道执行引擎（PipelineEngine）、处理器抽象基类（BaseProcessor）和管道上下文（PipelineContext）
- **模块**: M-003
- **接口**: 无（内部框架）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-013 映射: PipelineEngine 按配置顺序依次执行处理器
  - [ ] AC-015 映射: BaseProcessor 定义 process(context) -> context 统一接口
  - [ ] AC-016 映射: PipelineContext 支持处理器间数据传递（get/set 键值对）
  - [ ] AC-T016-1: 处理器执行异常不中断管道，记录错误并继续下一个处理器（可配置 fail_fast 模式）
  - [ ] AC-T016-2: 管道执行前后触发日志记录（含执行耗时）
- **deliverables** (交付物):
  - [ ] `src/intellisource/pipeline/engine.py` -- 管道执行引擎
  - [ ] `src/intellisource/pipeline/base.py` -- 处理器抽象基类
  - [ ] `src/intellisource/pipeline/context.py` -- 管道上下文
  - [ ] `src/intellisource/pipeline/__init__.py` -- 模块导出
  - [ ] `tests/unit/pipeline/test_engine.py` -- 管道引擎测试
  - [ ] `tests/unit/pipeline/test_context.py` -- 上下文测试
- **context_load**:
  - arch#§2.M-003
  - prd#§2.F-004

### T-017: 管道条件分支与批处理模式
- **目标**: 扩展管道引擎支持条件跳过（基于内容类型/标签）、条件分支和批处理模式
- **模块**: M-003
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-014 映射: 处理器可配置条件表达式，不满足时跳过该处理器
  - [ ] AC-017 映射: 支持批处理模式（一次传入多条内容，处理器批量处理）
  - [ ] AC-T017-1: 条件表达式支持基于 content_type、tags、source_type 的简单规则
  - [ ] AC-T017-2: 批处理模式下管道上下文维护每条内容的独立状态
  - [ ] AC-T017-3: 条件分支支持 if-else 路由到不同处理器子链
- **deliverables** (交付物):
  - [ ] `src/intellisource/pipeline/condition.py` -- 条件评估器（ConditionEvaluator）
  - [ ] `src/intellisource/pipeline/batch.py` -- 批处理适配器（BatchProcessor）
  - [ ] `tests/unit/pipeline/test_condition.py` -- 条件分支测试
  - [ ] `tests/unit/pipeline/test_batch.py` -- 批处理测试
- **context_load**:
  - arch#§2.M-003
  - prd#§2.F-004

### T-018: 内置处理器(解析/去重/打标/格式化)
- **目标**: 实现管道内置的基础处理器：HTML 解析、内容指纹去重、关键词打标、格式转换
- **模块**: M-003
- **接口**: 无
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-015 映射: 每个处理器实现 BaseProcessor 接口，可独立注册到管道
  - [ ] AC-T018-1: HTMLParser 从 body_html 提取纯文本存入 body_text
  - [ ] AC-T018-2: ContentDedup 基于内容指纹（SHA-256）检测重复内容并标记
  - [ ] AC-T018-3: KeywordTagger 基于预定义关键词库为内容添加标签
  - [ ] AC-T018-4: FormatConverter 将内容转换为统一格式（清理多余空白、标准化编码等）
- **deliverables** (交付物):
  - [ ] `src/intellisource/pipeline/processors/parser.py` -- HTML 解析处理器
  - [ ] `src/intellisource/pipeline/processors/dedup.py` -- 指纹去重处理器
  - [ ] `src/intellisource/pipeline/processors/tagger.py` -- 关键词打标处理器
  - [ ] `src/intellisource/pipeline/processors/formatter.py` -- 格式转换处理器
  - [ ] `tests/unit/pipeline/test_processors.py` -- 内置处理器测试
- **context_load**:
  - arch#§2.M-003
  - arch-intellisource-v1-data#§4.E-003
  - arch-intellisource-v1-data#§4.E-004
