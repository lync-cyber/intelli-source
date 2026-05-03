---
id: "code-review-T-058-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-058"]
---

# CODE-REVIEW T-058 — 上下文压缩增强 (r1)

Layer 1 delegated to hook（`.claude/settings.json` 中 `Edit` matcher + `lint_format` hook 已配置，编码阶段实时修复；orchestrator 另行验证 ruff check + format 全部通过）。

Layer 2 必跑（task_kind=feature，AC 数=7 > CODE_REVIEW_L2_SKIP_LIGHT_MAX_AC=2）。

---

## 审查范围

| 文件 | 行数 |
|------|------|
| `src/intellisource/agent/compaction.py` | 204 |
| `src/intellisource/llm/prompts/compaction_summary.txt` | 27 |
| `tests/unit/agent/test_compaction.py` | 411 |

---

## 关键复核点结论

**A（mock 有效性）**: `_make_gateway` 的 `estimate_tokens` 使用 `len(text) // 4` 模拟 token 计数，属于简化近似而非生产精度，但已足以验证逻辑分支。mock 行为与被测逻辑的期望一致，非无效 mock。

**B（< 3 条 tool 消息边界）**: `_prune_old_tool_messages` 在 `tool_indices` 长度 < 3 时，`tool_indices[-3:]` 自然退化为全集，所有 tool 消息均进入 `protected_indices`，逻辑正确。但此场景无专项测试（见 R-001）。

**C（阈值数值断言）**: `test_needs_compaction_uses_min_of_both_limits` 内联注释说明了计算过程（100 chars // 4 = 25 > 10），断言为布尔结果而非阈值数值本身；`test_result_fits_within_60_percent_of_context_window` 断言 `total_tokens <= context_window * 0.6`（见 R-003）。

**D（签名变更调用方影响）**: `grep compact_messages` 在 `src/` 下仅有 `compaction.py` 自身；在 `tests/` 下仅有 `test_compaction.py`。签名变更（旧 `(messages, gateway, max_tokens)` → 新 `(messages, gateway, profile, context_token_budget, model)`）无存量调用方，无破坏性影响。

---

## 问题列表

### [R-001] MEDIUM: AC-T058-3 缺少 "tool 消息数 < 3" 边界测试

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `test_last_three_tool_messages_protected` 和 `test_old_tool_messages_are_pruned` 均使用恰好 5 条 tool 消息（2 旧 + 3 新）测试。当消息列表中 tool 消息总数少于 3 条（例如只有 1 条或 2 条）时，`_prune_old_tool_messages` 应保留全部 tool 消息；此路径无专项测试用例覆盖。代码逻辑本身正确（Python 切片 `[-3:]` 在元素数不足时自然取全集），但缺乏对该边界的显式断言。
- **建议**: 在 `TestToolOutputPruning` 中补充：① 仅 1 条 tool 消息时 `_prune_tool_messages` 不删除任何消息；② 恰好 3 条 tool 消息时 3 条全部受保护。

---

### [R-002] MEDIUM: `test_tool_messages_pruned_before_user_messages` 断言过弱

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: 该测试声称验证 "tool 消息优先于 user/assistant 消息被裁剪"，但实际断言为：
  ```python
  assert ("user" in result_roles or "assistant" in result_roles or len(result) < len(messages))
  ```
  三个条件的 `or` 组合使得即使 tool 消息全部保留、user/assistant 消息被全部裁掉，断言也因第三分支 `len(result) < len(messages)` 而通过。断言不能有效区分"tool 先被裁"与"user 先被裁"这两种截然相反的结果。
- **建议**: 改为：在极端 token 压力（tiny budget）下，结果中所有旧 tool 消息内容缺失，且 user/assistant 消息至少有一条存在；或直接通过 `_prune_tool_messages` 白盒测试该排序性质（已有其他测试补充，可删除此重复覆盖）。

---

### [R-003] MEDIUM: `_build_summary_prompt` 向 PromptBuilder 注入无意义静态占位符

- **category**: structure
- **root_cause**: self-caused
- **描述**: `_build_summary_prompt` 将模板中的 `{goal_section}`、`{context_section}` 等五个占位符均替换为静态字符串 `"[Summarize from conversation]"`。经实际渲染验证，LLM 收到的 prompt 中这五段均为该静态文本，而非对话内容摘要或空白供 LLM 填充。`compaction_summary.txt` 的设计意图是让 LLM 依据 `{conversation_history}` 自行产出各段，因此这五个 `add_context` 调用制造了混乱的语义（"请填写这里" + 已填写了无意义占位符）。在当前实现下，LLM 最终仍能工作（末尾指令足够明确），但模板使用方式不符合 `PromptBuilder` 的设计语义（`add_context` 应提供实际语境内容）。
- **建议**: 去掉这五条 `add_context` 调用，将模板中对应占位符改为非变量格式（如直接写 `## Goal` 后留空，或移除这五行），让 `{conversation_history}` 承载全部输入。

---

### [R-004] MEDIUM: `compact_messages` 后置路径中 `needs_compaction` 条件冗余遍历

