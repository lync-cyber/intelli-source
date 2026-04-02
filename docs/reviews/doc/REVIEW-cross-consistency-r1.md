# REVIEW: 跨文档一致性审查
<!-- date: 2026-04-02 | reviewer: reviewer | scope: prd+arch+dev-plan 全量交叉审查 -->

## 审查范围

- PRD: docs/prd/prd-intellisource-v1.md
- ARCH 主卷: docs/arch/arch-intellisource-v1.md
- ARCH 模块分卷: docs/arch/arch-intellisource-v1-modules.md
- ARCH API 分卷: docs/arch/arch-intellisource-v1-api.md
- ARCH 数据分卷: docs/arch/arch-intellisource-v1-data.md
- DEV-PLAN 主卷: docs/dev-plan/dev-plan-intellisource-v1.md
- DEV-PLAN Sprint 1~4 分卷: docs/dev-plan/dev-plan-intellisource-v1-s1~s4.md

## Layer 1 结果

全部 10 个文件通过 doc_check.py 检查（PASS），仅有非阻塞性 WARN。

## Layer 2 审查结论

**结论: approved_with_notes**

存在 0 个 CRITICAL 问题、1 个 HIGH 问题、7 个 MEDIUM 问题、3 个 LOW 问题。

---

## CRITICAL 问题

无。

---

## HIGH 问题

### [R-001] HIGH: T-003 任务卡内部实体数量矛盾且与 ARCH 数据分卷不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: DEV-PLAN 主卷 Sprint 1 表的 T-003 标题为"ORM模型定义(全部实体含E-013)"，但 Sprint 1 分卷 T-003 的任务目标写"定义全部 **12** 个数据实体"，tdd_acceptance AC-T003-1 写"**12** 个 ORM 模型（**E-001~E-012**）"，context_load 引用"arch-intellisource-v1-data#§4（全部实体 **E-001~E-012**）"。然而 ARCH 数据分卷实际定义了 **13** 个实体（E-001~E-013，其中 E-013 为 AgentExecutionLog）。这意味着 T-003 的开发者可能遗漏 E-013 的 ORM 模型定义。
- **建议**: 将 s1 分卷 T-003 的目标改为"定义全部 13 个数据实体"，AC-T003-1 改为"13 个 ORM 模型（E-001~E-013）"，context_load 改为"E-001~E-013"。

---

## MEDIUM 问题

### [R-002] MEDIUM: 9 个 PRD 验收标准未被 DEV-PLAN 任何任务引用

- **category**: completeness
- **root_cause**: self-caused
- **描述**: 以下 PRD AC 在 DEV-PLAN 的 tdd_acceptance 字段中完全未被引用，存在实现遗漏风险:
  - **AC-014** (F-004: 条件跳过 -- 编排层根据内容类型/标签决定跳过特定操作)
  - **AC-022** (F-005: 每条内容在入库时生成唯一内容指纹，全链路基于指纹幂等处理)
  - **AC-033** (F-007: Agent 每次执行记录完整的工具调用链 AgentExecutionLog)
  - **AC-047** (F-010: 内置 Agent 调用 LLM 对推送内容重排序)
  - **AC-048** (F-010: 内置 Agent 为推送内容生成引导语/摘要)
  - **AC-049** (F-010: LLM 不可用时降级 -- 默认时间排序+无引导语)
  - **AC-050** (F-011: 内置 Agent 调用 LLM 理解检索意图)
  - **AC-052** (F-011: 内置 Agent 对检索结果生成摘要后异步回调)
  - **AC-069** (F-015: embedding 向量由外部 Agent 生成并通过 store_processed 传入)

  其中 AC-022 和 AC-033 的功能虽然在相关任务中隐含实现（T-018 fingerprint 操作、T-028 AgentExecutionLog 记录），但未被显式标注为 TDD 测试点。AC-047/048/049 属于 F-010（P2 优先级），可能是有意不纳入 v1 开发范围，但未明确说明。
- **建议**:
  1. AC-022 补充到 T-018 的 tdd_acceptance
  2. AC-033 补充到 T-028 的 tdd_acceptance
  3. AC-014 补充到 T-028 的 tdd_acceptance（Agent 编排层决定条件跳过）
  4. AC-050/052 补充到 T-029 或 T-028 的 tdd_acceptance
  5. AC-069 补充到 T-019 的 tdd_acceptance（store_processed 支持外部传入 embedding）
  6. AC-047/048/049 如 v1 不实现，在 DEV-PLAN §5 风险项中注明"F-010 推送优化为 P2，v1 仅实现基础推送"

