# config/subscriptions/ — 订阅定义（推给谁 / 走哪个渠道）

把 `*.yaml` 放进本目录定义订阅。实际文件被 `.gitignore` 忽略，仓库只追踪本说明。

- **模板**：[`../examples/subscriptions.example.yaml`](../examples/subscriptions.example.yaml)
- **谁扫描它**：`SubscriptionLoader`，经环境变量 `IS_SUBSCRIPTION_CONFIG_DIR`（默认 `config/subscriptions`）
- **生效**：`intellisource subscriptions reload`（全量同步，YAML 删掉的订阅被 PAUSE，不丢历史）

完整说明见 [`../README.md`](../README.md)。
