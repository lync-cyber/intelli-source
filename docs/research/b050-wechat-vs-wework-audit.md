---
id: research-b050-wechat-vs-wework-audit
doc_type: research
author: orchestrator
status: approved
deps: [backlog-intellisource-v1]
---

# 微信公众号 (wechat) vs 企业微信 (wework) 支持矩阵审计

> 用途：B-031 走查阶段 5 步骤 13/14 闭环后，用户提议"默认优先支持企业号"；本审计核实代码层 / 配置层 / 文档层现状，为 B-050 立项提供事实基础。
> 范围：仅做现状审计 + 用户视角对比；不涉及代码改动（实施留给 B-050）。

## 1. 代码层 — 两条通路对称度

| 层 | wechat (公众号) | wework (企业号) | 文件 | 对称性 |
|----|----------------|----------------|------|--------|
| **出站推送** | `WeChatDistributor` (template / news) | `WeWorkDistributor` (text / markdown / news) | [channels/wechat.py](../../src/intellisource/distributor/channels/wechat.py) (234 行) / [channels/wework.py](../../src/intellisource/distributor/channels/wework.py) (259 行) | ✓ 对等，wework 多 markdown |
| **入站客服** | `WeChatCustomerServiceClient` | `WeWorkCustomerServiceClient` | [wechat_cs_client.py](../../src/intellisource/distributor/wechat_cs_client.py) (68 行) / [wework_cs_client.py](../../src/intellisource/distributor/wework_cs_client.py) (74 行) | ✓ 对等，共享 [base_cs_client.py](../../src/intellisource/distributor/base_cs_client.py) |
| **Webhook 验签** | sha1 token | sha1 token + AES-CBC 加密 | [api/routers/webhooks.py](../../src/intellisource/api/routers/webhooks.py) `/wechat` / `/wework` | wechat 明文 / wework 强制加密 |
| **Composition wiring** | `_install_webhook_state` 分支 1 | `_install_webhook_state` 分支 2 + `_wecom_crypto` | [composition.py:465-547](../../src/intellisource/composition.py) | ✓ 对等，wework 额外 3 个 env (`IS_WECOM_*`) |
| **Background dispatch** | `_dispatch_chat_reply` → AgentRunner | 同 | [api/routers/webhooks.py:51](../../src/intellisource/api/routers/webhooks.py) | ✓ 共用 |

**结论**：两条通路在代码层完全对等，无"未实现"功能缺口。差异仅在"加密强制度"和"配置数量"。

## 2. 配置层 — env 变量映射

| 用途 | wechat env | wework env | 数量差 |
|------|-----------|-----------|--------|
| Distributor + CS messenger 公共凭据 | `IS_WECHAT_APP_ID` / `IS_WECHAT_APP_SECRET` | `IS_WEWORK_CORP_ID` / `IS_WEWORK_CORP_SECRET` / `IS_WEWORK_AGENT_ID` | +1 |
| Webhook 签名 token | `IS_WECHAT_WEBHOOK_TOKEN` | `IS_WEWORK_WEBHOOK_TOKEN` | 持平 |
| AES 加密配置（仅 wework） | — | `IS_WECOM_TOKEN` + `IS_WECOM_ENCODING_AES_KEY` + `IS_WECOM_CORP_ID` | +3（独立命名空间） |
| **合计** | 3 | 7 | wework 比 wechat 多 4 个 env |

**注意**：wework 的 `IS_WECOM_CORP_ID` 与 `IS_WEWORK_CORP_ID` 是同一个 corp_id 的两份配置（命名空间分离是历史遗留）；docker/.env.example 当前只列了 4 个 wework var，遗漏 `IS_WECOM_*` 三个。

## 3. 默认渠道概念 — 当前不存在

- **subscriptions.channel** 字段（值 ∈ `wechat` / `wework` / `email`）决定每条订阅走哪个 channel
- composition.build_distributor_facade 一次性 wire 三个 channel，**任一缺失 hard-fail**（B-033 待处理）
- API 层 / pipeline 层无"默认渠道"概念
- walkthrough §0.2 默认要求三个 channel 全填占位（包括明知 N/A 的）

## 4. 用户视角对比（产品维度）

