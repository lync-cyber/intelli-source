# config/sources/ — 信源定义（内容从哪来）

把 `*.yaml` 放进本目录定义信源（rss / api / web）。实际文件被 `.gitignore` 忽略（含私有 URL / 密钥占位），仓库只追踪本说明。

- **模板**：[`../examples/sources.example.yaml`](../examples/sources.example.yaml)
- **谁扫描它**：`ConfigLoader`，经环境变量 `IS_SOURCE_CONFIG_DIR`（默认 `config/sources`）
- **生效**：`intellisource source diff` 预览 → `reload`（加法 upsert，YAML 没有的 DB 信源保留）

完整说明见 [`../README.md`](../README.md)。
