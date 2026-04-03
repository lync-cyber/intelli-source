# REVIEW: Cross-Document Independent Review (r2)
<!-- id: REVIEW-cross-doc-r2 | date: 2026-04-03 | reviewer: independent-architect -->
<!-- scope: prd-intellisource-v1, arch-intellisource-v1 (main + modules + api + data), dev-plan-intellisource-v1 (main + s1) -->
<!-- type: independent-review | status: completed -->

## 审查摘要

本报告为独立架构审查，对 IntelliSource 全部设计文档（PRD、架构、开发计划）进行从零开始的质量评估。总体而言，文档质量较高，架构决策务实且适合项目规模（自部署、小团队）。以下列出需关注的问题，按严重等级排序。

**结论: approved_with_notes**

无 CRITICAL 或 HIGH 问题。发现若干 MEDIUM 和 LOW 级别的改进项，不阻塞实施但建议在合适时机处理。

---

## 问题列表

### [R-001] MEDIUM: Webhook 回调端点需同时支持 GET 验证请求

- **category**: completeness
- **root_cause**: self-caused
- **描述**: API-020 和 API-021 仅定义了 POST 方法用于接收消息。但微信公众号和企业微信在首次配置 Webhook URL 时，会发送 GET 请求进行 URL 验证（echostr 回显机制）。未定义 GET 处理将导致 Webhook 配置失败。
- **建议**: 为 API-020 和 API-021 各补充一个 GET 方法定义，接收 signature/timestamp/nonce/echostr 参数，校验签名后回显 echostr。

### [R-002] MEDIUM: LLMCallLog 分区表的 FK 约束限制

- **category**: feasibility
- **root_cause**: self-caused
- **描述**: E-007 LLMCallLog 声明按 created_at 月份做 Range Partition，同时 ER 图中有 `LLMCallLog }o--|| ProcessedContent` 的 FK 关系（content_id 字段）。PostgreSQL 原生分区表对外键支持有限：分区表可以持有指向其他表的 FK（PostgreSQL 12+），但在旧版本中有限制且需注意性能。此外 content_id 是 NULL 可选的，说明并非所有调用都关联内容。这不是阻塞问题，但实现时需注意分区表上的 FK 行为验证。
- **建议**: T-047 实现分区表时，验证 PostgreSQL 16 下分区表持有 FK 的行为。若有问题，可将 content_id 改为应用层关联而非数据库 FK。

### [R-003] MEDIUM: 配置热加载与数据库状态同步的一致性边界未明确

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: PRD F-001 备注和 M-001 说明数据库是运行时权威来源，配置文件是种子数据，重载操作"合并到数据库（新增或更新），不删除"。但未明确以下场景：(1) 配置文件中修改了一个已在数据库中通过 API 修改过的信源（以谁为准？）；(2) ConfigWatcher 自动检测到文件变更时是否与手动 API-005 reload 使用相同的合并策略。
- **建议**: 在 arch#M-001 或 T-009 实现提示中补充合并策略的优先级规则（建议：配置文件重载时以配置文件值覆盖数据库值，即"最后写入者胜"，并在重载响应中返回冲突列表供用户确认）。

### [R-004] MEDIUM: dev-plan Sprint 1 的 T-005 对 zhparser 的强依赖增加测试环境复杂度

- **category**: feasibility
- **root_cause**: self-caused
- **描述**: T-005（pgvector 向量存储与检索）的 AC-T005-4 要求 "PostgreSQL 全文检索（zhparser 中文分词）与向量检索结果正确融合"。zhparser 是 PostgreSQL C 语言扩展，需要编译安装或使用特定 Docker 镜像。这对开发者本地测试环境和 CI 环境提出了额外要求。风险项中已提到此问题（zhparser 依赖），但未给出 Sprint 1 阶段的具体缓解方案。
- **建议**: 在 T-005 中增加备选方案说明：测试环境中若 zhparser 不可用，可降级使用 PostgreSQL 内置的 `english` 或 `simple` 分词配置运行测试，正式环境使用 zhparser。或将 zhparser 相关测试标记为需要特定环境的集成测试（pytest mark）。

