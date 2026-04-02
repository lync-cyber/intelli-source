# REVIEW: arch-intellisource-v1 (r1)
<!-- date: 2026-04-02 | reviewer: reviewer | doc_id: arch-intellisource-v1 -->
<!-- scope: main + modules + api + data volumes -->
<!-- upstream: prd-intellisource-v1 (approved) -->

## Layer 1 结果
- **主卷** (arch-intellisource-v1.md): PASS
- **模块分卷** (arch-intellisource-v1-modules.md): PASS
- **接口分卷** (arch-intellisource-v1-api.md): PASS (2 WARN: 行数超阈值; ID编号不连续缺少M-002/M-003/M-004)
- **数据分卷** (arch-intellisource-v1-data.md): PASS

Layer 1 WARN 说明: API 分卷 ID 不连续警告为误报 -- 该分卷的 ID 前缀为 API-xxx，M-xxx 属于模块分卷，脚本按 M-xxx 正则匹配产生误检。行数超阈值为合理警告(641行)，但作为接口契约分卷，21个API定义的体量属正常范围。

## Layer 2 审查结果

### [R-001] HIGH: 订阅规则(Subscription)缺少管理API
- **category**: completeness
- **root_cause**: self-caused
- **描述**: 数据模型定义了 E-009 Subscription 实体，模块 M-007 描述了 SubscriptionMatcher 组件，但接口契约(API分卷)中未定义任何订阅规则的 CRUD 接口。用户无法通过 API 创建、查询、更新或删除订阅规则，这意味着订阅功能在 API 层不可达。PRD F-009 AC-043 要求"基于用户订阅规则精准匹配推送内容"，但未提供管理这些规则的 API 入口。
- **建议**: 在接口契约分卷中补充订阅规则的 CRUD 接口 (建议 API-022 至 API-025)，路径建议为 `/api/v1/subscriptions`，支持创建/列表/更新/删除操作。

### [R-002] HIGH: 实体关系图引用了未定义的 ChatMessage 实体
- **category**: consistency
- **root_cause**: self-caused
- **描述**: 数据分卷 4.1 实体关系图中，ChatSession 与 ChatMessage 存在 "包含消息" 关系 (`ChatSession ||--o{ ChatMessage : "包含消息"`)，但实体定义中只有 E-011 ChatSession，没有 ChatMessage 的实体定义。E-011 的 `context` 字段(JSONB)似乎内嵌存储了对话消息，与 ER 图中独立实体的表达不一致。
- **建议**: 二选一: (1) 移除 ER 图中 ChatMessage 实体，明确 context JSONB 字段存储对话历史; (2) 新增 E-013 ChatMessage 实体定义，将对话消息独立建表。考虑到 PRD AC-053 仅要求保持最近5轮上下文，JSONB 内嵌方案更简洁，建议选方案(1)。

### [R-003] HIGH: API-005 重载配置接口存在路径遍历安全风险
- **category**: security
- **root_cause**: self-caused
- **描述**: API-005 `/api/v1/sources/reload` 的请求体接受 `file_path` 参数，允许调用方指定任意配置文件路径。持有 API Key 的攻击者可能利用此参数进行路径遍历攻击，读取或加载服务器上的任意文件。
- **建议**: (1) 移除 `file_path` 参数，仅从预定义配置目录加载; 或 (2) 对 `file_path` 实施严格白名单校验，限制在指定配置目录下; 并在 arch#5.2 安全方案中补充输入校验策略说明。

### [R-004] MEDIUM: 工作流(Workflow)缺少查询/更新/删除 API
- **category**: completeness
- **root_cause**: self-caused
- **描述**: 接口契约定义了 API-010(创建工作流) 和 API-011(执行工作流)，但缺少工作流的列表查询(GET /workflows)、详情查询(GET /workflows/{id})、更新(PATCH /workflows/{id})和删除(DELETE /workflows/{id})接口。PRD F-014 AC-063 要求"定义和执行自定义工作流"，定义暗含完整的 CRUD 生命周期管理。
- **建议**: 补充工作流 CRUD 接口，至少包含列表查询和删除操作。

### [R-005] MEDIUM: API-003 使用 PUT 方法但语义为部分更新
- **category**: convention
- **root_cause**: self-caused
- **描述**: API-003 更新信源使用 PUT 方法，但请求体中所有字段均为 `required: false`，这是 PATCH 的语义(部分更新)。按 REST 规范，PUT 应为全量替换(所有字段必填)，PATCH 用于部分更新。主卷 §7.1 命名规范中 API 路径约定了 kebab-case 复数名词，但未明确 HTTP 方法语义约定。
- **建议**: 将 API-003 方法改为 PATCH，或将所有字段改为 required: true 以匹配 PUT 语义。建议采用 PATCH。

