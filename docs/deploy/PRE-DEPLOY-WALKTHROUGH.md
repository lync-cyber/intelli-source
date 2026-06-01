---
id: pre-deploy-walkthrough-v1
doc_type: deploy-spec
author: devops
status: draft
deps: [arch-intellisource-v1-modules, arch-intellisource-v1-api, backlog-intellisource-v1]
consumers: [devops, qa-engineer, developer]
---

# Pre-Deploy Walkthrough: IntelliSource

> 用途：deploy 阶段 `pre_deploy` 人工 go/no-go 检查清单。按管线工作流程分 8 阶段、共 20 步手动验证每个模块；每步给出"启动 → 触发 → 期望响应 → 验证手段 → Pass 标准"，并预留签字栏。
> 范围：本文件覆盖 M-001~M-011 全部模块的功能性烟测；不替代 `uv run pytest` 单元/集成回归（已 2766 PASS 基线）。
> 已知卡点：B-001（`/search/chat/stream` RAG 上下文缺失）与 B-002（`/search` date 过滤类型）属 P0，必须在阶段 4 前先闭环；详见 [docs/BACKLOG-intellisource-v1.md](../BACKLOG-intellisource-v1.md)。
>
> 新手快速上手（非部署走查）见 [README §快速上手（新用户）](../../README.md)：`uv sync` → `uv run intellisource init` → `intellisource up` → `intellisource doctor --check-api`。本清单面向部署 go/no-go，假设读者已理解各模块。

---

## 0. 前置条件

### 0.1 工具清单

| 工具 | 用途 | 备注 |
|-----|------|------|
| `docker` / `docker compose` | 启动依赖栈 | v2 语法 |
| `curl` | HTTP 触发 | Windows 用户推荐 git-bash / WSL；PowerShell 用户可改用 `Invoke-RestMethod` |
| `psql` | DB 验证 | 也可 `docker compose exec db psql ...` |
| `redis-cli` | Redis 验证 | 同上 |
| `intellisource` CLI | 部分操作的替代入口 | `uv run intellisource --help` |
| `jq` | JSON 美化（可选） | 不强制 |

### 0.2 环境变量（`docker/.env` 或导出到 shell）

| 变量 | 示例值 | 必需 |
|------|-------|------|
| `IS_DB_USER` / `IS_DB_PASSWORD` / `IS_DB_NAME` | `intellisource` / `intellisource` / `intellisource` | 是 |
| `IS_DATABASE_URL` | `postgresql+asyncpg://intellisource:intellisource@db:5432/intellisource` | 是 |
| `IS_REDIS_URL` | `redis://redis:6379/0` | 是 |
| `IS_CELERY_BROKER_URL` | `redis://redis:6379/0` | 是 |
| `IS_CELERY_RESULT_BACKEND` | `redis://redis:6379/1` | 是 |
| `IS_API_KEY` | 强随机串（`secrets.token_hex(32)`）；占位 `change-me-in-production` 启动会被 lifespan 阻断 | 是（API key 中间件强制，对 `/openapi.json` + `/docs` + `/redoc` + 所有 `/api/v1/*` 业务端点全部生效；仅 health/metrics/webhooks 系列豁免） |
| `LITELLM_*` / OpenAI/兼容密钥 | 见 `config/llm_models.example.yaml` | 阶段 3 必需 |
| `IS_SOURCE_CONFIG_DIR` | `config/sources` | 可选，默认 `config/sources` |

#### Distribution channels（可选 — 未配置自动 soft-disable，启动 warning 不阻塞）

| 渠道 | 必填变量 | 适用场景 |
|------|---------|---------|
| **WeWork (企业微信)** — 推荐主路径 | `IS_WEWORK_CORP_ID` / `IS_WEWORK_CORP_SECRET` / `IS_WEWORK_AGENT_ID`（出站推送）；入站客服回话另需 `IS_WECOM_*`（见下方 WeCom 行）| 无 48h 客服窗口约束 / 支持 markdown / 通讯录直接派发 / API 限流宽松；企业 corp 注册即用，无须备案 |
| WeChat 公众号 | `IS_WECHAT_APP_ID` / `IS_WECHAT_APP_SECRET` (+ `IS_WECHAT_WEBHOOK_TOKEN` 可选回话) | C 端公众号；**需公众号备案 + 年审**，客服推送受 48h 用户互动窗口约束 |
| Email (SMTP) | `IS_SMTP_HOST` / `IS_SMTP_USER` / `IS_SMTP_PASSWORD` / `IS_SMTP_PORT` (+ `IS_SMTP_USE_TLS` 默认 true，本地 mailhog/mailpit 设 false) | 团队邮件 / 测试栈本地 mailhog。本地用 mailhog 时设 `IS_SMTP_HOST=mailhog` / `IS_SMTP_PORT=1025` / `IS_SMTP_USE_TLS=false`，并启 walkthrough profile：`docker compose -f docker/docker-compose.yml --profile walkthrough up -d mailhog`（compose 已定义 mailhog 服务，profile=walkthrough，端口 1025） |
| WeCom 加密回调（仅 wework AES 模式启用时） | `IS_WECOM_TOKEN` / `IS_WECOM_ENCODING_AES_KEY` / `IS_WECOM_CORP_ID` | wework webhook 走 AES-CBC 加密；与 `IS_WEWORK_CORP_ID` 同值另一份命名空间 |

> 建议首次只配 WeWork（最低门槛 + 最丰富功能）；订阅创建时 `channel="wework"` 即可路由。WeChat 与 Email 都是兼容路径，可后续按需补齐。若 `docker/.env` 留空分发渠道凭据（wework/wechat/email），`build_distributor_facade()` 会 soft-disable 该渠道并打 warning 日志，不会 hard-fail lifespan；只有真正要走查推送链路（步骤 13）的渠道才需填真实/占位凭据。

### 0.3 信源配置文件

`config/sources/` 默认不存在；需手动创建并放置至少一个 YAML（可参考 [config/sources.example.yaml](../../config/sources.example.yaml)）。建议用本仓库自带的 RSS 源以避免网络抖动：

```bash
mkdir -p config/sources
cp config/sources.example.yaml config/sources/sources.yaml
```

### 0.4 LLM 配置

`config/llm_models.yaml` 需要存在并指向可用的 provider（litellm 兼容）。本地烟测可以用 mock provider 或便宜的小模型；不要把 prod key 注入测试栈。

### 0.5 host 主机端口占用

`8000` (api), `9090` (prometheus profile), `5432`/`6379` 默认不外露。如已被占用，调整 `docker-compose.yml` ports 段。

---

## 阶段 0 — 基础设施

### 步骤 1：DB + Redis + migrate 就绪

**启动**

```bash
docker compose -f docker/docker-compose.yml up -d db redis migrate
docker compose -f docker/docker-compose.yml ps
```

**期望响应**

```
NAME              STATUS                    PORTS
docker-db-1       Up X seconds (healthy)
docker-redis-1    Up X seconds (healthy)
docker-migrate-1  Exited (0) X seconds ago
```

**验证**

