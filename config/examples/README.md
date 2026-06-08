# config/examples/ — 配置模板集中处

这里是所有**只读样例**，照着复制到对应位置即可。`intellisource init` 会自动从这里播种起始配置。

| 模板 | 复制到 | 说明 |
|------|--------|------|
| `sources.example.yaml` | `config/sources/sources.yaml` | 信源（rss / api / web） |
| `subscriptions.example.yaml` | `config/subscriptions/subscriptions.yaml` | 订阅（推给谁 / 走哪个渠道） |
| `llm_models.example.yaml` | `config/llm_models.yaml` | LLM 模型路由（含各任务 profile） |

```bash
# 手动复制（init 已自动做过，仅在需要重置时用）
cp config/examples/sources.example.yaml        config/sources/sources.yaml
cp config/examples/subscriptions.example.yaml  config/subscriptions/subscriptions.yaml
cp config/examples/llm_models.example.yaml     config/llm_models.yaml
```

完整说明见 [`../README.md`](../README.md)。