| 维度 | wechat (公众号) | wework (企业号) | 友好方 |
|------|----------------|----------------|--------|
| 注册门槛 | 需企业资质备案 + 公众号年审 | 企业微信 corp 注册免费 + 即开即用 | **wework** |
| 用户身份 | openid (28+ 字符不透明 ID) | user_id (管理员可指定 / 通讯录可读) | **wework** |
| 推送时间窗口 | 客服消息受 48h 用户互动窗口约束 | 无时间窗口限制，任何时间可主动推 | **wework** |
| 消息类型 | template（结构化）+ customer-service text/news | text / markdown / news / image / file / voice / video | **wework** |
| 富文本支持 | 不支持 markdown | 支持 markdown 渲染（标题 / 表格 / 加粗 / 链接） | **wework** |
| 主动推送限制 | template 需用户授权 + 限频 | 应用消息无限频，仅企业总配额限制 | **wework** |
| 群组与 @ 提及 | 不支持（消息为 1-1） | 支持 `mentioned_list` / 群聊 webhook | **wework** |
| API 限流 | 严格（模板 100k/day，客服 1000/s 但需 48h 窗口） | 宽松（消息发送 30k/min/agent） | **wework** |
| 用户授权前提 | 用户需先关注公众号 | 企业通讯录直接派发，无需用户主动关注 | **wework** |
| 安全性 | 明文 XML（兼容模式） | 强制 AES-CBC 加密 | **wework**（但配置复杂度 +） |
| 国际化 | 仅简体中文用户 | 仅简体中文用户 | 持平 |
| 集成成本 | 配置少（3 env）但 API 路径多 | 配置多（7 env）但 API 行为统一 | **wechat 略低** |

**总分**：wework 在 9/12 维度上更友好。仅"配置变量数量"和"加密路径复杂度"上 wechat 占优——这两点都是首次接入门槛问题，不影响日常运行体验。

## 5. "默认优先 wework" 的实施面

实施 = 文档调整 + 默认值倾斜 + （可选）composition 路由调整。

### 5.1 文档层（无代码改动）

- [docker/.env.example](../../docker/.env.example) §59-79 "Distribution channels" 段：把 `IS_WEWORK_*` 块挪到 `IS_WECHAT_*` 之前；行内注释加 "推荐 / 主路径"
- [docs/deploy/PRE-DEPLOY-WALKTHROUGH.md](../deploy/PRE-DEPLOY-WALKTHROUGH.md) §0.2：把 wework 标 "推荐渠道"，wechat 标 "可选 / 需公众号备案资质"
- [docs/prd/](../prd/) PRD 文档把 wework 列为 P0 / wechat 列为 P1（如果 PRD 现在没区分）
- [docs/arch/](../arch/) ARCH 文档 M-007 推送模块说明把 wework 标 "主路径" / wechat 标 "兼容路径"

### 5.2 默认值调整

- subscriptions 模板（[config/sources.example.yaml](../../config/sources.example.yaml) 或新增的 `config/subscriptions.example.yaml`）默认 channel = "wework"
- walkthrough 步骤 13 推送示例从 wechat 改 wework

### 5.3 代码层（依赖 B-033 闭环）

- B-033 后：composition.build_distributor_facade 改可选 channel；当 wework 配齐 + wechat 缺失时，channels dict 不含 wechat 但 lifespan 正常启动
- subscriptions.channel = "wechat" 但 channels 不含 wechat → 返回明确 `ChannelDisabled` 错误（已在 facade.py:118 实现 "skipped + unknown" 路径，需细化 channel_name）

## 6. 立项建议

立 **B-050 (P3)** "默认优先 wework 渠道 + 文档与默认值调整"，依赖 B-033 (P2 channel 可选)。代码改动小（< 50 LOC），主要工作是文档侧。

风险：低；现有 wechat 路径完全保留，仅默认推荐与首次接入示例倾向 wework。

## 7. 顺带发现的小问题

- `IS_WECOM_*` 三个变量未列入 docker/.env.example（合并入 B-034 doc drift 修订）
- `_install_webhook_state` 分支 4 (B-033 carryover): 当 wework 全空 + IS_WECOM_* 全空但 wechat 配齐时，wecom_crypto=None 但 wework_cs_messenger 也为 None，wework webhook 永远 503 — 这是预期行为但 walkthrough 无说明
