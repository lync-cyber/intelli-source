# REVIEW: arch-intellisource-v1 (r3)
<!-- date: 2026-04-03 | reviewer: reviewer | doc_id: arch-intellisource-v1 -->
<!-- scope: amendment review — M-001 AppSettings, M-008 compress策略, E-011 context结构, §5 配置引用 -->
<!-- upstream: prd-intellisource-v1 (approved), AC-066, AC-053 -->
<!-- previous: REVIEW-arch-intellisource-v1-r2 (approved) -->
<!-- review_type: amendment -->

## 审查背景

本次为 amendment 审查（用户发起的变更修订），审查范围限定于以下修订内容:

1. M-001 新增 AppSettings 模型及配置分组（chat/llm/search/pagination/embedding）
2. M-008 ChatSessionManager 支持 truncate/compress 两种策略，新增 ContextCompressor 组件和 M-001 依赖
3. E-011 context 字段从简单数组改为 `{summary, messages}` 结构
4. §5 硬编码值改为引用 M-001 AppSettings

未修改的内容不在本次审查范围内。

## Layer 1 结果

- **主卷** (arch-intellisource-v1.md): PASS
- **模块分卷** (arch-intellisource-v1-modules.md): PASS
- **数据分卷** (arch-intellisource-v1-data.md): PASS

## Layer 2 审查结果

### [R-001] MEDIUM: M-005 CircuitBreaker 描述仍硬编码熔断参数值

- **category**: consistency
- **root_cause**: self-caused
- **描述**: M-005 内部组件 `CircuitBreaker` 描述为"连续失败 5 次触发，60s 恢复探测"，仍使用硬编码数值。而 §5.3 熔断机制已修订为引用 `M-001 AppSettings.llm.circuit_breaker_threshold`（默认 5 次）和 `circuit_breaker_cooldown`（默认 60s）。M-001 AppSettings.llm 分组也已定义这两个配置项。M-005 作为熔断器的实现模块，其描述应与 §5.3 保持一致，引用 M-001 配置而非硬编码。
- **建议**: 将 M-005 CircuitBreaker 描述修改为"熔断器实现（AC-029），连续失败次数达到 M-001 AppSettings.llm.circuit_breaker_threshold（默认 5）触发，冷却时间由 circuit_breaker_cooldown 配置（默认 60s）"。

### [R-002] MEDIUM: compress 模式 LLM 调用失败时缺少降级策略

- **category**: completeness
- **root_cause**: self-caused
- **描述**: M-008 ContextCompressor 调用 M-005 LLM 网关对历史对话进行语义压缩。但未说明当 LLM 调用失败（网络异常、熔断触发、配额耗尽等）时的降级行为。系统其他 LLM 依赖组件（M-004 各处理器）均有明确的降级映射（见 §5.3 降级策略表），而 compress 模式的压缩调用缺少对应的降级方案。这可能导致 compress 模式下 LLM 不可用时会话上下文管理行为不确定。
- **建议**: 在 M-008 ContextCompressor 或 ChatSessionManager 描述中补充降级策略，例如: "LLM 压缩调用失败时，降级为 truncate 模式（丢弃最早对话，保留最近 max_rounds 轮）"。同时建议在 §5.3 降级映射表中增加对应行。

### [R-003] LOW: E-004 ASSUMPTION 中配置项名称与 M-001 定义不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: E-004 embedding 字段的 [ASSUMPTION] 标注中提及"通过 M-001 配置管理模块的 embedding_dimension 配置项管理"，而 M-001 AppSettings.embedding 分组中定义的配置项名为 `dimension`（非 `embedding_dimension`）。完整引用路径应为 `AppSettings.embedding.dimension`。虽然语义可理解，但与 M-001 的实际定义不一致，可能导致开发者在实现时产生混淆。
- **建议**: 将 E-004 中的 `embedding_dimension 配置项` 修改为 `AppSettings.embedding.dimension 配置项`，保持与 M-001 定义的一致性。

### [R-004] LOW: ContextCompressor "压缩 prompt 模板可配置" 未在 M-001 AppSettings 中体现

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: M-008 ContextCompressor 描述中提到"压缩 prompt 模板可配置"，但 M-001 AppSettings.chat 配置分组中未包含 prompt 模板相关配置项。目前不清楚该配置是通过 AppSettings 管理、通过独立配置文件管理，还是仅为未来预留的扩展点。
- **建议**: 明确 prompt 模板的配置方式。如果通过 AppSettings 管理，在 chat 分组中新增配置项（如 `compress_prompt_template`）；如果通过独立文件管理，在 ContextCompressor 描述中说明文件路径规则；如果为未来预留，标注 [ASSUMPTION] 并说明 v1 使用内置默认模板。

## 审查摘要

| 等级 | 数量 |
|------|------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 2 |
| LOW | 2 |

**总体评价**: 本次 amendment 修订质量整体良好。M-001 AppSettings 配置分组设计合理，chat/llm/search/pagination/embedding 五个分组覆盖了 §5 中引用的所有运行参数。M-008 的 truncate/compress 双策略设计与 PRD AC-053 的要求一致，ContextCompressor 作为独立组件职责清晰。E-011 context 字段的 `{summary, messages}` 新结构与 M-008 的两种模式描述匹配，DEFAULT 值设计正确。§5 中硬编码值到 M-001 AppSettings 引用的替换完整且默认值一一对应。

存在 2 个 MEDIUM 级别问题: M-005 模块描述与 §5.3 的配置引用方式不一致（R-001），以及 compress 模式缺少 LLM 失败降级策略（R-002）。这两个问题不影响整体架构可行性，但应在后续修订中补齐以保证文档内部一致性和实现完备性。

## 结论

**approved_with_notes**
