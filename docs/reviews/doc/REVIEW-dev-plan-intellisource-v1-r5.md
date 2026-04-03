# REVIEW: dev-plan-intellisource-v1 (r5)

<!-- doc_id: dev-plan-intellisource-v1 | reviewer: reviewer | date: 2026-04-03 -->
<!-- review_round: 5 | review_type: independent-rescan -->

## 审查概要

- **被审文档**: dev-plan-intellisource-v1 (主卷 + Sprint 1~5 分卷)
- **审查轮次**: r5 (独立复审，不参考历史审查报告)
- **上游依赖**: prd-intellisource-v1, arch-intellisource-v1 (含 api/data/modules 分卷)
- **Layer 1 结果**: 主卷 PASS; Sprint 1 PASS (1 WARN); Sprint 2~4 PASS; Sprint 5 PASS (1 WARN)
- **总体判定**: **approved_with_notes**

## Layer 2: AI 语义审查

---

### [R-001] MEDIUM: PRD AC-066/AC-067 (内容删除与存储统计API) 未在任何任务中覆盖

- **category**: completeness
- **root_cause**: upstream-caused
- **描述**: PRD F-014 定义了 AC-066（内容删除操作：单条删除和批量删除）和 AC-067（存储统计查询），这两个验收标准在 dev-plan 的全部 47 个任务中均未覆盖。T-043 声明覆盖的是 AC-061 和 AC-065，其 deliverables 中的 `contents.py` 路由仅提及内容列表/详情，未包含 DELETE 端点或存储统计端点。此问题根源在于 ARCH API 分卷中未定义对应的 API 接口（ARCH r4 审查中已标记为 MEDIUM），导致 dev-plan 无上游接口可引用。
- **建议**: 如果 ARCH 层面已接受此遗漏（approved_with_notes），则在 dev-plan 中明确标注 AC-066/AC-067 为"ARCH 已知遗漏，v1 不纳入开发任务"。否则需在 T-043 或新增任务中补充相应 API 端点的开发。

---

### [R-002] MEDIUM: M-010 AlertManager 组件未在任何任务中覆盖

- **category**: completeness
- **root_cause**: self-caused
- **描述**: ARCH 模块分卷 M-010 定义了 `AlertManager` 组件（关键指标异常时触发告警，对应 prd AC-060 的"关键指标异常时自动触发告警"部分）。T-006（结构化日志与可观测性基础）和 T-007（健康检查与指标端点）的 deliverables 和 tdd_acceptance 中均未提及 AlertManager 的实现。T-006 覆盖了日志/指标/追踪，T-007 覆盖了健康检查端点，但告警触发机制被遗漏。
- **建议**: 在 T-007 的 tdd_acceptance 中补充 AlertManager 相关的验收标准（如：关键指标超阈值时记录告警事件），或在 T-006 中增加告警管理器的 deliverable。如果告警依赖外部告警系统（如 Prometheus Alertmanager），可标注为 [ASSUMPTION] 并说明 v1 仅产出指标，告警规则由用户在外部配置。

---

### [R-003] MEDIUM: T-020 依赖图中缺少对 T-022 的直接依赖边 (实际依赖关系不完整)

- **category**: consistency
- **root_cause**: self-caused
- **描述**: 主卷依赖图中标注 T-020(熔断器) --> T-022(LLM结构化提取处理器)，但从任务定义看，T-022 的依赖是 T-019 和 T-016，并非 T-020。T-022 的 tdd_acceptance 中 AC-T022-3 提到降级逻辑使用 arch#5.3 降级映射表，这在语义上依赖 FallbackManager（T-020 产出），但 Sprint 总览表中 T-022 的依赖列为 "T-019, T-016"，未包含 T-020。依赖图与任务卡的依赖声明存在矛盾。
- **建议**: 统一依赖声明 -- 如果 T-022 确实依赖 T-020 的 FallbackManager，应在 Sprint 3 总览表中将 T-022 的依赖更新为 "T-019, T-016, T-020"。如果 T-022 不直接依赖 T-020（降级逻辑内嵌实现），则从依赖图中移除 T-020 --> T-022 的边。

---

### [R-004] LOW: T-004 的 Repository 粒度与 ARCH 实体覆盖不完全对齐

