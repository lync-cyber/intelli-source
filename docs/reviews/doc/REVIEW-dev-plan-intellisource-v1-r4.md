# REVIEW: dev-plan-intellisource-v1 (r4) — Amendment 审查
<!-- date: 2026-04-03 | reviewer: reviewer | doc_type: dev-plan -->
<!-- scope: amendment — T-008 AppSettings 新增, T-039 truncate/compress 双策略重写, 主卷 Sprint 5 表更新 -->
<!-- Layer 1: 跳过（仅审查修订增量） | Layer 2: 已执行 -->

## 审查范围

本次审查为 amendment（用户发起的变更修订），仅审查修订部分:

- T-008 (s1 分卷): 新增 AppSettings 相关验收标准和交付物
- T-039 (s5 分卷): 重写为支持 truncate/compress 双策略，复杂度 M->L
- 主卷 Sprint 5 表: T-039 行更新

上游参考:

- prd#§2.F-001: AC-066（统一配置管理）
- prd#§2.F-011: AC-053（可配置上下文策略）
- arch#§2.M-001: AppSettings 定义（chat/llm/search/pagination/embedding 分组）
- arch#§2.M-008: ChatSessionManager + ContextCompressor
- arch-data#§4.E-011: ChatSession 实体（context JSONB 结构）

## Layer 2 审查结果

### 完整性 (completeness)

**T-008 AppSettings 覆盖验证**: AC-T008-4 至 AC-T008-8 逐一覆盖了 arch#§2.M-001 AppSettings 的全部 5 个配置分组（chat/llm/search/pagination/embedding），每个字段名和默认值与架构定义完全一致。AC-066 映射条目正确描述了 AppSettings 的整体职责。覆盖完整，无遗漏。

**T-039 双策略覆盖验证**: AC-T039-1~5 覆盖 ChatSessionManager 基础能力，AC-T039-6~8 覆盖 compress 模式的完整流程（触发条件/压缩行为/降级处理）。与 arch#§2.M-008 的 ChatSessionManager 和 ContextCompressor 定义完全对齐。降级处理（AC-T039-8）对应 arch 中 compress 模式的容错设计。覆盖完整。

### 一致性 (consistency)

**T-008 与 arch#§2.M-001 一致性**: 所有字段名、类型、默认值与 arch 定义一致。环境变量覆盖前缀 `IS_` 与 arch 定义一致。无矛盾。

**T-039 与 arch#§2.M-008 一致性**: truncate 模式行为（保留最近 N 轮，N=max_rounds）与 arch 一致；compress 模式行为（超过 compress_threshold 时调用 LLM 生成摘要存入 summary 字段）与 arch 一致；context JSONB 结构 `{summary: string|null, messages: [...]}` 与 arch-data#§4.E-011 定义一致。

**主卷 Sprint 5 表与 s5 分卷一致性**: T-039 行复杂度已更新为 L，TDD 测试点已更新为 `AC-053, AC-066`，与分卷任务卡一致。

**主卷 Sprint 1 表与 s1 分卷一致性问题**: 见 R-001。

**T-008 与 T-046 交付物冲突**: 见 R-002。

### 可行性 (feasibility)

**T-039 复杂度 M->L 合理性**: 原 T-039 仅实现 truncate 模式（固定 5 轮截断），复杂度 M。修订后新增 compress 模式（LLM 调用 + 摘要管理 + 降级处理）和 ContextCompressor 组件，复杂度提升为 L 合理。新增的交付物（compressor.py + test_compressor.py）与职责扩展匹配。

**T-008 复杂度维持 M**: T-008 新增 AppSettings 模型定义，但 pydantic-settings 模型定义属于声明式代码（字段+默认值+类型），工作量增加有限，维持 M 合理。

### 规范性 (convention)

**AC 编号**: T-008 新增 AC-T008-4~8，与已有 AC-T008-1~3 连续。T-039 新增 AC-T039-6~8，与已有 AC-T039-1~5 连续。编号规范无问题。

**任务卡格式**: 新增内容的格式（tdd_acceptance 缩进、deliverables 格式、context_load 引用格式）与已有任务卡风格一致。

## 问题列表

### [R-001] MEDIUM: 主卷 Sprint 1 表 T-008 行 TDD 测试点未包含 AC-066

- **category**: consistency
- **root_cause**: self-caused
- **描述**: s1 分卷 T-008 任务卡新增了 `AC-066 映射` 验收标准，但主卷 Sprint 1 表中 T-008 行的 TDD 测试点仍为 `AC-001, AC-003`，未同步添加 AC-066。作为对比，主卷 Sprint 5 表中 T-039 行已正确更新为 `AC-053, AC-066`。主卷与分卷之间存在不一致。
- **建议**: 将主卷 Sprint 1 表 T-008 行的 TDD 测试点更新为 `AC-001, AC-003, AC-066`。

### [R-002] LOW: T-008 与 T-046 同时声明 config/settings.example.toml 交付物

- **category**: consistency
- **root_cause**: self-caused
- **描述**: T-008 (Sprint 1) 新增交付物 `config/settings.example.toml -- 系统运行参数配置示例文件`，而 T-046 (Sprint 5) 原有交付物 `config/settings.example.toml -- 系统配置示例`。两个任务声明了同一文件路径，职责归属不明确。从逻辑上看，T-008 定义 AppSettings 模型时创建初始示例文件更合理，T-046 负责 Docker 部署时应引用而非重复声明。
- **建议**: 保留 T-008 的 settings.example.toml 交付物声明（与 AppSettings 模型定义同步产出），将 T-046 中的该条目移除或改为引用标注（如"复用 T-008 产出的 config/settings.example.toml"）。

## 审查结论

**approved_with_notes**

本次 amendment 修订质量整体良好。T-008 的 AppSettings 验收标准完整覆盖了 arch#§2.M-001 的全部配置分组；T-039 重写后的双策略设计与 arch#§2.M-008 完全对齐，复杂度调整合理，降级处理考虑周全。无 CRITICAL 或 HIGH 级别问题。存在 1 个 MEDIUM 问题（主卷 Sprint 1 表 T-008 TDD 测试点遗漏 AC-066）和 1 个 LOW 问题（交付物重复声明），建议修复以保持文档内部一致性。
