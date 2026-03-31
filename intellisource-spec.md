# IntelliSource — 完整工具规格与设计工作流

> 面向"AI + 工业自动化"领域微信公众号创作的信息检索、交叉验证与结构化输出工具

---

## 第一部分：完整功能特性列表

### 1. 工具定位

IntelliSource 解决的核心问题是：公众号创作者从"手动搜索 → 拼凑素材 → 凭记忆核实"的低效流程，升级为"系统采集 → 自动验证 → 结构化素材包"的可信赖工作流。

与 TrendRadar 的本质区别：TrendRadar 解决"信息太多看不过来"（热度聚合 + 关键词过滤）；IntelliSource 解决"这些信息哪些是真的、哪些对我有用、我能基于它们写出可信的内容吗"（事件感知 + 事实校验 + 领域排序 + 知识积累）。

### 2. 统一配置体系

所有行为通过一个集中的 YAML 配置树控制，用户只需要编辑这一个入口：

```yaml
# intellisource.yaml — 唯一的配置入口

# ─── 全局设置 ───
global:
  timezone: "Asia/Shanghai"
  language: "zh"                      # 主语言
  data_dir: "./data"                  # 数据存储目录
  log_level: "INFO"
  proxy:
    enabled: false
    url: ""

# ─── 领域定义 ───
domain:
  name: "AI + 工业自动化"
  keywords_file: "keywords.yaml"       # 领域关键词库（独立文件）
  credibility_file: "credibility.yaml" # 来源可信度分级（独立文件）
  columns:                             # 公众号栏目定义
    - id: "academic"
      name: "学术前沿"
      content_types: ["paper"]
      style: "论文解读，侧重方法论和创新点"
    - id: "industry"
      name: "行业动态"
      content_types: ["announcement", "article"]
      style: "深度分析，侧重影响和竞品对比"
    - id: "tech"
      name: "技术专栏"
      content_types: ["repo", "article"]
      style: "工程实践，侧重架构和实现细节"
    - id: "people"
      name: "人物故事"
      content_types: ["article"]
      style: "叙事为主，侧重引用和个人观点"

# ─── 信息源配置 ───
sources:
  arxiv:
    enabled: true
    categories: ["cs.AI", "cs.RO", "cs.SY", "cs.MA"]
    max_results: 100
    schedule: "0 6 * * *"             # 每天早 6 点
    tier: 1

  rss:
    enabled: true
    schedule: "0 */4 * * *"           # 每 4 小时
    request_interval_ms: 2000
    freshness_max_days: 3
    feeds:
      - id: "ieee-spectrum"
        name: "IEEE Spectrum"
        url: "https://spectrum.ieee.org/feeds/feed.rss"
        tier: 2
        focus: ["robotics", "AI"]
      - id: "jiqizhixin"
        name: "机器之心"
        url: "https://www.jiqizhixin.com/rss"
        tier: 2
      # ... 更多 feeds

  github:
    enabled: true
    languages: ["python", "cpp", "rust"]
    min_stars_velocity: 50             # 日增 star 数阈值
    schedule: "0 8,20 * * *"
    tier: 3

  company_blogs:
    enabled: true
    schedule: "0 */6 * * *"
    sites:
      - id: "openai"
        name: "OpenAI Blog"
        url: "https://openai.com/blog/rss.xml"
        tier: 1
      - id: "abb"
        name: "ABB News"
        url: "https://new.abb.com/news/feed"
        tier: 1
      # ... 更多公司

  web_search:
    enabled: true
    provider: "tavily"                 # tavily | searxng
    tavily_api_key_env: "TAVILY_API_KEY"
    searxng_url: ""                    # 自托管 SearXNG 地址
    tier: 4                            # 搜索结果默认 tier 4

  policy:
    enabled: false                     # 默认关闭，需要 Firecrawl
    sites: []
    schedule: "0 */6 * * *"
    tier: 1

# ─── 处理参数 ───
processing:
  dedup:
    method: "hybrid"                   # exact | semantic | hybrid
    semantic_threshold: 0.85           # cosine similarity 阈值
    time_window_hours: 72              # 语义去重的时间窗口
  
  entity_extraction:
    enabled: true
    model: "same_as_ai"               # 使用 AI 配置中的模型
  
  translate:
    enabled: false                     # 是否翻译非主语言内容
    target_language: "zh"
  
  embedding:
    provider: "chromadb"
    model: "default"                   # ChromaDB 默认 embedding
    collection: "content_items"

# ─── 验证参数 ───
verification:
  enabled: true
  min_sources_for_verified: 2          # 至少 N 个独立来源才标记"已验证"
  auto_verify_tier1: true              # tier 1 来源是否自动标记为已验证
  claim_extraction:
    enabled: true                      # 是否做声明级验证（更精细但更耗 token）
  credibility_weights:
    source_authority: 0.40
    temporal_freshness: 0.20
    cross_validation: 0.30
    consistency: 0.10

# ─── 分析参数 ───
analysis:
  event_clustering:
    enabled: true
    llm_confirm: true                  # 向量召回后是否用 LLM 确认
    cluster_time_window_hours: 72
  
  ranking:
    domain_relevance_weight: 0.30
    novelty_weight: 0.20
    authority_weight: 0.20
    freshness_weight: 0.15
    verification_weight: 0.15
    freshness_decay_rate: 0.02         # 指数衰减速率
  
  trend_detection:
    enabled: true
    min_mentions: 3                    # 至少 N 次提及才算趋势
    window_days: 7

# ─── 输出配置 ───
output:
  structured_json:
    enabled: true
    include_claims: true               # 输出中包含声明级验证详情
    include_writing_angles: true       # 输出中包含写作角度建议
  
  html_report:
    enabled: true
    output_dir: "./output/reports"
  
  draft_generation:
    enabled: false                     # 是否自动生成草稿
    prompt_template: "default"
  
  notifications:
    feishu_webhook: ""
    wechat_webhook: ""
    email: { enabled: false }

# ─── AI 模型 ───
ai:
  provider: "litellm"
  model: "claude-sonnet-4-20250514"
  api_key_env: "AI_API_KEY"
  api_base: ""                         # 自定义 API 端点
  max_tokens: 4000
  timeout: 120
  temperature: 0.3

# ─── 知识库 ───
knowledge:
  enabled: true
  hot_data_retention_days: 30          # 热数据保留天数
  distill_on_expire: true              # 过期数据是否蒸馏为知识
  entity_profile: true                 # 是否维护实体档案

# ─── Pipeline 组合 ───
pipelines:
  daily_collection:
    schedule: "0 7,12,19 * * *"
    steps:
      - arxiv_collect
      - rss_collect
      - github_trending
      - normalize
      - deduplicate
      - entity_extract
      - embed_index
      - event_cluster
      - rank_filter
      - html_report
      - push_notify

  reactive_query:
    trigger: "on_demand"               # MCP 调用触发
    steps:
      - local_index_search
      - web_search_fallback
      - normalize
      - deduplicate
      - entity_extract
      - cross_check
      - credibility_score
      - rank_filter
      - structure_output

  deep_research:
    trigger: "on_demand"
    steps:
      - web_search_fallback
      - normalize
      - deduplicate
      - translate
      - entity_extract
      - embed_index
      - cross_check
      - credibility_score
      - claim_verify
      - event_cluster
      - trend_detect
      - rank_filter
      - structure_output
      - draft_generate

# ─── MCP Server ───
mcp:
  enabled: true
  transport: "stdio"                   # stdio | sse
  tools:
    - search_topic
    - deep_dive
    - verify_claim
    - compare_sources
    - generate_brief
    - recall_history

# ─── 监控 ───
monitoring:
  health_check:
    enabled: true
    expected_daily_items:               # 每个源的日均数据量基线
      arxiv: 80
      rss: 200
      github: 30
    alert_on_consecutive_failures: 3
  coverage_report:
    enabled: true
    schedule: "0 22 * * *"             # 每晚 10 点
  keyword_expansion:
    enabled: true
    schedule: "0 0 * * 1"             # 每周一凌晨
```

