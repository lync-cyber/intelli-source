# REVIEW: arch-intellisource-v1 (r3)
<!-- date: 2026-04-03 | reviewer: reviewer | doc_id: arch-intellisource-v1 -->
<!-- scope: main + modules + api + data volumes -->
<!-- upstream: prd-intellisource-v1 (approved) -->
<!-- previous: REVIEW-arch-intellisource-v1-r2 -->

## Layer 1 结果

- **主卷** (arch-intellisource-v1.md): PASS
- **API 分卷** (arch-intellisource-v1-api.md): PASS (2 WARN: 行数超 500 行阈值; ID 编号不连续缺少 M-002~M-004)
- **数据分卷** (arch-intellisource-v1-data.md): PASS
- **模块分卷** (arch-intellisource-v1-modules.md): PASS

Layer 1 WARN 说明: 与 r1/r2 一致，API 分卷行数因包含 29 个完整 API 定义 + 通用类型定义，体量合理。ID 不连续警告为脚本误判（分卷 ID 前缀为 API-xxx，M-xxx 属于模块分卷）。

## Layer 2 审查结果

本轮为 r2 approved 后的常规审查轮次，对全部 4 卷进行 6 维度语义审查。

### [R-001] MEDIUM: 分卷文档 status 元数据未与主卷同步

- **category**: convention
- **root_cause**: self-caused
- **描述**: 主卷 `arch-intellisource-v1.md` 头部元数据为 `status: approved`，但 API 分卷、数据分卷、模块分卷的头部元数据仍为 `status: draft`。分卷作为主卷的组成部分，其状态应与主卷一致。当前不一致可能导致下游 Agent（tech-lead/developer）在读取分卷时误判文档状态。
- **建议**: 将 `arch-intellisource-v1-api.md`、`arch-intellisource-v1-data.md`、`arch-intellisource-v1-modules.md` 头部的 `status: draft` 统一更新为 `status: approved`。

### [R-002] LOW: API-013 即时问答接口未明确同步/异步语义

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: PRD AC-052 要求"检索结果经 LLM 摘要后异步回调返回给用户，不阻塞消息通道"。API-013 `/api/v1/search/chat` 采用同步请求-响应模式，这在 REST API 直接调用场景下是合理的；而消息渠道（微信/企业微信）的异步回调流程则通过 API-020/API-021 Webhook 接入。但 API-013 的 `desc` 字段未说明此接口为同步模式，也未交叉引用 Webhook 异步流程，可能导致开发者在实现时对 AC-052 的满足方式产生困惑。
- **建议**: 在 API-013 的 `desc` 中补充说明"本接口为同步 REST 调用模式；消息渠道用户的异步检索流程通过 API-020/API-021 Webhook 接入，由 M-008 内部异步处理后回调返回结果（对应 AC-052）"。

### [R-003] LOW: API-015 ContentDetail 响应未包含 structured_data 字段

- **category**: completeness
- **root_cause**: self-caused
- **描述**: 数据模型 E-004 ProcessedContent 包含 `structured_data JSONB` 字段，用于存储 LLM 结构化提取结果（对应 F-005 AC-018）。但 API-015 `/api/v1/contents/{id}` 的响应体定义中未包含 `structured_data` 字段。作为核心 LLM 处理结果之一，API 消费者可能需要通过内容详情接口访问此数据。
- **建议**: 在 API-015 响应体中补充 `structured_data: { type: "object | null", desc: "LLM 结构化提取结果" }` 字段；若该字段设计上仅供内部使用而不对外暴露，建议在 E-004 或 API-015 中明确标注。

### [R-004] LOW: E-007 LLMCallLog ER 图关系基数与字段约束不完全匹配

- **category**: consistency
- **root_cause**: self-caused
- **描述**: ER 图中 `LLMCallLog }o--|| ProcessedContent` 表示"多对一且必须关联"，但 E-007 字段定义中 `content_id UUID NULL` 允许为空。实际场景中检索类 LLM 调用（如 M-008 意图理解）可能不关联特定内容，`content_id` 允许为空是合理的，但 ER 图的 `}o--||` 基数符号暗示这是必须的关系。
- **建议**: 将 ER 图中的关系修改为 `LLMCallLog }o--o| ProcessedContent`（零或一对多），或在 ER 图注释中说明 content_id 可为空。

## 审查摘要

| 等级 | 数量 |
|------|------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 1 |
| LOW | 3 |

**总体评价**: 架构文档经过 r1/r2 两轮修订后质量优良。4 卷文档在功能覆盖、技术选型、接口定义、数据模型设计等方面完整、一致且可行。所有 14 个 PRD 功能需求（F-001 至 F-014）均已映射到模块和接口，AC 引用覆盖全面。技术栈选型有明确理由和调研支撑。安全方案（API Key 认证、路径遍历防护、敏感配置管理、平台签名验证）设计合理。非功能架构（缓存、异步、重试、熔断、降级）描述充分。本轮发现的 1 个 MEDIUM 问题为分卷元数据状态同步遗漏，3 个 LOW 问题为文档清晰度和内部一致性的微小改进建议，均不影响架构的正确性和可实施性。

## 结论

**approved_with_notes**
