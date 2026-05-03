---
id: "code-review-T-058-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-058"]
---

# CODE-REVIEW T-058 — 上下文压缩增强 (r2)

Layer 1 delegated to hook（`.claude/settings.json` 中 `Edit` matcher + `lint_format` hook 已配置；orchestrator 已独立验证 ruff check + format clean、mypy --strict 零错误）。

增量 Layer 2：仅复核 r1 中 R-001~R-006 修订点 + 是否引入回归，不重做全量审查。

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
| R-001 | AC-T058-3 缺少 tool < 3 条边界测试 | 已闭环 | 新增 `test_single_tool_message_not_pruned`（断言内容保留 + `len(pruned) == len(messages)`）和 `test_exactly_three_tool_messages_all_protected`（断言 3 条全在 + 长度不变），边界覆盖完整 |
| R-002 | `test_tool_messages_pruned_before_user_messages` 断言过弱 | 已闭环 | 改为白盒调用 `_prune_tool_messages`，明确断言 old tool 0/1 内容不在结果中、user query 和 assistant response 在结果中；三重 `or` 弱断言已消除 |
| R-003 | `_build_summary_prompt` 注入五个静态占位符 | 已闭环 | 代码侧仅保留 `add_context("conversation_history", ...)`；模板侧五段标题均为纯文本（`## Goal / Context / Changes / State / Next Steps`），无冗余变量占位符；LLM 依据 `{conversation_history}` 自行填写各段，语义清晰 |
| R-004 | `compact_messages` 重复 `_total_tokens` 遍历 | 已闭环 | `compact_messages` 顶部第 166 行一次性调用 `_total_tokens` 并缓存结果，第 167~169 行内联阈值比较，不再调用 `needs_compaction`；`needs_compaction` 公开 API 完整保留，调用方契约无破坏性变更 |
| R-005 | 五段测试未验证 `{conversation_history}` 占位符存在 | 已闭环 | `test_compaction_summary_txt_has_five_sections` 新增 `assert "{conversation_history}" in content`，显式验证占位符存在性 |
| R-006 | `except Exception` 捕获粒度过宽 | 部分改善，遗留 MEDIUM（见 N-001） | `_build_summary_prompt` 已移至 try 块外（`FileNotFoundError` 可正常上抛）；try 块改为 `except LLMError` + `except RuntimeError` 双重捕获；但真实生产路径中 litellm 原生异常两者均无法捕获，见 N-001 |

---

## 新增问题

### [N-001] MEDIUM: `except RuntimeError` 无法覆盖 litellm 原生异常，生产降级路径存在漏洞

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: 修订后的 try 块捕获 `LLMError`（IntelliSource 内部异常）和 `RuntimeError`（Python 内置）。测试侧 `_make_failing_gateway` 使用 `RuntimeError("LLM unavailable")` 模拟失败，因此 19 个测试全部通过。但在生产路径中，`LLMGateway.complete()` 重试耗尽后会 re-raise litellm 原生异常（如 `RateLimitError`、`APIConnectionError`、`ServiceUnavailableError`、`InternalServerError`），其继承链为 `OpenAIError → Exception`，**既不继承 `LLMError`，也不继承 `RuntimeError`**。验证：`uv run python -c "import litellm; print([c.__name__ for c in litellm.RateLimitError.__mro__])"` 输出 `['RateLimitError', ..., 'APIStatusError', 'APIError', 'OpenAIError', 'Exception', ...]`，无 `RuntimeError` 或 `LLMError`。此外，`compact_messages` 调用 `gateway.complete(prompt)` 时不传 `task_type`，导致 `_try_fallback` 中 `task_type is None` → 直接 re-raise 原始 litellm 异常，而非转换为 `LLMError`。在此条件下，当前 except 链全部跳过，异常向上穿透，`_truncation_fallback` 不会执行，接口契约（"LLM 失败时降级到截断"）在生产环境无法兑现。
- **建议**: 将次级 catch 从 `except RuntimeError` 改为 `except Exception`（限于 `Exception`，保留 `KeyboardInterrupt`/`SystemExit` 的正常传播），在日志中加入 `type(exc).__name__` 以区分错误来源；或在 `LLMGateway._try_fallback` 中统一将 litellm 异常包装为 `LLMError` 再 re-raise，从根本上消除异常类型不一致。

---

## 回归检查

- `compact_messages` 内联阈值公式 `min(int(profile.context_window * 0.8), context_token_budget)` 与 `needs_compaction` 一致，无数值偏差。
- `needs_compaction` 函数签名和行为完整保留，r1 §D 已确认无存量调用方，无破坏性变更。
- 模板 `compaction_summary.txt` 去除了五个冗余变量占位符，仅保留 `{conversation_history}`；`PromptBuilder.build()` 的 `format_map` 不再有多余 key，无 `KeyError` 风险。
- 测试文件末尾 `_prune_tool_messages` 白盒 helper（第 422~428 行）被 `TestToolOutputPruning` 正确引用，无循环导入或作用域问题。

---

## AC 覆盖汇总（r2 更新）

| AC | 描述 | 覆盖状态 |
|----|------|---------|
| AC-T058-1 | token 计数保留策略（estimate_tokens） | 已覆盖 |
| AC-T058-2 | compaction_summary.txt 五段模板 | 已覆盖（含 `{conversation_history}` 占位符存在性断言） |
| AC-T058-3 | tool 消息优先裁剪 + 保护最近 3 条 | 已覆盖（含 <3 条边界，共 5 个测试） |
| AC-T058-4 | 自动触发阈值 min(context_window×0.8, budget) | 已覆盖 |
| AC-T058-5 | 压缩后 token ≤ context_window × 0.6 | 已覆盖 |
| AC-T058-6 | LLM 失败 fallback 到 truncation | 测试通过（RuntimeError 路径），生产路径覆盖不完整（见 N-001） |
| AC-T058-7 | mypy --strict 零错误 | 已验证（orchestrator 报告） |

---

## 三态判定

无 CRITICAL、无 HIGH；存在 1 条 MEDIUM（N-001）；R-001~R-006 全部闭环（R-006 部分改善但遗留 MEDIUM）。

**verdict: approved_with_notes**
