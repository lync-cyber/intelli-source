---
id: "deploy-spec-intellisource-v1"
version: "1.0.0"
doc_type: deploy-spec
author: devops
status: approved
deps: ["arch-intellisource-v1"]
consumers: [devops]
volume: main
required_sections:
  - "## 1. 构建流程"
  - "## 2. 环境配置"
  - "## 3. CI/CD流水线"
  - "## 4. 发布检查清单"
---
# Deployment Specification: IntelliSource v1

[NAV]
- §1 构建流程 — 前置条件、镜像构建、SBOM、漏洞扫描
- §2 环境配置 — 部署架构、env 矩阵 (dev/staging/prod)、环境变量清单、密钥、容量
- §3 CI/CD流水线 — Pipeline 阶段、staging/prod 发布、Smoke、监控告警、回滚 SOP
- §4 发布检查清单 — 上线门禁逐项签字
[/NAV]

---

## 1. 构建流程

### 1.1 前置条件

- Docker Engine ≥ 24.x + Docker Compose v2
- 目标主机有 `docker/.env`（从 `docker/.env.example` 复制并填写）
- `config/llm_models.yaml` 已配置可用 provider
- `config/sources/` 目录下至少有一个有效 YAML 信源配置
- 仓库根目录可访问（构建上下文 `context: ..`，`docker/Dockerfile` 内路径相对根目录）
- **DB 镜像必须包含 zhparser 扩展**：`alembic/versions/001_initial_schema.py` 初始化时执行 `CREATE EXTENSION IF NOT EXISTS zhparser`（中文全文检索依赖）。标准 `pgvector/pgvector:pg16` 镜像不预装 zhparser，需使用包含 zhparser 的自定义 PostgreSQL 镜像，或在容器首次启动后、执行迁移前手动安装（参见 arch#§1.4 技术栈说明）。

### 1.2 镜像构建

```bash
# 在仓库根目录执行
docker build -f docker/Dockerfile -t intellisource:${GIT_SHA_SHORT} .

# 多阶段构建说明：
#   Stage 1 (builder): python:3.11-slim + uv sync --frozen --no-dev
#   Stage 2 (runtime): python:3.11-slim + venv copy + src/ + config/ + alembic/
```

**注意**：构建上下文为仓库根目录（`context: ..`），`docker/Dockerfile` 内路径均相对于根目录。

### 1.3 SBOM 生成

每次构建必须生成 SBOM（Software Bill of Materials），随每次发布归档作为供应链安全证据。

```bash
# 选项 A：使用 syft 生成 CycloneDX JSON 格式 SBOM
syft intellisource:${GIT_SHA_SHORT} -o cyclonedx-json > sbom-${GIT_SHA_SHORT}.json

# 选项 B：使用 Docker BuildKit 内置 SBOM（需 buildx）
docker buildx build \
  --sbom=true \
  --output type=image,name=intellisource:${GIT_SHA_SHORT} \
  -f docker/Dockerfile .
```

### 1.4 容器镜像漏洞扫描（门禁）

上线门禁：任何 HIGH / CRITICAL CVE 未确认即合并属于 release blocker。

```bash
# 使用 trivy 扫描镜像
trivy image --severity HIGH,CRITICAL intellisource:${GIT_SHA_SHORT}
# 期望：exit code 0（无 HIGH/CRITICAL）

# 或使用 grype
grype intellisource:${GIT_SHA_SHORT} --fail-on high
# 期望：exit code 0
```

CI 中集成扫描步骤，扫描失败（发现 HIGH/CRITICAL 漏洞）阻塞合并。发现漏洞时：

1. 评估 CVE 是否影响 IntelliSource 的使用场景（上下文豁免需有书面记录）
2. 如影响，升级依赖包或基础镜像后重新扫描
3. 豁免条目必须记录在 CORRECTIONS-LOG 并附 CVE 编号和豁免原因

---

## 2. 环境配置

### 2.1 部署架构

