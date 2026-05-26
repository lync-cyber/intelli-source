---
id: "review-deploy-spec-intellisource-v1-r1"
doc_type: review
author: reviewer
status: approved
deps: ["deploy-spec-intellisource-v1"]
---

# 文档审查报告：deploy-spec-intellisource-v1

**审查对象**: `docs/deploy-spec/deploy-spec-intellisource-v1.md`（722 行）
**审查层**: Layer 2 语义审查（Layer 1 已 PASS，仅余 1 行数 WARN）
**审查日期**: 2026-05-26
**verdict**: **needs_revision**

---

## 问题列表

### [R-001] HIGH: §3.6 Docker tag 回滚命令使用了无效的 `-e` 标志

- **category**: feasibility
- **root_cause**: self-caused
- **描述**: §3.6 "Docker Tag 回滚"中的命令使用了 `-e "IMAGE_TAG=${PREV_TAG}"` 标志：

  ```bash
  docker compose -f docker/docker-compose.yml \
    up -d --no-deps --force-recreate \
    -e "IMAGE_TAG=${PREV_TAG}" api
  ```

  `docker compose up` 命令不支持 `-e` 标志（`docker compose run` 才支持）。执行此命令将报错并导致回滚操作失败。

  同时，`docker/docker-compose.yml` 中所有服务均使用 `build:` 指令而非 `image:` 指令，不支持通过 `IMAGE_TAG` 环境变量切换镜像版本——当前 Compose 文件无 `IMAGE_TAG` 引用，运行时传入该变量无任何效果。

- **建议**: 回滚命令需要重新设计。选项 1：如果目标是切换到预构建的特定 tag 镜像，需要先将 `docker-compose.yml` 中的 `build:` 改为 `image: intellisource:${IMAGE_TAG:-latest}`，然后通过 `IMAGE_TAG=<tag> docker compose up -d --no-deps api` 实现切换；选项 2：若继续使用 `build:` 模式，回滚操作应改为 `git checkout <prev-tag> && docker compose build api && docker compose up -d --no-deps api`，配合 `COMPOSE_IMAGE_TAG` 或 build arg 实现版本切换。此 HIGH 问题可能在生产紧急回滚场景下造成严重后果。

---

### [R-002] HIGH: §3.4 Smoke 测试检查的 Celery 任务名包含不存在的任务

- **category**: feasibility
- **root_cause**: self-caused
- **描述**: §3.4 "Celery Worker 消费验证"中的 grep 命令检查三个任务名：

  ```bash
  grep -E "(run_pipeline|collect_source|distribute_content)"
  ```

  经核查，`src/intellisource/scheduler/tasks.py` 中唯一注册的 Celery task 名是 `run_pipeline`（`@celery_app.task(name="run_pipeline")`）。`collect_source` 和 `distribute_content` 作为 Celery task 名在整个 `src/` 目录中均不存在。

  该 smoke 测试中的 grep 命令仅会匹配 `run_pipeline`，`collect_source` 和 `distribute_content` 永远不会出现在输出中，但命令本身不会报错（grep 只要找到 `run_pipeline` 就返回 0）。这导致该检查项实际上无法验证文档所声称的"三任务全部已注册"。

- **建议**: 将 grep 模式修正为实际存在的任务名。根据 `tasks.py` 实现，当前应仅检查 `run_pipeline`。如果 `collect_source`/`distribute_content` 是计划中的任务名，需先实现再加入 smoke 验证。建议改为：

  ```bash
  grep -E "run_pipeline"
  ```

---

### [R-003] MEDIUM: §3.4 smoke 指标验证仅覆盖 7 项，与 §3.5（11 项）和 B-014 要求不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: §3.5 "指标清单（B-014）"中定义了 11 项指标，changelog 中也明确记录"B-014 全部 11 项指标验证命令"，但 §3.4 的 smoke 脚本只用 `grep` 验证了 7 项指标（`http_requests_total`、`llm_calls_total`、`pushes_total`、`celery_tasks_total`、`llm_circuit_open`、`intellisource_health_status`、`llm_call_failures_total`），遗漏了以下 4 项：

  | 遗漏指标 | 类型 | 注册来源 |
  |---------|------|---------|
  | `http_request_duration_seconds` | Histogram | `middleware.py` |
  | `llm_call_latency_seconds` | Histogram | `llm/gateway/_metrics.py` |
  | `celery_task_failures_total` | Counter | `scheduler/signals.py` |
  | `scheduler_beat_sync_failed_total` | Counter | `scheduler/boot.py` |

  此外，§4.4 发布检查清单中写"§3.4 **六项**核心指标全部出现"——实际上 §3.4 验证了 7 项，与正文数字不一致。

