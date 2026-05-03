---
id: "code-review-T-058-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-058"]
---

# CODE-REVIEW T-058 — 上下文压缩增强 (r2)

Layer 1 delegated to hook（orchestrator 已验证 ruff check + format 全部通过）。

增量 Layer 2：仅复核 r1 中 R-001~R-006 修订点 + 是否引入回归。

---

## 审查范围

| 文件 | 行数 |
|------|------|
| `src/intellisource/agent/compaction.py` | 208 |
| `src/intellisource/llm/prompts/compaction_summary.txt` | 27 |
| `tests/unit/agent/test_compaction.py` | 429 |

---

## R-001~R-006 闭环矩阵

| 编号 | 原问题 | 修订状态 | 说明 |
|------|--------|----------|------|
| R-001 | AC-T058-3 缺少 tool < 3 条边界测试 | 已闭环 | 新增 `test_single_tool_message_not_pruned`（含 `len(pruned) == len(messages)` 断言）和 `test_exactly_three_tool_messages_all_protected`（断言 3 条全在 + 长度不变），覆盖完整 |
| R-002 | `test_tool_messages_pruned_before_user_messages` 断言过弱 | 已闭环 | 改为白盒调用 `_prune_tool_messages`，明确断言 old tool 0/1 内容不在结果中、user query 和 assistant response 内容在结果中；三重 `or` 弱断言已消除 |
| R-003 | `_build_summary_prompt` 注入五个静态占位符 | 已闭环 | 代码侧仅保留 `add_context("conversation_history", ...)`；模板侧五段标题均为纯文本 `## Goal / Context / Changes / State / Next Steps`，无变量占位符，LLM 将依据 `{conversation_history}` 自行填写各段 |
| R-004 | `compact_messages` 重复 `_total_tokens` 遍历 | 已闭环 | `compact_messages` 顶部一次性调用 `_total_tokens`（第 166 行），内联阈值比较（第 167~169 行），不再调用 `needs_compaction`；`needs_compaction` 公开 API 完整保留，无破坏性变更 |
| R-005 | 五段测试未验证 `{conversation_history}` 占位符存在 | 已闭环 | `test_compaction_summary_txt_has_five_sections` 新增断言 `assert "{conversation_history}" in content`，明确验证模板中占位符存在 |
| R-006 | `except Exception` 捕获粒度过宽 | 部分闭环，见新增问题 N-001 | `_build_summary_prompt` 已移至 try 块外（`FileNotFoundError` 正常上抛）；try 块改为 `except LLMError` + `except RuntimeError` 双重捕获；但见下文 N-001 说明 |

---

## 新增问题

### [N-001] MEDIUM: `except RuntimeError` 无法覆盖 litellm 原生异常，生产路径存在未捕获漏洞

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: 修订后的 try 块捕获两种类型：`LLMError`（IntelliSource 内部异常基类）和 `RuntimeError`（Python 内置）。测试侧的 `_make_failing_gateway` 使用 `RuntimeError("LLM unavailable")` 模拟失败，因此测试全部通过。但在生产路径中，`LLMGateway.complete()` 在重试耗尽后会 re-raise litellm 原生异常（如 `RateLimitError`、`Timeout`、`APIConnectionError`、`InternalServerError`），这些异常的继承链为 `OpenAIError → Exception`，**既不继承 `LLMError`，也不继承 `RuntimeError`**。在此场景下，当前 try-except 无法捕获，异常将穿透 `compact_messages` 向上传播，而非执行 `_truncation_fallback`。降级语义丢失，调用方（agent 主循环）将感知到 `compact_messages` 抛出 litellm 异常，与接口契约（"LLM 失败时 fallback 到截断"）不符。
- **验证依据**: `uv run python -c "from litellm import exceptions; print([c.__name__ for c in exceptions.RateLimitError.__mro__])"` 输出 `['RateLimitError', 'RateLimitError', 'APIStatusError', 'APIError', 'OpenAIError', 'Exception', ...]`，无 `RuntimeError` 或 `LLMError`。
- **建议**: 将次级 catch 从 `except RuntimeError` 改为 `except Exception`（排除 `BaseException`，保留 `KeyboardInterrupt`/`SystemExit` 的正常传播），并在日志中加入 `exc.__class__.__name__` 以便区分 LLMError 与 litellm 原生异常；或在 `LLMGateway._try_fallback` 中统一将 litellm 异常包装为 `LLMError` 后 re-raise（从根本上消除异常类型不一致）。

---

## 回归检查

- `compact_messages` 内联阈值判断逻辑与 `needs_compaction` 共用相同公式 `min(int(profile.context_window * 0.8), context_token_budget)`，未引入数值偏差。
- `needs_compaction` 函数签名和行为不变，无存量调用方受影响（r1 §D 已确认）。
- 模板 `compaction_summary.txt` 去掉了 `{goal_section}` 等 5 个变量占位符，仅保留 `{conversation_history}`；`PromptBuilder.build()` 的 `format_map` 不再有多余 key，无意外 `KeyError` 风险。
- 测试文件 `_prune_tool_messages` 白盒 helper 定义在文件末尾（第 422~428 行），被 `TestToolOutputPruning` 中的白盒测试正确引用。

---

## AC 覆盖汇总（更新后）

| AC | 描述 | 覆盖状态 |
|----|------|---------|
| AC-T058-1 | token 计数保留策略 | 已覆盖 |
| AC-T058-2 | compaction_summary.txt 五段模板 | 已覆盖（含 `{conversation_history}` 占位符存在性断言） |
| AC-T058-3 | tool 消息优先裁剪 + 保护最近 3 条 | 已覆盖（含 <3 条边界，共 5 个测试） |
| AC-T058-4 | 自动触发阈值 min(context_window×0.8, budget) | 已覆盖 |
| AC-T058-5 | 压缩后 token ≤ context_window × 0.6 | 已覆盖 |
| AC-T058-6 | LLM 失败 fallback 到 truncation | 已覆盖（测试通过，但见 N-001：生产路径覆盖不完整） |
| AC-T058-7 | mypy --strict 零错误 | 已验证 |

---

## 三态判定

无 CRITICAL、无 HIGH；存在 1 条 MEDIUM（N-001）；R-001~R-006 全部闭环（R-006 部分改善）。

**verdict: approved_with_notes**
