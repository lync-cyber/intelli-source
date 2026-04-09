# CODE-REVIEW: 交付物合规性审查 — r1
<!-- date: 2026-04-09 | scope: arch目录结构 vs 实际文件 | reviewer: manual -->

## 审查目标

对比架构设计文档 (`arch-intellisource-v1.md` §6 目录结构) 与实际代码目录，识别并修复所有偏离设计文档的交付物缺失或不合规问题。

---

## 审查范围

- 架构文档: `docs/arch/arch-intellisource-v1.md` §6 目录结构
- 模块文档: `docs/arch/arch-intellisource-v1-modules.md` M-004/M-005/M-006/M-008/M-011
- 代码审查报告: `CODE-REVIEW-sprint2-r1` 至 `CODE-REVIEW-sprint5-r2`
- Sprint 审查报告: `SPRINT-REVIEW-s5-r1`

---

## 发现的问题

### [R-001] MEDIUM: llm/prompts/ 目录仅含空 `__init__.py`，无模板文件
- **category**: completeness
- **root_cause**: self-caused
- **描述**: 架构文档 §6 明确列出 `llm/prompts/context_compress.txt` 为 LLM prompt 模板目录，但实际仅有空 `__init__.py`。5 个 LLM 处理器（extractor, dedup, cluster, summarizer, tagger）的 prompt 均硬编码在各自的 `.py` 文件中，违反关注点分离原则。
- **建议**: 创建 prompt 模板加载器，将硬编码 prompt 提取为 `.txt` 模板文件。
- **修复状态**: ✅ 已修复
  - 创建 `llm/prompts/__init__.py` — 提供 `load_prompt()` 模板加载函数（带 `lru_cache`）
  - 创建 6 个模板文件: `extraction.txt`, `dedup.txt`, `cluster.txt`, `summarizer.txt`, `tagger.txt`, `context_compress.txt`
  - 重构 5 个处理器使用 `load_prompt()` 替代硬编码 f-string

### [R-002] MEDIUM: agent/compaction.py 缺失
- **category**: completeness
- **root_cause**: self-caused
- **描述**: 架构文档 §6 列出 `agent/compaction.py` 为"对话上下文 LLM 压缩"模块。实际逻辑内联于 `search/chat_session.py` 的 `compact_context()` 方法，使用简单字符串截断而非 LLM 压缩。SPRINT-REVIEW-s5-r1 注1 已记录此偏差。
- **建议**: 创建独立 `agent/compaction.py`，实现基于 LLM 的上下文压缩（带截断回退）。
- **修复状态**: ✅ 已修复
  - 创建 `agent/compaction.py` — 提供 `compact_messages()` 异步函数
  - 使用 `context_compress.txt` 模板通过 LLM gateway 进行语义摘要
  - 保留字符串截断作为 fallback

### [R-003] MEDIUM: llm/processors/optimizer.py 缺失
- **category**: completeness
- **root_cause**: self-caused
- **描述**: 架构文档 §6 行380 列出 `llm/processors/optimizer.py` 为"推送优化"处理器。实际文件不存在，`processors/__init__.py` 也未导出该类。
- **建议**: 创建 `PushOptimizer` 处理器，实现基于 LLM 的推送内容优化。
- **修复状态**: ✅ 已修复
  - 创建 `llm/processors/optimizer.py` — `PushOptimizer(BaseProcessor)` 类
  - 更新 `processors/__init__.py` 导出 `PushOptimizer`

### [R-004] MEDIUM: api/deps.py 缺失
- **category**: completeness
- **root_cause**: self-caused
- **描述**: 架构文档 M-011 定义 API 层应有独立依赖注入模块。SPRINT-REVIEW-s5-r1 注3 记录"认证逻辑内联于 AuthMiddleware"。缺少 FastAPI 依赖注入辅助函数。
- **建议**: 创建 `api/deps.py` 提供 `get_db_session()` 和 `require_api_key()` 可复用依赖。
- **修复状态**: ✅ 已修复
  - 创建 `api/deps.py` — `get_db_session()` (AsyncIterator) 和 `require_api_key()` (Header 依赖)

