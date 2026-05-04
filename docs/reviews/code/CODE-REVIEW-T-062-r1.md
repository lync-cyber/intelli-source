---
id: "code-review-t-062-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-062"]
---

# CODE-REVIEW T-062 (r1)

> Layer 1 delegated to hook (`.claude/settings.json` matcher=Edit, command=`python -m cataforge.hook.scripts.lint_format`)；最终 ruff check + format clean，mypy --strict src/ no issues across 102 files。

## 审查范围

- impl_files:
  - src/intellisource/llm/prompts/__init__.py (M)
  - src/intellisource/llm/prompt_builder.py (M)
  - src/intellisource/llm/prompts/extraction.structured.txt (A)
  - src/intellisource/llm/prompts/extraction.concise.txt (A)
  - src/intellisource/llm/prompts/summarizer.structured.txt (A)
- test_files:
  - tests/unit/llm/test_prompt_builder.py (M, +18 tests across TestPromptVariantNaming / TestLoadPromptVariantStyle / TestVariantFilesNonEmpty / TestPromptBuilderVariantStyle)
- 关联 commit: d355560 + 25b35c0 (state)

## 验证状态

- 全量回归: 1754 PASSED (43 in target file)
- mypy --strict src/: clean (102 files)
- ruff check + format --check: clean (15 files)
- AC 覆盖（implementer self-report 与本审查独立核验一致）:
  - AC-T062-1 ✅ `{name}.{style}.txt` 命名 (TestPromptVariantNaming)
  - AC-T062-2 ✅ 优先变体 + fallback (TestLoadPromptVariantStyle.test_load_prompt_style_fallback_when_variant_missing / TestPromptBuilderVariantStyle.test_prompt_builder_missing_variant_falls_back_to_base)
  - AC-T062-3 ✅ extraction + summarizer 的 structured 变体存在并非空 (TestVariantFilesNonEmpty)
  - AC-T062-4 ✅ extraction.concise 存在并非空
  - AC-T062-5 ✅ load_prompt 签名向后兼容（style 为关键字仅参数 `*, style=None`，不传时与原行为一致）
  - AC-T062-6 ✅ mypy --strict 零错误

## 问题列表

### [R-001] LOW: dev-plan deliverables 字面与实际文件名偏离未在任务卡 deliverables block 同步
- **category**: consistency
- **root_cause**: input-caused
- **描述**: dev-plan-s7.md 第 192-197 行 deliverables 仍写 `summarization.structured.txt`，实际产出为 `summarizer.structured.txt`（Option A 已在任务卡 status 行说明，但 deliverables 字面未改）。后续 sprint-review / retro 若按字面对账可能被误判为 deliverable 缺失。
- **建议**: 把 deliverables block 中的 `summarization.structured.txt` 改为 `summarizer.structured.txt`，或保留原文并加 `→ summarizer.structured.txt (Option A)` 注释；与 status 行已写的偏离说明保持单一事实来源。

### [R-002] LOW: variant 加载新增 style 入参扩展了路径组件输入面，复用既有 name 的未校验状态
- **category**: security
- **root_cause**: upstream-caused
- **描述**: `_read_template(name, style)` 把 style 与 name 共同 f-string 到 `{name}.{style}.txt` 拼路径。`Path` 概念上允许 `..` / `/` 这类组件解析，理论上若 style 受不可信输入控制（M-005 ModelProfile.prompt_style 来自 YAML 配置）可触发包目录外的 `.txt` 读。当前 name 已有同类形态、未做白名单/规范化，T-062 未引入新缺陷但放大了既有面。
- **建议**: 单独列入清理任务（建议放 sprint-8 chore），在 `_read_template` 入口对 name/style 做 `if "/" in s or ".." in s: raise ValueError` 之类的轻量校验；或限制 `prompt_style` 取值为 ModelProfileConfig 既有 enum（default/structured/concise）。本任务范围内不强制修。

### [R-003] LOW: test_load_prompt_style_loads_variant_content 断言强度可加强
- **category**: test-quality
- **root_cause**: self-caused
- **描述**: tests/unit/llm/test_prompt_builder.py:481-488 仅断言 `result != default`，而未直接核对变体模板文件的字面内容。若未来某次重构把 variant 解析路径改成"先尝试 base 再 fallback variant"（语义反转），该断言仍可能在变体内容碰巧不同的情况下通过。同 class 的 test_extraction_structured_is_nonempty 断言了具体占位符，整体覆盖未失锚，故仅 LOW。
- **建议**: 把该测试的断言加强为读取 `prompts/extraction.structured.txt` 文件内容并 `assert variant_content in result` 或直接 `==`；可与 R-001 一起在轻量 follow-up 处理。

## 判定

- 无 CRITICAL / HIGH
- 3 LOW (1 input-caused, 1 upstream-caused, 1 self-caused)
- **verdict: approved_with_notes**

R-001 / R-003 可在 sprint-7 末尾或 sprint-8 chore 一并修；R-002 单独入 backlog 跟踪（不阻塞当前任务）。无 needs_revision 触发条件。