### 3. 核心功能特性

#### 3.1 采集能力（Collect）

- 多源并行采集：arXiv API、RSS 订阅、GitHub Trending、公司官网、政策页面、按需 Web 搜索
- 信息源四级可信度分层：Tier 1 原始事实 → Tier 2 专业解读 → Tier 3 社区信号 → Tier 4 聚合衍生
- 每个源独立配置调度周期、过滤参数、最大条目数
- Source Plugin 自注册机制：新增来源只需写一个文件 + 改配置，零侵入已有代码
- 信息源健康监控：数据量基线异常检测、连续失败告警

#### 3.2 处理能力（Process）

- 格式标准化：所有来源输出统一 ContentItem 数据模型（含 identity、provenance、verification state、lifecycle、embedding 五组字段）
- 双重去重：精确标题匹配 + embedding 语义相似度（阈值可配），支持跨语言识别同一事件
- NER 实体抽取：用 LLM 从标题和摘要中提取公司名、人名、技术术语
- 向量索引构建：ChromaDB 持久化，支持语义搜索和相似度查询
- 可选翻译：检测非主语言内容，用 LLM 翻译标题和摘要

#### 3.3 验证能力（Verify）— IntelliSource 核心差异化

- **事件级聚类**：两阶段（向量召回 + LLM 确认），将多来源对同一事件的报道聚合为事件簇，自带多源覆盖分析
- **声明级验证**：从事件簇中提取离散事实声明，对每个声明独立搜索佐证，输出 verified / unverified / disputed 三态
- **可信度评分模型**：四因子加权（来源权威性 40% + 时效性 20% + 交叉验证 30% + 一致性 10%），权重可配
- **LLM 辅助判断**：对低分信息做逻辑一致性检查，检测夸大或误导性表述

