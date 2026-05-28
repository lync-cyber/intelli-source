---
id: research-b051-config-bootstrap-ux
doc_type: research
author: orchestrator
status: approved
deps: [backlog-intellisource-v1]
---

# 配置管理与首次接入引导优化 — 现状审计 + 候选方案

> 用途：用户提议"研究如何优化配置管理和引导，简化用户初始配置时的上手难度"；本研究梳理现有配置面 / 痛点 / 候选方案。
> 范围：仅产出方向与候选，不写代码（实施留给 B-051 决策后）。

## 1. 当前配置面盘点

| 配置源 | 路径 | 字段数 | 是否必填 | 默认能否跑 |
|--------|------|-------|---------|-----------|
| 容器环境变量 | [docker/.env.example](../../docker/.env.example) | ~32 var | 部分必填（DB/Redis/API_KEY/LLM key 必填，channel 全 optional 但当前 hard-fail） | ❌ 需手动填 5+ 个 |
| LLM 路由 | [config/llm_models.yaml](../../config/llm_models.yaml) | 1 默认 + 6 任务（extract/dedup/tag/chat/summarize/embed） | 是 | ✓ 仓库自带 deepseek-v4 配置 |
| 信源定义 | `config/sources/*.yaml`（目录默认不存在） | N 个文件 × ~10 字段 | 是 | ❌ 需 `mkdir -p config/sources && cp sources.example.yaml ...` |
| 管线 YAML | `config/pipelines/*.yaml`（5 个 pipeline） | 已就位 | 否（仓库自带） | ✓ |
| docker-compose 服务定义 | [docker/docker-compose.yml](../../docker/docker-compose.yml) | 9 services × ports / profiles | 否 | ✓ 默认 profile 全跑 |
| Prometheus 监控 | [docker/prometheus/](../../docker/prometheus/) | profile `observability` | 否（可选） | ✓ |
| 订阅渠道凭据 | docker/.env 中 wechat/wework/email 段 | 10+ var（占位允许） | composition hard-fail（B-033）| ❌ 当前需填占位 |

**首次最小可跑栈**需要：

1. `cp docker/.env.example docker/.env`
2. 编辑 `docker/.env` 填 `IS_API_KEY`（必填，无默认值）+ 至少一个 LLM key（OPENAI/ANTHROPIC/DEEPSEEK）+ wechat/wework/email 占位（B-033 hard-fail 阻塞）
3. `cp config/sources.example.yaml config/sources/sources.yaml` （或手动创建）
4. `docker compose -f docker/docker-compose.yml up -d`
5. `curl -H "X-API-Key: ..." localhost:8000/health`

**痛点**：4 步骤、每步可能失败、错误信息分散在各容器 log 中、`/health` 显示 degraded 不解释原因。

## 2. 痛点分类

### 2.1 信息散布

| 痛点 | 位置 | 影响 |
|------|------|------|
| 必填变量提示散在 `.env.example` 注释 + walkthrough §0.2 + composition.py 错误信息 | 三处 | 用户跨文件查找 |
| 渠道 hard-fail 无 graceful 提示（B-033 待闭环）| composition.py:127 | 首次启动 lifespan 崩溃，错误信息埋在 stdout |
| LLM key 缺失，pipeline 执行才报错 | runtime | 启动看似成功，触发任务才知道 LLM 不可用 |
| sources/ 目录不存在不告警 | startup | 默认任何信源都不会加载，但启动正常，用户以为 "怎么没数据" |

### 2.2 默认值不友好

| 痛点 | 当前 | 建议 |
|------|------|------|
| `IS_API_KEY=change-me-in-production` | 占位字符串 | 启动时如发现该值 → 拒绝启动 + 提示生成命令 |
| `IS_PUSH_OPTIMIZE_ENABLED=0` | 默认关 | 合理 |
| 渠道配置全空 | hard-fail | B-033 改 soft-disable + log.warning |
| LLM models default | deepseek-v4-pro | 合理（有低成本默认） |

### 2.3 上手交互缺失

- 无 CLI 引导命令（`cataforge setup` 是框架 scaffold 用，与 intellisource 应用配置无关）
- 无 "doctor" 一键检查命令（缺失变量、目录、镜像、依赖、连通性）
- walkthrough 是事实上的上手 checklist，但藏在 deploy 子目录、20 步流程过长

## 3. 候选方案

### 选项 A — `intellisource init` 交互式 CLI（推荐主路径）

**核心**：仿照 `npm init` / `cookiecutter`，命令行交互式问答生成 `.env` + `config/sources/default.yaml` + （可选）首条订阅。