- **建议**: 将 §3.4 smoke 脚本补全至 11 项指标的 grep 验证，与 §3.5 完全对应。同时将 §4.4 中的"六项"改为正确数字（按修正后的实际验证项数）。

---

### [R-004] MEDIUM: §3.4 metrics 端点鉴权描述与实现不符

- **category**: consistency
- **root_cause**: self-caused
- **描述**: §3.4 注释写"metrics 端点可达（需 IS_API_KEY 鉴权或配置白名单）"，§2.4 密钥轮换步骤 4 也写"curl -H "X-API-Key: <新 key>" http://localhost:8000/api/v1/metrics 返回 200"。但实际实现（`src/intellisource/api/middleware.py`）中，`/api/v1/metrics` 已被列入 `_EXEMPT_EXACT` 集合，完全豁免认证——无需 API Key 即可访问。

  同样，Prometheus scrape 配置（`docker/prometheus/prometheus.yml`）中没有配置任何 `authorization`、`bearer_token` 或 `basic_auth`，进一步证实 metrics 端点是公开的。

  这个不一致会引起两类问题：(1) 运维人员误以为 metrics 端点需要认证，可能无谓地排查 403 问题；(2) §2.4 中的轮换验证命令携带了不必要的 `X-API-Key` 头，对读者造成误导，实际上没有该头也能访问。

- **建议**: 将 §3.4 注释改为"metrics 端点为公开可达（已在 AuthMiddleware 中豁免认证，Prometheus 可无凭据直接抓取）"。将 §2.4 密钥轮换步骤 4 改为不带 `X-API-Key` 的 curl 命令，或删除该验证步骤（该步骤验证的是 metrics 而非 api_key 变更生效，逻辑上也不准确）。

---

### [R-005] MEDIUM: 部署文档未提及 zhparser 扩展对 DB 镜像的特殊要求

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `alembic/versions/001_initial_schema.py` 在数据库初始化时执行 `CREATE EXTENSION IF NOT EXISTS zhparser`，该扩展是 PostgreSQL 中文全文检索（`to_tsvector('chinese', ...)`）的依赖，在 `arch-intellisource-v1#§1.4` 技术栈中也有明确记录（"Docker 部署时需使用包含 zhparser 的 PostgreSQL 镜像"）。

  但 `docker-compose.yml` 使用的是 `pgvector/pgvector:pg16` 标准镜像，该镜像不预装 zhparser。部署文档 §1.1 前置条件和 §2.1 部署架构均未提及此依赖，操作者按文档部署后执行迁移将因扩展缺失报错或静默跳过（取决于 `IF NOT EXISTS` 后的实际状态）。

  注：该问题在 arch 文档中有记录，属 deploy-spec 未将 arch 约定落地为可执行步骤。

- **建议**: 在 §1.1 前置条件中增加"DB 镜像必须包含 zhparser 扩展（标准 `pgvector/pgvector:pg16` 不含，需使用自定义镜像或在容器启动后手动安装）"的说明，并在 §4.1 发布检查清单中增加 `SELECT extname FROM pg_extension WHERE extname = 'zhparser'` 的验证步骤（与 pgvector 验证并列）。

---

### [R-006] MEDIUM: §2.5 优先队列名称与实现不符

- **category**: consistency
- **root_cause**: self-caused
- **描述**: §2.5 "Celery Worker 并发"表格中写"优先级队列 high / normal / low"，并提示通过 `--queues high,normal,low` 启动。但 `src/intellisource/scheduler/queues.py` 中实际队列名为 `queue.priority.high`、`queue.priority.normal`、`queue.priority.low`。

  使用 `--queues high,normal,low` 无法消费这些队列；正确命令应为 `--queues queue.priority.high,queue.priority.normal,queue.priority.low`。

  此外，`docker-compose.yml` 中的 `worker` 服务命令为 `celery worker --loglevel=info`，未指定 `--queues`，而 Celery 默认会消费所有已在 `celery_app.conf.task_queues` 中声明的队列（代码中已通过 `task_queues=[Queue(name) for name in _all_queue_names]` 配置），所以容器化部署实际上无需 `--queues` 参数——文档中的 `--queues` 建议会引发歧义。