- **category**: performance
- **root_cause**: self-caused
- **描述**: `compact_messages` 内部调用路径为：`needs_compaction` → `_total_tokens`（O(n) 完整遍历）→ 若触发则进入 LLM 路径，再次对 `pruned` 列表逐条调用 `estimate_tokens`（另一次 O(n) 遍历）。在高频调用场景（每轮对话末尾触发）中，这意味着 token 估算被执行两次：一次用于阈值判断，一次用于 recent-message 选择。当前实现不缓存 `_total_tokens` 的中间结果。此问题在现有测试规模下不显著，但对长对话（messages 较多时）有可见开销。
- **建议**: 在 `compact_messages` 中缓存 `_total_tokens` 的返回值并传给 `needs_compaction`（或直接内联），避免对同一 `messages` 列表重复估算。

---

### [R-005] LOW: `test_compaction_summary_txt_has_five_sections` 仅验证小写关键词存在，不验证占位符格式

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: 该测试检查 `"goal"`、`"context"` 等关键词出现在模板文件中（大小写不敏感），但未验证占位符格式 `{goal_section}` 是否存在。若模板被修改为去掉 `{}` 变量语法，此测试仍会通过，而实际的 `format_map` 替换会静默失效。
- **建议**: 补充对 `{goal_section}` 等完整占位符格式的存在性断言（或改为验证 `compaction_summary.txt` 中确实出现 `{` 字符）。

---

### [R-006] LOW: `except Exception` 捕获粒度过宽，与 arch §5.3 分类框架不对齐

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `compact_messages` 中捕获 LLM 调用失败的代码为：
  ```python
  except Exception as exc:
      logger.warning("LLM summarization failed, using truncation fallback: %s", exc)
      return _truncation_fallback(...)
  ```
  arch §5.3 定义了 `LLMError` 及 `RECOVERABLE_DEGRADED` 类别，降级到截断策略对应此分类的标准处理路径。当前使用裸 `Exception` 会遮蔽非 LLM 故障（如 `PromptBuilder` 初始化失败的 `FileNotFoundError`、`gateway.estimate_tokens` 中的 `TypeError` 等），这些不应静默 fallback 到截断。
- **建议**: 改为捕获 `LLMError`（或更具体的 `LLMGateway` 异常），其余异常重新抛出；或至少排除 `KeyboardInterrupt`、`SystemExit`、`BaseException` 子类。

---

## AC 覆盖汇总

| AC | 描述 | 覆盖状态 |
|----|------|---------|
| AC-T058-1 | token 计数保留策略 | 已覆盖（TestTokenBasedRetention × 2） |
| AC-T058-2 | compaction_summary.txt 五段模板 | 已覆盖（TestStructuredSummaryTemplate × 3） |
| AC-T058-3 | tool 消息优先裁剪 + 保护最近 3 条 | 已覆盖（TestToolOutputPruning × 3），边界缺失（见 R-001） |
| AC-T058-4 | 自动触发阈值 min(context_window×0.8, budget) | 已覆盖（TestAutoTriggerThreshold × 4） |
| AC-T058-5 | 压缩后 token ≤ context_window × 0.6 | 已覆盖（TestPostCompactionTokenBudget × 1） |
| AC-T058-6 | LLM 失败 fallback 到 truncation | 已覆盖（TestFallbackToTruncation × 2） |
| AC-T058-7 | mypy --strict 零错误 | 已验证（orchestrator 报告） |

---

## 结构与约定

- **命名**: 全文遵循 arch §7.1（snake_case 函数/变量、UPPER_SNAKE_CASE 常量 `_PROTECTED_TOOL_COUNT`、`_DEFAULT_CONTEXT_TOKEN_BUDGET`）。私有函数以 `_` 前缀标注，符合约定。
- **类型标注**: 完整（`list[dict[str, Any]]`、`ModelProfile`、`-> bool`、`-> list[...]`），mypy strict 通过。
- **模块职责**: `compaction.py` 职责单一，仅包含压缩逻辑；`needs_compaction` 公开接口与 `compact_messages` 分离合理，允许调用方独立检查阈值。
- **docstring**: 所有公开函数及关键私有函数均有完整 Args/Returns，符合 §7.2 规范；无"之前/used to"等设计阶段残留叙述。
- **安全性（security）**: `_build_summary_prompt` 通过 `format_map` 将 `conversation_history`（用户消息内容）注入模板。实测验证：未知占位符（`{unknown_key}`）在 `format_map` 中不触发 `KeyError`（Python `str.format_map` 按 mapping 查找，缺失 key 保留原始 `{unknown_key}` 字面量）；因此用户消息中的任意 `{...}` 语法不会引发异常或触发非预期模板替换。风险已通过实际 Python 行为验证为低风险。

---

## 三态判定

无 CRITICAL、无 HIGH；存在 4 条 MEDIUM（R-001 ~ R-004）和 2 条 LOW（R-005 ~ R-006）。

**verdict: approved_with_notes**