### [R-005] MEDIUM: API-006 任务列表的 type 过滤值定义与数据模型不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: API-006 定义了 type 查询参数，可选值为 `collect | process | distribute | workflow`。但数据模型中，CollectTask (E-002) 的 trigger_type 是 `scheduled | manual | message`，TaskChain (E-008) 没有 type 字段。API 中的 "type" 概念（collect/process/distribute/workflow）在数据模型中没有直接对应的字段，需要在实现时通过逻辑推断或增加字段来支持。
- **建议**: 在 E-002 或 E-008 中增加 task_type 字段来区分任务类型（collect/process/distribute），或在 API 文档中明确 type 过滤的实现方式（例如：collect = 查 CollectTask 表，workflow = 查 TaskChain + Workflow 关联）。

### [R-006] MEDIUM: Source 实体软删除但无级联处理策略说明

- **category**: completeness
- **root_cause**: self-caused
- **描述**: 数据模型通用约定提到 "Source 实体采用软删除（deleted_at 字段），其他实体随信源级联保留"。API-004 描述也是软删除。但未说明软删除后的行为：(1) 软删除的 Source 关联的 Subscription 是否自动暂停？(2) 软删除的 Source 的历史内容（RawContent/ProcessedContent）是否仍可通过 API-014/015 查询？(3) API-001 列表是否默认排除已删除的信源？
- **建议**: E-001 索引 `idx_source_status` 已有 `WHERE deleted_at IS NULL` 条件，说明查询默认排除已删除。建议在 API-004 描述中补充级联行为说明（如：软删除后关联订阅自动暂停，历史内容保持可查询但不再更新）。

### [R-007] MEDIUM: Sprint 1 T-009 依赖 T-004 但 T-008 也依赖 T-001，依赖链较长

- **category**: feasibility
- **root_cause**: self-caused
- **描述**: Sprint 1 的依赖链为 T-001 -> T-002 -> T-003 -> T-004 -> T-009，同时 T-001 -> T-008 -> T-009。T-009（配置加载与热加载）同时依赖 T-008（配置模型）和 T-004（Repository），意味着 T-009 必须等到 Sprint 1 的大部分任务完成后才能开始。这使得 Sprint 1 中的并行度有限，实际可并行的只有 T-006/T-007/T-008 与 T-002/T-003 两条链路。
- **建议**: 这是合理的依赖关系，无需调整。但团队应注意 Sprint 1 的关键路径较长（10 个任务串联），确保 T-001 至 T-003 的早期任务不出现阻塞。

### [R-008] LOW: API 路径命名不完全统一

- **category**: convention
- **root_cause**: self-caused
- **描述**: 大部分 API 路径使用复数名词（sources, tasks, workflows, subscriptions, contents, clusters），但 `/api/v1/search` 和 `/api/v1/search/chat` 使用了动词。虽然搜索端点使用动词在 REST API 中是常见做法，但与其他路径风格不完全一致。`/api/v1/llm/stats` 也是缩写+名词，与资源路径风格有差异。
- **建议**: 无需修改。搜索和统计端点使用非 CRUD 风格是行业惯例，不影响可用性。

### [R-009] LOW: dev-plan Sprint 分卷 s1 status 仍为 draft

- **category**: consistency
- **root_cause**: self-caused
- **描述**: dev-plan-intellisource-v1-s1.md 的文档头 status 为 `draft`，而主文档 dev-plan-intellisource-v1.md 的 status 为 `approved`。分卷文件状态应与主文档一致。
- **建议**: 将 dev-plan-intellisource-v1-s1.md 的 status 更新为 `approved`。

### [R-010] LOW: ER 图中 ChatSession 未体现与其他实体的关系

