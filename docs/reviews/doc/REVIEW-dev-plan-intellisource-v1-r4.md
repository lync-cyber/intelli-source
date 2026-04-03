# REVIEW: dev-plan-intellisource-v1 (r4)
<!-- date: 2026-04-03 | reviewer: reviewer | doc_type: dev-plan -->
<!-- Layer 1: PASS (主卷+全部5个Sprint分卷) | Layer 2: 已执行 -->

## 审查范围

- 主卷: docs/dev-plan/dev-plan-intellisource-v1.md
- 分卷: dev-plan-intellisource-v1-s1.md ~ s5.md (5个Sprint分卷)
- 上游依赖: prd-intellisource-v1 (approved), arch-intellisource-v1 + 分卷 (approved/draft)
- 上一轮审查: REVIEW-dev-plan-intellisource-v1-r3.md (approved)

## Layer 1 结果

### 主卷: PASS

`doc_check.py dev-plan` 对主卷检查全部通过。

### 分卷: PASS (全部5个Sprint分卷)

| 分卷 | 结果 | WARN |
|------|------|------|
| s1 | PASS | 1 (ID编号不连续 -- 预期行为，Sprint分卷仅含本Sprint任务ID) |
| s2 | PASS | 0 |
| s3 | PASS | 0 |
| s4 | PASS | 0 |
| s5 | PASS | 1 (ID编号不连续 -- 预期行为，Sprint分卷仅含本Sprint任务ID) |

## Layer 2 审查

### 完整性 (completeness)

**PRD功能覆盖验证**: 逐一核对PRD F-001至F-014的全部65个AC（AC-001至AC-065）在dev-plan任务卡中的映射情况。

| PRD功能 | AC范围 | 覆盖任务 | 覆盖状态 |
|---------|--------|---------|---------|
| F-001 信源配置 | AC-001~004 | T-008, T-009 | 完整 |
| F-002 采集引擎 | AC-005~008 | T-010~T-013 | 完整 |
| F-003 频率自适应 | AC-009~012 | T-014, T-015 | 完整 |
| F-004 处理管道 | AC-013~017 | T-016~T-018 | 完整 |
| F-005 LLM提取/去重/聚类 | AC-018~022 | T-022~T-024 | 完整 |
| F-006 LLM摘要/打标/分析 | AC-023~027 | T-025, T-026 | 完整 |
| F-007 LLM服务治理 | AC-028~033 | T-019~T-021 | 完整 |
| F-008 任务编排 | AC-034~039 | T-027~T-030 | 完整 |
| F-009 多渠道分发 | AC-040~046 | T-031~T-035 | 完整 |
| F-010 推送LLM优化 | AC-047~049 | T-036 | 完整 |
| F-011 即时检索 | AC-050~053 | T-037~T-040 | 完整 |
| F-012 存储与检索 | AC-054~056 | T-002~T-005, T-047 | 完整 |
| F-013 可观测性 | AC-057~060 | T-006, T-007 | 完整 |
| F-014 API与CLI | AC-061~065 | T-041~T-046 | 完整 |

全部65个AC均有对应任务卡覆盖，无遗漏。

**任务卡完整度**: 47个任务卡（T-001至T-047）均包含完整的目标、模块、复杂度、tdd_acceptance、deliverables、context_load字段。

**依赖关系完整度**: 主卷依赖图包含全部47个任务节点和对应的有向边，与各任务卡声明的依赖一致。

### 一致性 (consistency)

**与ARCH模块映射一致性**: 每个任务卡标注的模块ID与arch-intellisource-v1-modules中的模块定义一致。

**与ARCH API一致性**: 涉及API的任务卡（T-007, T-009, T-021, T-028, T-030, T-031, T-040, T-041~T-046）所引用的API ID与arch-intellisource-v1-api中的定义一致。

**与ARCH数据模型一致性**: 涉及数据实体的任务卡所引用的E-XXX实体与arch-intellisource-v1-data中的定义一致。

**内部一致性**: 主卷Sprint总览表中的任务ID、任务名、模块、复杂度、依赖、TDD测试点与各Sprint分卷任务卡详情一致。

**依赖图一致性**: 主卷Mermaid依赖图中的边与各任务卡声明的依赖字段一致。关键路径说明与依赖图吻合。

### 可行性 (feasibility)

**Sprint负载评估**（使用S=1, M=2, L=3权重）:

- Sprint 1: 9个任务, 权重=1+2+3+3+2+2+1+2+2=18
- Sprint 2: 9个任务, 权重=2+2+2+1+2+2+2+2+2=17
- Sprint 3: 8个任务, 权重=2+3+2+2+3+3+2+1=18
- Sprint 4: 10个任务, 权重=3+2+2+2+2+2+2+1+1+2=19
- Sprint 5: 11个任务, 权重=3+2+2+2+2+2+2+2+2+2+1=22

Sprint间负载相对均衡。Sprint 5任务数最多但包含多个M复杂度的API路由层任务，整体可行。

**依赖关系可行性**: 依赖图为DAG（无循环），每个Sprint内的任务依赖均可在当前或前序Sprint中满足。跨Sprint依赖合理（后序Sprint任务依赖前序Sprint产出）。