- **category**: completeness
- **root_cause**: self-caused
- **描述**: T-004 的 deliverables 列出了 5 个 Repository（source, content, task, subscription, push），但 ARCH 定义了 12 个实体 (E-001~E-012)。部分实体的数据访问逻辑分散在后续任务中（如 E-012 Workflow 在 T-030，E-011 ChatSession 在 T-039，E-007 LLMCallLog 在 T-021），这是合理的按业务模块分配方式。但 E-005 ContentCluster、E-006 Digest、E-008 TaskChain 的 Repository 未在任何任务的 deliverables 中显式声明，其数据访问可能隐含在 T-024（聚类）、T-025（简报）、T-027（任务链）中。
- **建议**: 对于隐含包含 Repository 逻辑的任务（T-024、T-025、T-027），建议在任务卡的 deliverables 或实现提示中明确标注将包含对应实体的数据访问代码，便于开发者理解范围。

---

### [R-005] LOW: T-040 的 TDD 测试点使用非标准 AC 编号格式

- **category**: convention
- **root_cause**: self-caused
- **描述**: T-040 的 tdd_acceptance 中使用了 `AC-T040` 格式的编号（如 AC-T040-1 至 AC-T040-6），而主卷 Sprint 5 总览表中该任务的 TDD 测试点列为 "AC-T040"。这与其他任务的格式一致（任务级 AC 使用 AC-T{NNN}-N 格式），但总览表中的 "AC-T040" 引用不够精确，其他任务在总览表中引用的是 PRD 级 AC 编号（如 AC-054, AC-055），而非任务级编号。
- **建议**: 在主卷 Sprint 5 总览表中，T-040 的 TDD 测试点列可补充说明"无 PRD 级 AC 映射，全部为任务级 AC"。这是因为 Webhook 回调处理是 ARCH 层面新增的技术实现需求，在 PRD 中没有直接对应的 AC 编号。

---

### [R-006] LOW: 关键路径分析中 T-004 到 T-019 的跳跃未充分说明

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: 主卷关键路径为 T-001 -> T-002 -> T-003 -> T-004 -> T-019 -> ... 其中 T-004(Repository) 到 T-019(LLM网关) 的依赖关系在依赖图中通过 T-004 --> T-019 边体现，但 T-019 的任务卡依赖列为 "T-006, T-004"，即同时依赖 T-006（日志）和 T-004（Repository）。关键路径选择了 T-004 --> T-019 而非 T-006 --> T-019，这是因为 T-004(L=3) 的权重大于 T-006(M=2)，路径正确。但关键路径说明中未解释为何跳过了 T-005~T-009，可能对读者造成困惑。
- **建议**: 在关键路径说明中补充一句"T-004 到 T-019 的连接基于 T-019 对 M-009 数据访问层的依赖"，帮助读者理解路径选择逻辑。

---

## 审查总结

| 维度 | 评估 |
|------|------|
| 完整性 (completeness) | 良好。47 个任务覆盖了 PRD 绝大部分 AC，仅 AC-066/AC-067 缺失（上游 ARCH 也未定义）和 AlertManager 组件遗漏 |
| 一致性 (consistency) | 良好。与 ARCH 模块划分、API 定义、数据模型基本一致，依赖图个别边与任务卡声明有矛盾 |
| 可行性 (feasibility) | 优秀。技术方案可落地，复杂度评估合理，5 个 Sprint 的任务分布均匀 |
| 安全性 (security) | 良好。认证、敏感词过滤、Webhook 签名验证均有对应任务覆盖 |
| 规范性 (convention) | 良好。任务卡格式统一，AC 编号体系清晰，个别引用格式不一致 |
| 清晰度 (ambiguity) | 良好。每个任务的目标、验收标准和交付物定义明确，可作为 TDD 开发的直接输入 |

## 判定结论

**approved_with_notes**

无 CRITICAL 或 HIGH 问题。发现 3 个 MEDIUM 问题和 3 个 LOW 问题，均为完善性建议：

- R-001 (MEDIUM): AC-066/AC-067 缺失，属上游传导问题
- R-002 (MEDIUM): AlertManager 组件未覆盖
- R-003 (MEDIUM): 依赖图与任务卡依赖声明不一致
- R-004~R-006 (LOW): Repository 覆盖说明、AC 编号格式、关键路径说明的完善建议
