# REVIEW: IntelliSource Cross-Document Design Review
<!-- date: 2026-04-03 | reviewer: independent-reviewer | scope: prd + arch + dev-plan -->
<!-- reviewed_docs: prd-intellisource-v1, arch-intellisource-v1 (main + modules + api + data), dev-plan-intellisource-v1 (main + s1) -->

## Layer 1: 脚本检查跳过(降级)

本次为跨文档综合审查，不按单文档执行 Layer 1 脚本检查。

## Layer 2: AI 语义审查

---

## 审查结论: **approved_with_notes**

无 CRITICAL 或 HIGH 级别问题。发现 7 个 MEDIUM 和 5 个 LOW 级别改进建议。整体文档质量良好：PRD 需求完整且有清晰的 AC 编号体系，架构设计合理（模块化单体 + 事件驱动适配自部署场景），数据模型详实，API 设计规范统一，开发计划依赖图完整且关键路径标注清晰。

---

## 问题列表

### [R-001] MEDIUM: Webhook 回调端点缺少 GET 验证路由

- **category**: completeness
- **root_cause**: self-caused
- **描述**: API-020 和 API-021 仅定义了 POST 方法用于接收消息回调。但微信公众号和企业微信在首次配置 Webhook URL 时，均需要通过 GET 请求进行服务器验证（echostr 回显）。当前 API 契约未定义此 GET 路由，将导致 Webhook 配置无法通过平台验证。
- **建议**: 为 `/api/v1/webhooks/wechat` 和 `/api/v1/webhooks/wework` 各增加 GET 方法定义，包含 signature/timestamp/nonce/echostr 参数，返回 echostr 明文。

### [R-002] MEDIUM: E-009 Subscription 的 source_id 关系语义与 ER 图不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: ER 图中 Source 与 Subscription 的关系为 `Source ||--o{ Subscription : "被订阅"`，暗示每个 Subscription 必须关联一个 Source。但 E-009 字段定义中 `source_id` 为 `FK -> Source.id, NULL`（允许为空，空表示匹配全部信源），API-023 也标注 source_id 为 optional。ER 图的 `||--o{` 关系符号表示"一对多"，左侧 `||` 表示"恰好一个"，与实际的可选语义矛盾。
- **建议**: ER 图中将 `Source ||--o{ Subscription` 改为 `Source }o--o{ Subscription`（零或多对零或多）以准确反映可选关联关系。

### [R-003] MEDIUM: LLMCallLog 的 content_id 未声明 FK 约束但 ER 图暗示外键关系

- **category**: consistency
- **root_cause**: self-caused
- **描述**: E-007 LLMCallLog 的 `content_id` 字段类型标注为 `UUID, NULL`，无 FK 约束声明。但 ER 图中有 `LLMCallLog }o--|| ProcessedContent : "处理关联"` 的关系，且右侧 `||` 暗示 ProcessedContent 必须存在。实际上 LLM 调用可能不关联特定内容（如搜索意图理解、对话摘要等场景），content_id 应允许为 NULL 且不应有强 FK 约束。ER 图需要修正。
- **建议**: ER 图改为 `LLMCallLog }o--o| ProcessedContent`（零或一个），同时确认 content_id 不设 FK 约束（避免级联问题和性能影响，日志表应松耦合）。

### [R-004] MEDIUM: T-009 配置加载的 sync_to_db 行为与 PRD F-001 备注中"不删除"语义需在测试中明确覆盖

- **category**: completeness
- **root_cause**: self-caused
- **描述**: PRD F-001 备注明确说明"重载操作将配置文件内容合并到数据库（新增或更新），不删除数据库中已有但配置文件中不存在的信源"。T-009 的 AC-T009-2 描述为 `sync_to_db() 将配置同步到 Source 表（新增/更新/标记删除）`，其中提到"标记删除"与 PRD 的"不删除"语义矛盾。
- **建议**: 修正 AC-T009-2 描述，移除"标记删除"，改为"新增或更新，不删除已有信源"，保持与 PRD F-001 备注一致。或者如果设计意图确实需要标记删除，则需在 PRD 中更新备注说明。

### [R-005] MEDIUM: T-005 pgvector 测试对 zhparser 扩展有硬依赖，增加 CI 环境复杂度

- **category**: feasibility
- **root_cause**: self-caused
- **描述**: T-005 的 AC-T005-4 要求"PostgreSQL 全文检索（zhparser 中文分词）与向量检索结果正确融合"。zhparser 是一个 PostgreSQL C 扩展，需要在测试数据库中预先安装，这对 CI 环境（GitHub Actions 等）提出了额外的镜像要求。风险项中已提到此问题，但 T-005 的测试策略中未说明 zhparser 不可用时的降级方案。
- **建议**: 在 T-005 中增加实现提示：zhparser 不可用时，测试降级为使用 `simple` 或 `english` 配置验证全文检索逻辑的正确性，zhparser 中文分词效果验证放入集成测试。

### [R-006] MEDIUM: API-006 任务列表的 type 查询参数枚举值与 CollectTask 实体不匹配

- **category**: consistency
- **root_cause**: self-caused
- **描述**: API-006 的 type 查询参数支持 `collect | process | distribute | workflow`，但 E-002 CollectTask 的 trigger_type 枚举为 `scheduled | manual | message`。数据模型中只有 CollectTask 和 TaskChain 两个任务相关实体，没有 "process" 或 "distribute" 类型的独立任务实体。这意味着 API-006 的 type 过滤要么需要额外的任务类型标识（当前数据模型未定义），要么需要修正为基于 trigger_type 过滤。
- **建议**: 在 E-002 CollectTask 中增加 `task_type` 字段（或在 E-008 TaskChain 中增加），枚举值 `collect | process | distribute`，与 API 查询参数对齐。或者将 API-006 的 type 参数改为 trigger_type 过滤。