IntelliSource 由 6 个容器组成，通过 Docker Compose 单主机编排；Prometheus 为可选 observability 组件（`--profile observability` 启用）。

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Host                                                                    │
│                                                                          │
│  ┌──────────┐   HTTP:8000    ┌─────────────────────┐                    │
│  │  Client  │ ─────────────▶ │  api (FastAPI)       │                   │
│  └──────────┘                │  uvicorn 0.0.0.0:8000│                   │
│                              └────────┬────────────┘                    │
│                                       │ depends_on (healthy)            │
│         ┌─────────────────────────────┼─────────────────┐               │
│         │                             │                 │               │
│  ┌──────▼──────┐           ┌──────────▼──────┐  ┌───────▼──────┐       │
│  │  db          │           │  redis:7-alpine │  │  worker      │       │
│  │  pgvector    │           │  db=0: broker   │  │  Celery      │       │
│  │  pg16        │           │  db=1: results  │  │  worker -l   │       │
│  └─────────────┘           └─────────────────┘  └──────────────┘       │
│         │                                                                │
│  ┌──────▼──────┐           ┌─────────────────┐                          │
│  │  migrate     │           │  beat            │                        │
│  │  alembic     │           │  Celery beat     │                        │
│  │  exit(0)     │           │  scheduler       │                        │
│  └─────────────┘           └─────────────────┘                          │
│                                                                          │
│  ─ ─ ─ ─  profile: observability  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─               │
│  ┌──────────────────────────┐                                            │
│  │  prometheus:v2.55.1      │  scrape: api:8000/api/v1/metrics          │
│  │  port 9090               │  rules:  /etc/prometheus/alerts.yml       │
│  └──────────────────────────┘                                            │
└──────────────────────────────────────────────────────────────────────────┘
```

#### 网络端口

| 服务 | 容器端口 | 宿主机端口 | 说明 |
|------|---------|-----------|------|
| api | 8000 | 8000 | HTTP API + /metrics |
| prometheus | 9090 | 9090 | observability profile 启用时 |
| db | 5432 | 不对外暴露 | 仅 Docker 内部网络 |
| redis | 6379 | 不对外暴露 | 仅 Docker 内部网络 |

### 2.2 环境差异矩阵 (dev / staging / prod)

| 维度 | dev | staging | prod |
|------|-----|---------|------|
| 镜像 tag | `intellisource:dev`（本地构建） | `intellisource:${GIT_SHA_SHORT}-staging` | `intellisource:${RELEASE_TAG}` |
| 副本数 (api) | 1 | 1 | 建议 2+（负载均衡前置）|
| 副本数 (worker) | 1 | 1 | 建议 2+（并发 task 吞吐）|
| 日志级别 | `DEBUG` | `DEBUG` 可选 | `INFO` |
| LLM API Key | 个人 dev key / mock | staging 专用 key（独立配额）| prod key |
| DB 数据 | 本地 docker volume | staging 独立库，可定期从 prod 脱敏同步 | prod |
| Prometheus | 通常不启用 | 可启用 | 建议启用 + Alertmanager 接入 |
| `IS_PUSH_OPTIMIZE_ENABLED` | `0` | `0`（避免误推） | 按需 `0`/`1` |
| 数据库迁移 | 开发者本地执行 | 自动 (CI) | 灰度前手动确认 |
| pre_deploy 检查点 | N/A | 自动通过 smoke 即可 | 必须人工 go/no-go 签字 |

### 2.3 环境变量清单

所有变量使用 `IS_` 前缀（arch#§7.1 约定）。将 `docker/.env.example` 复制为 `docker/.env` 并填入真实值后，`docker compose` 会自动加载。

**注意**：`docker/.env` 含有敏感凭据，绝不提交到版本控制（已列入 `.gitignore`）。

#### 数据库

| 变量名 | 必填 | 默认值 | 敏感度 | 说明 |
|--------|------|--------|--------|------|
| `IS_DATABASE_URL` | 是 | `postgresql+asyncpg://intellisource:intellisource@db:5432/intellisource` | HIGH | 完整异步 DSN；设置后覆盖 IS_DB_* 默认值 |
| `IS_DB_USER` | 是 | `intellisource` | MEDIUM | PostgreSQL 用户名 |
| `IS_DB_PASSWORD` | 是 | `intellisource` | HIGH | PostgreSQL 密码；生产环境必须替换 |
| `IS_DB_NAME` | 是 | `intellisource` | LOW | 数据库名 |

#### Redis / Celery

| 变量名 | 必填 | 默认值 | 敏感度 | 说明 |
|--------|------|--------|--------|------|
| `IS_REDIS_URL` | 是 | `redis://redis:6379/0` | LOW | Redis 连接 URL（API + 缓存）|
| `IS_CELERY_BROKER_URL` | 是 | `redis://redis:6379/0` | LOW | Celery broker（db=0）|
| `IS_CELERY_RESULT_BACKEND` | 是 | `redis://redis:6379/1` | LOW | Celery 结果后端（db=1）|

#### API 鉴权

| 变量名 | 必填 | 默认值 | 敏感度 | 说明 |
|--------|------|--------|--------|------|
| `IS_API_KEY` | 是 | `change-me-in-production` | HIGH | Bearer token，保护 `/api/v1/*` 受保护端点；生产环境必须替换为强随机字符串 |

#### LLM 配置