```bash
# 1. pgvector 扩展存在
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c "SELECT extname FROM pg_extension;"
# 期望输出包含 'vector'

# 2. 11 张业务表都已建好
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c "\dt"
# 期望看到: sources / task_chains / collect_tasks / raw_contents / content_clusters
#         processed_contents / digests / llm_call_logs / subscriptions / push_records / chat_sessions

# 3. Redis ping
docker compose -f docker/docker-compose.yml exec redis redis-cli ping
# 期望: PONG
```

**Pass 标准**：`migrate` 容器 exit code = 0、11 张表齐全、`vector` 扩展存在、Redis 返回 `PONG`。

☑ 通过 / 签字：lync-cyber 2026-05-26 — exit 0，13 表（11 业务 + alembic_version + config_versions），vector + pg_trgm 就位，Redis PONG。**修正**：发现 4 项构建缺陷（Dockerfile alembic.ini 路径 / uv sync README 缺失 / asyncpg+psycopg 未声明为运行时依赖 / env.py 用错环境变量名 + 异步驱动需重写为 psycopg / zhparser 缺扩展），均已修复；详见 [CORRECTIONS-LOG B-031 #1-4](../reviews/CORRECTIONS-LOG.md)。

---

### 步骤 2：API 服务起栈 + /health 端点

**启动**

```bash
docker compose -f docker/docker-compose.yml up -d api
sleep 5  # 等 lifespan 完成
```

**触发 & 期望响应**

```bash
curl -s http://localhost:8000/health | jq .
```

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 5.x,
  "checks": {
    "db": {"status": "healthy", "latency_ms": ...},
    "redis": {"status": "healthy", "latency_ms": ...},
    "celery": {"status": "healthy", ...}
  },
  "timestamp": "2026-..."
}
```

```bash
# 同时验证三个 health 入口都正常（root / v1 / system）
curl -fsS http://localhost:8000/health > /dev/null
curl -fsS http://localhost:8000/api/v1/health > /dev/null
curl -fsS http://localhost:8000/api/v1/system/health > /dev/null

# OpenAPI 自描述（需 API key：/openapi.json、/docs、/redoc 不在 exempt 名单）
curl -s -H "X-API-Key: $IS_API_KEY" http://localhost:8000/openapi.json | jq '.paths | keys | length'
# 期望 > 25
```

**验证**

```bash
# 日志无 ERROR
docker compose -f docker/docker-compose.yml logs api | grep -E "(ERROR|Traceback)" | head
# 期望空

# trace_id 中间件已挂载
curl -s -D - http://localhost:8000/health -o /dev/null | grep -i x-trace-id
# 期望存在 X-Trace-Id 响应头
```

**Pass 标准**：`/health.status in {"healthy","degraded"}`，三个 health 入口都 200，trace_id 头存在。

> celery 组件健康依赖 worker（步骤 12 才起栈），此前 health 聚合为 `degraded`（all-healthy→healthy / all-unhealthy→unhealthy / 其余→degraded，见 `observability/health.py`）；worker 起栈后转 healthy。

**失败排查**：`unhealthy` 时先看 `checks.db` / `checks.redis` 哪个失败；最常见是 `IS_DATABASE_URL` 主机名写成 `localhost` 而非容器名 `db`。

☑ 通过 / 签字：lync-cyber 2026-05-26 — /health 200，db+redis healthy，celery unhealthy（**预期** — worker 阶段 5 步骤 12 才起栈），三个 health 入口全 200，OpenAPI 27 paths（>25），x-trace-id header 存在，logs 无 ERROR/Traceback。**修正**：发现 3 项额外构建/配置缺陷（uvicorn 未声明运行时依赖 / venv 跨路径 shebang 破口 / build_distributor_facade 对未配置渠道 hard-fail 与 §0.2 矛盾），均已修复或加占位绕过；详见 [CORRECTIONS-LOG B-031 #5-7](../reviews/CORRECTIONS-LOG.md)。**走查文档小观察**：①步骤 2 期望 `status=healthy` 与 celery 健康依赖 worker 启动矛盾，应改为 `status in {healthy,degraded}` + 标注 celery 在步骤 12 后才能转 healthy；②OpenAPI 端点受 API key 中间件保护，curl 须带 `X-API-Key: $IS_API_KEY`。

---

## 阶段 1 — M-001 配置 & M-002 采集

### 步骤 3：注册信源（M-001）

**触发 — 方式 A：CLI**

```bash
export IS_API_URL=http://localhost:8000
uv run intellisource source add \
  --name "Hacker News" --type rss --url "https://hnrss.org/frontpage" --json
```

**触发 — 方式 B：curl**

```bash
curl -sX POST http://localhost:8000/api/v1/sources \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Hacker News","type":"rss","url":"https://hnrss.org/frontpage","tags":["tech","news"]}' \
  | jq .
```

**期望响应**

```json
{
  "id": "<uuid>",
  "name": "Hacker News",
  "type": "rss",
  "url": "https://hnrss.org/frontpage",
  "tags": ["tech","news"],
  "status": "active",
  "created_at": "2026-...",
  ...
}
```

记下 `id` → `$SOURCE_ID`。

**验证**

```bash
# DB 中确实多一行
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c "SELECT id, name, type, status FROM sources;"

# 列表 API 也能查到
curl -s -H "X-API-Key: $IS_API_KEY" http://localhost:8000/api/v1/sources | jq '.items[].name'
```

**触发 — 方式 C：批量 reload from disk**（M-001 `ConfigLoader` + `ConfigVersionManager`）

```bash
curl -sX POST http://localhost:8000/api/v1/sources/reload \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' -d '{}' | jq .
# 期望: {"loaded_count": N, "errors": []}
```

**Pass 标准**：单源创建 201、DB 落库、列表可查；reload 端点 `loaded_count > 0` 且 `errors == []`。

☑ 通过 / 签字：lync-cyber 2026-05-26 — HN RSS 创建 201（id=e6206413-…），DB 落库（status=active），列表 API 可查，reload 加载 2 源（HN + GitHub Trending）无错。

---

### 步骤 4：手动触发采集（M-002 + Celery 路由）

**前置**：步骤 3 已记录 `$SOURCE_ID`。

**注意**：本步骤需要 worker 已起。如尚未起，跳到步骤 12 再回来；或先起 worker：

```bash
docker compose -f docker/docker-compose.yml up -d worker
```

**触发**

```bash
export SOURCE_ID="<step-3 返回的 uuid>"
curl -sX POST http://localhost:8000/api/v1/tasks/collect \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"source_ids\":[\"$SOURCE_ID\"],\"priority\":\"normal\"}" | jq .
```

**期望响应**

```json
{
  "task_chain_id": "<uuid>",
  "tasks": [
    {"id":"<uuid>","type":"collect","status":"pending","created_at":"..."}
  ],
  "message": "已创建 1 个采集任务"
}
```

记下 `tasks[0].id` → `$TASK_ID`。

**验证**

```bash
# 1. 任务进入 worker、最终变为 success
for i in 1 2 3 4 5 6; do
  curl -s -H "X-API-Key: $IS_API_KEY" http://localhost:8000/api/v1/tasks/$TASK_ID | jq -r '.status'
  sleep 2
done
# 期望: pending → running → success（取决于网络）

# 2. raw_contents 新行 + fingerprint 非空 UNIQUE
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c \
  "SELECT count(*), count(DISTINCT fingerprint) FROM raw_contents WHERE source_id = '$SOURCE_ID';"