#### 3.4 分析能力（Analyze）

- **领域相关性排序**：五因子模型（领域匹配度 30% + 信息新颖度 20% + 来源权威度 20% + 时效性 15% + 验证状态 15%），所有权重可配
- **趋势检测**：关键词/实体频率变化追踪，突增检测（过去 7 天内提及次数 ≥ 阈值）
- **新颖度感知**：相对于知识库已有内容计算增量价值，避免重复推荐已充分报道的话题

#### 3.5 输出能力（Output）

- **结构化写作素材包**：每个事件输出 JSON 包含要点摘要、声明验证详情、可引用片段、数据来源列表、写作角度建议
- **栏目模板适配**：按用户定义的栏目（学术前沿 / 行业动态 / 技术专栏 / 人物故事）自动调整输出格式和风格
- **草稿生成**：LLM 基于已验证素材生成初稿，prompt 模板可自定义
- **多渠道分发**：HTML 报告、飞书/企微推送、JSON 导出、MCP 工具接口
- **Sink Plugin 自注册**：新增渠道只需写一个文件 + 改配置

#### 3.6 对话式研究助手（Reactive Mode）

通过 MCP Server 暴露六个原子工具，支持 Claude 等 AI 客户端多轮对话式调用：

- `search_topic`：领域信息搜索，返回带可信度的排序结果
- `deep_dive`：对特定事件深挖，补充搜索 + 逐一验证声明
- `verify_claim`：验证一个具体声明
- `compare_sources`：对比同一事件的不同来源（哪些一致、矛盾、独有）
- `generate_brief`：基于选定事件生成写作素材包
- `recall_history`：回溯一个实体过去 N 天的历史信息和趋势

响应式查询采用"本地优先 + Web 补充"策略：先查 ChromaDB 索引（毫秒级），不够再触发实时搜索（秒级）。

#### 3.7 长期知识图谱

- 热数据层：最近 N 天的 ContentItem 全量数据（SQLite + ChromaDB），实时更新
- 冷知识层：过期数据"蒸馏"为实体档案（公司/人物/技术的持续画像）、事件时间线（摘要 + 来源链接）、实体关系图
- 支持回答长周期问题："ABB 今年发布了几款新产品""工业视觉检测过去半年的趋势"

#### 3.8 运维与自我进化

- 覆盖率日报：按信号层级、内容类型、语言统计，标注降级来源和覆盖盲区
- 关键词库自动扩展：LLM 每周分析新出现的高频术语，人工确认后加入
- 实体图谱扩展：首次出现的新公司/产品自动触发背景搜索，提示是否加入长期监控

### 4. 设计模式总结