| 变量名 | 必填 | 默认值 | 敏感度 | 说明 |
|--------|------|--------|--------|------|
| `IS_LLM_CONFIG_PATH` | 否 | `config/llm_models.yaml` | LOW | 模型路由配置文件路径（容器内相对路径）|
| `IS_LLM_DEFAULT_MODEL` | 否 | — | LOW | 覆盖默认模型（如 `gpt-4o`）|
| `OPENAI_API_KEY` | 条件必填 | — | HIGH | 使用 OpenAI provider 时必填；格式 `sk-...` |
| `ANTHROPIC_API_KEY` | 条件必填 | — | HIGH | 使用 Anthropic provider 时必填；格式 `sk-ant-...` |
| `AZURE_API_KEY` | 条件必填 | — | HIGH | 使用 Azure OpenAI 时必填 |
| `AZURE_API_BASE` | 条件必填 | — | MEDIUM | Azure 端点 URL |
| `AZURE_API_VERSION` | 条件必填 | — | LOW | Azure API 版本（如 `2024-02-01`）|

#### 信源配置

| 变量名 | 必填 | 默认值 | 敏感度 | 说明 |
|--------|------|--------|--------|------|
| `IS_SOURCE_CONFIG_DIR` | 否 | `config/sources` | LOW | 信源 YAML 文件目录（容器内路径）|

#### 可观测性

| 变量名 | 必填 | 默认值 | 敏感度 | 说明 |
|--------|------|--------|--------|------|
| `IS_LOG_LEVEL` | 否 | `INFO` | LOW | 日志级别：DEBUG / INFO / WARNING / ERROR |

#### 分发渠道（均选填，留空则禁用对应渠道）

| 变量名 | 敏感度 | 说明 |
|--------|--------|------|
| `IS_WECHAT_APP_ID` | MEDIUM | 微信公众号 AppID |
| `IS_WECHAT_APP_SECRET` | HIGH | 微信公众号 AppSecret |
| `IS_WECHAT_WEBHOOK_TOKEN` | HIGH | 微信服务端校验 Token |
| `IS_WEWORK_CORP_ID` | MEDIUM | 企业微信 CorpID（出站推送必填）|
| `IS_WEWORK_CORP_SECRET` | HIGH | 企业微信应用 Secret（出站推送必填）|
| `IS_WEWORK_AGENT_ID` | MEDIUM | 企业微信应用 AgentID（出站推送必填）|
| `IS_WECOM_CORP_ID` | MEDIUM | 入站 webhook receiver 校验 CorpID（与 `IS_WEWORK_CORP_ID` 同值；入站客服回话必填）|
| `IS_WECOM_TOKEN` | HIGH | 入站 webhook 回调签名验证 Token（入站客服回话必填）|
| `IS_WECOM_ENCODING_AES_KEY` | HIGH | 入站 webhook AES-CBC 解密密钥（43 位 EncodingAESKey；入站客服回话必填）|
| `IS_WEWORK_WEBHOOK_TOKEN` | LOW | 明文回调 Token 字段；wework webhook 走 AES 加密路径（`IS_WECOM_TOKEN` 验签），当前不消费此值 |
| `IS_SMTP_HOST` | LOW | SMTP 服务器地址 |
| `IS_SMTP_USER` | MEDIUM | SMTP 登录用户名 |
| `IS_SMTP_PASSWORD` | HIGH | SMTP 登录密码 |
| `IS_SMTP_PORT` | LOW | SMTP 端口（默认 587）|

#### 功能开关

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `IS_PUSH_OPTIMIZE_ENABLED` | 否 | `0` | `1` 启用推送优化去重；staging 建议保持 `0` |
| `IS_BEAT_DISABLED` | 否 | `0` | `1` 禁用容器内 beat；外部调度时使用 |

### 2.4 密钥清单与轮换

#### 密钥清单（部署门禁）

| 密钥名 | 用途 | 注入方式 | 轮换建议 |
|--------|------|---------|---------|
| `IS_DB_PASSWORD` | PostgreSQL 认证 | Docker Env / Secret Manager | 90 天或人员变更时 |
| `IS_API_KEY` | API 端点鉴权 | Docker Env / Secret Manager | 90 天或泄露时 |
| `OPENAI_API_KEY` | LLM 调用 | Docker Env / Secret Manager | 按 provider 策略 |
| `ANTHROPIC_API_KEY` | LLM 调用 | Docker Env / Secret Manager | 按 provider 策略 |
| `IS_WECHAT_APP_SECRET` | 微信渠道 | Docker Env / Secret Manager | 按微信平台策略 |
| `IS_WECHAT_WEBHOOK_TOKEN` | 微信回调签名验证 | Docker Env / Secret Manager | 按微信平台策略或泄露时 |
| `IS_WEWORK_CORP_SECRET` | 企业微信出站推送凭据 | Docker Env / Secret Manager | 按企微平台策略 |
| `IS_WECOM_TOKEN` | 企业微信入站 webhook 回调签名验证 | Docker Env / Secret Manager | 按企微平台策略或泄露时 |
| `IS_WECOM_ENCODING_AES_KEY` | 企业微信入站 webhook AES-CBC 解密 | Docker Env / Secret Manager | 按企微平台策略或泄露时 |
| `IS_SMTP_PASSWORD` | 邮件渠道 | Docker Env / Secret Manager | 90 天或泄露时 |

