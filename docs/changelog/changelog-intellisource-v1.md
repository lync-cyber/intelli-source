---
id: "changelog-intellisource-v1"
version: "1.0.0"
doc_type: changelog
author: devops
status: approved
deps: []
consumers: [all]
---
# Changelog: IntelliSource v1

## [1.0.0-rc2] - 2026-05-26

### Fixed (deploy-spec r2 修订)

- **R-001 HIGH** §3.6 回滚命令重新设计：移除无效 `-e` 标志，改为 `git checkout <prev-tag> && docker compose build` 方式；新增 prebuilt 镜像模式参考改造步骤说明
- **R-002 HIGH** §3.4 Smoke Celery 任务 grep 修正为唯一实际注册的任务名 `run_pipeline`，删除不存在的 `collect_source`/`distribute_content`
- **R-003 MEDIUM** §3.4 指标端点 grep 从 7 项补全至全部 11 项，与 §3.5 B-014 清单完全 1:1 对应（补入 `http_request_duration_seconds`、`llm_call_latency_seconds`、`celery_task_failures_total`、`scheduler_beat_sync_failed_total`）
- **R-004 MEDIUM** §3.4 注释及 §2.4 密钥轮换步骤修正：`/api/v1/metrics` 已在 `AuthMiddleware._EXEMPT_EXACT` 中豁免认证，无需 API Key；轮换验证步骤改为分开验证业务端点鉴权和 metrics 可达性
- **R-005 MEDIUM** §1.1 前置条件补充 zhparser 扩展依赖说明（标准 pgvector/pgvector:pg16 不含，需自定义镜像）；§4.1 检查清单新增 `SELECT extname FROM pg_extension WHERE extname = 'zhparser'` 验证项
- **R-006 MEDIUM** §2.5 优先队列名修正为实际名称 `queue.priority.{high,normal,low}`；新增说明容器化部署无需手动 `--queues`（已通过 `celery_app.conf.task_queues` 自动声明）
- **R-007 LOW** §4.4 指标数量从"六项"修正为"11 项"
- **R-008 LOW** §2.4 密钥清单补入 `IS_WECHAT_WEBHOOK_TOKEN` / `IS_WEWORK_WEBHOOK_TOKEN` 两行（HIGH 敏感度，轮换建议按平台策略或泄露时）
- **R-009 LOW** §4.5 promtool 验证项内联可执行 `docker run promtool check rules` 命令

---

## [1.0.0] - 2026-05-26

### Added
- 部署规范文档 (deploy-spec-intellisource-v1)，覆盖 9 个章节：部署架构、环境变量清单、部署流程、Smoke 测试清单、监控 SLO 与告警、回滚 SOP、容量与扩展性、安全与合规、上线 Checklist
- CI/CD 流水线阶段定义，含 `promtool check rules` 告警规则校验步骤（B-015）
- Staging 验证阶段指标覆盖检查，包含全部 11 项指标验证命令（B-014）：`http_requests_total`、`llm_calls_total`、`llm_call_failures_total`、`llm_circuit_open`、`llm_call_latency_seconds`、`pushes_total`、`celery_tasks_total`、`celery_task_failures_total`、`scheduler_beat_sync_failed_total`、`intellisource_health_status`、`http_request_duration_seconds`
- SBOM 生成（syft / Docker BuildKit attestation）与镜像漏洞扫描（trivy / grype）门禁规范
- 8 条 Prometheus alert 的响应 SOP（ApiInstanceDown、ApiHighRequestLatency、LLMCircuitOpen、LLMCallFailureRateHigh、PushFailureRateHigh、HealthDegradedFor5m、CeleryTaskFailureRateHigh、SchedulerBeatSyncFailing）
- 回滚决策树与 Alembic downgrade 命令参考
- 环境变量敏感度分级（HIGH / MEDIUM / LOW）与密钥轮换指引