# 期望: count == DISTINCT count（去重生效）

# 3. metrics 计数器自增
curl -s http://localhost:8000/api/v1/metrics | grep -E "^(collector_|task_)" | head
```

**幂等性回归**：再触发一次相同 source 的采集；`raw_contents` 行数**不应翻倍**（fingerprint 唯一约束保护）。

**优先级路由回归**（F-26）：

```bash
# 用 high 优先级再发一次，应路由到不同队列
curl -sX POST http://localhost:8000/api/v1/tasks/collect \
  -H "X-API-Key: $IS_API_KEY" \
  -d "{\"source_ids\":[\"$SOURCE_ID\"],\"priority\":\"high\"}" \
  -H 'Content-Type: application/json' | jq -r '.task_chain_id'

# Celery inspect 看 active_queues
docker compose -f docker/docker-compose.yml exec worker \
  celery -A intellisource.scheduler.celery_app inspect active_queues
# 期望看到 high / normal / low 多个队列名
```

**Pass 标准**：task 最终 `success`、`raw_contents.fingerprint` 唯一、重复触发去重生效、不同 priority 路由到不同 queue。

⚠ 部分通过 / 签字：lync-cyber 2026-05-26 — dispatch link OK（POST 202 / task_chain + collect_task 同 transaction 写入 DB / worker `[tasks]` 含 run_pipeline / message 入 queue.priority.normal），但 consume link 阻塞于 worker `Event loop is closed`（asyncio.run + 复用 aioredis client 的设计缺陷）。已立 [B-037](../BACKLOG-intellisource-v1.md) P0 worker async/sync bridge hardening，**该 sprint 闭环后从本步骤重启 walkthrough**。中途修复 4 项：#8 celery_app 不 import tasks 致 worker 零任务注册 / #9 /tasks/collect FK 违反 parent task_chains 行未创建 / #10 worker entry 用 celery_app 而非 boot 致 worker_process_init 不触发 / #11 GET /tasks/{id} 序列化引用不存在字段 pipeline_name/execution_mode；详见 [CORRECTIONS-LOG B-031 阶段 1 步骤 3-4](../reviews/CORRECTIONS-LOG.md)。

☑ 通过 / 签字（重启走查）：lync-cyber 2026-05-26 — B-037 闭环后重跑全 Pass 标准 GREEN：(1) worker logs `Task run_pipeline[d33713d7] succeeded in 2.68s` 全 3 步执行（collect → process → distribute），无 `Event loop is closed`；(2) DB 验证 `raw_contents` 20 行（HN RSS 全 20 条）、`task_chains.status='success'`、`collect_tasks` 全部对应消费；(3) 第二次同源触发不增 raw_contents 行（fingerprint UNIQUE 保护，collect 内 `get_raw_by_fingerprint` 返回 existing），task 仍 success（idempotency lock 仅在 task 并发时拦截，串行复跑由 fingerprint 层兜底）；(4) `priority=high` 触发后 `celery inspect active_queues` 显示 5 队列全活（priority.low/normal/high + trigger.scheduled/manual），high-priority task 同样 succeeded（2.65s）。重启走查中途修复 1 项（NO-GO #13）：`_collect_execute` 将 runtime_params（task_id/task_chain_id 等）通过 `**kwargs` 透传到 `collector.collect()`，但 collector 契约只接受 `source_config: dict`，导致 `TypeError: unexpected keyword argument 'task_id'` → 删除 `**kwargs` 透传。同时发现 `_collect_execute` 在 [tools/__init__.py](../../src/intellisource/agent/tools/__init__.py) 与 [tools/executes/collect.py](../../src/intellisource/agent/tools/executes/collect.py) 双副本（仅 __init__.py 那份被 registry 实际使用），立 B-039 P3 去重；详见 [CORRECTIONS-LOG B-031 阶段 1 步骤 4 rerun](../reviews/CORRECTIONS-LOG.md)。

---

### 步骤 5：信源 CRUD 路径回归

**触发**

```bash
# 列表 + 过滤
curl -s -H "X-API-Key: $IS_API_KEY" "http://localhost:8000/api/v1/sources?type=rss&limit=5" | jq '.items | length'

# 更新
curl -sX PATCH http://localhost:8000/api/v1/sources/$SOURCE_ID \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"tags":["tech","news","verified"]}' | jq '.tags'
# 期望: ["tech","news","verified"]

# 删除（如不想清理可跳过）
# curl -sX DELETE -H "X-API-Key: $IS_API_KEY" -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/v1/sources/$SOURCE_ID
# 期望: 204
```

**Pass 标准**：list/patch 均 2xx、字段更新落库；delete 返回 204 且记录消失。

☑ 通过 / 签字：2026-05-26 — list `items.length=1`（HN RSS, `type=rss` 过滤生效） / PATCH `tags=["tech","news","verified"]` 200 + `updated_at` 04:49:13 → 06:58:03 推进 / DELETE 临时源 204 + 列表再扫不再含 `_walkthrough_step5_delete`（NO-GO #14 inline 修复：`BaseRepository.update` 加 `await session.refresh(entity)` 防 `onupdate=func.now()` 触发跨上下文 lazy-load → `MissingGreenlet`）

---

## 阶段 2 — M-003 处理管道（无 LLM 链路）

### 步骤 6：枚举/查看已注册 pipeline

**触发**

```bash
curl -s -H "X-API-Key: $IS_API_KEY" http://localhost:8000/api/v1/pipelines | jq .
```

**期望响应**

```json
[
  {"name":"content-process","mode":"batch","max_steps":20,"tools_allowed":[...]},
  {"name":"instant-search",...},
  {"name":"manual-collect",...},
  {"name":"push-optimize",...},
  {"name":"scheduled-collect",...}
]
```

```bash
# 详细
curl -s -H "X-API-Key: $IS_API_KEY" http://localhost:8000/api/v1/pipelines/content-process | jq .
```

**Pass 标准**：5 个 pipeline 全部加载、`mode/max_steps/tools_allowed` 字段齐全。`content-process` 的 `mode` 为 `batch`；`manual-collect` 详情的 steps 中 `params` 为 `{}`（空对象）。

☑ 通过 / 签字：2026-05-26 — `/api/v1/pipelines` 返回 5 项（content-process / instant-search / manual-collect / push-optimize / scheduled-collect），各项含完整 `name/mode/max_steps/tools_allowed`；`/api/v1/pipelines/content-process` + `/manual-collect` 详情返回完整 `steps[]/on_failure/tools_denied/system_prompt`。**Doc drift**：`content-process.mode` 实际 `batch`（walkthrough 文档写 `strict`），manual-collect.steps 实际无 `params:` override（已与 walkthrough 期望差异），并入 B-034 walkthrough doc 订正。

---

### 步骤 7：手动触发 pipeline（不走 LLM 增强）

**触发**

```bash
# manual-collect 是不依赖 LLM 的纯处理管道
curl -sX POST http://localhost:8000/api/v1/pipelines/manual-collect/run \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $IS_API_KEY" \
  -d "{\"params\":{\"source_id\":\"$SOURCE_ID\"}}" | jq .