#### 密钥管理规则

**禁止**：

- 将 `docker/.env`（含实际密钥值）提交到版本控制
- 在 Dockerfile 或 docker-compose.yml 中硬编码密钥字面量
- 在 CI 日志中输出密钥（避免 `--verbose` 泄露）

**推荐注入方式**（按优先级）：

1. **平台 Secret 机制**（CI/CD）：GitHub Actions `${{ secrets.* }}` / GitLab CI masked variables
2. **外部 Secret Manager**（生产环境）：AWS Secrets Manager / Azure Key Vault / HashiCorp Vault — 应用启动时动态拉取
3. **Docker Env 文件**（仅限非生产）：`docker/.env`，确保 `.gitignore` 覆盖，主机权限 `600`

#### IS_API_KEY 轮换

`/api/v1/metrics` 端点已在 `AuthMiddleware._EXEMPT_EXACT` 中豁免认证，Prometheus 可无凭据直接抓取，无需在 `prometheus.yml` 中配置 `bearer_token`。`IS_API_KEY` 仅保护其他业务端点（`/api/v1/*` 中非豁免路径）。轮换步骤：

1. 在 Secret Manager / `.env` 中生成新的随机字符串替换 `IS_API_KEY`
2. `docker compose restart api` 使新 key 生效
3. 验证 API 端点鉴权生效：`curl -fsS -H "X-API-Key: <新 key>" http://localhost:8000/api/v1/pipelines` 返回 200
4. 验证 metrics 端点仍可无凭据访问：`curl -fsS http://localhost:8000/api/v1/metrics` 返回 200

### 2.5 容量与扩展性

> 本节部分内容基于单主机 Docker Compose 部署场景，标注 [ASSUMPTION] 的项目缺乏生产数据支撑，需要在真实负载下调整。

#### Celery Worker 并发

| 参数 | 默认值 | 说明 |
|------|--------|------|
| Worker 进程数 | CPU 核数（Celery 默认）| 可通过 `--concurrency N` 调整 |
| 优先级队列 | `queue.priority.high` / `queue.priority.normal` / `queue.priority.low` | 已通过 `celery_app.conf.task_queues` 自动声明全部队列，容器化部署无需手动指定 `--queues` |
| 任务超时 | [ASSUMPTION] 300s | 需按实际 LLM 调用时长调整 |

单主机建议：`--concurrency 4` 启动 worker，避免 LLM 并发调用过多触发速率限制。

容器化部署（`docker-compose.yml` 默认 `celery worker --loglevel=info`）会自动消费所有已声明队列，无需附加 `--queues`。非容器化或需要多 worker 分工时，手动指定方式为：

```bash
celery -A intellisource.scheduler.celery_app worker --queues queue.priority.high,queue.priority.normal,queue.priority.low
```

#### Redis 内存

| 用途 | 估算 | 说明 |
|------|------|------|
| Celery broker 队列 | [ASSUMPTION] < 100 MB | 取决于任务积压量 |
| LLM 结果缓存 | [ASSUMPTION] < 500 MB | 按缓存条目和过期策略 |
| Celery result backend | [ASSUMPTION] < 50 MB | 结果默认过期 |
| 总建议分配 | ≥ 1 GB | 含系统开销 |

#### PostgreSQL 连接池

| 参数 | 配置位置 | 建议值 | 说明 |
|------|---------|--------|------|
| pool_size | SQLAlchemy engine | [ASSUMPTION] 5-10 | 每个 api 实例 |
| max_overflow | SQLAlchemy engine | [ASSUMPTION] 10 | 突发连接上限 |
| PostgreSQL max_connections | postgresql.conf | 100（默认）| 需大于 pool_size × 实例数 |

#### LLM 调用配额

[ASSUMPTION] 需在 `config/llm_models.yaml` 中为每个 provider 配置 rate limit（litellm `rpm`/`tpm` 参数）。建议按以下场景规划：

- 采集处理：每篇内容约 2-4 次 LLM 调用（extract / tag / summarize / dedup）
- 搜索对话：每次对话 1-2 次 LLM 调用
- 生产峰值：[ASSUMPTION] 按实际信源数量和采集频率估算 token 消耗

---

## 3. CI/CD流水线

### 3.1 CI/CD 阶段定义（GitHub Actions）

```
lint          →  ruff check + ruff format + mypy --strict
test          →  uv run pytest (全量 2838 PASS 基线)
arch-check    →  lint-imports + deptry + vulture  [B-025: 强制门禁]
promtool      →  promtool check rules docker/prometheus/alerts.yml  [B-015 要求]
sbom          →  syft 生成 SBOM（CycloneDX JSON）
scan          →  trivy / grype 镜像漏洞扫描，HIGH/CRITICAL 阻塞合并
build         →  docker build + tag
push          →  推送到 Container Registry
deploy-staging→  docker compose up（staging 环境）
smoke         →  §3.4 smoke 套件自动执行
deploy-prod   →  需要手动触发（pre_deploy 检查点）
```

