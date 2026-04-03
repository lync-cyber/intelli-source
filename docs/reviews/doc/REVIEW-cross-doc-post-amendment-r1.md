# REVIEW: 跨文档修订后复审
<!-- id: REVIEW-cross-doc-post-amendment-r1 | date: 2026-04-03 | reviewer: reviewer -->
<!-- scope: prd, arch (main + modules + api + data), dev-plan (main + s1~s5) -->
<!-- trigger: 情感分析移除 + 引用统一 + §5.4新增 + 配置版本管理 + status更新 -->

## 审查摘要

本次审查针对情感分析移除、引用一致性调整、§5.4新增内容、M-001配置版本管理存储策略补充、分卷status更新等变更进行跨文档复审。共发现 2 个 HIGH 级别问题和 4 个 MEDIUM 级别问题。

## 问题列表

### [R-001] HIGH: E-007 call_type 枚举中残留 sentiment 值

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `docs/arch/arch-intellisource-v1-data.md` 第 168 行，E-007 LLMCallLog 的 `call_type` 字段说明为 `调用类型: extract/dedup/cluster/summarize/tag/sentiment/search/optimize`，其中 `sentiment` 未被移除。情感分析功能已从系统中删除，此处残留会导致开发实现时引入无用的枚举值。
- **建议**: 将 `call_type` 说明修改为 `调用类型: extract/dedup/cluster/summarize/tag/search/optimize`，移除 `sentiment`。

### [R-002] HIGH: M-004 职责描述中残留"情感分析"

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `docs/arch/arch-intellisource-v1-modules.md` 第 61 行，M-004 的职责描述为"基于 LLM 实现结构化提取、语义去重、聚类、摘要、打标和**情感分析**等高级内容处理"，其中"情感分析"未被移除。
- **建议**: 将职责描述修改为"基于 LLM 实现结构化提取、语义去重、聚类、摘要、打标等高级内容处理"。

### [R-003] MEDIUM: arch 主卷 NAV 块未列出 §5.4 数据运维

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `docs/arch/arch-intellisource-v1.md` 第 13 行 NAV 块中 §5 的子章节列表为 `§5.1 性能, §5.2 安全, §5.3 错误处理`，缺少新增的 `§5.4 数据运维`。NAV 块应与文档实际章节结构保持同步。
- **建议**: 将 NAV 块第 13 行更新为 `- §5 非功能架构 → §5.1 性能, §5.2 安全, §5.3 错误处理, §5.4 数据运维`。

### [R-004] MEDIUM: arch§5.4 引用 T-045 实现 cleanup/reindex CLI 命令，但 T-045 任务卡未包含这些交付物

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `docs/arch/arch-intellisource-v1.md` §5.4 数据运维中声明:
  - `intellisource cleanup sessions` 由 T-045 实现（第 306 行）
  - `intellisource reindex embeddings` 由 T-045 实现（第 314 行）
  
  但 `docs/dev-plan/dev-plan-intellisource-v1-s5.md` 中 T-045 的 tdd_acceptance 和 deliverables 均未提及这两个 CLI 子命令。开发者实现 T-045 时可能遗漏这些功能。
- **建议**: 在 T-045 的 tdd_acceptance 中补充:
  - `AC-T045-7: intellisource cleanup sessions 清理超时会话`
  - `AC-T045-8: intellisource reindex embeddings 批量重新生成 embedding`

### [R-005] MEDIUM: config_history 表在 M-001 模块中引用但数据模型分卷中无对应实体定义

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `docs/arch/arch-intellisource-v1-modules.md` 第 26 行 M-001 ConfigVersionManager 描述中提到"历史快照以 JSONB 形式存入独立的 config_history 表"，但 `docs/arch/arch-intellisource-v1-data.md` 的实体列表（E-001~E-012）中并无 `config_history` 表的实体定义。主卷 §4 实体交叉引用目录也未列出此表。这将导致开发者在实现配置版本管理时缺乏数据模型参考。
- **建议**: 二选一: (a) 在 arch-intellisource-v1-data.md 中新增 E-013 ConfigHistory 实体定义（含 id, source_id, version, config_snapshot, changed_at 等字段），同步更新主卷§4实体目录; 或 (b) 将配置历史存储设计改为利用已有的 E-001 Source 表扩展（如 JSONB 数组字段），并更新 M-001 描述。

### [R-006] MEDIUM: NAV-INDEX 中所有文档状态仍为 draft，与文档实际 status: approved 不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `docs/NAV-INDEX.md` 中 prd、arch（含分卷）、dev-plan（含分卷）共 11 个文档条目的状态列均显示 `draft`，但这些文档头部的 `status` 字段均已更新为 `approved`。NAV-INDEX 作为文档导航的统一入口，状态应与文档实际状态同步。
- **建议**: 将 NAV-INDEX.md 中所有已审批文档的状态列从 `draft` 更新为 `approved`。

## 未发现问题的检查项（确认通过）

- **PRD AC 编号 AC-025 缺失**: F-006 从 AC-024 跳至 AC-026。此为情感分析相关 AC 移除后的编号间隙，属于预期行为（重新编号会导致下游所有引用失效），不计为问题。
- **E-004 实体描述一致性**: 移除 sentiment 后，E-004 在数据模型、API 文档和模块文档中的描述一致，无矛盾。
- **E-009 match_rules**: 数据模型（`{keywords: [], tags: []}`）与 API-023/API-024 中的 match_rules 定义一致。
- **所有分卷 status 更新**: 11 个文档的 `<!-- status: approved -->` 均已正确更新。
- **降级策略引用**: 各处降级策略和熔断参数已统一引用 `arch#§5.3`，未发现重复定义。
- **§5.4 新增内容质量**: 数据运维和 embedding 迁移方案与现有架构（pgvector、Alembic、CLI）一致，步骤清晰可执行。

## 审查结论

**approved_with_notes**

R-001 和 R-002 为情感分析残留，严重等级为 HIGH，因为会直接导致开发实现偏差。但考虑到这两个问题的修复非常明确且局限（仅需删除两处文本），且不涉及架构逻辑变更，将其判定为 HIGH 而非 CRITICAL。

如果按严格三态判定（存在 HIGH 即 needs_revision），结论应为 **needs_revision**。请 orchestrator 或用户决定是否要求修复后再继续，或接受并在开发阶段注意这两处残留。
