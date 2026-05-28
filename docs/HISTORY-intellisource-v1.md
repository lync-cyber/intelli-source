---
id: history-intellisource-v1
doc_type: history
author: orchestrator
status: approved
deps: []
---

# IntelliSource v1 闭环历史

> CLAUDE.md §项目状态 归档 — 历史闭环条目的详细 prose 留在此文件，CLAUDE.md 仅保留摘要 + 链接。
> 写入顺序：旧 → 新；最新闭环保留在 CLAUDE.md 直到归档轮替。
> 最后归档：2026-05-28 (B-057+B-058 闭环后整理；同步移除 CLAUDE.md 中过期长 prose)

## audit-fix
- **audit-fix-pr53** (commit 7e10e77): F-01~F-11 P0 + F-12~F-27 P1 + F-28~F-48 P2/P3 — 39 项，详见 PR #53 描述
- **audit-fix-pr54** (commit 31bddde): F-11 receiver_id / F-25 health 豁免 / F-42 PG /search 真链路 / idempotency RuntimeWarning / F-20+F-21 health 并发 / F-22 metrics 4 路径 / F-23 trace_id 跨 worker / F-24 alerts.yml / F-26 priority queue / F-27 content_not_found / 2 xfail (HybridIndex tags/date) / 1 placeholder skip 删 / 46 docker skip 转 deselect — 14 项

## backlog-b001 ~ b010 早期质量项

- **B-001 + B-002**: `/search/chat/stream` 切 `AgentRunner.run_flexible_stream` (新增 RAG-aware 流式入口 + LLMGateway.stream_complete 支持 messages 参数 + FlexibleLoop.run_stream) + `SearchRequest.date_from/to: str → datetime`（非法值 422 而非 500）；SSE 事件契约 step/sources/token/done/error
- **B-003 ~ B-006** (3 batch): B-006 storage fixture ARRAY→JSON conftest mutation / B-003 `intellisource_health_status` labeled gauge + HealthDegradedFor5m alert / B-004 `scheduler.dispatch.send_task_with_trace()` facade + guardrail (src/ 范围) / B-005 MetricsCollector labeled counter (pushes_total{channel,status} + llm_calls_total{model})；详见 [docs/reviews/code/CODE-REVIEW-backlog-p1-r1.md](reviews/code/CODE-REVIEW-backlog-p1-r1.md)
- **B-007**: LLMGateway 单类 732 行拆为 6 mixin (`_complete` 200 / `_chat` 200 / `_stream` 185 / `_queue` 54 / `_metrics` 44 / `_protocols` 80) + facade `__init__.py` 120 行；`_GatewayProtocol` mypy --strict self-type 兜底；公共 API 零破坏；详见 [docs/reviews/code/CODE-REVIEW-B-007-r1.md](reviews/code/CODE-REVIEW-B-007-r1.md)
- **B-008**: `truncate_summary` 接入 LLM summarizer（`summarizer.structured` 模板 + `gateway.complete(response_format=json_object)` + `tool_deps` 注入）；产出 `{title, summary, timeline[], key_points[]}` 结构化摘要；3 层 fallback；PRD AC-023 [ASSUMPTION] 移除
- **B-009** (decision-only, reaffirm 选项 ②): PRD AC-063 [ASSUMPTION] 在 sprint-9 锁定 YAML-as-source-of-truth；pipelines router 现状即决策实现 (list/detail/run, 无 HTTP CRUD)；完整 workflow CRUD (DB 存储 + 历史版本) 保留 v2+ 范畴
- **B-010** (deploy-spec): devops 子代理产出 [docs/deploy-spec/deploy-spec-intellisource-v1.md](deploy-spec/deploy-spec-intellisource-v1.md) 755 行 — 4 模板必填段全覆盖；dev/staging/prod 三环境矩阵 + zhparser DB 镜像要求 (R-005) + 11 项指标家族 (B-014 全覆盖) + queue.priority.* + promtool check rules (B-015) + SBOM + trivy/grype 漏洞门禁 + git checkout+rebuild 回滚 + run_pipeline 唯一注册任务 smoke + webhook token 轮换。r1 needs_revision (2 HIGH + 4 MEDIUM + 3 LOW) → devops r2 修订 9 项全部闭环 → approved；详见 [docs/reviews/doc/REVIEW-deploy-spec-intellisource-v1-r2.md](reviews/doc/REVIEW-deploy-spec-intellisource-v1-r2.md)
- **B-029 + B-030**: alerts.yml `LLMCallFailureRateHigh` + `PushFailureRateHigh` 按 `model`/`channel` label 拆分 + annotations 模板化 / R-002 guardrail 注释 + R-003 `_ALLOWED_POSIX` 精确路径匹配 + R-004 register 集中化