`promtool check rules` 步骤的参考命令（B-015）：

```bash
docker run --rm \
  -v "$PWD/docker/prometheus:/etc/prometheus" \
  prom/prometheus:v2.55.1 \
  promtool check rules /etc/prometheus/alerts.yml
```

### 3.2 Staging 部署步骤

```bash
# 1. 启动基础设施 + 数据库迁移
docker compose -f docker/docker-compose.yml up -d db redis migrate
docker compose -f docker/docker-compose.yml wait migrate

# 2. 启动应用服务
docker compose -f docker/docker-compose.yml up -d api worker beat

# 3. 启动可观测性（可选）
docker compose -f docker/docker-compose.yml --profile observability up -d prometheus

# 4. 等待 api 健康
until curl -fsS http://localhost:8000/health > /dev/null 2>&1; do
  echo "等待 api 就绪..."; sleep 3
done

# 5. 执行 smoke 套件（见 §3.4）
```

### 3.3 Prod 灰度发布步骤

1. **pre_deploy 检查点**：人工 go/no-go 确认（参考 [PRE-DEPLOY-WALKTHROUGH.md](../deploy/PRE-DEPLOY-WALKTHROUGH.md) 20 步签字）
2. **停止 beat**：避免迁移期间 beat 调度旧任务

   ```bash
   docker compose -f docker/docker-compose.yml stop beat
   ```

3. **运行数据库迁移**：

   ```bash
   docker compose -f docker/docker-compose.yml run --rm migrate
   # 验证：migrate 容器 exit(0)
   ```

4. **滚动更新 api**（若有负载均衡前置，可蓝绿切换）：

   ```bash
   docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate api
   ```

5. **验证 api 健康**后，更新 worker：

   ```bash
   docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate worker
   ```

6. **重启 beat**：

   ```bash
   docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate beat
   ```

7. **执行 smoke 套件**（见 §3.4），全部通过后完成发布

### 3.4 Smoke 测试清单

以下测试在 staging 部署完成后、prod 发布前必须全部通过。

#### 健康端点

```bash
# 三个 health 入口全部 200
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/api/v1/health
curl -fsS http://localhost:8000/api/v1/system/health

# status 字段为 healthy
curl -s http://localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='healthy', d"
```

#### 指标端点（B-014 要求）

```bash
# metrics 端点为公开可达（已在 AuthMiddleware 中豁免认证，Prometheus 可无凭据直接抓取）
METRICS=$(curl -s "http://localhost:8000/api/v1/metrics")

# 验证全部 11 项指标家族均已暴露（与 §3.5 清单 1:1 对应）
echo "$METRICS" | grep -E "^# HELP http_requests_total"
echo "$METRICS" | grep -E "^# HELP http_request_duration_seconds"
echo "$METRICS" | grep -E "^# HELP llm_calls_total"
echo "$METRICS" | grep -E "^# HELP llm_call_failures_total"
echo "$METRICS" | grep -E "^# HELP llm_call_latency_seconds"
echo "$METRICS" | grep -E "^# HELP llm_circuit_open"
echo "$METRICS" | grep -E "^# HELP pushes_total"
echo "$METRICS" | grep -E "^# HELP celery_tasks_total"
echo "$METRICS" | grep -E "^# HELP celery_task_failures_total"
echo "$METRICS" | grep -E "^# HELP scheduler_beat_sync_failed_total"
echo "$METRICS" | grep -E "^# HELP intellisource_health_status"

# 验证 label 维度
echo "$METRICS" | grep 'llm_calls_total{' | head -3   # 应含 model label
echo "$METRICS" | grep 'pushes_total{' | head -3       # 应含 channel, status label
```

#### /search/chat/stream 端到端

```bash
# SSE 流式端点端到端（需先有 processed_contents 数据）
curl -N -s -X POST http://localhost:8000/api/v1/search/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message":"test"}' | head -20

# 期望：至少出现 data: {"type":"token"...} 或 data: {"type":"done"...}
```

#### Celery Worker 消费验证

```bash
# worker 已注册任务（当前唯一注册的 task 名为 run_pipeline）
docker compose -f docker/docker-compose.yml exec worker \
  celery -A intellisource.scheduler.celery_app inspect registered 2>/dev/null | \
  grep -E "run_pipeline"

# 三优先级队列已就绪
docker compose -f docker/docker-compose.yml exec worker \
  celery -A intellisource.scheduler.celery_app inspect active_queues 2>/dev/null | \
  grep -E "(queue\.priority\.high|queue\.priority\.normal|queue\.priority\.low)"
```

#### Prometheus 抓取验证（observability profile）