```text
$ uv run intellisource init
? 推荐分发渠道（按用户友好度排序）：
  ▶ 企业微信 (推荐 - 配置略多但消息体验好)
    微信公众号 (需要企业资质 + 公众号备案)
    Email SMTP
    都先跳过 (后续添加)
? 企业微信 corp_id: __________
? 企业微信 corp_secret: __________
? LLM provider: deepseek (推荐 - 低成本) / openai / anthropic
? OPENAI_API_KEY: __________
? 首个信源 RSS URL（可空）: https://news.ycombinator.com/rss
✓ 写入 docker/.env
✓ 写入 config/sources/default.yaml
✓ 下一步: docker compose -f docker/docker-compose.yml up -d
```

- 成本：~300 LOC CLI + 1 模板文件
- 优势：错误前置、可选项可视化、用户决策只问一次
- 风险：CLI 维护成本（pipeline / channel 增删时需同步）

### 选项 B — `make bootstrap` 一键脚本

**核心**：纯 shell/Makefile，无交互：检测 `.env` + `config/sources/` 是否存在 → 不存在则 copy example → 提示用户填空。

```makefile
bootstrap:
	@[ -f docker/.env ] || cp docker/.env.example docker/.env
	@mkdir -p config/sources
	@[ -f config/sources/default.yaml ] || cp config/sources.example.yaml config/sources/default.yaml
	@echo "请编辑 docker/.env 填入 IS_API_KEY 与 LLM key，然后跑 make up"
```

- 成本：~30 LOC Makefile
- 优势：零依赖、零学习成本
- 风险：仅减少 2 步，主要痛点（必填项发现）未解决

### 选项 C — `intellisource doctor` 启动前/启动后检查

**核心**：在 `intellisource` CLI 加 `doctor` 子命令，扫描必填项缺失 + 默认值未改 + 目录缺失 + 服务连通性。

```text
$ uv run intellisource doctor
✓ docker/.env present
✗ IS_API_KEY = "change-me-in-production" (默认占位，请修改)
✓ IS_DATABASE_URL parsed OK
✗ OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY 均未设置（pipeline 将无法执行 LLM step）
✓ config/sources/ 含 1 个 yaml
○ wechat 凭据：未配置（订阅将跳过 wechat 渠道）
○ wework 凭据：未配置（订阅将跳过 wework 渠道）
✗ Email SMTP：IS_SMTP_HOST 未设置（订阅将跳过 email 渠道）
✗ Redis: connection refused (是否已 `docker compose up redis`？)
```

- 成本：~400 LOC
- 优势：可独立运行 / 可在 CI 跑 / 配 `--strict` 退非 0 可阻塞 docker entry
- 风险：与 cataforge framework 的 `cataforge doctor` 命名空间冲突，需明确边界

### 选项 D — B-033 软降级 + 配置 warnings 统一

**核心**：先把 B-033 关掉（channels soft-disable），所有缺失项启动时统一 log.warning 列在一处 + `/health` 端点返回 missing list。

- 成本：B-033 立项实施 ~80 LOC + healthcheck 改 ~30 LOC
- 优势：兼容现状最小、不引入新文件、`/health` 已是事实上的状态入口
- 风险：解决一半问题（运行时友好），首次接入门槛不变

### 选项 E — 单一配置文件 `intellisource.yaml`

**核心**：把 docker/.env + config/sources/* + （可选）pipelines 折叠为 `intellisource.yaml`，CLI 启动时展开为各处真实文件。

- 成本：~1000+ LOC + 大幅 doc 重写
- 优势：用户单点配置，认知负担最低
- 风险：重构大、与 docker-compose env 体系冲突、12-factor 反模式

## 4. 建议组合

**短期（B-051 第一刀）**：D + B（最小成本启动）
- B-033 落地 → channels soft-disable + 统一 startup warnings
- Makefile `bootstrap` 目标减少首次步骤数
- `IS_API_KEY=change-me-in-production` 启动校验 + 拒绝（占位被实际使用时硬阻断）

**中期（B-051 第二刀）**：C
- `intellisource doctor` 命令补 SOP 自检
- 集成到 docker entrypoint 启动前跑（`--strict` 模式）
- `/health` 端点暴露 missing-config 列表

**长期（B-051 第三刀）**：A
- `intellisource init` 交互式引导
- 引导默认 wework 优先（与 B-050 协同）
- 引导生成首个测试信源（HN RSS）

**不推荐**：E（重构成本与收益不匹配）

## 5. 决策点

需要用户在 B-051 立项后选定具体路径：

1. 仅做 D（短期最小）
2. D + C（短中期，无 CLI 重交互）
3. D + C + A（长期完整）— **推荐**
4. B + C + A（跳过 soft-fail 重构，CLI 主路径）

## 6. 顺带发现

- `.env.example` 行 28 `IS_API_KEY=change-me-in-production` 是固定占位，任何用户复制不改即生产环境安全事故；当前无启动校验
- `config/llm_models.yaml` 与 `config/llm_models.example.yaml` 双份且仅小差异，新用户不知用哪份
- `docker compose --profile observability` / `--profile walkthrough` 已是事实上的"按需启动"，与 B-051 方向契合，可作为 selecting feature 的基础