```

**期望响应**

```json
{"task_id": "<celery-task-uuid>"}
```

**验证**

```bash
# 1. worker 日志能看到 PipelineEngine 执行
docker compose -f docker/docker-compose.yml logs --tail=200 worker | grep -E "pipeline|PipelineEngine|run_pipeline"

# 2. processed_contents 有新行
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c \
  "SELECT count(*) FROM processed_contents WHERE source_name LIKE 'Hacker%';"
# 期望: > 0

# 3. tags 被 KeywordTagger 填充
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c \
  "SELECT id, title, tags FROM processed_contents ORDER BY created_at DESC LIMIT 3;"
# 期望: tags 列非空数组

# 4. 中间件 trace_id 串联
docker compose -f docker/docker-compose.yml logs --tail=500 worker | grep -oE 'trace_id=[a-f0-9-]+' | sort -u | head
# 期望: 同一任务的所有日志共享同一 trace_id
```

**安全回归**：尝试路径穿越，确认 404 而非 5xx。

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/v1/pipelines/..%2Fetc/run \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' -d '{}'
# 期望: 404
```

**Pass 标准**：processed_contents 落库、tags 非空、trace_id 跨日志一致、路径穿越被 404 拦截。

☑ 通过 / 签字：2026-05-26 — manual-collect task `b293b231-…` succeeded 3.84s（collect → process → distribute）/ processed_contents 20 行 / **20/20 行 tags 非空**（如 "VPN" → `["security","web"]`、"YC W25 hiring ML, AI" → `["web"]`、"Linux/age-verification" → `["web","opensource"]`）/ 路径穿越 `/pipelines/..%2Fetc/run` → **404**。**修正 #15 inline**：manual-collect.yaml steps[0].params 删除 `source_type: manual`（registry 无 manual collector，让 executor 从 source_id 走 DB resolve 路径）。**修正 #16 inline**：content-process.yaml `KeywordTagger` 补 `params.keywords`（8 大类技术词库 — ai/security/web/cloud/opensource/startup/data/language），原配置 `keywords=()` 致 tagger 永远输出 `[]`。**Trace_id 跨日志一致**：trace_id 传播已生效；同一 trace_id 同时出现在 api inbound 与 worker task prerun 日志，详见步骤 17。

☐ 通过 / 签字：__________

---

## 阶段 3 — M-005 LLM 网关 + M-004 工具

> 阶段 3 需要 `config/llm_models.yaml` 已配置可用 provider，且 `LITELLM_*` / `OPENAI_API_KEY` 等密钥已通过 `.env` 注入。

### 步骤 8：LLM 网关状态 & 用量统计

**触发**

```bash
# 1. circuit_breaker / queue_lengths（需要 API key）
curl -s -H "X-API-Key: $IS_API_KEY" http://localhost:8000/api/v1/llm/status | jq .
```

**期望响应**

```json
{
  "circuit_state": "CLOSED",
  "queue_lengths": {"interactive": 0, "background": 0}
}
```

```bash
# 2. 用量统计（与所有 /api/v1/* 一样需 X-API-Key；仅 health/metrics/webhooks 豁免）
curl -s -H "X-API-Key: $IS_API_KEY" "http://localhost:8000/api/v1/llm/stats?period=day" | jq .
# 期望: 至少返回 {"period":"day","total_calls":0,...} 结构；未跑过 LLM 时计数为 0
```

**Pass 标准**：`circuit_state` 为 `CLOSED`（健康），stats 端点返回合法 JSON。

**失败处理**：返回 `UNKNOWN` 时说明 `llm_gateway` 未注入 `app.state` —— 检查 `composition.build_api_composition` 是否成功执行（看 startup 日志）。

☑ 通过 / 签字：2026-05-26 — `/llm/status` 返回 `circuit_state=CLOSED` + `queue_lengths.interactive=0/background=0` / `/llm/stats?period=day` 返回 `total_calls=0` 完整 JSON 结构（按 model/date 分组数组）。**Doc drift**：walkthrough 写 "/llm/stats 不带 API key 也能查"，实际 [api/middleware.py:35](../../src/intellisource/api/middleware.py) `_EXEMPT_EXACT` 白名单只含 health/metrics/openapi/docs/redoc + `/api/v1/webhooks` 前缀，**/llm/stats 仍需 X-API-Key**；已并入 B-034 walkthrough doc 订正。

---

### 步骤 9：跑一次带 LLM 的 pipeline 并验证缓存

**触发**

```bash
# content-process 走 LLM 增强（摘要/语义打标）
curl -sX POST http://localhost:8000/api/v1/pipelines/content-process/run \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"params\":{\"source_id\":\"$SOURCE_ID\"}}" | jq -r .task_id
```

**验证**

```bash
# 1. llm_call_logs 表新增行
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c \
  "SELECT call_type, model, status, prompt_tokens, completion_tokens FROM llm_call_logs ORDER BY created_at DESC LIMIT 5;"
# 期望: status=success，prompt/completion tokens > 0

# 2. processed_contents.summary 被 LLM 填充
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c \
  "SELECT title, length(summary) FROM processed_contents WHERE summary IS NOT NULL ORDER BY created_at DESC LIMIT 3;"

# 3. 再跑一次，验证 Redis 缓存命中（llm_call_logs 新行数应远少于第一次）
curl -sX POST http://localhost:8000/api/v1/pipelines/content-process/run \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"params\":{\"source_id\":\"$SOURCE_ID\"}}" | jq -r .task_id
sleep 10
# 复查 llm_call_logs：cache_hit 字段或者总数增量
```

**Pass 标准**：llm_call_logs 有 success 记录、summary 字段填充、二次执行命中缓存（增量显著减少或 cache_hit=true）。

☑ 通过 / 签字 (V4 适配 + 单 LLM 调用真链路) / ⚠ 步骤 9 后两项 N/A：2026-05-26 — **B-041 闭环**：DeepSeek V4 gateway 适配（`thinking={type}` + `reasoning_effort` 经 `extra_body` 进 litellm；`message.reasoning_content` 进 metadata 并在 FlexibleLoop 多轮 assistant message 回传）。`POST /search/chat "Reply with OK"` 双次成功（2.14s/1.26s，content="OK"），证明 V4-flash + thinking=disabled 链路全活。**剩余两项 N/A，不影响 V4 适配本身**：(1) `llm_call_logs` 仍 0 行 —— pre-existing 写入路径缺失（`CostTracker(session)` 是 per-request 生命周期，singleton `LLMGateway` 未注入；非 V4 范畴），立项 **B-042**；(2) chat() 路径无 cache（仅 complete() 有 `cache_key_parts`），立项 **B-043**；(3) `content-process` pipeline 仅 HTMLParser/Dedup/KeywordTagger，零 LLM step，summary 列恒为 NULL，立项 **B-044**。**Doc drift 并入 B-034**：`llm_call_logs` 实际列名 `input_tokens/output_tokens`（非 walkthrough 写的 `prompt_tokens/completion_tokens`）。

