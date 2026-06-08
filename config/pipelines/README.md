# config/pipelines/ — 管线定义（采集 → 处理 → 分发的编排）

每个 `*.yaml` 是一条管线（如 `scheduled-collect` 定时采集、`instant-search` 即时检索、`admin-agent` 管理助手）。这些文件**随仓库提交、可直接编辑**，没有 `.example` 中间层。

- **谁扫描它**：`pipeline/definition_service.py`（默认目录 `config/pipelines/`）
- **`mode`**：`strict`（固定步骤）或 `flexible`（agent 自由编排，用 `system_prompt` + `tools_allowed`）
- **`system_prompt`**：该管线 agent 的专属人设——属用户可改配置；与 `src/intellisource/llm/prompts/` 里跨管线复用的任务提示词是两回事

完整说明见 [`../README.md`](../README.md)。
