---
id: "review-dev-plan-intellisource-v1-r4"
doc_type: review
author: reviewer
status: approved
deps: ["dev-plan-intellisource-v1"]
---
# REVIEW: dev-plan-intellisource-v1 (r4)
<!-- date: 2026-04-03 | reviewer: reviewer | doc_type: dev-plan -->
<!-- Layer 1: 跳过（增量变更审查） | Layer 2: 已执行 -->

## 审查范围

- 增量变更审查，聚焦"多轮对话上下文压缩"设计改进涉及的文件:
  - 主卷: docs/dev-plan/dev-plan-intellisource-v1.md (Sprint 规划表 T-039 行更新)
  - 分卷 s3: docs/dev-plan/dev-plan-intellisource-v1-s3.md (T-019 新增 AC-T019-5)
  - 分卷 s5: docs/dev-plan/dev-plan-intellisource-v1-s5.md (T-038 新增 AC-T038-5; T-039 重写)
- 上游依赖: arch-intellisource-v1 (approved), arch-intellisource-v1-data (approved), arch-intellisource-v1-modules (approved), prd-intellisource-v1 (approved)

## Layer 2 结果

### 完整性 (completeness)

T-039 的 10 条 AC 覆盖了三层压缩策略:

- **意图分离**: AC-T039-2 (context 结构化 JSONB 存储，assistant 消息分离 content/full_content) + AC-T038-5 (intent_summary 输出)
- **Token 预算滑动窗口**: AC-T039-3 (get_context_for_llm() 按 token 预算从最近轮次向前填充)
- **异步摘要压缩**: AC-T039-6 (should_compress 触发条件) + AC-T039-7 (compress_older_turns 压缩执行) + AC-T039-8 (异步执行)

会话生命周期管理: AC-T039-1 (创建/获取) + AC-T039-4 (超时清理) + AC-T039-5 (新会话创建)
可观测性: AC-T039-9 (压缩调用记录到 LLMCallLog)
向后兼容: AC-T039-10 (旧格式自动迁移)

覆盖完整，无明显遗漏。

### 一致性 (consistency)

**Sprint 规划表与任务卡一致性**: 主卷 T-039 行 (复杂度 L, 依赖 T-038/T-019, TDD测试点 AC-053/AC-T039) 与 s5 分卷任务卡一致。

**与 arch 上游一致性**:

- T-039 deliverables 与 arch#§6 目录结构完全匹配: `search/session.py`, `search/context_compressor.py`, `llm/prompts/context_compress.txt`
- T-039 AC 与 arch-modules#M-008 组件列表一致: ChatSessionManager, ContextCompressor 均已列出
- 配置参数引用 (`chat.context_token_budget`, `chat.session_timeout_hours`, `chat.compress_after_turns`, `chat.compress_model`) 与 arch#§5.1 对话配置表完全对应
- T-039 context_load 引用 `arch-intellisource-v1-data#§4.E-011（含 Context Schema）` 已验证存在且包含完整的 Context Schema 定义
- arch#§5.1 缓存策略中"对话上下文压缩"描述与 T-039 三层策略一致
- arch#§5.3 降级策略表中"上下文压缩"降级方案为"截断最旧轮次（保留最近 N 轮原文）"，T-039 的 get_context_for_llm() 截断最旧轮次行为与此一致

**T-019 依赖合理性**: T-019 在 Sprint 3, T-039 在 Sprint 5, Sprint 顺序保证依赖可满足。T-039 实现提示明确说明使用 `LLMGateway.estimate_tokens()` (AC-T019-5) 进行 token 计数，依赖链清晰。

**T-038 与 T-039 衔接**: T-038 AC-T038-5 定义 SearchSummarizer 输出 schema 包含 intent_summary 字段; T-039 实现提示说明"意图分离搭便车于 T-038 SearchSummarizer 的 intent_summary 输出"; T-039 AC-T039-2 定义 assistant 消息分离 content（意图摘要）与 full_content（完整回答）。数据流衔接清晰。

### 可行性 (feasibility)

