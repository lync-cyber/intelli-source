---
id: "code-review-B-008-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["B-008"]
---

# CODE-REVIEW: B-008 — LLM summarizer (PRD AC-023 P2 兑现)

> Layer 1 delegated to pre-review CI checks (ruff check + ruff format --check + mypy --strict 全 clean)
> Layer 2 全维度审查（feature 任务 + 涉及 LLM 集成 + agent.tools wiring，不命中短路）

## 审查范围

- `src/intellisource/pipeline/processors/tools.py` — 新增 `DIGEST_SCHEMA` + `_SUMMARIZE_SYSTEM_PROMPT` + `_build_summarize_prompt` + `llm_summarize` (+105 行)
- `src/intellisource/agent/tools/__init__.py` — 新增 `_llm_summarize_execute()` 包装器 + ToolDefinition 注册 (+44 行)
- `src/intellisource/agent/prompts/content_process.txt` — Step 5 Summarize 建议 `llm_summarize` 优先 (+2 行)
- `tests/unit/pipeline/test_llm_summarize.py` — 17 个新测试覆盖 success / fallback × N / empty cluster / prompt 完整性
- `tests/unit/agent/test_tools.py` — 工具计数 17→18 + `TestLlmSummarizeTool` 5 个新测试

## 验证基线

- 全量回归: 2849 PASS / 0 FAIL / 0 skip / 0 xfail / 51 deselected（+22 净 vs B-007+B-029+B-030 闭环后 2827）
- mypy --strict: 154 source files clean
- ruff check + format: clean

## 维度审查总结

| 维度 | 结论 | 备注 |
|-----|------|------|
| structure | ✅ PASS | 与 `truncate_summary` 并列设计；DIGEST_SCHEMA / system prompt / build_prompt helper 模块级常量；lazy import SchemaEnforcer 避循环 import |
| consistency | ✅ PASS | `truncate_summary` 签名 + 行为完全保留；llm_summarize 返回字典 shape 与 truncate_summary 完全等价（fallback 后调用方零感知） |
| convention | ✅ PASS | 中文 system prompt + 英文 code/user prompt 与项目语言定位一致；`# noqa: BLE001` 与现有 distributor/llm fallback 路径同模式合法 |
| security | ✅ PASS | 无敏感数据 / 鉴权变化；prompt 注入风险：cluster_contents 进入 user prompt，但 LLM 输出已被 JSON schema 严格约束（无法执行任意指令） |
| integration-wiring | ✅ PASS | `_llm_summarize_execute()` 通过 `tool_deps.llm_gateway` 注入 — 与 `llm_complete` / `summarize_for_user` 同模式；ToolDefinition 注册 + content_process.txt prompt 同步推荐；`llm_gateway` 缺失时 execute 包装器直接 fallback truncate_summary（防止 wiring 漏装时整链路 break） |
| error-handling | ✅ PASS | `except Exception` 捕获所有 fallback 触发源（SchemaValidationError / JSONDecodeError / LLMOutputError / litellm 错误 / 熔断器 etc.）；logger.warning 含异常类型 + 消息；empty cluster 早返回不调 LLM |
| test-quality | ✅ PASS | 17 个测试覆盖 success / 4 类 fallback 触发 / empty cluster / prompt 完整性；agent.tools 注册测试 5 个；断言强度足（不仅 mock 计数，验证返回结构 + logger 调用） |

## 设计亮点

1. **Fallback 透明**: caller 拿到的字典 shape 完全一致（{title, summary, timeline, key_points}）— LLM 成功 timeline 含真实事件、失败 timeline=[]；调用方无需 try/except 区分
2. **Empty cluster 早返回**: `if not cluster_contents: return await truncate_summary([])` 避免无意义 LLM 调用 + 等价于 truncate_summary 空输入语义
3. **Prompt 设计**: system 强约束 JSON 格式 + user 拼接每篇 doc 的 title/date/content；引导 LLM 提取 timeline.{date, event} 与 key_points
4. **JSON Schema 严格**: timeline items 内嵌 `required: [date, event]`，迫使 LLM 输出结构化时间线（非自由文本）
5. **Wiring 安全网**: agent.tools 包装器在 `llm_gateway` 缺失时直接 fallback truncate_summary，无需调用方做装配缺口检测

## 问题列表

无 CRITICAL / HIGH / MEDIUM / LOW。

### Potential micro-polish（不阻塞、不立项）
- user prompt 是英文 + system prompt 是中文 — LLM 实际输出语言由 cluster_contents 的语言决定（schema 约束字段名而非值的语言），跨语言场景下可能产出混合语言 summary；当前 v1 IntelliSource 主要中文场景这是合理设计
- `from intellisource.llm.gateway._types import SchemaEnforcer` 直接 import 私有模块 — PR #59 _types 仍作为内部 API；如果未来 _types 重命名 / 移动，需同步更新此 import 点

## ASSUMPTION（implementer 报告，reviewer 已确认合理）

1. `timeline.date` 格式 free-form string（非强制 ISO 8601）— LLM 适应原文日期表述
2. `task_type="summarize"` 已存在于路由配置（与 `_summarize_for_user_execute` 同 task_type）
3. `SchemaEnforcer.validate()` 同时做 JSON parse + jsonschema 校验（已由 17 测试 PASS 间接确认）

## 判定

**verdict: approved**

- 0 issue
- Fallback 完整 + 测试覆盖足 + mypy strict + 2849 PASS 零退化
- 直接进入 closeout（BACKLOG 删 B-008 + amend or new PR + 更新 CLAUDE.md）