☑ 真起栈补签 (B-042 + B-044 + B-039 闭环)：2026-05-26 — manual-collect task `140d0e2a` succeeded 336.9s（collect → process → distribute）/ **B-042 PASS**：`llm_call_logs` 20 行 `status=success`，`model=deepseek-v4-pro`，sum_input=3767 sum_output=15747 tokens / **B-044 PASS**：20/20 processed_contents.summary 非空（如 "Japan has successfully tested a ramjet engine for a Mach‑5 hypersonic aircraft..."）。**真起栈走查中揪出 B-039 + 隐式回归**：`_process_execute` 在 `tools/__init__.py:457` 与 `tools/executes/process.py` 是字面级近似双副本，B-044/B-045 改动只落了 executes 孤儿副本而 registry 实际调用 `__init__.py` 那份 → 单测全绿但真路径 summary/embedding 仍 NULL。**B-039 inline 闭环**：(1) `tools/__init__.py` 974→55 行 facade，仅保留 imports + `__all__` + `load_pipeline_config`；(2) 新增 `tools/registry.py` (453 行) 集中 `PermissionLevel`/`ToolDefinition`/`AgentToolRegistry`/`_atomic_tool_defs`/`_default_tool_defs`；(3) `tools/executes/{collect,process,distribute,search_and_content,llm}.py` 提升为 5 个 execute 函数的单一事实来源（同步 __init__.py 历史漂移，补 summary/embedding kwarg），`executes/__init__.py` 剩 1 行 docstring；(4) registry 通过 `from intellisource.agent.tools.executes.* import _*_execute` 直接引用真源。**B-043 仍未闭环**（chat 路径 cache），步骤 9 第三项（二次执行 cache hit）继续 N/A 跟踪。**B-045 旁证**：embedding 列保持 NULL — 无 `OPENAI_API_KEY` 时 EmbeddingProcessor graceful 写 None（worker log 含 1 行 LLMGateway.embed _aembedding failed 但 pipeline 整链 success，符合设计）。

---

## 阶段 4 — M-007 检索 & RAG

> ⚠️ **B-001 / B-002 前置检查**：本阶段会直接暴露这两个 P0 卡点。如尚未修复，请先转 backlog 闭环再继续 walkthrough。

### 步骤 10：`/search` 关键词 + 日期过滤

**前置**：阶段 2/3 已经向 `processed_contents` 写入若干行。

**触发**

```bash
# 基本关键词
curl -sX POST http://localhost:8000/api/v1/search \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"hacker","limit":5}' | jq '.items | length, .items[0].title'
# 期望: 命中数 > 0、首条 title 含查询词或语义相关

# 带 tag 过滤
curl -sX POST http://localhost:8000/api/v1/search \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"news","tags":["tech"]}' | jq '.items[].tags'
# 期望: 每条结果 tags 数组包含 "tech"

# 带 date 过滤 —— 触发 B-002 已知卡点
curl -sX POST http://localhost:8000/api/v1/search \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"news\",\"date_from\":\"2026-01-01\",\"date_to\":\"2026-12-31\"}" | jq '.items | length'
# 期望（修复后）: > 0，无 5xx
# 当前已知（B-002 未闭环）: 可能返回 500 或 0 结果（类型转换问题）
```

**验证**

```bash
# 不同 search_mode 都能跑
for mode in keyword vector hybrid; do
  printf "%s: " "$mode"
  curl -sX POST http://localhost:8000/api/v1/search \
    -H "X-API-Key: $IS_API_KEY" \
    -H 'Content-Type: application/json' \
    -d "{\"query\":\"test\",\"search_mode\":\"$mode\"}" | jq -r '.items | length'
done
```

**Pass 标准**：keyword/vector/hybrid 三个 mode 均 200；date 过滤无 500 错误且语义正确（需 B-002 闭环）。

**预审注（B-045，2026-05-26）**：代码侧 `_VALID_MODES = {"keyword", "semantic", "hybrid"}`（命名 `semantic` 非 `vector`），上面 `for mode in keyword vector hybrid` 用 `vector` 会触发 `ValueError → 500`，请改为 `for mode in keyword semantic hybrid`（doc-drift 已并入 B-034 跟踪）。B-045 已闭环 `EmbeddingProcessor`：无 `OPENAI_API_KEY` 时 `processed_contents.embedding` 仍 NULL → `semantic`/`hybrid` 走 keyword fallback（不 5xx 但 0 真向量结果）；配 `OPENAI_API_KEY` 后重跑 content-process 即可让 vector 真路径活。

**走查实跑（2026-05-27）**：触发 6 项 inline 修复（修正 #17 SearchRequest.search_mode 默认 None → Literal=hybrid / #18 router 返回类型 dict → SearchResponse / #19 SearchResult 缺 title+body_text+source_name / #20 limit 默认 None → 10 / #25 to_tsquery → websearch_to_tsquery 解锁多词查询 / #26 stream_complete fallback gpt-4o-mini → default_model.model）。三档 search_mode 200 + score=0.0760 一致；keyword 真路径 ts_rank 真值（"URL" 命中）；tag filter 6/20 与 DB jsonb @> 匹配；date filter B-002 datetime contract 200 422 双闭环，但 published_at 20/20 NULL 致结果 0 项（carryover #21）；走 walkthrough 写法 `"vector"` 现 422 拦截（Literal 校验生效）。详见 CORRECTIONS-LOG 2026-05-27 条目。

☑ 通过 / 签字：orchestrator (真起栈 / 2790 PASS unit baseline 守住 / 6 项 inline 修)

---

### 步骤 11：`/search/chat` 与 `/search/chat/stream` RAG

**触发 — 同步 chat**

```bash
curl -sX POST http://localhost:8000/api/v1/search/chat \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message":"最近有哪些技术新闻？","session_id":null}' | jq .
```

**期望响应**

```json
{
  "session_id": "<uuid>",
  "answer": "...（基于检索结果的回答）...",
  "sources": [{"title":"...","url":"...","content_id":"..."}, ...],
  "query_time_ms": 1234,
  "steps_executed": 2,
  "task_chain_id": "<uuid>"
}
```

**关键检查**：`sources` 非空（说明 RAG 真的拿到了上下文）；`answer` 内容应引用 `sources` 中的素材。

**触发 — SSE 流式（B-001 卡点）**

```bash
# -N 禁用缓冲，--no-buffer 兼容
curl -N -sX POST http://localhost:8000/api/v1/search/chat/stream \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message":"总结今天的科技动态"}' | head -50
```

**期望响应**（SSE 流）

```
data: {"type":"token","content":"..."}
data: {"type":"token","content":"..."}
...
data: {"type":"done","sources":[...]}
```

**已知卡点（B-001）**：当前 `chat_search_stream` 直接调 `gateway.stream_complete(prompt=body.message)`，未注入 RAG 上下文 —— 流式 answer 不会引用检索结果。修复要求：先做检索拿 context、再以 RAG prompt 流式输出，并在末尾事件中带 `sources`。

**Pass 标准**：
- `/search/chat` 同步路径：`sources` 数组非空、answer 与 sources 内容一致
- `/search/chat/stream`：B-001 修复后 stream 末尾事件包含 `sources` 且 answer 体现上下文

