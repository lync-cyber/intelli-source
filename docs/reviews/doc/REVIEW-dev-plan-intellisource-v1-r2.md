# REVIEW: dev-plan-intellisource-v1 (r2)
<!-- date: 2026-04-02 | reviewer: reviewer | doc_type: dev-plan -->
<!-- Layer 1: PASS (主卷+全部5个Sprint分卷) | Layer 2: 已执行 -->

## 审查范围
- 主卷: docs/dev-plan/dev-plan-intellisource-v1.md
- 分卷: dev-plan-intellisource-v1-s1.md ~ s5.md (5个Sprint分卷)
- 上游依赖: prd-intellisource-v1 (approved), arch-intellisource-v1 + 分卷 (approved)
- 上一轮审查: REVIEW-dev-plan-intellisource-v1-r1.md

## r1 问题修复验证

### [R-001] r1 — 交叉引用短格式 doc_id (HIGH)
**状态**: 已修复。全部 5 个 Sprint 分卷的 Layer 1 交叉引用检查均已通过，`arch-data` / `arch-api` 已替换为完整 doc_id 格式 `arch-intellisource-v1-data` / `arch-intellisource-v1-api`。

## Layer 1 结果

### 主卷: PASS
`doc_check.py dev-plan` 对主卷检查全部通过。

### 分卷: PASS (全部5个Sprint分卷)
| 分卷 | 结果 | WARN |
|------|------|------|
| s1 | PASS | 0 |
| s2 | PASS | 0 |
| s3 | PASS | 0 |
| s4 | PASS | 0 |
| s5 | PASS | 1 (ID编号不连续 -- 预期行为，Sprint分卷仅含本Sprint任务ID) |

## Layer 2 结果

### 完整性 (completeness)

**AC 覆盖验证**: 对照 PRD 全部 65 个 AC (AC-001 ~ AC-065)，dev-plan 的 tdd_acceptance 字段中均有对应映射或任务级 AC 覆盖，无遗漏。

**任务卡字段完整性**: 全部 47 个任务卡均包含目标、模块、接口、复杂度、tdd_acceptance、deliverables、context_load 字段。部分任务额外包含 "实现提示" 字段，提供了有价值的技术指导。

### 一致性 (consistency)

审查发现以下不一致问题:

1. **Sprint 总览表与任务卡 AC 映射偏差**: 主卷 Sprint 1 表中 T-007 列出 `AC-059, AC-060`，但 T-007 任务卡中仅实现 AC-060 相关内容（健康检查端点）。AC-059（TracingMiddleware trace_id 注入）实际在 T-006 任务卡中实现。Sprint 表中 T-007 应仅列 `AC-060`。(见 R-001)

2. **Sprint 总览表 T-040 AC 映射不精确**: 主卷 Sprint 5 表中 T-040 列出 `AC-050`，但 T-040 任务卡的 tdd_acceptance 仅包含自定义 AC-T040 项（签名验证、消息解析、路由转发等），未直接映射 AC-050。AC-050（LLM 理解检索意图）的直接实现在 T-038。T-040 是 AC-050 的消息入口但非直接实现者。(见 R-002)

3. **deliverables 文件路径与 arch#§6 目录结构偏差**: 多个任务卡的 deliverables 包含 arch#§6 目录树中未列出的文件:
   - T-007: `observability/health.py`
   - T-014: `collector/proxy.py`
   - T-023: `llm/processors/fingerprint.py`
   - T-029: `scheduler/idempotency.py`
   - T-035: `distributor/frequency.py`
   - T-039: `search/session.py`（arch 目录树仅有 `search/chat.py`）

   这些均为合理的实现级细化，但与 arch#§6 存在差异。(见 R-003)

### 可行性 (feasibility)

1. **T-003 复杂度与范围匹配**: T-003 定义为 L 复杂度，目标是定义全部 12 个 ORM 模型。考虑到 12 个实体含复杂关系映射（FK、JSONB、pgvector 类型、GIN/HNSW 索引），L 复杂度评估合理。

2. **Sprint 依赖链合理性**: Sprint 间依赖遵循 "基础设施 -> 业务逻辑 -> 集成层" 的合理递进关系。Sprint 1（存储/配置/可观测性）为后续 Sprint 提供必要基础。

3. **关键路径权重计算**: 主卷 §4 关键路径权重 24（S=1,M=2,L=3）与实际路径节点复杂度之和一致（1+2+3+3+2+3+2+2+2+2+2=24），计算正确。

### 安全性 (security)

1. **敏感配置处理**: T-008 支持 `${ENV_VAR}` 环境变量占位符，T-044 实现 API Key 认证中间件，T-040 实现 Webhook 签名验证。与 arch#§5.2 安全方案一致。

