---
id: "review-arch-intellisource-v1-r3"
doc_type: review
author: reviewer
status: approved
deps: ["arch-intellisource-v1"]
---
# REVIEW: arch-intellisource-v1 (r3)
<!-- date: 2026-04-03 | reviewer: reviewer | scope: incremental-change -->
<!-- focus: 多轮对话上下文压缩设计改进 -->
<!-- reviewed-files: arch-intellisource-v1-data.md, arch-intellisource-v1-modules.md, arch-intellisource-v1.md -->
<!-- upstream: prd-intellisource-v1#§2.F-011 (AC-053), dev-plan-intellisource-v1-s5#T-039 -->
<!-- layer1: skipped (incremental review, not full doc check) -->

## 审查范围

本次审查针对"多轮对话上下文压缩"设计改进的增量变更，涉及:

1. E-011 ChatSession 数据模型变更（context 字段结构化）
2. M-008 模块新增 ContextCompressor 组件
3. 主卷 §5.1 对话配置表、§5.3 降级映射表、§6 目录结构更新

## 问题列表

### [R-001] HIGH: E-007 LLMCallLog.call_type 枚举未包含 "context_compress"

- **category**: consistency
- **root_cause**: self-caused
- **描述**: E-007 LLMCallLog 的 `call_type` 字段 CHECK 约束列出的枚举值为 `extract/dedup/cluster/summarize/tag/sentiment/search/optimize`，不包含 `context_compress`。然而 dev-plan T-039 AC-T039-9 明确要求"压缩调用记录到 LLMCallLog（call_type='context_compress'）"。数据模型与下游开发计划之间存在不一致，开发时插入 call_type='context_compress' 的记录将违反 CHECK 约束。
- **建议**: 在 E-007 的 `call_type` CHECK 枚举中追加 `context_compress`。

### [R-002] MEDIUM: M-009 存储模块缺少 ChatSession 数据访问层

- **category**: completeness
- **root_cause**: self-caused
- **描述**: M-009 存储与检索模块的内部关键组件列表中有 SourceRepository、ContentRepository、TaskRepository、PushRepository 等，但未列出 ChatSession 相关的 Repository。同时 §6 目录结构的 `storage/repositories/` 下也未包含 `session.py` 或 `chat_session.py`。E-011 ChatSession 实体的 CRUD 操作（创建会话、更新 context、按超时清理）需要数据访问层支持。
- **建议**: 在 M-009 内部关键组件中补充 `ChatSessionRepository`，并在 §6 目录结构的 `storage/repositories/` 下新增 `session.py`。

### [R-003] MEDIUM: Context Schema 中 token_count 计数方式未明确

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: E-011 Context Schema 定义了 `summary.token_count`、`recent_turns[].token_count` 和 `total_token_count` 三个 token 计数字段，但未说明 token 计数使用哪种 tokenizer（如 tiktoken cl100k_base、模型原生 tokenizer 等）。不同 tokenizer 对同一文本的 token 计数差异可达 10-20%，当 compress_model 与主模型不同时，token 预算管理可能产生偏差。
- **建议**: 在 Context Schema 或 §5.1 对话配置表中说明 token 计数统一使用 `LLMGateway.estimate_tokens()` 方法（T-039 实现提示中已提及），并标注该方法的 tokenizer 选择策略。

### [R-004] MEDIUM: ER 关系图未包含 ChatSession 实体

- **category**: completeness
- **root_cause**: self-caused
- **描述**: §4.1 实体关系 Mermaid ER 图中列出了 Source、CollectTask、RawContent 等实体的关系，但 ChatSession (E-011) 未出现在关系图中。虽然 ChatSession 是相对独立的实体（不与其他表存在 FK 关系），但作为完整的实体关系全景图应予以体现。
- **建议**: 在 ER 图中补充 ChatSession 实体（可标注为独立实体，无外键关联）。

### [R-005] LOW: Context Schema 中 recent_turns 数组的 role 枚举缺少 "system"

- **category**: feasibility
- **root_cause**: self-caused
- **描述**: recent_turns 中 role 字段仅允许 `user|assistant`。如果未来需要在上下文中注入系统级提示（如检索结果、搜索上下文摘要），缺少 "system" 角色可能需要重新调整 schema。当前设计通过 summary 字段间接承担了部分系统上下文的职责，设计是合理的，但建议考虑预留。
- **建议**: 当前设计可接受。如需预留扩展性，可在 role 枚举中增加 `system`，或在文档中注明"system 级上下文通过 summary 字段承载，不进入 recent_turns"。

### [R-006] LOW: §5.1 对话配置表缺少 compress_model 的空值行为说明位置不一致

- **category**: convention
- **root_cause**: self-caused
- **描述**: `compress_model` 配置项的默认值列为 `--`（表示为空），说明列写了"为空则使用默认模型"。但"默认模型"具体指什么（LLMGateway 的主模型? 还是 litellm 的默认模型?）未在配置表或 M-005 中明确定义。
- **建议**: 将说明调整为"为空则使用 LLMGateway 配置的主模型"或类似明确表述，与 M-005 LLMGateway 的模型配置关联。

## 审查结论

**判定: needs_revision**

存在 1 个 HIGH 级别问题 (R-001: E-007 call_type 枚举遗漏 context_compress)，该问题会导致开发阶段数据库约束冲突，必须在进入开发前修复。

MEDIUM 问题 3 个 (R-002, R-003, R-004)，建议一并修复以保证文档完整性和清晰度。LOW 问题 2 个 (R-005, R-006)，可选择性处理。