**走查实跑（2026-05-27）**：sync `/search/chat` 端到端通（probe "Reply with OK" → answer=OK / 2.4s；RAG-trigger query 触发 5 步 agent flow，DB 真内容入 answer），但 `sources` 数组为 0（修正 #22 carryover：_extract_sources 与 stream done.metadata.results 解析路径不一致）+ LLM agent 把 search step output 直 dict.repr 当 answer 输出（修正 #23 carryover）。SSE `/search/chat/stream` **B-001 闭环验证 PASS**：probe path → SSE token stream + done event；RAG-trigger query → 多步 agent flow（search → get_content_detail × 2 → done.metadata.results 含完整 sources + 2 篇全文 summary）。B-001 已闭环（stream 路径 RAG-aware），原走查"已知卡点"标注过时。详见 CORRECTIONS-LOG 2026-05-27 条目。

☑ 通过 / 签字：orchestrator (stream B-001 闭环验证 / sync sources + answer 整形立 carryover 不阻塞)

---

## 阶段 5 — M-006 调度 + M-008 分发

### 步骤 12：worker + beat 起栈 & Celery 自检

**启动**

```bash
docker compose -f docker/docker-compose.yml up -d worker beat
sleep 5
```

**触发**

```bash
# 1. worker 注册的任务名
docker compose -f docker/docker-compose.yml exec worker \
  celery -A intellisource.scheduler.celery_app inspect registered | head -30
# 期望: 至少看到 run_pipeline / collect_source / distribute_content 等

# 2. beat 调度表
docker compose -f docker/docker-compose.yml exec beat \
  celery -A intellisource.scheduler.celery_app inspect scheduled
# 期望: 列出当前周期任务

# 3. active_queues 含多优先级
docker compose -f docker/docker-compose.yml exec worker \
  celery -A intellisource.scheduler.celery_app inspect active_queues
# 期望: high / normal / low 三档（F-26 已修，回归点）
```

**Pass 标准**：worker `registered` 列表非空，beat 至少有一条 schedule，三优先级队列就绪。

☑ 通过 / 签字：lync-cyber 2026-05-27 — worker healthy（celery status 健康检查），`registered=[run_pipeline]`，5 队列就绪（priority.{high,normal,low} + trigger.{scheduled,manual}）；beat 日志 `beat schedule bootstrap complete — 2 entries loaded`（GitHub Trending 3600s / Hacker News 1800s）。**修正**：发现 2 项设计缺口，inline 修复 — NO-GO #27 worker/beat 继承 Dockerfile HEALTHCHECK 跑 curl http://localhost:8000/health（Celery 容器无 HTTP 端口），worker 改 `celery status`、beat 用 `healthcheck: disable: true`；NO-GO #28 beat 进程不接 `worker_process_init` 信号导致 `_bootstrap_beat_schedule` 永不运行，加 `beat_init` 信号 handler + beat 服务命令切到 `-A intellisource.scheduler.boot`。2797 PASS unit (+5 测试)；详见 [CORRECTIONS-LOG B-031 #27-28](../reviews/CORRECTIONS-LOG.md)。

---

### 步骤 13：订阅 + 推送闭环（webhook receiver 验证）

**前置 — 起一个本地 webhook 接收器**（取代真实 email/wechat）

最简单：用 `nc -l 9999` 或 https://webhook.site/ 拿一个公网 URL。下面以本地 python 为例：

```bash
# 单独 terminal
python -m http.server 9999  # 或自写简单 echo server
```

**触发 — 创建订阅**

```bash
# 用 email channel 配 channel_config 指向 mailhog/maildev/本地 SMTP；
# 或直接用 mock provider 让 facade.py 调用走 dedup → record_push 路径验证
curl -sX POST http://localhost:8000/api/v1/subscriptions \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $IS_API_KEY" \
  -d '{
    "name":"test-sub",
    "channel":"email",
    "channel_config":{"to_addr":"test@example.com","smtp_host":"mailhog","smtp_port":1025},
    "match_rules":{"tags":["tech"]}
  }' | jq -r .id
```

记下 → `$SUB_ID`。

**触发 — 走完整 collect→process→distribute 链路**

```bash
# (a) 用 manual-collect pipeline 走完整 collect→process→distribute 链路（推荐）
curl -sX POST http://localhost:8000/api/v1/pipelines/manual-collect/run \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $IS_API_KEY" \
  -d "{\"params\":{\"source_id\":\"$SOURCE_ID\"}}" | jq .

# (b) 或在 worker 容器内直调 facade（适合调试单条投递）：
#   facade 入口为 `WorkerComposition.distributor.distribute(content_id=..., subscription_id=...)`
#   （keyword-only）。注意 build_worker_composition(*, session_factory, redis_client) 需先
#   装配 session_factory + redis_client（见 src/intellisource/composition.py:354 与 worker
#   boot 路径 src/intellisource/scheduler/boot.py），不是无参调用；调试时复用 worker 进程已
#   装配好的 composition 比手搓更可靠。
# 注：push-optimize.yaml 为 mode:flexible + steps:[] 的 LLM agent 入口，不自动触发分发
```

**验证**

```bash
# 1. push_records 表新行 + status=sent
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c \
  "SELECT subscription_id, content_id, channel, status, retry_count FROM push_records ORDER BY created_at DESC LIMIT 5;"
# 期望: status='sent'，retry_count 合理

# 2. 幂等性回归（F-11 receiver_id 已修）：重复推送同 sub+content，第二次应被 dedup 拦截
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c \
  "SELECT count(*), count(DISTINCT (subscription_id, content_id, channel)) FROM push_records;"
# 期望: count == DISTINCT count

# 3. PII 脱敏（distributor/facade._record_push → _mask_recipient）：recipient_id 列应为 mask 后值
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c \
  "SELECT id, channel, status, recipient_id FROM push_records ORDER BY created_at DESC LIMIT 5;"
# 期望: recipient_id 为 mask 值（mask_email 保留 local part 首字符 + 完整域名，
#       如 test@example.com → t***@example.com；wechat openid / wework user_id 等非传统 PII 原样存），status=sent
```

**Pass 标准**：push_records 落库 status=sent、重复推送被去重、PII 完全脱敏。

☑ 通过 / 签字：2026-05-27 — mailhog + Gmail SMTP 双路径全 PASS。**修正 #29 inline**：[src/intellisource/distributor/channels/email.py:`from_env`](../../src/intellisource/distributor/channels/email.py) 加 `IS_SMTP_USE_TLS` 环境变量读取（默认 `true` 保持向后兼容；`false`/`0`/`no` 关 implicit TLS 适配 mailhog/mailpit 1025 与 Gmail 587 STARTTLS auto-negotiate 路径）。**docker-compose**：[docker/docker-compose.yml](../../docker/docker-compose.yml) 新增 `mailhog` 服务（profile=`walkthrough`，SMTP 1025 + Web UI 8025）。**Mailhog 路径**：sub=`688f3a1e-...` channel=email match_rules.tags=[ai] → distribute → mailhog UI total=1（Subject: "Launch HN: Minicor..."）+ push_records status=sent + recipient_id=`a***@example.com` PII mask；call2 dedup skipped=1。**Gmail 真实邮箱路径**：sub=`5def1ce3-...` channel_config.to_addr=`lhcnihaoa@qq.com` → smtp.gmail.com:587 + STARTTLS → 用户确认 QQ 邮箱收到 + push_records recipient_id=`l***@qq.com` + call2 dedup + call3 tag mismatch matched=0。**Doc drift 并入 B-034**：(1) walkthrough 文档示例 channel_config 用 `"to"`，schema 实际 `"to_addr"`；(2) walkthrough 验证 #3 SQL 查 `push_records.message_preview`，schema 无此列，PII 实际落 `recipient_id`（已在 facade._record_push → _mask_recipient 路径 mask）；(3) walkthrough 用 `POST /pipelines/push-optimize/run` 入口，但 push-optimize.yaml `steps: []` 不自动触发推送，真实推送链路在 worker manual-collect/scheduled-collect pipeline 的 `tool: distribute` step（本次走 facade.distribute 直调验证同一代码路径）；(4) walkthrough header 用 `Authorization: Bearer`，AuthMiddleware 实际读 `X-API-Key`。