### [R-007] MEDIUM: 数据模型中缺少 RawContent 到 ProcessedContent 处理过程中的管道执行记录

- **category**: completeness
- **root_cause**: self-caused
- **描述**: 架构设计中 M-003 处理管道是核心组件，支持多个处理器顺序执行。但数据模型中没有管道执行记录实体（如 PipelineRun 或 ProcessingLog）来记录每条内容经过了哪些处理器、每个处理器的执行结果和耗时。ProcessedContent 的 `processing_status` 仅记录最终状态，无法追溯中间步骤。对于 v1 自部署场景，这不是阻塞问题（可通过结构化日志追溯），但会增加问题排查难度。
- **建议**: 作为 v1 权衡，可接受不建管道执行记录表。建议在 ProcessedContent 的 structured_data JSONB 字段中记录 `pipeline_trace` 子键，包含各处理器名称和执行状态，作为轻量级追溯方案。

### [R-008] LOW: NAV-INDEX 中所有文档状态显示为 draft，与 CLAUDE.md 中 prd/arch/dev-plan 均为 approved 不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: NAV-INDEX.md 中 prd-intellisource-v1 状态为 `draft`，arch 系列和 dev-plan 系列也均为 `draft`。但 CLAUDE.md 项目状态区显示 `prd: approved`、`arch: approved`、`dev-plan: approved`。PRD 文档头也标注 `status: approved`。NAV-INDEX 未同步更新。
- **建议**: 更新 NAV-INDEX.md 中 prd、arch、dev-plan 各文档的状态列为 `approved`。

### [R-009] LOW: dev-plan Sprint 1 分卷状态为 draft，与主卷 approved 不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `dev-plan-intellisource-v1.md` 主卷文档头标注 `status: approved`，但 `dev-plan-intellisource-v1-s1.md` 分卷文档头标注 `status: draft`。分卷应随主卷同步状态。
- **建议**: 将 Sprint 分卷的 status 更新为 `approved`。

### [R-010] LOW: Workflow 和 TaskChain 的删除行为未完全定义

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: API-029 删除工作流时说明"关联的已执行任务链记录保留"，但未说明 Workflow 是物理删除还是软删除。E-012 Workflow 模型没有 `deleted_at` 字段，暗示为物理删除。物理删除后 TaskChain 的 workflow_id 外键将指向不存在的记录（FK 约束可能导致删除失败）。
- **建议**: 明确 Workflow 删除策略：(1) 物理删除并将关联 TaskChain.workflow_id 设为 NULL（需 ON DELETE SET NULL）；或 (2) 增加 deleted_at 字段实现软删除。建议采用软删除以保持数据一致性。

### [R-011] LOW: API 路径中 webhooks 使用了复数形式但其他路径未统一

- **category**: convention
- **root_cause**: self-caused
- **描述**: API 路径约定为 kebab-case 复数名词。大部分路径遵循（`/sources`, `/tasks`, `/workflows`, `/subscriptions`, `/contents`, `/clusters`）。但 `/api/v1/webhooks/wechat` 中 `webhooks` 下的 `wechat` 和 `wework` 是专有名词非资源名，风格可以接受。另外 `/api/v1/search` 和 `/api/v1/search/chat` 使用了动词形式而非资源名词，与 RESTful 资源命名惯例稍有偏差。
- **建议**: 搜索和问答端点使用动词形式是业界常见做法（Google Search API 等也用 `/search`），可接受。无需修改。

### [R-012] LOW: dev-plan 关键路径中 T-004 到 T-019 跨 Sprint 跳跃较大

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: 关键路径为 T-001 -> T-002 -> T-003 -> T-004 -> T-019 -> ...。T-004 在 Sprint 1（数据访问层），T-019 在 Sprint 3（LLM 网关）。依赖图中 T-004 -> T-019 存在，但中间有 Sprint 2 的全部任务（采集引擎和处理管道）。这意味着 Sprint 2 不在关键路径上，理论上 Sprint 2 的延迟不影响最终交付。这个分析是正确的，但文档中未明确说明 Sprint 2 可以与 Sprint 1 部分并行的可能性。
- **建议**: 在关键路径说明中增加一句：Sprint 2 任务（采集引擎/处理管道）不在主关键路径上，如资源允许可与 Sprint 1 末期并行启动。

---

## 审查总结

| 等级 | 数量 |
|------|------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 7 |
| LOW | 5 |

**总体评价**:

文档体系完整度高，PRD 的 14 个功能点全部映射到架构模块，65 个验收标准（AC-001 至 AC-065）在开发计划中均有对应的 TDD 测试点覆盖。架构选型（模块化单体 + pgvector 共库 + Celery 异步任务链）对自部署小团队场景是务实的选择。API 设计统一使用游标分页、统一错误码格式、Webhook 使用平台签名验证而非 API Key，这些细节处理到位。

主要改进方向集中在：(1) 数据模型与 ER 图的一致性细节（R-002, R-003, R-006）；(2) 文档间状态同步（R-008, R-009）；(3) 个别设计决策的边界行为需要明确（R-001 Webhook GET 验证, R-004 配置同步删除语义, R-010 Workflow 删除策略）。

这些问题均不阻塞 Sprint 1 的开发工作，可在后续迭代中逐步修正。