- **建议**: 将 §2.5 优先队列名修正为实际名称（`queue.priority.high / queue.priority.normal / queue.priority.low`），并说明容器化部署下无需手动指定 `--queues`（已通过 `celery_app.conf.task_queues` 自动声明）；`--queues` 仅在非容器化或需要多 worker 分工时手动指定。

---

### [R-007] LOW: §4.4 checklist 数字"六项"与 §3.4 实际验证项不符

- **category**: consistency
- **root_cause**: self-caused
- **描述**: §4.4 发布检查清单写"§3.4 **六项**核心指标全部出现在 `/api/v1/metrics` 输出中"，但 §3.4 的 smoke 脚本实际验证了 7 个 grep 命令（7 项指标）。数字不一致会在签字时引起混淆。（若按 R-003 建议扩充至 11 项，该项应同步更新为"11 项"。）

- **建议**: 在 §3.4 修正后，将 §4.4 中的数字同步更新为准确值。

---

### [R-008] LOW: §2.4 密钥轮换未覆盖微信/企微 webhook token 的轮换步骤

- **category**: completeness
- **root_cause**: self-caused
- **描述**: §2.3 环境变量清单中将 `IS_WECHAT_WEBHOOK_TOKEN` 和 `IS_WEWORK_WEBHOOK_TOKEN` 标记为 HIGH 敏感度，但 §2.4 密钥清单未包含这两个 token 的轮换建议（仅覆盖了 DB 密码、API Key、LLM Key、渠道 AppSecret/CorpSecret 和 SMTP 密码）。Webhook token 用于验证来自微信/企微平台的回调消息签名，泄露后攻击者可伪造 webhook 回调。

- **建议**: 在 §2.4 密钥清单表格中补充 `IS_WECHAT_WEBHOOK_TOKEN` 和 `IS_WEWORK_WEBHOOK_TOKEN` 两行，注入方式和轮换建议与同渠道的 AppSecret/CorpSecret 保持一致（"按微信/企微平台策略"）。

---

### [R-009] LOW: §4.5 promtool 验证步骤无可执行命令，可操作性不足

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: §4.5 监控验证检查项写"所有告警规则通过 `promtool check rules` 语法检查（B-015）"，但未给出具体命令——完整的 `docker run ... promtool check rules ...` 命令仅在 §3.1 CI/CD 流水线定义中出现。在人工 pre-deploy 签字场景下，操作者需要手动翻回 §3.1 才能找到命令，降低了检查清单的自包含性。

- **建议**: 在 §4.5 该检查项下方内联引用命令（可简化为"见 §3.1 promtool 步骤"并附命令），或直接复制 §3.1 中的 docker run 命令，确保 §4 发布检查清单可独立执行。

---

## 审查总结

| 编号 | 严重等级 | category | 简述 |
|------|---------|---------|------|
| R-001 | HIGH | feasibility | §3.6 回滚命令 `-e` 标志无效 + `IMAGE_TAG` 与 Compose 文件不匹配 |
| R-002 | HIGH | feasibility | §3.4 smoke 检查不存在的 Celery 任务名 `collect_source`/`distribute_content` |
| R-003 | MEDIUM | consistency | §3.4 smoke 仅验证 7/11 指标，与 §3.5 和 B-014 要求不一致 |
| R-004 | MEDIUM | consistency | §3.4/§2.4 描述 metrics 端点需鉴权，但实现已豁免认证 |
| R-005 | MEDIUM | completeness | 未说明 zhparser 扩展对 DB 镜像的要求 |
| R-006 | MEDIUM | consistency | §2.5 优先队列名称 `high/normal/low` 与实现 `queue.priority.*` 不符 |
| R-007 | LOW | consistency | §4.4 "六项"数字与 §3.4 实际验证 7 项不符 |
| R-008 | LOW | completeness | §2.4 密钥清单遗漏两个 HIGH 敏感度 webhook token |
| R-009 | LOW | ambiguity | §4.5 promtool 检查项缺少可直接执行的命令 |

**verdict**: **needs_revision**（存在 R-001、R-002 两个 HIGH 级问题）

主要修订方向：(1) R-001 回滚命令需重新设计以匹配实际 Compose 结构；(2) R-002 需核实并修正 smoke 测试中的 Celery 任务名；(3) R-003 至 R-006 为 MEDIUM 一并在 r2 中修复。