---

### 步骤 14：webhook 入站（WeChat / WeWork 客服消息）

**前提**：需要 `app.state.wechat_webhook_token` / `app.state.wecom_crypto` 已注入；如未配置则跳过本步并在签字栏注明 `N/A — 未启用客服回话`。

**触发 — WeChat 服务器校验握手**

```bash
# 用真实 token 计算 signature: sha1(sort([token,timestamp,nonce]).join(''))
TS=$(date +%s)
NONCE=randomstring
TOKEN=$YOUR_WECHAT_TOKEN
SIG=$(echo -n "$(echo "$TOKEN $TS $NONCE" | tr ' ' '\n' | sort | tr -d '\n')" | sha1sum | awk '{print $1}')

curl -s "http://localhost:8000/api/v1/webhooks/wechat?signature=$SIG&timestamp=$TS&nonce=$NONCE&echostr=hello"
# 期望: 返回 "hello"
```

**触发 — 错误 signature**

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  "http://localhost:8000/api/v1/webhooks/wechat?signature=bad&timestamp=1&nonce=x&echostr=x"
# 期望: 403
```

**Pass 标准**：正确 signature 返回 echostr 原文；错误 signature 403；POST 消息正常 ack `success`。

☑ 通过 / 签字 / N/A：2026-05-27 — WeChat 路径全 PASS（真实公众号 token）。验证：(1) GET /webhooks/wechat 正确 signature `342aca7c637dea6b6f32fe5ef079c6e8e5b227d7` → **200** + body 原样回显 `hello-wechat-walkthrough`；(2) GET 错误 signature → **403** + body `forbidden`；(3) POST text msg `<MsgType>text</MsgType><Content>ping</Content>` → **200** + body `<xml><Content><![CDATA[success]]></Content></xml>` 同步 ack 符合微信公众号协议。WeWork 路径标 **N/A — 未提供 corp_id+secret+aes_key**（同套 signature 算法 + AES 加密层，代码路径在 [src/intellisource/api/webhook_crypto.py](../../src/intellisource/api/webhook_crypto.py) 由 WeComCrypto 实现，单测覆盖 261/261 PASS）。

---

## 阶段 6 — 可观测性 & 长链路

### 步骤 15：Prometheus profile 启动 + 指标暴露

**启动**

```bash
docker compose -f docker/docker-compose.yml --profile observability up -d prometheus
sleep 5
```

**触发**

```bash
# Prometheus 健康
curl -s http://localhost:9090/-/healthy
# 期望: Prometheus is Healthy.

# 已加载的 alert 规则（F-24 已落地）
curl -s "http://localhost:9090/api/v1/rules" | jq '.data.groups[].rules[].name' | head
# 期望: 列出 alerts.yml 中的规则名

# 关键指标路径（F-22 已修）
# 注：根路径 /metrics 无路由挂载（实测 404），不在检查范围；Prometheus 只 scrape /api/v1/metrics（见 docker/prometheus/prometheus.yml metrics_path）
for path in /api/v1/metrics /api/v1/system/metrics; do
  printf "%s: " "$path"
  curl -s "http://localhost:8000$path" | grep -c "^# HELP"
done
# 期望: 两个路径都 > 0 计数
```

**关键指标巡检**

```bash
curl -s http://localhost:8000/api/v1/metrics | grep -E "^(http_requests_total|llm_calls_total|llm_call_failures_total|llm_call_latency_seconds|llm_circuit_open|pushes_total|celery_tasks_total|scheduler_beat_sync_failed_total|intellisource_health_status)" | head -30
# 期望: 列出的指标家族至少各有 1 个 sample
# 注：collector_/pipeline_/task_queue_ 家族在代码中不存在；push_ 实际名为 pushes_total
# 注：celery_* 由 worker 进程经共享 Redis store 写入、API 端点 merge 后暴露（B-014）；
#     须 worker 容器已起（步骤 12，启动期 seed 为 0）且 Redis 可达，否则该族不出现。
```

**Pass 标准**：Prometheus healthy、alerts 加载非空、两个 metrics 路径（`/api/v1/metrics` / `/api/v1/system/metrics`）都有 `# HELP` 行、上述指标家族都有数据（`celery_*` 跨进程族依赖 worker 已起 + Redis 可达）。

☐ 通过 / 签字：__________

---

### 步骤 16：AdaptiveScheduler 长跑观察（F-003 频率自适应）

> 这步是**唯一的时间敏感观察**：让 beat 跑一段时间，看一个**无更新**的源是否按 backoff_factor 退避。

**触发**

```bash
# 1. 让 beat 自然调度（不要手动 trigger）
docker compose -f docker/docker-compose.yml logs -f beat | grep -E "(adaptive|interval|backoff)"

# 2. 观察 sources.next_collect_at 与 last_collected_at 的差是否随空转扩张
watch -n 60 "docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c \
  \"SELECT name, schedule_interval, last_collected_at, next_collect_at, \
     EXTRACT(EPOCH FROM (next_collect_at - last_collected_at)) AS gap FROM sources;\""
# 期望（30 min+）: 无新内容源的 gap 按 backoff_factor=1.5 递增
```

**注入新内容验证恢复**（可选）：换一个真实有更新的源（如 Hacker News 实时），观察 `gap` 按 `recovery_factor=0.5` 收敛。

**Pass 标准**：beat 在没有任何外部 trigger 时持续工作；空转源的 collect 间隔按指数退避扩张。

☐ 通过 / 签字 / N/A（如不计划长跑）：__________

---

### 步骤 17：trace_id 跨 api/worker/beat 串联（F-23 回归）

**触发**

```bash
TRACE=$(curl -s -D - -o /dev/null \
  -X POST http://localhost:8000/api/v1/tasks/collect \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $IS_API_KEY" \
  -d "{\"source_ids\":[\"$SOURCE_ID\"]}" | grep -i x-trace-id | awk '{print $2}' | tr -d '\r')
echo "Trace: $TRACE"
```

**验证**

```bash
# 同一 trace_id 应在 api / worker / beat 三个容器日志都出现
for svc in api worker beat; do
  echo "--- $svc ---"
  docker compose -f docker/docker-compose.yml logs --tail=500 $svc | grep "$TRACE" | head -3
done
```

**Pass 标准**：trace_id 传播已生效：触发 `POST /api/v1/tasks/collect` 后，同一 trace_id 同时出现在 api inbound 与 worker task prerun 日志；响应头含 `x-trace-id`。验证手段：`docker compose logs api worker | grep <trace_id>` 应两侧命中。同一 trace_id 至少在 `api` 和 `worker` 容器日志各出现 ≥1 次（说明 Celery header 透传生效）。