```bash
# Prometheus 健康
curl -fsS http://localhost:9090/-/healthy

# alert 规则已加载
curl -s "http://localhost:9090/api/v1/rules" | \
  python3 -c "import sys,json; rules=json.load(sys.stdin); names=[r['name'] for g in rules['data']['groups'] for r in g['rules']]; print('\n'.join(names))"
# 期望输出包含：HealthDegradedFor5m / LLMCallFailureRateHigh / PushFailureRateHigh / ApiInstanceDown 等

# Prometheus scrape 目标状态
curl -s "http://localhost:9090/api/v1/targets" | \
  python3 -c "import sys,json; targets=json.load(sys.stdin); [print(t['labels']['job'], t['health']) for t in targets['data']['activeTargets']]"
# 期望：intellisource-api up
```

### 3.5 监控 SLO 与告警

#### 指标清单（B-014）

| 指标名 | 类型 | labels | 说明 |
|--------|------|--------|------|
| `http_requests_total` | Counter | — | HTTP 请求总数（任意 method/status，API 进程，启动期 eager 注册）|
| `http_request_duration_seconds` | Histogram | — | HTTP 请求延迟（MetricsCollector 不支持带标签直方图）|
| `llm_calls_total` | Counter | `model` | LLM 调用总数（按模型）|
| `llm_call_failures_total` | Counter | `model` | LLM 调用失败数（按模型）|
| `llm_call_latency_seconds` | Histogram | — | LLM 调用延迟 |
| `llm_circuit_open` | Gauge | — | 任一熔断器 OPEN 即 1，否则 0（熔断器构造期 eager 注册）|
| `pushes_total` | Counter | `channel, status` | 推送总数（按渠道和状态）|
| `celery_tasks_total` | Counter | — | Celery 任务总数（worker 进程经共享 Redis store 暴露，B-014）|
| `celery_task_failures_total` | Counter | — | Celery 任务失败数（同上，跨进程）|
| `scheduler_beat_sync_failed_total` | Counter | — | Beat 调度同步失败数 |
| `intellisource_health_status` | Gauge | `component` | 组件健康状态（0=healthy, 1=degraded, 2=unhealthy）|

#### SLO 定义

| SLO | 目标值 | 告警阈值 |
|-----|--------|---------|
| API 可用性 | 99.5% / 30 天 | `up == 0` 持续 5 分钟 → CRITICAL |
| API p99 延迟 | < 5s | p99 > 5s 持续 10 分钟 → WARNING |
| LLM 调用失败率 | < 20% / 模型 | > 20% 持续 10 分钟 → WARNING |
| 推送失败率 | < 20% / 渠道 | > 20% 持续 10 分钟 → WARNING |
| 组件健康状态 | 全部 healthy | 任一 degraded/unhealthy 持续 5 分钟 → WARNING |
| Celery 任务失败率 | < 20% | > 20% 持续 10 分钟 → WARNING |

#### 告警响应 SOP

##### ApiInstanceDown（CRITICAL）

- **触发条件**：`up{job="intellisource-api"} == 0` 持续 5 分钟
- **首要排查路径**：
  1. `docker compose -f docker/docker-compose.yml ps api` → 检查容器状态
  2. `docker compose -f docker/docker-compose.yml logs --tail=100 api` → 看启动错误
  3. 检查 `IS_DATABASE_URL` 主机名是否为容器名 `db`（非 `localhost`）
- **可能根因**：容器崩溃 / OOM / DB 连接失败导致 lifespan 异常
- **Escalation owner**：运维 on-call
- **止血操作**：`docker compose -f docker/docker-compose.yml restart api`

##### HealthDegradedFor5m（WARNING）

- **触发条件**：`max(intellisource_health_status{component=~"db|redis|celery"}) > 0` 持续 5 分钟
- **首要排查路径**：
  1. `curl -s http://localhost:8000/health | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['checks'], indent=2))"` → 定位具体组件
  2. 针对 `db`：`docker compose ps db` + `docker compose logs db`
  3. 针对 `redis`：`docker compose exec redis redis-cli ping`
  4. 针对 `celery`：`docker compose logs worker | tail -50`
- **可能根因**：DB 连接池耗尽 / Redis OOM / Worker 进程崩溃
- **Escalation owner**：运维 on-call

##### LLMCallFailureRateHigh（WARNING）

- **触发条件**：`sum by (model) (rate(llm_call_failures_total[5m])) / ... > 0.2` 持续 10 分钟
- **首要排查路径**：
  1. 检查 `$labels.model` 指向哪个模型
  2. `curl -s -H "X-API-Key: $IS_API_KEY" http://localhost:8000/api/v1/llm/status` → circuit_state
  3. 查 DB：`SELECT error_message, count(*) FROM llm_call_logs WHERE status != 'success' GROUP BY error_message LIMIT 10`
  4. 检查 provider API Key 是否有效、是否触发速率限制
- **可能根因**：LLM provider 故障 / API Key 过期 / 配额耗尽 / 网络不通
- **Escalation owner**：应用 on-call → LLM provider 支持
- **止血操作**：切换备用 model（修改 `IS_LLM_DEFAULT_MODEL` 并重启 api/worker）