### [R-003] MEDIUM: API-013 所属模块在主卷与 API 分卷不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: ARCH 主卷接口交叉引用表 (第 151 行) 标注 API-013（即时问答）所属模块为 **M-004** (内置编排 Agent 模块)，但 API 分卷 API-013 定义 (第 355 行) 标注 `module: M-008`。从功能语义看，即时问答需要 Agent 处理（意图理解+检索+摘要），应归属 M-004；而 API-012（混合检索）归属 M-008 是合理的。
- **建议**: 将 API 分卷 API-013 的 `module` 从 `M-008` 改为 `M-004`，与主卷保持一致。

### [R-004] MEDIUM: T-003 deliverables 引用不存在的 T-047

- **category**: consistency
- **root_cause**: self-caused
- **描述**: Sprint 1 分卷 T-003 的 deliverables 中写 `初始迁移脚本（草稿版，由 T-047 完善和验证）`，但当前 DEV-PLAN 的任务编号范围为 T-001~T-046，**T-047 不存在**。这是一个从之前版本（5 Sprint 方案）残留的悬空引用。实际负责数据库迁移的任务为 T-046。
- **建议**: 将 T-003 deliverables 中的 `T-047` 改为 `T-046`。

### [R-005] MEDIUM: PRD 术语表中"处理管道/处理器"与架构设计矛盾

- **category**: consistency
- **root_cause**: upstream-caused
- **描述**: PRD §5 术语表仍包含"处理管道 (Pipeline)"和"处理器 (Processor)"两个术语，其定义为"由多个有序处理器组成的内容加工链路"和"处理管道中的单个处理步骤"。但架构设计已将此概念替换为"原子操作 (Atomic Tool)"+ "内置编排 Agent"的架构模式，不再使用"管道/处理器"概念。术语表后半部分已正确添加了"原子操作"、"内置编排 Agent"、"Playbook"、"ToolSpec"等新术语，但旧术语未清理。
- **建议**: 从 PRD §5 术语表中移除或标注"处理管道"和"处理器"为已废弃术语，避免下游开发者误解。

### [R-006] MEDIUM: ARCH §7.3 Git commit scope 包含过时的 "pipeline"

- **category**: consistency
- **root_cause**: self-caused
- **描述**: ARCH §7.3 Git 约定中的 commit scope 列表为 `collector | pipeline | llm | scheduler | distributor | search | storage | api | cli | config`。其中 `pipeline` 对应旧设计中的"处理管道"概念，当前架构中对应的模块为 M-003（tools 原子操作）和 M-004（agent 内置编排），应使用 `tools` 和 `agent` 替代。同时缺少 `mcp`（M-012）和 `observability`（M-010）。
- **建议**: 将 scope 列表更新为: `collector | tools | agent | llm | scheduler | distributor | search | storage | api | mcp | cli | config | observability`

### [R-007] MEDIUM: ARCH API 分卷 API-010 步骤配置描述使用旧术语"管道"

- **category**: consistency
- **root_cause**: self-caused
- **描述**: API-010 (创建工作流) 的 steps 字段中 config 描述为"步骤配置（信源/**管道**/渠道参数）"。当前架构中不存在"管道"概念，应为"处理操作"或"原子操作"。
- **建议**: 将描述改为"步骤配置（信源/原子操作/渠道参数）"。

### [R-008] MEDIUM: DEV-PLAN 依赖图缺少 T-004 -> T-024 边 (T-024 依赖 T-004)

- **category**: completeness
- **root_cause**: self-caused
- **描述**: Sprint 3 分卷 T-024 (LLM 统一网关) 的任务依赖列表中写 `T-006, T-004`（通过 Sprint 3 主表推断: 依赖列 "T-006, T-004"），但查看主表实际为 `T-006, T-004`。然而 DEV-PLAN §2 依赖图中 T-024 仅有 `T-006 --> T-024` 边，缺少 `T-004 --> T-024` 边。再查主表: T-024 的依赖列为 `T-006, T-004`，确认依赖图遗漏。
- **建议**: 在 DEV-PLAN §2 依赖图中补充 `T-004 --> T-024` 边。