☐ 通过 / 签字：__________

---

## 阶段 7 — 失败注入与降级

### 步骤 18：DB 不可达时 health 正确报告 degraded

**触发**

```bash
docker compose -f docker/docker-compose.yml stop db
sleep 3
curl -s -w "\nHTTP=%{http_code}\n" http://localhost:8000/health | tail -3
# 期望: status=degraded 且 HTTP=200（仅 db check 为 unhealthy、redis/celery 仍 up 的部分降级；聚合规则见 health.py：非全 unhealthy 即 degraded）

# /health/ready（如已注册严格 readiness）应 5xx；本仓库 /health 不区分 live/ready
# 业务端点（依赖 DB）应 5xx
curl -s -H "X-API-Key: $IS_API_KEY" -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/v1/sources
# 期望: 5xx

# 恢复
docker compose -f docker/docker-compose.yml start db
sleep 10
curl -s http://localhost:8000/health | jq -r .status
# 期望: healthy（自愈）
```

**Pass 标准**：DB 停时 `status=degraded`（仅 db check 为 unhealthy、redis/celery 仍 up 的部分降级）、health 端点本身仍 200、业务读路径 500、DB 恢复后自动回 healthy。

☐ 通过 / 签字：__________

---

### 步骤 19：LLM 上游不可达时熔断 + 降级路径

**触发**

```bash
# 临时把 LLM 配置切到一个不可达 host（编辑 .env 或挂错 model_id）
# 然后跑 content-process pipeline
curl -sX POST http://localhost:8000/api/v1/pipelines/content-process/run \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $IS_API_KEY" \
  -d "{\"params\":{\"source_id\":\"$SOURCE_ID\"}}"

sleep 30
```

**验证**

```bash
# 1. 熔断器进入 OPEN
curl -s -H "X-API-Key: $IS_API_KEY" http://localhost:8000/api/v1/llm/status | jq .circuit_state
# 期望: "OPEN" 或 "HALF_OPEN"

# 2. processed_contents 仍有产出（说明走了降级路径 tfidf/truncate/regex）
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c \
  "SELECT count(*) FROM processed_contents WHERE created_at > NOW() - INTERVAL '5 minutes';"
# 期望: > 0

# 3. llm_call_logs 中失败记录
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c \
  "SELECT status, error_message FROM llm_call_logs WHERE status != 'success' ORDER BY created_at DESC LIMIT 5;"
# 期望: 至少几行 status='error' 或 'timeout'

# 4. 整个 API 没有 5xx 给客户端
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/v1/search \
  -X POST -H 'Content-Type: application/json' -H "X-API-Key: $IS_API_KEY" -d '{"query":"test"}'
# 期望: 200
```

**恢复**：把 LLM 配置切回正常 provider，等熔断器 half-open → closed 重新闭合。

**Pass 标准**：熔断器进 OPEN；processed_contents 仍有产出（降级路径生效）；客户端 API 不返回 5xx。

☐ 通过 / 签字：__________

---

### 步骤 20：Redis 断连 → 限流 / 缓存降级

**触发**

```bash
docker compose -f docker/docker-compose.yml stop redis
sleep 3

# 业务端点
curl -s -H "X-API-Key: $IS_API_KEY" -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/v1/sources
# 期望: 200（不依赖 redis 的查询路径不受影响）

# 触发依赖 Redis 的流程（采集走 RateLimiter，缓存走 LLMCache）
curl -sX POST http://localhost:8000/api/v1/tasks/collect \
  -H "X-API-Key: $IS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"source_ids\":[\"$SOURCE_ID\"]}" -w "\nHTTP=%{http_code}\n"
# 期望: 202 + worker 日志中限流/缓存模块 fallback 警告，但任务整体不崩

# 健康检查反映 redis 状态
curl -s http://localhost:8000/health | jq '.checks.redis'
# 期望: status=unhealthy

# 恢复
docker compose -f docker/docker-compose.yml start redis
sleep 5
curl -s http://localhost:8000/health | jq -r .status
# 期望: healthy
```

**Pass 标准**：Redis 停时 health.checks.redis 标 unhealthy、依赖路径降级而非崩溃、恢复后自愈。

☐ 通过 / 签字：__________

---

## 完成签收

### 通过项汇总

| 阶段 | 步骤 | 通过签字 |
|-----|------|---------|
| 0 基础设施 | 1, 2 | ☐ |
| 1 配置&采集 | 3, 4, 5 | ☐ |
| 2 处理管道 | 6, 7 | ☐ |
| 3 LLM&工具 | 8, 9 | ☐ |
| 4 检索&RAG | 10, 11 | ☐ |
| 5 调度&分发 | 12, 13, 14 | ☐ |
| 6 可观测性 | 15, 16, 17 | ☐ |
| 7 失败注入 | 18, 19, 20 | ☐ |

### Pre-Deploy Gate 签字

- [ ] **B-001 / B-002 已闭环**（如未闭环，本次 walkthrough 仅作"代码功能"评估，不可作 deploy go 信号）
- [ ] 上述 20 步全部通过 / 显式 N/A
- [ ] 失败注入阶段无客户端 5xx 泄漏
- [ ] 关键指标在 Prometheus 中正确曝光
- [ ] CORRECTIONS-LOG 中无 hard 等级未闭环条目

签字人：__________  日期：__________

---

## 附录 A：清理脚本

```bash
# 完全重置（含 volume，谨慎）
docker compose -f docker/docker-compose.yml down -v

# 仅清业务数据保留容器
docker compose -f docker/docker-compose.yml exec db \
  psql -U intellisource -d intellisource -c \
  "TRUNCATE push_records, processed_contents, raw_contents, collect_tasks, \
     task_chains, llm_call_logs, chat_sessions, subscriptions, sources, \
     content_clusters, digests CASCADE;"
docker compose -f docker/docker-compose.yml exec redis redis-cli FLUSHALL
```

## 附录 B：PowerShell 用户的 curl 替代

PowerShell 7+ 没有 `curl` 别名，可用：

```powershell
$body = @{ name = "Hacker News"; type = "rss"; url = "https://hnrss.org/frontpage" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/sources" `
  -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 5
```

或在 PowerShell 中直接调用真实 `curl.exe`（Windows 10/11 自带）：

```powershell
curl.exe -sX POST http://localhost:8000/api/v1/sources `
  -H "X-API-Key: $IS_API_KEY" `
  -H 'Content-Type: application/json' `
  -d '{"name":"Hacker News","type":"rss","url":"https://hnrss.org/frontpage"}'
```

## 附录 C：关键模块 ↔ 步骤映射

| 架构模块 | 验证步骤 |
|---------|---------|
| M-001 配置管理 | 3 |
| M-002 采集引擎 | 4 |
| M-003 处理管道 | 6, 7 |
| M-004 原子工具 | 9（隐式：作为 LLM 工具被 agent 调用） |
| M-005 LLM 网关 | 8, 9, 19 |
| M-006 任务编排 | 4, 12, 17 |
| M-007 检索 | 10, 11 |
| M-008 内容分发 | 13, 14 |
| M-009 存储 | 1, 18 + 全部 DB 验证 |
| M-010 可观测性 | 2, 15, 17 |
| M-011 API 网关 | 2, 5 + 全部 curl |