## B-031 PRE-DEPLOY-WALKTHROUGH 走查 + 部署破口闭环

- **阶段 0-1 partial**: 阶段 0 步骤 1-2 + 阶段 1 步骤 3 PASS / 步骤 4 partial（worker async/sync bridge 缺陷阻塞 → 立 B-037）。**12 项 NO-GO inline 修**：Dockerfile alembic.ini 路径 / uv sync README 缺失 → --no-install-project / asyncpg+psycopg 未声明运行时依赖 / env.py 错环境变量名 + sync driver URL 重写 / zhparser DO-EXCEPTION 优雅降级 / uvicorn 未声明 + venv 跨路径 shebang 破口 / distributor hard-fail 占位绕过 / celery_app 不 import tasks / /tasks/collect FK 违反 parent / worker entry 用 celery_app 而非 boot / GET /tasks/{id} 引用不存在字段。**6 项 carryover**: B-032 / B-033 / B-034 / B-035 / B-036 / B-037
- **B-037** (worker async/sync bridge hardening, 用户选 A: per-task lazy + NullPool): 新增 [src/intellisource/scheduler/lazy_redis.py](../src/intellisource/scheduler/lazy_redis.py) `LazyLoopRedis` 包装类（按 running event loop 缓存 `aioredis.Redis`，`__getattr__` 透明转发）；[scheduler/boot.py](../src/intellisource/scheduler/boot.py) `_build_redis_client` 返回 LazyLoopRedis，`init_worker_session_factory` 加 `poolclass=NullPool`
- **B-031 步骤 4-rerun**: B-037 闭环后真起 docker stack 重跑步骤 4：worker logs `Task run_pipeline succeeded in 2.68s` 全 3 步执行 / 20 raw_contents / fingerprint 复跑去重 / priority queue 路由 5 队列全活。**NO-GO #13**：`_collect_execute` 删 `**kwargs` 透传（collector 契约不接受）。**B-039 carryover**：tools 双副本去重
- **B-031 步骤 5**: 信源 CRUD list/PATCH/DELETE 全 Pass。**修正 #14**：[`BaseRepository.update`](../src/intellisource/storage/repositories/base.py) flush 后加 `await session.refresh(entity)`（修 PATCH /sources/{id} 500 `MissingGreenlet`）
- **B-031 步骤 6-8**: pipeline 枚举 + manual-collect 触发 + LLM 网关状态全 Pass。**修正 #15**：[manual-collect.yaml](../config/pipelines/manual-collect.yaml) steps[0] 删 `source_type: manual` override。**修正 #16**：[content-process.yaml](../config/pipelines/content-process.yaml) `KeywordTagger` 增 8 大类技术词库（ai/security/web/cloud/opensource/startup/data/language）。**B-040 carryover**：worker stdlib log → structlog/formatter migration
- **B-041** (DeepSeek V4 适配, 用户选 B 完整支持): `ModelTaskConfig` 加 `thinking` + `reasoning_effort` 字段；[llm/gateway/_extra_body.py](../src/intellisource/llm/gateway/_extra_body.py) `build_extra_body()` — deepseek 默认 thinking=disabled，task_cfg > profile > default 优先级；chat/complete/stream 三入口注入 `extra_body`；FlexibleLoop run+run_stream 把 `reasoning_content` 写入 assistant message dict 下一轮回传；llm_models.yaml 切回 v4-flash + v4-pro
- **B-031 步骤 9**: V4 gateway 适配链路 Pass。**3 项 P2-P3 carryover**: B-042 CostTracker / B-043 chat() LLMCache / B-044 LLMSummarizer
- **B-042** (用户选 C): `LLMGateway.__init__` 新增 `session_factory` kwarg；`_RetryMixin._emit_call_log(record)` 统一 cost_tracker（legacy）+ session_factory（生产 `async with session_factory() as s: CostTracker(s).log_call(record)`）双源；chat/stream/complete 三入口都写 log_call
- **B-044** (用户选 B, option-A 子集): 新增 [src/intellisource/pipeline/processors/summarizer.py](../src/intellisource/pipeline/processors/summarizer.py) `LLMSummarizer(BaseProcessor)` — `truncate_summary(cluster, tool_deps=_GatewayDeps(llm_gateway))` 经 `asyncio.run`（无 loop 直接 / 有 loop 走 ThreadPoolExecutor）；`PROCESSOR_REGISTRY` 注册（类级 `_NEEDS_LLM_GATEWAY=True` 标记）；`_build_processors_from_config(config, llm_gateway=None)` 按需注入
- **B-045** (用户选 B, embedding 链路): 新增 [src/intellisource/llm/gateway/_embed.py](../src/intellisource/llm/gateway/_embed.py) `_EmbedMixin.embed(text) -> list[float] | None`（litellm.aembedding，graceful 异常路径）；新增 [pipeline/processors/embedder.py](../src/intellisource/pipeline/processors/embedder.py) `EmbeddingProcessor`；`config/llm_models.yaml` 加 `embed: openai/text-embedding-3-small`；无 OPENAI_API_KEY 时 embedding 列 NULL（vector mode 走 keyword fallback 不崩）
- **B-039** (tools 双副本去重 + step 9 真起栈 PASS): `tools/executes/{collect,process,distribute,search_and_content,llm}.py` 升级为 7 个 execute 函数的单一事实来源；新增 [src/intellisource/agent/tools/registry.py](../src/intellisource/agent/tools/registry.py) (453 行) 集中业务实现；`tools/__init__.py` 974→55 行 facade。**真起栈 step 9 PASS**：manual-collect task succeeded 336.9s；llm_call_logs 20 行 status=success / model=deepseek-v4-pro；20/20 processed_contents.summary 非空
- **B-031 步骤 10-11**: 阶段 4 真起栈 6 项部署破口 inline 修：**#17** SearchRequest.search_mode → `Literal[...]`；**#18** router `-> SearchResponse`；**#19** SearchResult 扩 title/body_text/source_name；**#20** SearchRequest.limit 强制 int=10；**#25** `to_tsquery` → `websearch_to_tsquery`；**#26** [llm/gateway/_stream.py](../src/intellisource/llm/gateway/_stream.py) 删 `gpt-4o-mini` 硬编码兜底。**B-046 / B-047 carryover**
- **B-032** (PR #65, pgvector + zhparser 复合 DB 镜像 path A1): research skill 调研确认公开域不存在复合镜像；新增 [docker/db.Dockerfile](../docker/db.Dockerfile) (FROM pgvector/pgvector:pg16 + SCWS 1.2.3 源码编译 + amutu/zhparser master)；[alembic/versions/001_initial_schema.py](../alembic/versions/001_initial_schema.py) 移除 DO/EXCEPTION 包裹 + 新增 CREATE TEXT SEARCH CONFIGURATION zhparser；详见 [docs/research/b032-pgvector-zhparser-image-options.md](research/b032-pgvector-zhparser-image-options.md)
- **B-035** (CI 强制跑 docker integration): [.github/workflows/ci.yml](../.github/workflows/ci.yml) `integration-tests` job 改 build composite db image + cache type=gha；新增 `docker-compose-smoke` job — `docker compose up -d --wait db redis migrate api` + 3 SQL 探针验 zhparser 路径
- **B-031 步骤 12** (beat schedule bootstrap): **修正 #27** worker healthcheck 改 `celery status` + beat healthcheck.disable；**修正 #28** 新增 `beat_init_handler(**_)` 让 beat 进程接 module-level connect；docker-compose beat command 切到 `-A intellisource.scheduler.boot beat`。真起 stack PASS：beat 日志 `2 entries loaded`
- **B-031 步骤 13-14** (订阅 + WeChat webhook): **修正 #29** [`EmailDistributor.from_env`](../src/intellisource/distributor/channels/email.py) 加 `IS_SMTP_USE_TLS` 环境变量；docker-compose mailhog 服务 (profile=walkthrough)。mailhog + Gmail + WeChat 三路径 PASS。**4 项 doc drift 并入 B-034**
- **B-040** (worker stdlib log trace_id 注入): 新增 [src/intellisource/observability/logging.py](../src/intellisource/observability/logging.py) `TraceIdFormatter`；scheduler signals bind/unbind `structlog.contextvars`；顺带修 [agent/executors/flexible.py](../src/intellisource/agent/executors/flexible.py) `logger.info(extra={"args": ...})` 与 LogRecord.args 冲突
- **B-048** (F-02 cross-loop xfail 闭环): main CI integration tests 162 passed；移除 `test_run_pipeline_marks_raw_content_as_processed` 的 xfail，切到独立 `async_sessionmaker + create_async_engine(pg_container, poolclass=NullPool)` 与生产 worker 同型

## backlog-b050 ~ b055 配置 UX + 三入口对齐

- **B-050-B-051 audit** (audit-only, 无代码改动): 用户提议 (1) wework 默认优先 + (2) 配置管理 UX 优化。审计产出 [docs/research/b050-wechat-vs-wework-audit.md](research/b050-wechat-vs-wework-audit.md) + [docs/research/b051-config-bootstrap-ux.md](research/b051-config-bootstrap-ux.md)。立 B-050 P3 + B-051 P2
- **B-033 + B-051** (D+C+A 长期完整路径): 
  - **Phase D**: B-033 闭环 — `build_distributor_facade()` 改 soft-disable（每渠道 try/except + warning + 剔除）；[main.py:_lifespan](../src/intellisource/main.py) IS_API_KEY=change-me-in-production guard 阻断启动 + `_collect_startup_warnings()`；`Makefile bootstrap` target
  - **Phase C**: [api/routers/system.py](../src/intellisource/api/routers/system.py) `/health` 加 `missing_config` 字段；[cli/main.py](../src/intellisource/cli/main.py) 新增 `doctor` 子命令（`✓ / ✗ / ○` 三态 + `--check-api` + `--strict`）
  - **Phase A**: `intellisource init` 交互式 CLI — API key 自动生成 / LLM provider 三选一 / 渠道四选一 / HN RSS 起步信源
- **B-054 + B-055** (subscriptions 三入口对齐重构): subscriptions 配置 yaml/API/CLI 三入口行为对齐 + 单一 Pydantic schema + service layer 集中业务逻辑
  - **Phase 1**: [subscription_models.py](../src/intellisource/config/subscription_models.py) + [subscription_validator.py](../src/intellisource/config/subscription_validator.py) per-channel 规则 + [subscription_loader.py](../src/intellisource/config/subscription_loader.py) (独立 IS_SUBSCRIPTION_CONFIG_DIR env) + `SubscriptionRepository.upsert(by-name)` + `bulk_sync_from_configs` 软删 paused + `POST /api/v1/subscriptions/reload`
  - **Phase 2**: alembic migration `d4e5f6a7b8c9_add_subscription_config_versions.py` + `ConfigVersionManager` 泛化（**删向后兼容** — table_name+config_cls 强制 kwarg / session 必传）+ `POST /subscriptions/config/rollback/{version}`
  - **Layer 1+2 重构** (修 real bug + 抽 service): 删 SubscriptionCreate/Update Request；POST /subscriptions 直接接 SubscriptionConfig（修复 API 缺 frequency/quiet_hours/timezone/discipline_tags 漂移）；新增 [src/intellisource/subscription/service.py](../src/intellisource/subscription/service.py) `SubscriptionService` 集中调度；router 退化为薄 HTTP 转发；**修真 bug** — 旧 API 不跑 SubscriptionValidator 致 yaml/API 校验严格度不一致
  - **Phase 3 B-055 CLI 薄壳**: [cli/main.py](../src/intellisource/cli/main.py) `intellisource subscriptions list/add/patch/rm/reload/rollback` 子命令；HTTP 自调本地 API 复用 middleware + metrics
- **B-050** (文档+默认值倾斜, 无业务代码改动, 依赖 B-033): [docker/.env.example](../docker/.env.example) 段重排 WeWork → WeChat → Email + 补 IS_WECOM_TOKEN/AES_KEY/CORP_ID；[docs/deploy/PRE-DEPLOY-WALKTHROUGH.md §0.2](../docs/deploy/PRE-DEPLOY-WALKTHROUGH.md) Distribution channels 矩阵。PRD §F-006 / ARCH M-007 主路径标记待 change-guard amendment（B-053 候选）

## Learnings Registry (详细见各 RETRO 报告)

- [RETRO-intellisource-v1.md](reviews/retro/RETRO-intellisource-v1.md) — 6 EXP (sprint-1~7)，应用决策 deferred → backlog B-016
- [RETRO-intellisource-v1-sprint-9.md](reviews/retro/RETRO-intellisource-v1-sprint-9.md) — 2 EXP 强制立项 (EXP-005 装配缺口 5 次复发 → B-017 / EXP-006 truncation 4/4 跨 3 角色)
- [RETRO-intellisource-v1-sprint-8.md](reviews/retro/RETRO-intellisource-v1-sprint-8.md) — 1 正向 EXP-007 立项 (Mid-Progress Drop Contract 通用化 → B-018)
- [SKILL-IMPROVE-*.md](reviews/retro/) — 8 份建议
- **EXP-CONTRACT-DRIFT** (PR #64): 改动 `api/routers/` 返回类型 / `search.*` dataclass 字段 / `storage.*` SQL SELECT 列 / `llm/gateway/_stream` 模型解析 等"契约文件"时，**必须**在 push 前跑 `make test-integration`；强制门禁通过 `make contract-check`（diff 触发清单）+ `make check-all`（check + integration）实现