---

## LOW 问题

### [R-009] LOW: ARCH 模块分卷 status 仍为 draft，应与主卷一致为 approved

- **category**: convention
- **root_cause**: self-caused
- **描述**: ARCH 主卷 status 为 `approved`，但模块分卷（arch-intellisource-v1-modules.md）、API 分卷（arch-intellisource-v1-api.md）、数据分卷（arch-intellisource-v1-data.md）的 status 均为 `draft`。分卷与主卷共同构成架构文档，状态应保持一致。同样，DEV-PLAN 主卷为 `approved`，但 Sprint 分卷（s1~s4）均为 `draft`。
- **建议**: 将所有分卷的 status 从 `draft` 更新为 `approved`。

### [R-010] LOW: DEV-PLAN 主卷 T-037 TDD测试点使用自定义 AC 编号而非 PRD AC

- **category**: convention
- **root_cause**: self-caused
- **描述**: DEV-PLAN 主卷 Sprint 4 表中 T-037 的 TDD 测试点列写 `AC-T037`，这是唯一一个在主表中使用任务级自定义 AC 编号而非 PRD AC 编号的任务。Webhook 回调功能与 PRD F-011 (消息指令式即时检索) 和 F-009 (多渠道分发) 相关，可引用 AC-050（Agent 通过消息触发理解检索意图）。
- **建议**: 在主表 T-037 的 TDD 测试点列补充相关 PRD AC 引用（如 AC-050），格式改为 `AC-050, AC-T037`。

### [R-011] LOW: 架构设计一致性验证 -- 核心原则贯穿良好

- **category**: completeness
- **root_cause**: reviewer-calibration
- **描述**: 验证以下核心设计原则在三层文档中的贯穿情况:
  1. **"原子操作不内置LLM"**: PRD F-004 备注明确声明, ARCH M-003 设计原则确认, DEV-PLAN T-017~T-022 的原子操作均不涉及 LLM -- **一致**
  2. **"内置Agent通过function calling调用原子操作"**: PRD F-005 AC-018, ARCH M-004 BuiltinAgent 设计, DEV-PLAN T-028 AC-018 映射 -- **一致**
  3. **"Playbook降级机制"**: PRD F-005 AC-021/F-008 AC-037, ARCH M-004 PlaybookFallback/M-006 PlaybookRunner, DEV-PLAN T-027/T-028 -- **一致**
  4. **"MCP暴露"**: PRD F-015 AC-066~070, ARCH M-012 MCPServer, DEV-PLAN T-042 -- **一致**
  5. **"双协议暴露 (API+MCP) 共享同一 ToolRegistry"**: ARCH M-011 ToolsRouter + M-012 MCPServer 均依赖 M-003, DEV-PLAN T-041+T-042 均依赖 T-010 -- **一致**

  核心架构原则在文档间保持了良好的一致性，无矛盾发现。本条为正向确认记录。
- **建议**: 无需修改。

---

## 审查总结

### 功能覆盖

- PRD F-001~F-015 全部在 ARCH 模块表中有映射（M-001~M-012），无遗漏
- PRD 70 个 AC 中，9 个未被 DEV-PLAN 显式引用（见 R-002），需补充或标注

### 模块 ID 一致性

- M-001~M-012 在主卷交叉引用表与模块分卷定义一致，无旧模块名残留
- DEV-PLAN 中所有任务引用的模块 ID 与 ARCH 一致

### API 接口一致性

- API-001~API-030 在主卷交叉引用表与 API 分卷定义一致
- **唯一例外**: API-013 的模块归属不一致（见 R-003）

### 数据实体一致性

- E-001~E-013 在主卷交叉引用表与数据分卷定义一致
- **T-003 与数据分卷不一致**: T-003 写 E-001~E-012，实际应为 E-001~E-013（见 R-001）

### 任务依赖一致性

- T-001~T-046 编号连续无缺漏
- 依赖图与主表基本一致，发现 1 处遗漏边（见 R-008）
- T-003 存在对不存在任务 T-047 的悬空引用（见 R-004）

### 遗留设计残留

- PRD 术语表保留旧术语"处理管道/处理器"（见 R-005）
- ARCH §7.3 commit scope 包含旧术语"pipeline"（见 R-006）
- ARCH API-010 描述使用旧术语"管道"（见 R-007）