| 模式 | 解决什么问题 | 关键机制 |
|------|------------|---------|
| Plugin Registry | 新增来源/渠道不改已有代码 | 装饰器自注册 + 自动扫描 + YAML 配置驱动 |
| Step / Context / Pipeline | pipeline 流程可自由组合 | Step 原子化 + Context 松耦合 + 声明式组装 |
| 统一配置树 | 所有参数一个入口 | 单一 YAML + 子文件引用 + 环境变量覆盖 |
| 四级信号分层 | 区分信息可信度 | 入库时固定 source_tier，驱动验证力度和排序权重 |
| 事件聚类 | 识别"多条新闻说同一件事" | 向量召回 + LLM 确认两阶段 |
| 声明级验证 | 精确到"哪句话可信哪句不可信" | LLM 声明提取 + 独立搜索佐证 + 三态标记 |
| 领域相关性排序 | 按"对我多重要"而非"热不热"排 | 五因子加权 + 可学习的 DomainProfile |
| 热冷分离知识库 | 长期记忆 + 避免重复推荐 | 热数据过期蒸馏为冷知识实体档案 |
| Dual-mode 触发 | 定时养数据 + 实时用数据 | Cron pipeline + MCP 响应式接口共享 Core |

### 5. 技术栈

- 语言：Python 3.11+
- 存储：SQLite（元数据）+ ChromaDB（向量索引）
- AI：LiteLLM（兼容 100+ 模型提供商）
- 采集：requests + feedparser（RSS）、各平台 API client、Firecrawl（网页结构化）
- 搜索：Tavily API / SearXNG（自托管元搜索）
- 接口：FastMCP（MCP Server）
- 调度：APScheduler（轻量）或 Prefect（重型，可选）
- 加速：LlamaIndex Data Connectors（100+ 数据源 connector 可复用）

---

## 第二部分：从 0 到 1 设计工作流

本工作流的重点不是代码实现，而是**通过互动讨论逐步澄清需求、确定设计决策**的过程。每个 Phase 标注了 LLM 应主导的讨论、需要用户做出的决策、以及该阶段的验收产出。

### Phase 0：项目定义与边界确认

**目标**：对齐工具的目标、非目标、约束条件。

**LLM 主导的讨论**：

1. 确认目标公众号的定位
   - 具体覆盖哪些子领域？（AI 的哪些方向？工业自动化的哪些环节？）
   - 发文频率和每篇的信息密度？（日更短讯 vs 周更深度？）
   - 目标读者画像？（研究者 / 工程师 / 管理层 / 投资人？）

2. 确认工具的使用场景
   - 主要是定时推送素材报告，还是写作时按需查询？两者比例？
   - 是否需要多人协作？（多个编辑共用同一个知识库？）
   - 部署环境？（本地笔记本 / 云服务器 / GitHub Actions？）

3. 确认非目标（明确不做什么）
   - 是否需要自动发布到公众号？（还是只到草稿箱？）
   - 是否需要覆盖中文互联网热榜？（如果需要，可以直接复用 TrendRadar 的采集能力）
   - 是否需要处理视频/播客内容？

**用户决策清单**：
- [ ] 确认领域范围和子领域优先级
- [ ] 确认栏目列表和每个栏目的风格定义
- [ ] 确认部署环境和资源限制
- [ ] 确认核心使用场景（定时 vs 按需的比例）

**验收产出**：一份项目 charter（1 页），包含目标、非目标、约束条件、优先级排序。

---

### Phase 1：信息源规划

**目标**：确定要接入哪些信息源、优先级、以及每个源的可信度分级。

**LLM 主导的讨论**：

1. 用信息生命周期矩阵评估覆盖完整性
   - LLM 展示矩阵（萌芽 / 早期采纳 / 主流爆发 / 成熟 / 巩固 × 学术 / 开源 / 媒体 / 官方 / 政策 / 社区）
   - 逐格讨论：这个交叉点对你的公众号有多重要？有哪些可选来源？
   - 识别必须覆盖的核心格和可以暂缓的边缘格

2. 确定每个源的可信度分级
   - LLM 提供默认分级建议，用户确认或调整
   - 讨论边界 case：比如"知乎高赞回答算 Tier 几？""公司官方博客的技术文章 vs 新闻稿是否应该区分？"

3. 确定采集频率和数据量预期
   - 每个源每天预期产出多少条数据？
   - 哪些源需要实时采集（如公司新闻稿）？哪些日频即可（如 arXiv）？