2. **敏感词过滤**: T-026 实现 LLM 调用前后双重检查，与 prd#§2.F-006.AC-026 和 arch#§5.2 数据安全一致。

### 规范性 (convention)

1. **引用格式**: 修订后的分卷全部使用完整 doc_id 格式引用（如 `arch-intellisource-v1-data#§4.E-001`），符合 COMMON-RULES §文档引用格式。

2. **任务ID编号**: T-001 至 T-047 连续无跳号，Sprint 分配合理（S1: 9, S2: 9, S3: 8, S4: 10, S5: 11）。

3. **文档元数据**: 主卷和全部分卷的 `id`、`author`、`status`、`deps`、`consumers`、`volume` 字段齐全。

### 清晰度 (ambiguity)

1. **T-047 与 T-003 职责边界**: T-003 的 deliverables 已包含 `alembic/versions/{initial_migration}.py`（初始迁移脚本），T-047 的 deliverables 也包含 `alembic/versions/{initial}.py`（初始迁移脚本完整版）。T-047 实现提示中说明 "T-003 中已生成初始迁移脚本的草稿，此任务负责完善和验证"，职责边界已澄清，但 deliverables 路径重叠可能造成开发者困惑。(见 R-004)

## 问题列表

### [R-001] MEDIUM: Sprint 总览表 T-007 的 AC 映射包含应属于 T-006 的 AC-059
- **category**: consistency
- **root_cause**: self-caused
- **描述**: 主卷 §1 Sprint 1 表中 T-007 行的 "TDD测试点" 列为 `AC-059, AC-060`，但 AC-059（TracingMiddleware 为请求生成 trace_id）实际在 T-006 任务卡中实现。T-007 任务卡仅覆盖 AC-060（健康检查端点）和自定义 AC-T007 项。总览表与任务卡详情不一致。
- **建议**: 将主卷 T-007 行的 TDD测试点修改为 `AC-060`，同时将 T-006 行增加 `AC-059`（当前 T-006 行为 `AC-057, AC-058`，应改为 `AC-057, AC-058, AC-059`）。

### [R-002] LOW: Sprint 总览表 T-040 的 AC-050 映射不精确
- **category**: consistency
- **root_cause**: self-caused
- **描述**: 主卷 §1 Sprint 5 表中 T-040 行的 TDD测试点为 `AC-050`，但 T-040 任务卡中无 AC-050 的直接映射。AC-050（LLM 理解检索意图）的直接实现在 T-038。T-040 作为消息入口将用户消息路由到 M-008，是 AC-050 的间接参与者而非直接实现者。
- **建议**: 考虑将 T-040 行的 TDD测试点改为更精确的描述（如删除 AC-050，改为标注自定义 AC-T040），或在任务卡中明确补充 AC-050 的映射说明。此为表述精确度问题，不影响功能覆盖。

### [R-003] LOW: 多个任务卡 deliverables 文件路径超出 arch#§6 目录结构定义
- **category**: consistency
- **root_cause**: self-caused
- **描述**: 6 个任务卡的 deliverables 包含 arch#§6 未列出的文件路径（health.py, proxy.py, fingerprint.py, idempotency.py, frequency.py, session.py）。这些是合理的实现级细化，不影响模块边界，但与上游 arch 文档存在形式上的不一致。
- **建议**: 如后续有 arch 文档修订机会，建议补充这些文件到 §6 目录树。当前不阻塞开发计划。

### [R-004] LOW: T-003 与 T-047 的 Alembic 迁移脚本 deliverables 路径重叠
- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: T-003 deliverables 包含 `alembic/versions/{initial_migration}.py`，T-047 deliverables 包含 `alembic/versions/{initial}.py`。虽然 T-047 实现提示已说明是 "完善和验证" T-003 的草稿，但两个任务产出同一文件路径可能导致开发时产出物归属不清。
- **建议**: 在 T-003 的 deliverables 中标注迁移脚本为 "草稿版"，或在 T-047 中明确说明该交付物是对 T-003 产出的迭代而非独立产出。

## 审查结论

**approved_with_notes**

r1 报告中的 HIGH 级别问题（交叉引用短格式 doc_id）已全部修复，Layer 1 全部通过。Layer 2 语义审查未发现 CRITICAL 或 HIGH 级别问题。存在 1 个 MEDIUM 问题（Sprint 总览表 AC 映射偏差）和 3 个 LOW 问题（AC 映射精确度、deliverables 路径与 arch 偏差、迁移脚本路径重叠），均不影响开发计划的可执行性。