### [R-006] MEDIUM: 向量维度硬编码为 1536 未标注模型假设
- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: E-004 ProcessedContent 和 E-005 ContentCluster 的向量字段定义为 `VECTOR(1536)`，此维度对应 OpenAI text-embedding-ada-002 模型。但技术栈中 LLM 客户端使用 litellm 统一多模型接口，不同 embedding 模型维度不同(如 text-embedding-3-small 为 1536，但国内模型可能不同)。维度硬编码可能导致切换 embedding 模型时需要修改数据库 schema。
- **建议**: (1) 标注 [ASSUMPTION] 说明 v1 默认使用 1536 维度的 embedding 模型; (2) 在配置管理(M-001)中增加 embedding 维度配置项; (3) 考虑在 Alembic 迁移中预留维度变更方案。

### [R-007] MEDIUM: 全文检索依赖中文分词扩展未列入技术栈
- **category**: feasibility
- **root_cause**: self-caused
- **描述**: E-004 的索引定义中包含 `to_tsvector('chinese', title || ' ' || body_text)` 全文检索索引，但 PostgreSQL 默认不包含中文分词支持。需要安装 `zhparser` 或 `pg_jieba` 等中文分词扩展，这些依赖未在主卷 1.4 技术栈表中列出，也未在 Docker 部署配置中提及。
- **建议**: (1) 在技术栈表中增加中文分词扩展(推荐 zhparser); (2) 在 Docker 部署配置中确保 PostgreSQL 镜像包含该扩展; (3) 或者降级为使用 pgvector 纯语义检索替代全文检索，简化部署依赖。

### [R-008] MEDIUM: 健康检查响应 status 值 "overall" 语义不明
- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: API-018 健康检查响应体中 status 字段描述为 `"overall | degraded | unhealthy"`，其中 "overall" 语义不明确。通常健康检查状态使用 "healthy | degraded | unhealthy" 三态。"overall" 更像是一个分类标签而非状态值。
- **建议**: 将 status 枚举修改为 `"healthy | degraded | unhealthy"`。

### [R-009] LOW: API 层未定义速率限制策略
- **category**: security
- **root_cause**: self-caused
- **描述**: arch#5.2 安全方案定义了 API Key 认证，arch#5.1 定义了采集层的速率限制(Redis 令牌桶)，但 API 层本身未定义请求速率限制。持有 API Key 的用户可以无限制调用 API，可能导致资源耗尽。
- **建议**: 在 arch#5.2 或 arch#5.1 中补充 API 层速率限制策略(如每个 API Key 的 QPS 上限)，可复用已有的 Redis 令牌桶实现。此为 LOW 级别建议，因为 v1 面向个人/小团队自部署场景，API Key 本身已提供基本防护。

### [R-010] LOW: 数据清理策略仅 LLMCallLog 有分区方案，其他实体未提及
- **category**: completeness
- **root_cause**: upstream-caused
- **描述**: PRD#4 明确标注 "[ASSUMPTION] v1 不实现自动数据清理"，因此架构中未定义全面的数据清理策略是合理的。但 E-007 LLMCallLog 定义了按月分区和3个月归档策略，这与 PRD 假设存在轻微矛盾。其他可能增长较快的实体(E-003 RawContent, E-010 PushRecord)未提及任何清理或归档策略。
- **建议**: 统一数据清理策略: 要么所有实体均不定义清理方案(与 PRD 假设一致)，要么对所有高增长实体统一定义分区策略。LLMCallLog 的分区策略可保留但标注为可选优化项。

## 审查摘要

| 等级 | 数量 |
|------|------|
| CRITICAL | 0 |
| HIGH | 3 |
| MEDIUM | 5 |
| LOW | 2 |

**主要问题**: 3个 HIGH 级别问题集中在接口完整性和安全性 -- 订阅规则缺少管理API(R-001)使核心分发功能无法通过API操作; ER图与实体定义不一致(R-002)会导致开发歧义; 配置重载接口的路径遍历风险(R-003)为安全隐患。

**总体评价**: 架构文档整体质量较高，模块划分清晰，功能映射完整，技术选型有理有据。分卷组织合理，主卷保持精炼，各分卷聚焦对应领域。非功能架构(性能/安全/错误处理)定义充分。主要不足在于接口契约的完整性(订阅和工作流CRUD缺失)和个别安全/一致性问题。

## 结论

**needs_revision**

需修复 R-001, R-002, R-003 共 3 个 HIGH 级别问题后重新提交审查。