4. 讨论覆盖盲区
   - 有哪些信息类型是系统无法覆盖的？（闭门会议、付费报告、私域社群）
   - 如何在输出中标注这些盲区？

**用户决策清单**：
- [ ] 确认信息源清单和优先级排序（第一批接入哪些）
- [ ] 确认每个源的 tier 分级
- [ ] 确认采集频率
- [ ] 确认关键词库初始内容

**验收产出**：完成的 `sources.yaml` 和 `credibility.yaml` 配置文件，以及一份信息源覆盖分析。

---

### Phase 2：数据模型设计

**目标**：确定 ContentItem 的字段、事件簇的结构、知识图谱的 schema。

**LLM 主导的讨论**：

1. ContentItem 字段逐一确认
   - Identity 组：id 生成策略、content_type 枚举值、language 支持范围
   - Provenance 组：source_tier 的具体含义、raw_metadata 需要保留哪些源特有字段
   - Verification 组：verification_status 的状态流转、credibility_score 的范围和含义
   - Lifecycle 组：cluster_id 的生成时机、trend_velocity 的计算方式

2. 事件簇（EventCluster）结构设计
   - 一个事件簇包含哪些元数据？（摘要、来源分布、声明列表、可信度）
   - 事件簇的生命周期？（何时创建、何时合并、何时归档？）

3. 知识图谱 schema
   - 实体档案包含哪些字段？（名称、类型、简介、事件时间线、关系列表）
   - 是否需要实体之间的关系类型？（"ABB 生产 GoFa" vs "ABB 竞争 Fanuc"）
   - 知识蒸馏时保留多少细节？（只保留摘要 vs 保留完整声明验证结果）

**用户决策清单**：
- [ ] 确认 ContentItem 字段列表
- [ ] 确认 content_type 枚举值
- [ ] 确认事件簇的合并策略（纯自动 vs 需要人工确认）
- [ ] 确认知识图谱的深度（简单实体档案 vs 完整关系图谱）

**验收产出**：完成的 `models.py` 数据模型定义，以及存储层 schema 设计。

---

### Phase 3：Pipeline 架构设计

**目标**：确定 Step/Context/Pipeline 的抽象设计和具体 Step 列表。

**LLM 主导的讨论**：

1. Step 粒度讨论
   - 哪些操作应该是独立 Step？（指导原则：一个 Step 做且只做一件事，可独立测试、可被跳过或替换）
   - 讨论具体 case："去重和标准化应该是一个 Step 还是两个？""事件聚类和趋势检测呢？"

2. Pipeline 组合讨论
   - 展示四种预设 pipeline（daily_collection、reactive_query、deep_research、fact_check_only）
   - 用户是否需要其他组合？（如 "weekly_digest"、"topic_deep_dive"）
   - 讨论每种 pipeline 的步骤是否合理，是否需要增减

3. 条件逻辑讨论
   - 哪些 Step 应该有条件跳过？（如 translate 只在有外文内容时执行）
   - 哪些 Step 的错误应该 abort 整个 pipeline？（如果验证步骤失败，未验证的内容还要不要输出？）

4. 并行与串行策略
   - 哪些 Step 可以并行？（所有 collect 步骤、多个源的搜索）
   - 哪些必须串行？（去重必须在采集全部完成之后）

5. 扩展点讨论
   - 用户未来最可能新增什么 Step？（新的采集源？新的分析算法？新的输出格式？）
   - 这些扩展点是否被当前架构支持？

**用户决策清单**：
- [ ] 确认 Step 列表和分类
- [ ] 确认预设 Pipeline 组合
- [ ] 确认错误处理策略
- [ ] 确认 `pipelines.yaml` 配置

**验收产出**：完成的 Pipeline 架构设计，包括 Step 接口定义、Pipeline 引擎行为规范、预设 pipeline 组合。

---

### Phase 4：验证机制设计

**目标**：确定事实校验的具体策略、可信度评分模型、声明验证流程。

**LLM 主导的讨论**：

1. 可信度评分模型调参
   - LLM 展示默认四因子权重（来源权威 40% + 时效 20% + 交叉验证 30% + 一致性 10%）
   - 用真实案例讨论："一条来自 ABB 官网的消息（tier 1）但没有其他来源佐证，应该得多少分？""一条来自 Reddit 的消息（tier 3）但有 5 个独立来源佐证，又应该得多少分？"
   - 调整权重直到用户满意