T-039 复杂度从 M 调为 L 合理: AC 数量从隐含的 ~5 增至 10 条，deliverables 从 2 增至 5 个文件，涉及会话管理、压缩器、prompt 模板三个独立关注点，L 级别恰当。

所有 AC 均可直接编写测试:

- AC-T039-1~5: 标准 CRUD/生命周期测试
- AC-T039-6~7: 压缩触发条件和压缩执行结果可验证
- AC-T039-8: 可通过 mock asyncio.create_task 验证异步调用
- AC-T039-9: 可验证 LLMCallLog 记录存在
- AC-T039-10: 可构造旧格式数据验证迁移

### 规范性 (convention)

AC 编号格式统一: AC-T039-1 至 AC-T039-10，AC-T038-5，AC-T019-5，均符合 `AC-{task_id}-{N}` 规范。
文件路径命名符合 snake_case 约定。
context_load 引用格式符合 `{doc_id}#§{section}` 规范。

### 清晰度 (ambiguity)

AC 描述明确到可直接编写测试，无模糊表述。T-039 实现提示提供了充分的技术指引（意图分离搭便车机制、token 计数来源、异步压缩实现方式）。

## 问题列表

### [R-001] HIGH: 依赖图缺失 T-019 -> T-039 边

- **category**: consistency
- **root_cause**: self-caused
- **描述**: 主卷 §2 依赖图（mermaid）中仅有 `T-038 --> T-039` 边，缺失 `T-019 --> T-039` 边。但 Sprint 规划表 T-039 行明确标注依赖为 `T-038, T-019`。依赖图与 Sprint 表不一致，可能导致关键路径计算不准确和开发排期错误。
- **建议**: 在 mermaid 依赖图中添加 `T-019 --> T-039` 边。同时检查 §4 关键路径的次关键路径 `T-001 -> T-002 -> T-003 -> T-005 -> T-037 -> T-038 -> T-039 (权重 16)` 是否需要更新（因 T-039 现在还依赖 T-019，可能存在更长路径 T-001 -> ... -> T-019 -> T-039）。

### [R-002] MEDIUM: E-007 LLMCallLog.call_type 枚举缺少 "context_compress"

- **category**: consistency
- **root_cause**: upstream-caused
- **描述**: T-039 AC-T039-9 指定压缩调用记录到 LLMCallLog 时使用 `call_type="context_compress"`，但上游 arch-data#E-007 的 call_type 字段说明中枚举值为 `extract/dedup/cluster/summarize/tag/sentiment/search/optimize`，未包含 `context_compress`。虽然 VARCHAR(50) 类型不会在数据库层面阻止写入，但枚举说明不完整可能导致开发者对有效值产生困惑。
- **建议**: 此为上游 arch 文档问题，建议在后续 arch 修订时将 `context_compress` 添加到 E-007 call_type 枚举说明中。当前 dev-plan 中的定义本身是合理的，记录此差异供追踪。

### [R-003] LOW: T-039 AC-T039-3 中 max_recent_turns 配置未显式引用

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: arch#§5.1 对话配置表定义了 `max_recent_turns`（recent_turns 数组硬上限，默认 10），但 T-039 的 AC 中未显式引用此配置。AC-T039-3 描述"从最近轮次向前填充...超预算时截断最旧轮次"，虽然逻辑上 token 预算已隐式限制轮次数，但 max_recent_turns 作为硬上限的边界条件未在任何 AC 中体现。
- **建议**: 可在 AC-T039-3 或新增一条 AC 中补充: "recent_turns 数组长度不超过 `chat.max_recent_turns` 硬上限"。或在实现提示中注明此约束。低优先级，不影响核心功能。

## 审查结论

**needs_revision**

发现 1 个 HIGH 问题（依赖图与 Sprint 表不一致）。依赖图是开发排期和关键路径分析的基础，缺失的 T-019 -> T-039 边可能导致 Sprint 5 的任务调度出现阻塞。需修复 R-001 后重新审查。R-002 为上游文档问题（upstream-caused），记录供后续 arch 修订参考。R-003 为低优先级改进建议。
