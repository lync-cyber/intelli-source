# REVIEW: arch-intellisource-v1 (r4)
<!-- date: 2026-04-03 | reviewer: reviewer | review_type: Layer 2 AI语义审查(独立复审) -->

## 审查概要

| 项目 | 内容 |
|------|------|
| 文档ID | arch-intellisource-v1 (主卷 + api/data/modules 分卷) |
| 审查轮次 | r4 (独立复审，不参考历史REVIEW) |
| 上游依赖 | prd-intellisource-v1 (status: approved) |
| Layer 1 结果 | 主卷 PASS, API分卷 PASS (2 WARN: 行数超阈值; ID编号不连续为脚本误判), 数据分卷 PASS, 模块分卷 PASS |

## 总体判定

**approved_with_notes**

无 CRITICAL 或 HIGH 级别问题。发现 3 个 MEDIUM 和 2 个 LOW 级别建议，总体架构设计质量优秀，与 PRD 高度一致，可作为下游开发计划的输入。

## 审查维度评估

| 维度 | 评估 |
|------|------|
| 完整性(completeness) | 优秀 — 14个功能点全覆盖，11个模块、29个API、12个实体定义完整 |
| 一致性(consistency) | 优秀 — 与PRD的AC编号引用准确，技术约束匹配 |
| 可行性(feasibility) | 良好 — 技术栈成熟，个别设计点需关注实现细节 |
| 安全性(security) | 良好 — API Key认证、输入校验、敏感配置管理均已覆盖 |
| 规范性(convention) | 优秀 — 命名规范、代码风格、Git约定清晰明确 |
| 清晰度(ambiguity) | 良好 — 整体清晰，个别设计决策可补充说明 |

---

## 问题列表

### [R-001] MEDIUM: PRD AC-066/AC-067 内容删除与存储统计 API 缺失

- **category**: completeness
- **root_cause**: self-caused
- **描述**: PRD F-014 定义了 AC-066（内容删除操作：单条删除和批量删除）和 AC-067（存储统计查询：文档总数、向量索引大小、数据库存储用量），但 API 分卷（API-001 至 API-029）中没有对应的接口定义。现有 API-014/API-015 仅覆盖内容的查询功能，未提供 DELETE 方法。存储统计也未在 API-018（健康检查）或 API-019（系统指标）中体现。
- **建议**: 新增 API-030（DELETE /api/v1/contents/{id} 单条删除）、API-031（DELETE /api/v1/contents 批量删除，body 传 ID 列表）和 API-032（GET /api/v1/storage/stats 存储统计），或在现有 API-019 指标端点中增加存储统计维度。同时在主卷接口交叉引用目录中补充这些接口。

### [R-002] MEDIUM: E-004 向量维度硬编码 VECTOR(1536)，与配置化设计存在矛盾

- **category**: consistency
- **root_cause**: self-caused
- **描述**: 数据分卷 E-004 的 embedding 字段定义为 `VECTOR(1536)`，E-005 的 centroid 字段同样为 `VECTOR(1536)`，同时 [ASSUMPTION] 注释说明维度值通过 M-001 的 `embedding_dimension` 配置项管理，切换模型时需调整。但 DDL 层面硬编码了 1536 维度，这意味着切换到非 1536 维度的 embedding 模型（如 768 维度的模型）时需要执行 ALTER TABLE 修改列类型并重建索引，这是一个有破坏性的数据库迁移操作，仅靠配置变更无法完成。当前的 [ASSUMPTION] 标注已提到需执行 Alembic 迁移，但作为架构决策，这一约束对下游开发者不够显眼。
- **建议**: 在 arch#5.1 或数据分卷中增加一个显式说明段落，阐明 embedding 维度变更的操作流程和影响范围（需要重建向量索引、重新生成所有 embedding），使下游开发者和运维人员充分理解此约束。

### [R-003] MEDIUM: ChatSession 清理策略缺乏触发机制设计

- **category**: feasibility
- **root_cause**: self-caused
- **描述**: 数据分卷 E-011 ChatSession 定义了"超过 24 小时无活跃的会话自动清理"策略，但整个架构文档中未说明此清理由谁触发、以何种方式执行。M-008（即时检索模块）的组件列表中没有清理相关组件，M-006（任务编排模块）的定时任务中也未提及会话清理调度。
- **建议**: 在 M-008 或 M-006 的关键组件中补充 `SessionCleaner` 或类似组件说明，明确清理触发方式（如 Celery Beat 定时任务每小时检查过期会话），确保此策略在实现时有明确的归属模块。

### [R-004] LOW: API 路径命名风格混用

- **category**: convention
- **root_cause**: self-caused
- **描述**: arch#7.1 命名规范约定 API 路径使用 "kebab-case 复数名词"。绝大多数接口遵循了此约定（如 `/sources`, `/workflows`, `/subscriptions`），但部分路径使用了非复数形式或动词：`/api/v1/search`（单数）、`/api/v1/search/chat`（动词）、`/api/v1/llm/stats`（缩写+单数）。这些偏差在 REST 设计中属于常见实践（search 作为资源集合、stats 作为统计端点），并非严格错误，但与文档自身约定的"复数名词"规则不完全一致。
- **建议**: 可在 arch#7.1 命名规范中增加例外说明："操作型端点（search）和统计端点（stats）可使用单数或动词形式"，使规范与实际设计保持一致，避免下游开发者产生歧义。

### [R-005] LOW: LLMCallLog 分区策略与 LLM 用量统计 API 的时间范围兼容性

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: 数据分卷 E-007 LLMCallLog 定义了按 `created_at` 月份分区，3 个月保留期后可归档。API-017 LLM 用量统计支持 `date_from`/`date_to` 参数和 `period=month` 周期。如果用户查询超过 3 个月前的数据且分区已归档，查询行为未明确说明（返回空结果？报错？查询归档表？）。
- **建议**: 在 E-007 的分区策略说明或 API-017 的接口描述中补充归档后数据的查询行为约定，例如"归档分区不参与在线查询，统计结果仅包含在线分区数据范围"，或设计归档数据的访问路径。

---

## 审查结论

**approved_with_notes**

架构文档整体质量优秀，设计完整且与 PRD 高度一致。11 个模块覆盖了全部 14 个功能点，29 个 API 接口定义详实，12 个数据实体关系清晰。技术栈选型合理，非功能架构（缓存、安全、错误处理、降级）设计充分。

发现的 3 个 MEDIUM 问题和 2 个 LOW 问题均为完善性建议，不影响整体架构的可行性和正确性。其中 R-001（内容删除/存储统计 API 缺失）建议优先关注，因为对应的 PRD AC-066/AC-067 在 v1 范围内。
