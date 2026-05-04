---
id: "code-review-t-062-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-062"]
---

# CODE-REVIEW T-062 (r2)

> 跟进 r1 三个 LOW notes 的修复结果。Layer 1 delegated to hook；Layer 2 增量复查（仅审 r1 → r2 之间的 diff）。

## 审查范围（增量）

- src/intellisource/llm/prompts/__init__.py — 新增 `_validate_path_component` 校验 + 在 `_read_template` 入口对 name/style 调用
- tests/unit/llm/test_prompt_builder.py — 新增 `TestPromptPathComponentValidation`（3 个参数化测试）+ 强化 `test_load_prompt_style_loads_variant_content` 断言
- docs/dev-plan/dev-plan-intellisource-v1-s7.md §T-062 deliverables block — 同步实际产物名 + 全部勾选 [x]

## r1 → r2 闭环验证

### R-001 closed (consistency)
- dev-plan-s7.md §T-062 deliverables 已加 Option A 说明，`summarization.*` 字面改为 `summarizer.structured.txt`，所有条目 [x] 标记，并补录 `prompt_builder.py` 实际改动条目。

### R-002 closed (security)
- `_validate_path_component(value, field)` 拒绝空串 / 含 `/` / `\` / `..` / `\0` 的输入；`_read_template` 在 name 必校验、style 非空时校验。
- 新增 `TestPromptPathComponentValidation`：6 个 name 攻击向量 + 5 个 style 攻击向量 + PromptBuilder 透传校验，全部通过 ValueError 断言。
- 校验位于 `_read_template` 入口而非 `load_prompt`，确保 PromptBuilder 直接调用 `_read_template` 时也受保护，并避免 lru_cache 缓存非法值。

### R-003 closed (test-quality)
- `test_load_prompt_style_loads_variant_content` 现读取 `extraction.structured.txt` 字面内容，做 `format_map` 后与 `load_prompt` 结果 `==` 对比；保留对比 default 的 sanity assert。

## 验证状态

- 全量回归: 1766 PASSED（r1 时 1754 → r2 +12 新测试，无任何既有测试退化）
- 目标文件: 55 PASSED
- mypy --strict src/: clean (102 files)
- ruff check + format --check: clean (15 files)

## 问题列表

无。r1 三个 LOW 全部闭环；本轮无新增问题。

## 判定

- 无 CRITICAL / HIGH / MEDIUM / LOW
- **verdict: approved**

T-062 任务卡可标 done；进入 T-063 / Sprint-7 末尾 retrospective 流程。