- **category**: completeness
- **root_cause**: self-caused
- **描述**: E-011 ChatSession 在 ER 图中未出现。它通过 channel_user_id 间接关联到订阅用户，但与系统中的其他实体没有 FK 关系。这是合理设计（独立会话），但 ER 图未包含它可能让读者误以为遗漏。
- **建议**: 在 ER 图中添加 ChatSession 作为独立实体，或在 ER 图下方注明 "ChatSession 和 Workflow 为独立实体，无 FK 关联"。实际上 Workflow 已通过 TaskChain 体现在图中，仅 ChatSession 缺失。

### [R-011] LOW: ProcessedContent.source_url 和 source_name 冗余字段缺少同步策略

- **category**: consistency
- **root_cause**: self-caused
- **描述**: E-004 ProcessedContent 中 source_url 和 source_name 标注为"冗余，方便查询"。这种反范式设计在读多写少场景下是合理的，但未说明当 Source 的 name 或 RawContent 的 source_url 被更新时，这些冗余字段是否需要同步更新。
- **建议**: 在 E-004 备注中说明这些冗余字段为写入时快照，不随源数据更新。这对于已处理的历史内容是合理的（保留采集时的来源信息）。

### [R-012] LOW: T-040 的 TDD 测试点标识不规范

- **category**: convention
- **root_cause**: self-caused
- **描述**: dev-plan 主文档中 T-040 的 TDD 测试点列为 `AC-T040`，不符合 PRD 中的 AC-NNN 编号序列（AC-001 至 AC-065）。其他任务的自定义 AC 编号使用了 `AC-T{NNN}-N` 格式（如 AC-T001-1），T-040 的格式 `AC-T040` 不一致。
- **建议**: 将 `AC-T040` 改为具体的验收标准列表（如 AC-T040-1: 微信回调签名验证通过/拒绝 等），与其他任务卡的自定义 AC 格式一致。

### [R-013] LOW: 配置版本管理机制的存储策略未明确

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: F-001 AC-004 要求"支持配置文件版本管理，可回退到历史版本"。M-001 提到 ConfigVersionManager 组件。E-001 Source 有 config_version 字段。但未明确版本历史存储在哪里：是在 Source 表中通过版本号关联到某个历史快照表？还是在文件系统中保留历史版本？或利用 Git 等外部工具？
- **建议**: 在 M-001 中补充版本管理的实现策略说明。建议方案：在数据库中增加 SourceConfigHistory 表，或利用 Source 表的 JSONB metadata 字段存储前一版本快照（简单方案），或在 T-009 实现提示中说明。

---

## 正面评价

以下是文档中值得肯定的设计决策：

1. **架构风格选择务实**: 模块化单体 + 事件驱动对自部署小团队场景非常合适，避免了微服务的运维复杂度。

2. **pgvector 选型合理**: 与 PostgreSQL 共实例，<100万文档规模充足，避免引入额外基础设施。

3. **降级策略全面**: 每个 LLM 处理环节都有对应的传统逻辑降级方案，确保系统在 LLM 不可用时仍能运行核心功能。

4. **API 设计质量高**: 游标分页、统一错误响应、Webhook 签名验证、软删除等均为业界最佳实践。

5. **安全设计到位**: API Key 认证、路径遍历防护（API-005 白名单）、敏感配置环境变量注入、Webhook 平台签名验证等均已考虑。

6. **dev-plan 依赖分析完整**: 关键路径计算、风险项识别和缓解措施均有规划。任务粒度适中，TDD 验收标准明确。

7. **PRD 到架构的追溯性好**: 每个模块明确映射功能点，每个 AC 编号在 dev-plan 的 tdd_acceptance 中有引用。

---

## 审查结论

**approved_with_notes**

文档整体质量高，架构决策合理，PRD-Architecture-DevPlan 三者之间的一致性良好。发现 0 个 CRITICAL、0 个 HIGH、7 个 MEDIUM、6 个 LOW 问题。MEDIUM 问题主要集中在实现细节的明确性上（Webhook GET 验证、配置合并策略、软删除级联等），可在开发过程中逐步澄清，不阻塞 Sprint 1 的启动。
