# REVIEW: arch-intellisource-v1 (r4)
<!-- date: 2026-04-03 | reviewer: reviewer | doc_id: arch-intellisource-v1 -->
<!-- scope: amendment review — M-001 AppSettings, M-008 compress策略, E-011 context结构, §5 配置引用 -->
<!-- upstream: prd-intellisource-v1 (approved), AC-066, AC-053 -->
<!-- previous: REVIEW-arch-intellisource-v1-r3 (approved_with_notes) -->
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

### 审查维度 1: completeness（配置分组覆盖度 + compress 模式完整性）

M-001 AppSettings 定义了 5 个配置分组（chat/llm/search/pagination/embedding），逐一验证与 §5 引用的对应关系:

| §5 引用 | M-001 配置项 | 匹配 |
|---------|-------------|------|
| §5.1 LLM 缓存 TTL "默认 24h" | llm.result_cache_ttl: 86400 | 一致 |
| §5.1 检索缓存 TTL "默认 5min" | search.search_cache_ttl: 300 | 一致 |
| §5.1 默认分页 "默认 20 条" | pagination.default_page_size: 20 | 一致 |
| §5.1 最大分页 "默认 100 条" | pagination.max_page_size: 100 | 一致 |
| §5.3 熔断阈值 "默认 5 次" | llm.circuit_breaker_threshold: 5 | 一致 |
| §5.3 冷却时间 "默认 60s" | llm.circuit_breaker_cooldown: 60 | 一致 |

配置分组对 §5 引用的覆盖完整，默认值一一对应，无遗漏。

M-008 compress 模式流程: 对话轮数 > compress_threshold -> 调用 ContextCompressor -> M-005 LLM 网关生成摘要 -> 摘要存入 E-011 context.summary -> 保留最近 compress_threshold 轮原始对话。流程链路完整。

### 审查维度 2: consistency（跨文件一致性）

**E-011 context 结构与 M-008 描述的匹配**:

- E-011 DEFAULT: `{"summary": null, "messages": []}` -- 与 M-008 的 truncate 模式（仅使用 messages）和 compress 模式（summary + messages）描述一致
- E-011 说明 truncate 模式引用 `max_rounds`，compress 模式引用 `compress_threshold` -- 与 M-001 chat 分组配置项名称一致
- E-011 清理策略引用 `session_timeout_hours` -- 与 M-001 chat 分组配置项一致

**发现问题**:

### [R-001] MEDIUM: M-005 CircuitBreaker 组件描述仍硬编码熔断参数值

- **category**: consistency
- **root_cause**: self-caused
- **描述**: M-005 模块中 `CircuitBreaker` 组件描述为"连续失败 5 次触发，60s 恢复探测"，使用硬编码数值。而 §5.3 熔断机制已修订为引用 `M-001 AppSettings.llm.circuit_breaker_threshold`（默认 5 次）和 `circuit_breaker_cooldown`（默认 60s），M-001 llm 分组也已定义这两个配置项。M-005 作为熔断器的实现模块，其描述应与 §5.3 保持一致引用 M-001 配置，而非保留旧的硬编码描述。
- **建议**: 将 M-005 CircuitBreaker 描述修改为"熔断器实现（AC-029），连续失败次数达到 AppSettings.llm.circuit_breaker_threshold（默认 5）触发，冷却时间由 circuit_breaker_cooldown 配置（默认 60s）"。

### [R-002] MEDIUM: compress 模式 LLM 调用失败时缺少降级策略

- **category**: completeness
- **root_cause**: self-caused
- **描述**: M-008 ContextCompressor 调用 M-005 LLM 网关进行语义压缩，但未说明 LLM 调用失败时的降级行为。系统其他 LLM 依赖组件（M-004 各处理器）均在 §5.3 降级映射表中有明确的降级方案，而 ContextCompressor 的压缩调用缺少对应条目。这可能导致 compress 模式下 LLM 不可用时会话上下文管理行为不确定，影响用户多轮对话体验。
- **建议**: 在 M-008 ContextCompressor 描述中补充降级策略: "LLM 压缩调用失败时，降级为 truncate 模式（保留最近 max_rounds 轮原始对话，丢弃最早对话）"。同时在 §5.3 降级映射表中增加: "上下文压缩 | 降级为 truncate 模式"。

### 审查维度 3: feasibility（compress 模式技术可行性）

compress 模式设计在技术上可行:

- 触发时机明确: 对话轮数超过 compress_threshold 时触发，避免每次对话都调用 LLM
- 压缩粒度合理: 对早期对话生成摘要（限制 compress_max_tokens），保留最近 compress_threshold 轮原始对话
- LLM 调用路径清晰: 通过 M-005 LLM 网关调用，复用现有的重试/熔断基础设施
- 数据结构支持: E-011 context.summary 字段支持 null（truncate 模式）和 string（compress 模式），向后兼容

无 feasibility 问题。

### 审查维度 4: ambiguity（命名和默认值清晰度）

### [R-003] LOW: E-004 ASSUMPTION 中配置项名称与 M-001 实际定义不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: E-004 embedding 字段的 [ASSUMPTION] 标注中提及"维度值通过 M-001 配置管理模块的 embedding_dimension 配置项管理"，而 M-001 AppSettings.embedding 分组中定义的配置项名为 `dimension`。完整引用应为 `AppSettings.embedding.dimension`。E-005 centroid 也存在相同的 `embedding_dimension` 引用问题。
- **建议**: 将 E-004 和 E-005 中的 `embedding_dimension` 修改为 `AppSettings.embedding.dimension`，与 M-001 定义保持一致。

### [R-004] LOW: ContextCompressor "压缩 prompt 模板可配置" 未明确配置方式

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: M-008 ContextCompressor 描述中提到"压缩 prompt 模板可配置"，但 M-001 AppSettings.chat 配置分组中未包含 prompt 模板相关配置项。v1 是否使用内置默认模板、用户如何自定义模板，均未明确说明。
- **建议**: 在 ContextCompressor 描述中标注 [ASSUMPTION] 说明: "v1 使用内置默认压缩 prompt 模板，后续版本可扩展为通过配置文件自定义"。或在 M-001 chat 分组中新增 `compress_prompt_template` 配置项。

## 审查摘要

| 等级 | 数量 |
|------|------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 2 |
| LOW | 2 |

**总体评价**: 本次 amendment 修订质量良好。M-001 AppSettings 配置分组设计合理，5 个分组（chat/llm/search/pagination/embedding）完整覆盖了 §5 中所有需要可配置化的运行参数，默认值与 §5 引用一一对应。M-008 的 truncate/compress 双策略设计准确实现了 PRD AC-053 的要求，ContextCompressor 作为独立组件职责清晰、依赖明确。E-011 context 字段的 `{summary, messages}` 结构设计合理，DEFAULT 值正确支持两种模式，truncate 模式向后兼容（summary 为 null）。§5 中硬编码值到 M-001 AppSettings 引用的替换完整且准确。

2 个 MEDIUM 问题: M-005 CircuitBreaker 描述与 §5.3 配置引用方式不一致（R-001），compress 模式缺少 LLM 失败降级策略（R-002）。2 个 LOW 问题: E-004/E-005 配置项名称引用偏差（R-003），ContextCompressor prompt 模板配置方式不明确（R-004）。这些问题不影响整体架构可行性和正确性。

## 结论

**approved_with_notes**