**TDD验收标准充分性**: 各任务的tdd_acceptance条目数量适当（3-6个），覆盖核心功能验证。AC映射到PRD验收标准的同时，补充了实现级别的验收条件（AC-TXXX-N格式），为TDD编写提供了充分的输入。

### 安全性 (security)

**敏感配置处理**: T-008/T-009涉及配置加载，AC中包含环境变量注入（${ENV_VAR}占位符）和校验失败拒绝加载机制，与arch#§5.2安全方案一致。

**认证中间件**: T-044明确定义了API Key认证、Webhook豁免、请求追踪，与arch#§5.2认证机制一致。

**输入校验**: T-009引用了arch#§5.2输入校验策略（API-005白名单），T-040包含Webhook签名验证。

**敏感词过滤**: T-026覆盖了敏感词过滤与合规检查（AC-026），包含LLM调用前后双重检查。

无安全性遗漏。

### 规范性 (convention)

**命名规范**: 任务卡中的deliverables文件路径均使用snake_case，与arch#§7.1命名规范一致。

**ID编号规范**: 任务ID T-001至T-047连续无跳号。AC映射使用PRD原始编号（AC-NNN）和任务级自定义编号（AC-TXXX-N）两种格式，区分清晰。

**文档格式**: 主卷和分卷的元数据（id, author, status, deps, consumers, volume）格式规范。[NAV]块与实际章节结构一致。

### 清晰度 (ambiguity)

**任务边界清晰度**: 各任务卡的目标描述明确，模块归属清晰。T-003与T-047的迁移脚本职责已通过"草稿版/完整版"标注区分。

**context_load清晰度**: 每个任务卡的context_load引用明确指向上游文档的具体章节/条目，为TDD开发提供了精确的上下文范围。

**实现提示**: 复杂任务（T-005, T-011, T-014, T-020, T-023, T-034, T-046, T-047）提供了实现提示，降低了歧义风险。

## 问题列表

### [R-001] MEDIUM: Sprint分卷status字段为draft而主卷为approved

- **category**: consistency
- **root_cause**: self-caused
- **描述**: 主卷 dev-plan-intellisource-v1.md 的元数据 status 为 `approved`（与CLAUDE.md一致），但5个Sprint分卷（s1~s5）的元数据 status 仍为 `draft`。分卷作为主卷的组成部分，状态应与主卷保持同步。
- **建议**: 将5个Sprint分卷的元数据 `status: draft` 更新为 `status: approved`，保持与主卷一致。

### [R-002] LOW: T-005与T-037混合检索功能存在职责重叠描述

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: T-005（pgvector向量存储与检索）的deliverables包含 `vector.py` 并定义了 `HybridIndex.search()` 支持 keyword/semantic/hybrid 三种模式（AC-T005-3）。T-037（混合检索引擎）同样定义了 `HybridSearchEngine` 支持 keyword/semantic/hybrid 三种模式（AC-T037-1）。两者在"混合检索"能力上的职责边界描述不够清晰。从context_load和模块归属来看，T-005属于M-009（存储层的底层检索能力），T-037属于M-008（面向用户的检索服务层），但任务描述中未明确说明两者的调用关系。
- **建议**: 在T-037的实现提示中补充说明 `HybridSearchEngine` 封装了 T-005 的 `VectorStore` 和 `HybridIndex` 底层能力，增加了面向用户的过滤、排序和结果格式化逻辑，以明确分层关系。

### [R-003] LOW: T-040的tdd_acceptance使用AC-T040而非PRD AC映射

- **category**: convention
- **root_cause**: self-caused
- **描述**: T-040（Webhook回调处理）的主卷Sprint总览表中TDD测试点为 `AC-T040`，这是任务级自定义AC而非PRD级AC映射。虽然r2审查已确认此为合理设计（Webhook回调在PRD中无直接对应AC），但与其他任务卡的命名模式略有不同 -- 大多数任务至少有一个PRD AC映射。这不影响功能覆盖，仅为命名一致性的记录。
- **建议**: 无需修改，记录即可。T-040的功能支撑了F-011即时检索（AC-050~053）和F-009分发（AC-040~041），是实现层面的桥接任务。

### [R-004] LOW: collector/proxy.py缺少对应测试文件

- **category**: completeness
- **root_cause**: self-caused
- **描述**: T-014（速率限制与代理管理）的deliverables中包含 `src/intellisource/collector/proxy.py`（代理管理器），但测试文件仅列出 `tests/unit/collector/test_rate_limiter.py`，未包含proxy模块的测试文件。虽然proxy逻辑可能在test_rate_limiter.py中一并测试，但deliverables未明确标注。
- **建议**: 在T-014的deliverables中补充 `tests/unit/collector/test_proxy.py`，或在现有测试文件描述中注明包含proxy测试。

## 审查结论

**approved_with_notes**

Layer 1全部通过。Layer 2语义审查发现1个MEDIUM问题（Sprint分卷status字段不一致）和3个LOW问题（职责重叠描述、命名记录、测试文件缺失）。无CRITICAL或HIGH级别问题。MEDIUM问题为元数据状态同步问题，不影响开发计划的可执行性和正确性。开发计划整体质量良好，47个任务卡完整覆盖PRD全部65个AC，依赖关系合理，TDD验收标准充分。
