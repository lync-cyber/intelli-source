# llm/prompts/ — LLM 提示词模板目录

每个 `{name}.prompt.md` = YAML front-matter（`description` / `required_vars`）+ Jinja 正文。加载见 [`loader.py`](loader.py)（`load_prompt(name, *, style=None, **vars)`）。`_fragments/` 是可复用片段：`injection_guard.md` 提供 `untrusted(label, content)` 注入防御宏，`editor_persona.md` 是 digest 编辑人设。

## 模板清单（状态以"是否被生产代码加载"为准）

| 模板 | required_vars | 用途 | 状态 / 被谁调用 |
|------|---------------|------|-----------------|
| `flexible_agent_system` | tools | flexible RAG agent 身份 + 实时工具列表 | ✅ live — [flexible.py](../../agent/executors/flexible.py) |
| `render.{html,markdown,text}` | title, items | digest 渲染（HTML/MD/纯文本） | ✅ live — [llm_renderer.py](../../distributor/llm_renderer.py) |
| `digest_intro` | title, items | 日报/周报开场导语 | ✅ live — [digest_enhance.py](../../distributor/digest_enhance.py) |
| `digest_why` | title, summary | 单条"为什么值得关注" | ✅ live — digest_enhance.py |
| `compaction_summary` | conversation_history | 对话压缩五段式摘要 | ✅ live — [compaction.py](../../llm/compaction.py)（经 PromptBuilder） |
| `summarize_for_user` | content | 聊天中对单条内容做摘要 | ✅ live — [search_and_content.py](../../agent/tools/executes/search_and_content.py) |
| `optimizer` | subscription_name, original_title, body_text, draft_title, draft_summary | 推送通知标题/摘要改写 | ✅ live — [push_optimizer.py](../../distributor/push_optimizer.py) |
| `summarizer.structured`（base `summarizer` 为回退） | docs_text | 文档簇 JSON 摘要 | ✅ live — [summarize_cluster.py](../../agent/tools/executes/summarize_cluster.py)（`style="structured"`；pipeline 处理器经 agent.factory 注入间接调用） |
| `extraction` / `.concise` / `.structured` | schema, body_text | 结构化抽取 | 🅿️ planned — 当前抽取由正则实现，无 LLM 调用 |
| `dedup` | title, body_text, candidate_info | LLM 去重判定 | 🅿️ planned — 当前去重由指纹哈希实现 |
| `tagger` | title, body_text（可选 library_hint） | 标签分类 | 🅿️ planned — 当前打标由 tfidf 关键词实现 |
| `cluster` | title, body_text | 聚类主题标签 | 🅿️ planned — 无生产调用 |
| `context_compress` | conversation | 对话上下文压缩 | 🅿️ planned — 无生产调用 |

**图例**：✅ live = 生产代码 `load_prompt` 调用；🅿️ planned = 模板就绪但对应功能当前非 LLM 实现（extract=正则 / dedup=指纹 / tag=关键词），接线前请先确认要引入 LLM。

## style 变体

`load_prompt(name, style="concise")` 优先找 `{name}.{style}.prompt.md`，缺失则回退 `{name}.prompt.md`。style 由 `config/llm_models.yaml` 中 `profiles.<model>.prompt_style` 指定。当前有变体的：`extraction`（concise/structured）、`summarizer`（structured）。

## 改提示词的注意事项

- 处理**外部采集内容**时用 `{{ untrusted("label", var) }}` 包裹，不要裸插值（防提示注入）。
- 要 JSON 输出时，调用方应同时传 `response_format={"type": "json_object"}`，并在正文写明"only valid JSON, no markdown fences"。
- `required_vars` 缺供会在 `load_prompt` 抛 `ValueError`；改 required_vars 时同步所有调用方。