##### PushFailureRateHigh（WARNING）

- **触发条件**：`sum by (channel) (rate(pushes_total{status="failed"}[5m])) / ... > 0.2` 持续 10 分钟
- **首要排查路径**：
  1. 检查 `$labels.channel`（email / wechat / wework）
  2. 查 DB：`SELECT channel, error_message, count(*) FROM push_records WHERE status = 'failed' AND created_at > NOW() - INTERVAL '1h' GROUP BY channel, error_message`
  3. 验证对应渠道凭据（SMTP 密码 / WeChat AppSecret / WeWork CorpSecret）是否有效
- **可能根因**：渠道凭据过期 / SMTP 服务不可达 / 微信/企微 API 配额限制
- **Escalation owner**：应用 on-call

##### LLMCircuitOpen（WARNING）

- **触发条件**：`llm_circuit_open > 0` 持续 1 分钟
- **首要排查路径**：
  1. 确认 LLM provider 服务状态（status.openai.com 等）
  2. 检查 `llm_call_failures_total` 近期趋势
  3. 等待熔断器半开重试（通常 30-60s）
- **可能根因**：LLM provider 临时故障；降级路径（tfidf/truncate/regex）会自动接管
- **Escalation owner**：应用 on-call；降级路径已保证 API 不返回 5xx

##### CeleryTaskFailureRateHigh（WARNING）

- **触发条件**：`rate(celery_task_failures_total[5m]) / ... > 0.2` 持续 10 分钟
- **首要排查路径**：
  1. `docker compose logs worker | grep -E "(ERROR|Exception)" | tail -30`
  2. 检查 DB 连接（worker 依赖 PG + Redis）
  3. 查 `collect_tasks` 表中 `status='failed'` 的最近任务的 `error_message`
- **可能根因**：DB 不可达 / LLM 调用异常（已有熔断降级）/ 信源网络超时
- **Escalation owner**：应用 on-call

##### SchedulerBeatSyncFailing（CRITICAL）

- **触发条件**：`increase(scheduler_beat_sync_failed_total[10m]) > 0`（立即告警，无延迟）
- **首要排查路径**：
  1. `docker compose logs beat | tail -50` → 查 `populate_scheduler_from_sources` 错误
  2. 检查 DB 连接、`sources` 表中 `status='active'` 的信源是否有效
- **影响**：定时采集任务不会触发，直到 beat 重启成功
- **止血操作**：`docker compose restart beat`
- **Escalation owner**：应用 on-call

### 3.6 回滚 SOP

#### 快速回滚决策树

```
发现问题
  ├── API 不可达 / 5xx 激增
  │     → 立即执行 §Docker tag 回滚
  ├── 数据损坏 / 迁移失败
  │     → 执行 §Alembic downgrade（需先评估数据风险）
  ├── 配置错误（密钥/URL 错误）
  │     → 执行 §配置回滚（修改 .env + restart）
  └── 指标告警但功能基本可用
        → 观察 + 评估是否需要回滚
```

#### Docker Tag 回滚

当前 `docker/docker-compose.yml` 使用 `build:` 模式（非 `image:`），回滚方式为检出旧 Git tag 后重新构建：

```bash
# 1. 确认上一个稳定 tag（git tag 或本地镜像列表二选一）
git tag --sort=-creatordate | head -10
# 或：
docker images intellisource --format "{{.Tag}}\t{{.CreatedAt}}" | sort -r | head -5

# 2. 停止 beat（避免调度混乱）
docker compose -f docker/docker-compose.yml stop beat

# 3. 检出旧 tag 源码并重新构建
PREV_TAG="<上一个稳定 git tag>"
git checkout "${PREV_TAG}"
docker compose -f docker/docker-compose.yml build api worker

# 4. 用旧镜像拉起 api
docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate api

# 5. 验证 health
curl -fsS http://localhost:8000/health

# 6. 回滚 worker
docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate worker

# 7. 重启 beat
docker compose -f docker/docker-compose.yml up -d --no-deps beat
```

> **参考改造步骤（prebuilt 镜像模式）**：若需免重新构建的秒级回滚，可将 `docker-compose.yml` 中 `api` / `worker` 服务的 `build:` 替换为 `image: intellisource:${IMAGE_TAG:-latest}`，CI 推送预构建镜像到 Container Registry，回滚时执行：
>
> ```bash
> IMAGE_TAG=<prev-tag> docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate api worker
> ```
>
> 改造步骤已作为后续优化项记录（参见 backlog）。

#### 数据库迁移回滚（Alembic downgrade）

**警告**：downgrade 可能造成不可逆数据丢失（新列/表数据），执行前必须备份。