### [R-005] LOW: llm/schemas/ 仅有 extraction.json，缺少其他处理器 Schema
- **category**: completeness
- **root_cause**: self-caused
- **描述**: 架构文档 §6 行383-384 列出 `llm/schemas/*.json` 为 LLM 输入输出 JSON Schema 目录。实际仅有 `extraction.json`，缺少 dedup、cluster、summarize、tag 四种操作的 Schema。
- **建议**: 补充创建各处理器对应的 JSON Schema 文件。
- **修复状态**: ✅ 已修复
  - 创建 `dedup.json`, `cluster.json`, `summarize.json`, `tag.json`

### [R-006] LOW: CLAUDE.md 框架版本与 pyproject.toml 不一致
- **category**: consistency
- **root_cause**: self-caused
- **描述**: `pyproject.toml` version = "0.4.3"，而 `CLAUDE.md` 框架版本字段为 "0.4.2"。
- **建议**: 同步版本号。
- **修复状态**: 未修复（CLAUDE.md 为 orchestrator 专属写入区，不在本次修复范围内）

---

## 修复文件清单

### 新建文件 (14)

| 文件路径 | 说明 |
|---------|------|
| `src/intellisource/llm/prompts/__init__.py` | prompt 模板加载器 (`load_prompt()`) |
| `src/intellisource/llm/prompts/extraction.txt` | 结构化数据提取 prompt 模板 |
| `src/intellisource/llm/prompts/dedup.txt` | 语义去重判断 prompt 模板 |
| `src/intellisource/llm/prompts/cluster.txt` | 聚类主题生成 prompt 模板 |
| `src/intellisource/llm/prompts/summarizer.txt` | 摘要生成 prompt 模板 |
| `src/intellisource/llm/prompts/tagger.txt` | 语义标注 prompt 模板 |
| `src/intellisource/llm/prompts/context_compress.txt` | 上下文压缩 prompt 模板 |
| `src/intellisource/agent/compaction.py` | 对话上下文 LLM 压缩模块 |
| `src/intellisource/llm/processors/optimizer.py` | 推送内容优化处理器 |
| `src/intellisource/api/deps.py` | FastAPI 依赖注入辅助 |
| `src/intellisource/llm/schemas/dedup.json` | 去重结果 JSON Schema |
| `src/intellisource/llm/schemas/cluster.json` | 聚类主题 JSON Schema |
| `src/intellisource/llm/schemas/summarize.json` | 摘要结果 JSON Schema |
| `src/intellisource/llm/schemas/tag.json` | 标注结果 JSON Schema |

### 修改文件 (6)

| 文件路径 | 变更说明 |
|---------|---------|
| `src/intellisource/llm/processors/extractor.py` | 导入 `load_prompt`，替换硬编码 prompt |
| `src/intellisource/llm/processors/dedup.py` | 导入 `load_prompt`，替换硬编码 prompt |
| `src/intellisource/llm/processors/cluster.py` | 导入 `load_prompt`，替换硬编码 prompt |
| `src/intellisource/llm/processors/summarizer.py` | 导入 `load_prompt`，替换硬编码 prompt |
| `src/intellisource/llm/processors/tagger.py` | 导入 `load_prompt`，替换硬编码 prompt |
| `src/intellisource/llm/processors/__init__.py` | 新增导出 `PushOptimizer` |

---

## 测试验证

```
uv run pytest tests/ -x -q: 1563 passed, 0 failed, 18 warnings
uv run mypy --strict src/intellisource: Success, 0 errors (102 source files)
```

所有修复均通过现有测试套件验证，无回归。

---

## 审查统计

| 严重等级 | 数量 | 已修复 |
|----------|------|--------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 4 | 4 |
| LOW | 2 | 1 |

## 判定结论

**approved** — 所有 MEDIUM 问题已修复，剩余 1 个 LOW (版本号不一致) 为 orchestrator 专属区域，不影响功能。