2. 声明级验证的粒度讨论
   - 所有信息都需要做声明级验证吗？还是只对 tier 3+ 的低可信来源做？
   - 声明级验证会消耗较多 LLM token，成本是否可接受？
   - 如果不做声明级验证，fallback 到什么级别？（整条信息级？事件簇级？）

3. 验证结果的展示方式
   - 在输出中如何呈现验证状态？（颜色标记？详细报告？简单标签？）
   - 对于 "disputed"（来源间矛盾）的信息，如何处理？（标注两方观点？直接过滤？）

4. 自动验证 vs 人工确认
   - Tier 1 来源是否自动标记为 verified？
   - 验证结果是否需要人工复核的流程？

**用户决策清单**：
- [ ] 确认可信度评分的四因子权重
- [ ] 确认声明级验证的启用范围
- [ ] 确认 verified / unverified / disputed 的处理策略
- [ ] 确认 `verification` 配置参数

**验收产出**：完成的验证机制设计文档，包括评分公式、验证流程图、边界 case 处理规则。

---

### Phase 5：排序与输出设计

**目标**：确定领域排序公式、栏目模板、结构化输出格式。

**LLM 主导的讨论**：

1. 排序公式调参
   - LLM 展示默认五因子权重
   - 用 10 条真实数据做排序测试：用户看排序结果，判断"这个排序是否反映了我写公众号时的优先级"
   - 调整权重、讨论是否需要增减因子

2. 新颖度计算策略
   - "新颖度"是相对于什么计算的？（相对于过去 7 天的数据？还是整个知识库？）
   - 同一个话题如果有重大进展（如新论文发表），是否应该重新提高优先级？

3. 栏目模板设计
   - 每个栏目的结构化输出应该包含哪些字段？
   - 用具体案例讨论："学术前沿"栏目的素材包应该长什么样？需要论文方法论摘要吗？需要与前序工作的对比吗？
   - "行业动态"呢？需要竞品分析角度吗？需要对中国市场的影响分析吗？

4. 草稿生成的 prompt 风格
   - 是否需要草稿生成功能？如果需要，期望的风格是什么？
   - 草稿应该是完整文章还是要点提纲？
   - 是否需要不同栏目用不同的 prompt？

**用户决策清单**：
- [ ] 确认排序公式权重
- [ ] 确认每个栏目的输出模板
- [ ] 确认是否启用草稿生成及其风格
- [ ] 确认 `output` 和 `analysis.ranking` 配置

**验收产出**：完成的排序公式、栏目模板定义、结构化输出 JSON schema 示例。

---

### Phase 6：交互模式设计

**目标**：确定 MCP 工具接口、对话流程、以及定时/响应式的协同策略。

**LLM 主导的讨论**：

1. MCP 工具接口设计
   - 逐个讨论六个工具的入参、出参、行为：
     - `search_topic`：默认搜索范围？是否总是做验证？返回多少条？
     - `deep_dive`：深挖到什么程度？最多搜索几轮？
     - `verify_claim`：验证超时怎么处理？
     - `compare_sources`：输出格式？如何呈现矛盾点？
     - `generate_brief`：能同时基于多个事件生成吗？
     - `recall_history`：最远回溯多久？
   - 讨论是否需要额外的工具（如 `list_trending`、`get_coverage_report`）

2. 典型对话流程演练
   - LLM 模拟一个完整的写作场景：用户想写一篇关于"具身智能在工厂的应用"的文章
   - 演示 Claude 如何逐步调用工具：search → deep_dive → verify → compare → generate_brief
   - 用户评估这个流程是否自然、是否缺少环节

3. 定时与响应式的协同
   - 定时 pipeline 产出的报告，是否应该自动推送到飞书/邮件？
   - 响应式查询时，是否应该优先展示定时 pipeline 已经处理好的数据？
   - 知识库的更新节奏？（每次定时 pipeline 跑完后更新？还是响应式查询时也更新？）

**用户决策清单**：
- [ ] 确认 MCP 工具列表和接口定义
- [ ] 确认定时推送策略
- [ ] 确认 `mcp` 和 `pipelines` 配置
- [ ] 是否需要 Webhook Bot（企微/飞书机器人）