```bash
# 1. 备份当前 DB（在 migrate service 容器或独立 psql 执行）
docker compose -f docker/docker-compose.yml exec db \
  pg_dump -U intellisource intellisource > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. 查看当前迁移版本
docker compose -f docker/docker-compose.yml run --rm migrate \
  python -m alembic current

# 3. 查看历史版本
docker compose -f docker/docker-compose.yml run --rm migrate \
  python -m alembic history --verbose

# 4. 回退到指定版本（-1 退一步）
docker compose -f docker/docker-compose.yml run --rm migrate \
  python -m alembic downgrade -1

# 5. 验证版本
docker compose -f docker/docker-compose.yml run --rm migrate \
  python -m alembic current
```

#### 配置回滚

```bash
# 1. 修改 docker/.env 恢复旧值（保留变更记录）
# 2. 重启受影响的服务（不需要重新构建镜像）
docker compose -f docker/docker-compose.yml restart api worker beat
```

#### Redis State 影响评估

回滚场景下 Redis 中可能存储：

- **Celery 任务队列**（broker db=0）：回滚后 worker 可能以旧版本代码消费新版本任务。如任务格式不兼容，需 FLUSHDB 清空队列
- **LLM 结果缓存**（cache 使用 db=0 或配置键）：通常无需清空，旧版本可以读取缓存
- **Celery 任务结果**（result backend db=1）：通常无需清空

```bash
# 仅在任务格式不兼容时才清空 broker 队列
docker compose -f docker/docker-compose.yml exec redis redis-cli -n 0 FLUSHDB
# 注意：这会丢失所有待处理任务
```

---

## 4. 发布检查清单

每次生产发布前，逐项签字确认。

### 4.1 数据库迁移

- [ ] 执行 `alembic upgrade head`，migrate 容器 exit(0)
- [ ] 验证业务表结构：`\dt` 显示 11 张表齐全
- [ ] pgvector 扩展存在：`SELECT extname FROM pg_extension WHERE extname = 'vector'`
- [ ] zhparser 扩展存在：`SELECT extname FROM pg_extension WHERE extname = 'zhparser'`（中文全文检索依赖，缺失时迁移会报错或功能异常）
- [ ] 回滚路径已测试（staging 验证 `alembic downgrade -1` 后功能正常）

### 4.2 .env 与凭据签字

- [ ] `docker/.env` 已从 `.env.example` 更新，所有 HIGH 敏感度变量已替换默认值
- [ ] `IS_API_KEY` 为非 `change-me-in-production` 的强随机字符串
- [ ] `IS_DB_PASSWORD` 为非 `intellisource` 的强密码
- [ ] LLM provider API Key 已填写且有效（curl `/api/v1/llm/status` 返回 `circuit_state: CLOSED`）
- [ ] `config/llm_models.yaml` 已配置 prod provider

### 4.3 镜像 Tag

- [ ] 镜像已用 release tag 构建并推送到 Container Registry
- [ ] SBOM 已生成并归档
- [ ] 镜像漏洞扫描通过（无未确认的 HIGH / CRITICAL CVE）

### 4.4 Smoke 套件

- [ ] §3.4 三个健康端点全部 200
- [ ] §3.4 全部 11 项指标全部出现在 `/api/v1/metrics` 输出中
- [ ] §3.4 `/search/chat/stream` SSE 端点返回有效事件流
- [ ] §3.4 Celery worker 已注册任务，三优先级队列就绪
- [ ] §3.4 Prometheus 已加载所有告警规则（observability profile 启用时）

### 4.5 监控验证

- [ ] Prometheus 抓取目标 `intellisource-api` 状态为 `up`
- [ ] 所有告警规则通过 `promtool check rules` 语法检查（B-015）：

  ```bash
  docker run --rm \
    -v "$PWD/docker/prometheus:/etc/prometheus" \
    prom/prometheus:v2.55.1 \
    promtool check rules /etc/prometheus/alerts.yml
  ```

- [ ] `intellisource_health_status` gauge 所有组件值为 0（healthy）

### 4.6 安全门禁

- [ ] SBOM 已归档（`sbom-${GIT_SHA_SHORT}.json` 或 BuildKit `--attest type=sbom`）
- [ ] trivy / grype 镜像扫描通过；任何 HIGH/CRITICAL CVE 均已豁免或修复并记录至 CORRECTIONS-LOG
- [ ] 无密钥字面量泄露到 Dockerfile / docker-compose.yml / CI 日志
- [ ] `docker/.env` 未提交版本控制（确认 `git status` 干净）

### 4.7 回滚演练记录

- [ ] staging 上已执行一次 Docker tag 回滚演练，step 耗时已记录
- [ ] staging 上已验证 `alembic downgrade -1` 后应用正常启动
- [ ] 备份策略已验证（DB dump 可在 < 5 分钟内完成）

### 4.8 人工签字

```
发布版本 (tag): ___________
发布时间:       ___________
操作人签字:     ___________
review 确认:    ___________
```