**验收产出**：完成的 MCP 工具接口规范、对话流程示例、以及定时/响应式协同策略。

---

### Phase 7：配置体系与部署方案

**目标**：确定完整的配置文件结构、环境变量策略、部署方式。

**LLM 主导的讨论**：

1. 配置文件结构确认
   - 逐节 review `intellisource.yaml` 的配置项
   - 哪些配置应该支持环境变量覆盖？（API key、webhook URL）
   - 哪些配置在运行时可以动态修改？（关键词库、来源列表）

2. 部署方案选择
   - 本地运行 + cron / Docker + 定时器 / GitHub Actions
   - 各方案的优劣和适用场景讨论
   - MCP Server 的部署方式（本地 stdio vs 远程 SSE）

3. 安全与隐私
   - API Key 如何管理？（.env 文件 / 环境变量 / secret manager）
   - 采集的数据是否涉及隐私？存储加密？
   - LLM 调用是否有数据保留策略？

**用户决策清单**：
- [ ] 确认完整配置文件
- [ ] 确认部署方案
- [ ] 确认安全策略

**验收产出**：完成的配置文件模板、部署文档、环境准备 checklist。

---

### Phase 8：实现规划与迭代策略

**目标**：确定实现顺序、MVP 范围、迭代计划。

**LLM 主导的讨论**：

1. MVP 范围确定
   - 第一个可用版本需要包含哪些功能？（建议：3 个信息源 + 去重 + 基础排序 + HTML 报告）
   - 哪些功能可以延后？（声明级验证、知识图谱、草稿生成）

2. 实现优先级排序
   - LLM 建议实现顺序：Core 基础设施 → 采集层 → 处理层 → 基础输出 → 验证层 → 分析层 → MCP → 知识库
   - 用户确认或调整

3. 测试策略
   - 每个 Phase 的验收标准是什么？
   - 如何用真实数据做端到端测试？
   - 如何衡量"验证结果的准确性"？（与人工判断的一致率）

4. 迭代节奏
   - 每个迭代周期多长？（建议 1-2 周一个迭代）
   - 每个迭代结束时的交付物是什么？

**用户决策清单**：
- [ ] 确认 MVP 功能范围
- [ ] 确认实现优先级
- [ ] 确认迭代节奏
- [ ] 确认测试与验收标准

**验收产出**：实现路线图、MVP 定义、迭代计划。

---

### 协作约定

**LLM 在每个 Phase 中的行为规范**：

1. 先展示默认建议或设计方案，解释背后的 rationale
2. 用具体案例或数据驱动讨论（而不是抽象概念）
3. 在需要用户决策的地方明确提出选项和利弊
4. 每个 Phase 结束时汇总所有决策，生成/更新对应的配置文件或设计文档
5. 在下一个 Phase 开始时，回顾上一 Phase 的产出，确认无遗漏

**LLM 使用工具的策略**：

- 用 web search 查询最新的 API 文档、开源工具版本、竞品动态
- 用可视化工具展示架构图、数据流图、覆盖矩阵等辅助讨论
- 用代码执行工具做 prototype 验证（如测试某个 API 是否可用、某个 embedding 模型的效果）
- 在配置确认后生成对应的 YAML/Python 文件
- 在每个 Phase 结束时生成进度汇总

**触发下一 Phase 的条件**：

- 当前 Phase 的所有决策清单已确认
- 产出文件已生成且用户 review 通过
- 用户明确表示"进入下一阶段"

---

## 附录：TrendRadar 分析要点速查

| 方面 | TrendRadar 做法 | IntelliSource 改进 |
|------|---------------|-------------------|
| 去重 | 精确标题匹配 | 语义 embedding + LLM 确认的事件聚类 |
| 验证 | 无（信任所有输入） | 声明级三层递进验证 |
| 排序 | 热度三因子（排名/频次/热度） | 领域五因子（+领域匹配/新颖度/验证状态） |
| 交互 | 单向推送报告 | MCP 六工具对话式研究 |
| 记忆 | 按天存储，过期删除 | 热冷分离，过期蒸馏为知识 |
| 配置 | 多文件分散 | 单一 YAML 配置树 |
| 信源 | NewsNow API + RSS | 六类信源 + 四级可信度分层 |
| 扩展 | 需改代码 | Plugin Registry + 声明式 Pipeline |
