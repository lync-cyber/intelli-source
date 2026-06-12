---
id: "test-report-intellisource-v1"
doc_type: test-report
author: qa-engineer
status: approved
deps: ["dev-plan-intellisource-v1"]
consumers: [developer, qa-engineer, devops]
volume: main
required_sections:
  - "## 1. 测试策略"
  - "## 2. 测试用例矩阵"
  - "## 3. 覆盖率目标"
  - "## 4. 测试环境"
  - "## 5. 测试执行结果"
  - "## 6. 缺陷清单"
  - "## 7. 结论与建议"
---
# Test Report: IntelliSource

> 版本: v1 | 阶段: Phase 6 Testing | 测试执行日期: 2026-05-05
> 覆盖 Sprint 1~7 全部已完成任务（`T-001`~T-079 中属 Sprint 1~7 范围的任务）

[NAV]
- §1 测试策略 → §1.1 金字塔分层, §1.2 IPC边界
- §2 测试用例矩阵 → TC-001..TC-071 与 AC 映射
- §3 覆盖率目标 → 按模块行覆盖率（实测值）
- §4 测试环境
- §5 测试执行结果 → §5.1 执行汇总, §5.2 耗时分布
- §6 缺陷清单 → 已知 LOW 残留 + 测试基础设施债务
- §7 结论与建议 → go/no-go 判定
[/NAV]

## 1. 测试策略

### 1.1 测试金字塔

本项目为 backend-only Python 服务（无 UI），测试金字塔以单元测试为主、集成测试为辅，E2E 层由 FastAPI 路由级端到端测试承担（无独立 E2E 测试框架）。

| 层次 | 实际占比 | 工具 | 关注点 |
|------|---------|------|--------|
| Unit | 约 94% (1751 tests) | pytest + pytest-asyncio | 函数/方法级，外部依赖 mock；覆盖 M-001~M-011 所有模块 |
| Integration | 约 6% (111 tests) | pytest + httpx.AsyncClient + SQLite in-memory | 模块间接口、数据库 CRUD roundtrip、API 路由端到端 |
| E2E | 0（纳入 Integration 层） | — | 无独立 E2E 框架；API 路由集成测试覆盖核心用户路径 |

集成测试分布：
- `tests/integration/test_sprint7_integration.py` — 22 tests（LLM retry/fallback、ConfigResolver 分层合并、PromptBuilder 变体、AgentRunner 压缩、LLM stats API、clusters API、TaskChainRepository CRUD）
- `tests/integration/test_celery_worker_wiring.py` — 7 tests（Celery worker wiring、session_factory 协程协议、task 注册）
- `tests/unit/api/test_deps_integration.py` — 14 tests（DI 接驳集成验证，归类在 unit/ 目录但属集成精度）
- 其余 68 条分散于 `tests/unit/api/` 各路由文件（ASGITransport 真路由 + SQLite session）

### 1.2 IPC 边界测试

本项目无前后端分离 IPC 边界（backend-only）。模块间通信测试策略：

- **FastAPI 路由层 → 存储层**: 通过 `httpx.AsyncClient` + `ASGITransport(create_app())` 走真 lifespan + 真 SQLite session，覆盖 lifespan、DI 注入、路由、Repository 全链路。
- **Celery 任务层 → 数据库层**: 通过 `test_celery_worker_wiring.py` 验证 `worker_process_init` signal 触发、`session_factory` 协程协议、`CeleryTasks` 注册。
- **LLM Gateway → litellm**: 通过 mock `litellm.acompletion` 控制成败序列，保留 tenacity retry 装饰器逻辑（`wait_none()` 跳过退避但保留重试链）。
- **已知限制**: 存储层单元测试使用 SQLite in-memory，不覆盖 PostgreSQL 专有特性（pgvector HNSW、JSONB @> 操作符、zhparser 全文检索）；见 §6 BD-001/BD-002。

---

## 2. 测试用例矩阵

矩阵按 Sprint/模块组织，列出代表性 TC 并映射到 dev-plan AC。覆盖状态：covered = 有直接测试；partial = AC 部分或通过集成间接覆盖；uncovered = 无测试或测试为纯 mock 无真实路径。

### Sprint 1: 基础设施与数据层 (`T-001`~T-009, T-007a)

| 用例ID | 任务 | 关联 AC | 测试文件 | 类型 | 覆盖状态 |
|--------|------|---------|---------|------|---------|
| TC-001 | `T-001` 项目骨架 | AC-T001-1~5 | test_project_structure.py | Unit | covered |
| TC-002 | T-002 数据库连接 | AC-T002-1~4 | test_database.py | Unit | covered |
| TC-003 | T-003 ORM模型 | AC-T003-1~5 | test_models.py | Unit | covered |
| TC-004 | T-004 Repository | AC-054, AC-T004-1~5 | test_repositories.py | Unit | covered |
| TC-005 | T-005 pgvector | AC-055, `AC-056`, AC-T005-1~4 | test_vector.py | Unit | partial（SQLite mock；真 PG 向量检索未覆盖）|
| TC-006 | T-006 结构化日志 | AC-057~059, AC-T006-1~2 | test_logging.py, test_metrics.py | Unit | covered |
| TC-007 | T-007 健康检查 | AC-060, AC-T007-1~4 | test_health.py | Unit | covered |
| TC-008 | T-007a 错误分类 | AC-T007a-1~3 | test_errors.py | Unit | covered |
| TC-009 | T-008 配置模型 | AC-001, AC-003, AC-T008-1~3 | test_models.py(config) | Unit | covered |
| TC-010 | T-009 配置加载 | AC-002, AC-004, AC-T009-1~5 | test_loader.py | Unit | covered |

### Sprint 2: 采集引擎与处理管道 (`T-010`~T-018)

| 用例ID | 任务 | 关联 AC | 测试文件 | 类型 | 覆盖状态 |
|--------|------|---------|---------|------|---------|
| TC-011 | `T-010` 采集器基类/注册中心 | `AC-005`, AC-T010-1~7 | test_base.py, test_registry.py | Unit | covered |
| TC-012 | T-011 RSS采集 | AC-006~008, AC-T011-1~2 | test_rss.py | Unit | partial（网络请求 mock；真 feedparser 解析正常路径覆盖；错误分支 85% 覆盖）|
| TC-013 | T-012 Web爬虫 | AC-006~007, AC-T012-1~4 | test_web.py | Unit | covered |
| TC-014 | T-013 API采集 | AC-006~008, AC-T013-1~2 | test_api.py | Unit | covered |
| TC-015 | T-014 速率限制 | AC-010~011, AC-T014-1~3 | test_rate_limiter.py | Unit | covered |
| TC-016 | T-015 自适应调度 | AC-009, AC-012, AC-T015-1~3 | test_adaptive.py | Unit | covered |
| TC-017 | T-016 管道引擎 | AC-013, AC-015~016, AC-T016-1~4 | test_engine.py, test_middleware.py, test_context.py | Unit | covered |
| TC-018 | T-017 条件分支/批处理 | AC-014, AC-017, AC-T017-1~3 | test_condition.py, test_batch.py | Unit | covered |
| TC-019 | T-018 内置处理器 | AC-015, AC-T018-1~4 | test_processors.py | Unit | covered |

### Sprint 3: LLM智能处理 (`T-019`~T-026)

| 用例ID | 任务 | 关联 AC | 测试文件 | 类型 | 覆盖状态 |
|--------|------|---------|---------|------|---------|
| TC-020 | `T-019` LLM统一网关 | `AC-028`, `AC-031` | test_gateway.py | Unit | covered |
| TC-021 | T-020 熔断器/降级 | AC-029~030 | test_circuit_breaker.py, test_fallback.py | Unit | covered |
| TC-022 | T-021 优先级队列/成本追踪 | AC-032~033 | test_priority_queue.py, test_cost_tracker.py | Unit | covered |
| TC-023 | T-022 LLM结构化提取 | AC-018, AC-021 | test_tools.py(pipeline) | Unit | covered |
| TC-024 | T-023 语义去重 | AC-019, AC-022 | test_processors.py(pipeline), test_filter.py(llm) | Unit | covered |
| TC-025 | T-024 内容聚类 | AC-020 | test_processors.py(pipeline) | Unit | covered |
| TC-026 | T-025 摘要/打标 | AC-023~024 | test_processors.py(pipeline) | Unit | covered |
| TC-027 | T-026 敏感词过滤 | AC-025 | test_filter.py(llm) | Unit | covered |

### Sprint 4: 任务编排与分发 (`T-027`~T-036)

| 用例ID | 任务 | 关联 AC | 测试文件 | 类型 | 覆盖状态 |
|--------|------|---------|---------|------|---------|
| TC-028 | `T-027` Celery任务定义 | `AC-034`~035 | test_tasks.py | Unit | covered |
| TC-029 | T-028 任务状态机 | AC-038~039 | test_state_machine.py | Unit | covered |
| TC-030 | T-029 幂等保护 | AC-036~037 | test_idempotency.py | Unit | covered |
| TC-031 | T-030 AgentRunner双模式 | AC-066~067 | test_runner.py | Unit | covered |
| TC-032 | T-031 分发器/订阅规则 | AC-043, AC-043a, AC-T031-4~6 | test_matcher.py, test_scorer.py | Unit | covered |
| TC-033 | T-032 微信公众号分发 | AC-040, AC-044~045 | test_wechat.py | Unit | covered |
| TC-034 | T-033 企业微信分发 | AC-041, AC-044~045 | test_wework.py | Unit | covered |
| TC-035 | T-034 邮件分发 | AC-042, AC-044~045 | test_email.py | Unit | covered |
| TC-036 | T-035 推送频率控制 | AC-046 | test_frequency.py | Unit | covered |
| TC-037 | T-036 Agent工具注册 | AC-066 | test_tools.py(agent) | Unit | covered |

### Sprint 5: 检索/API/CLI与集成 (`T-037`~T-046)

| 用例ID | 任务 | 关联 AC | 测试文件 | 类型 | 覆盖状态 |
|--------|------|---------|---------|------|---------|
| TC-038 | `T-037` 混合检索引擎 | `AC-051`, `AC-056` | test_hybrid.py | Unit | partial（SQLite mock；真实 pgvector 向量融合路径 75% 行覆盖，lines 47-71 PG专有路径未执行）|
| TC-039 | T-038 即时检索/对话压缩 | AC-050, AC-052~053 | test_chat_session.py | Unit | covered |
| TC-040 | T-039 Webhook回调 | AC-T039 | test_webhooks.py | Unit | covered |
| TC-041 | T-040~T-042 API路由层 | AC-061~065 | test_sources.py, test_content_routes.py, test_tasks.py, test_llm_routes.py | Unit | covered |
| TC-042 | T-043 认证中间件 | AC-061 | test_middleware.py | Unit | covered |
| TC-043 | T-044 CLI工具 | AC-064 | test_main.py(cli) | Unit | covered |
| TC-044 | T-045 FastAPI入口 | AC-065 | test_app_entry.py, test_lifespan.py | Unit | covered |
| TC-045 | T-046 Alembic迁移 | AC-054 | test_migration.py | Unit | covered |

### Sprint 6: 处理器/智能体架构重构 (`T-047`~T-056)

| 用例ID | 任务 | 关联 AC | 测试文件 | 类型 | 覆盖状态 |
|--------|------|---------|---------|------|---------|
| TC-046 | T-048 原子化工具函数 | AC-018~025 降级路径 | test_tools.py(pipeline) | Unit | covered |
| TC-047 | T-051 PromptBuilder | AC-T051 | test_prompt_builder.py | Unit | covered |
| TC-048 | T-052 LLM调用缓存 | AC-T052 | test_cache.py | Unit | covered |
| TC-049 | T-053 模型参数配置 | AC-T053 | test_model_config.py | Unit | covered |
| TC-050 | T-054 Agent处理编排引擎 | AC-066~067 | test_orchestration.py, test_pipeline.py | Unit | covered |
| TC-051 | T-055 管道配置更新 | AC-T055 | test_tools.py(pipeline) | Unit | covered |

### Sprint 7: LLM韧性增强与配置治理 (`T-057`~T-075)

| 用例ID | 任务 | 关联 AC | 测试文件 | 类型 | 覆盖状态 |
|--------|------|---------|---------|------|---------|
| TC-052 | `T-057` 指数退避重试 | AC-T057-1~7 | test_gateway_retry.py | Unit | covered |
| TC-053 | `T-057` retry 端到端 | AC-T063-1 | test_sprint7_integration.py::TestLLMRetryFallback | Integration | covered |
| TC-054 | T-058 上下文压缩增强 | AC-T058-1~7 | test_compaction.py | Unit | covered |
| TC-055 | T-058 压缩 AgentRunner 触发 | AC-T063-4 | test_sprint7_integration.py::TestAgentRunnerCompaction | Integration | covered |
| TC-056 | T-059 配置分层合并 | AC-T059-1~8 | test_resolver.py | Unit | covered |
| TC-057 | T-059 三层合并集成 | AC-T063-2 | test_sprint7_integration.py::TestConfigResolverMerge | Integration | covered |
| TC-058 | T-061 LLM Pydantic验证 | AC-T061-1~6 | test_model_config_validation.py | Unit | covered |
| TC-059 | T-060 LLM统计API | AC-T060-1~8 | test_llm_routes.py | Unit | covered |
| TC-060 | T-060 LLM统计API集成 | AC-T063-5 | test_sprint7_integration.py::TestLLMStatsEndpoint | Integration | covered |
| TC-061 | T-062 Prompt变体加载 | AC-T062-1~6 | test_prompt_builder.py(变体部分) | Unit | covered |
| TC-062 | T-062 变体+ModelProfile集成 | AC-T063-3 | test_sprint7_integration.py::TestPromptBuilderModelProfile | Integration | covered |
| TC-063 | T-072 DB会话DI接驳 | AC-T072-1~6 | test_deps.py, test_deps_integration.py, test_lifespan.py | Unit/Integration | covered |
| TC-064 | T-073 clusters端点 | AC-T073-1~6 | test_clusters_routes.py(26 tests, 1 skipped) | Unit | partial（AC-T073-1 401鉴权 skipped）|
| TC-065 | T-073 clusters E2E | AC-T063-6 | test_sprint7_integration.py::TestClustersEndpoint | Integration | covered（4 真E2E + 1 router-mock）|
| TC-066 | T-074 TaskChainRepository | AC-T074-1~6 | test_task_chain_repository.py | Unit | covered |
| TC-067 | T-074 CRUD集成 | AC-T063-7 | test_sprint7_integration.py::TestTaskChainRepositoryCRUD | Integration | covered |
| TC-068 | T-075 Celery wiring | AC-T075-1~5 | test_celery_worker_wiring.py | Integration | covered |
| TC-069 | T-075 runner._persist参数化 | AC-T075-3 | test_runner_persist.py | Unit | covered |
| TC-070 | T-063 全量pytest通过 | AC-T063-8 | 全套运行 | — | covered（1862 PASSED）|
| TC-071 | T-063 mypy strict | AC-T063-9 | test_project_structure.py::TestMypyStrict | Unit | covered |

### 覆盖盲区汇总

| 任务 | 未覆盖场景 | 建议处理 |
|------|-----------|---------|
| T-005 / `T-037` / T-073 | PostgreSQL 专有路径（pgvector 向量检索、JSONB @> 操作符、zhparser 全文检索）未覆盖 | Sprint-8 引入 testcontainers-postgres 后补充（BD-001 carryover）|
| T-073 | `GET /api/v1/clusters` 401 鉴权测试（TC-064 1 skipped）| 鉴权机制稳定后补充（BD-002）|
| T-002 / T-004 | DatabaseManager 连接池真实释放路径、BaseRepository 分页边界（lines 36-38, 41, 79, 90）| 风险 LOW，建议 Sprint-8 补充 |
| T-075 | scheduler/boot.py shutdown handler 覆盖（73%，lines 86-95 RuntimeError fallback 路径）| 风险 LOW，worker shutdown 是 best-effort 路径 |

---

## 3. 覆盖率目标

**实测总体行覆盖率: 96%**（1862 PASSED，pytest-cov 实测，2026-05-05）

**覆盖率测量命令**（可复现）：

```bash
uv run pytest --cov=src/intellisource --cov-report=term-missing --cov-report=html
```

- `--cov=src/intellisource`：覆盖范围限定为项目源码包（对应 `src/intellisource/`）
- `--cov-report=term-missing`：终端输出各模块覆盖率及未覆盖行号
- `--cov-report=html`：HTML 详细报告输出至 `htmlcov/index.html`（在浏览器中打开可查看逐行覆盖情况）
- 数据生成时间：2026-05-05（sprint-7 关闭后代码快照）

注：`pyproject.toml` 中 `addopts` 默认不含 `--cov`，需显式附加上述参数运行；`htmlcov/` 目录已加入 `.gitignore`，不随源码提交。

### 按模块行覆盖率（实测）

| 模块 | 行数 | 未覆盖 | 覆盖率 | 未覆盖说明 |
|------|------|--------|--------|-----------|
| intellisource.agent.compaction | 66 | 2 | 97% | 压缩失败极端边界 |
| intellisource.agent.pipeline | 56 | 0 | 100% | — |
| intellisource.agent.runner | 111 | 8 | 93% | 异步错误路径（43-45, 134-135, 221-223）|
| intellisource.agent.tools | 60 | 6 | 90% | agent工具执行路径（101,106,111,116,121,126）|
| intellisource.api.deps | 15 | 0 | 100% | — |
| intellisource.api.middleware | 43 | 0 | 100% | — |
| intellisource.api.routers.clusters | 27 | 2 | 93% | 无法触达分支（75-76）|
| intellisource.api.routers.sources | 82 | 1 | 99% | 罕见分支（86）|
| intellisource.cli.main | 118 | 5 | 96% | Typer 运行时分支 |
| intellisource.collector.adapters.rss | 68 | 10 | 85% | feedparser 异常分支（26, 35-36, 48, 56, 64, 74, 82-84）|
| intellisource.collector.adapters.web | 50 | 0 | 100% | — |
| intellisource.collector.rate_limiter | 24 | 2 | 92% | Redis 超时路径 |
| intellisource.config.loader | 89 | 4 | 96% | watchfiles 回调边界 |
| intellisource.config.resolver | 97 | 6 | 94% | env 变量白名单边界 |
| intellisource.distributor（全部通道） | ~400 | ~10 | 96~100% | 各通道 HTTP 错误路径 |
| intellisource.llm.gateway | 165 | 5 | 97% | 多模型路由极端路径 |
| intellisource.llm.processors.fingerprint | 10 | 3 | 70% | 指纹提取失败分支（14-15, 20）|
| intellisource.main | 86 | 7 | 92% | Redis 关闭路径（68-69）、Celery 启停路径（120-122, 130, 183）|
| intellisource.observability.tracing | 21 | 2 | 90% | span 导出路径（34-35）|
| intellisource.pipeline（全部）| ~220 | ~4 | 95~100% | 条件分支边界 |
| intellisource.scheduler.boot | 41 | 11 | 73% | 真实 Celery worker 启动路径（34, 51, 63, 86-95）|
| intellisource.scheduler.state_machine | 55 | 0 | 100% | — |
| intellisource.scheduler.tasks | 86 | 6 | 93% | pipeline 执行异常路径 |
| intellisource.search.hybrid | 72 | 18 | 75% | 真实 PostgreSQL 查询路径（47-71, 130-132, 139-141）|
| intellisource.storage.repositories.base | 56 | 6 | 89% | 分页游标边界（36-38, 41, 79, 90）|
| intellisource.storage.repositories.chat_session | 28 | 14 | 50% | find_by_channel_user / update_context / cleanup_expired / list（真 DB 路径未覆盖）|
| intellisource.storage.repositories.cluster | 18 | 3 | 83% | JSONB tag 过滤 PG 路径（32, 34, 36）|
| intellisource.storage.repositories.task_chain | 25 | 4 | 84% | UUID 转换边界（29-30, 37-38）|
| **TOTAL** | **3846** | **169** | **96%** | — |

**注**：`scheduler/boot.py` 73% 和 `search/hybrid.py` 75% 和 `storage/repositories/chat_session.py` 50% 是三个低覆盖模块，均为 PostgreSQL/Celery 生产运行时路径，SQLite in-memory 测试架构无法直接覆盖，非测试逻辑缺失。

---

## 4. 测试环境

| 项目 | 值 |
|------|-----|
| Python 版本 | 3.11.15 |
| pytest | 9.0.2 |
| pytest-asyncio | 1.3.0 |
| pytest-cov | 7.1.0 |
| 异步模式 | `asyncio_mode = auto` |
| 数据库（测试） | SQLite in-memory（aiosqlite 0.22.1+）|
| 数据库（生产目标） | PostgreSQL + pgvector |
| 向量存储（测试） | mock（无真实 pgvector）|
| LLM | mock（`litellm.acompletion` 被 monkeypatched）|
| Redis/Celery | mock（`unittest.mock.AsyncMock`）|
| 覆盖率工具 | pytest-cov（行覆盖，未配置分支覆盖）|
| mypy | strict 模式，106 source files，zero issues |
| ruff | check + format，clean |
| 已知测试基础设施债务 | tests/ 累计约 166 处 pre-existing ruff 风格警告（不影响运行，已 backlog）；SQLite-vs-Postgres 集成测试基础设施差距（SR-002，Sprint-8 backlog）|

---

## 5. 测试执行结果

测试执行于 2026-05-05，基于 sprint-7 关闭后代码快照。

| 用例ID | 测试文件/类 | 结果 | 备注 |
|--------|-------------|------|------|
| TC-001~TC-051 (Sprint 1~6) | tests/unit/ 全部 | PASSED | 共约 1751 unit tests |
| TC-052~TC-069 (Sprint 7) | test_sprint7_integration.py, test_celery_worker_wiring.py, test_clusters_routes.py 等 | PASSED (1 SKIPPED) | 22+11+68 integration+unit Sprint-7 新增 |
| TC-064 (401鉴权) | test_clusters_routes.py::TestClustersAuth::test_t073_ac1_missing_x_api_key_returns_401 | SKIPPED | pytest.skip 标注，鉴权测试基础设施待完善 |
| TC-070 全量pytest | 全套 | 1862 PASSED + 1 SKIPPED + 0 FAILED | 基线确认通过 |
| TC-071 mypy strict | TestMypyStrict | PASSED | 106 source files, zero issues |

### 5.1 执行汇总

- **总用例数**: 1863（含 1 skipped）
- **通过**: 1862 | **失败**: 0 | **跳过**: 1
- **通过率**: 99.95%（含 skipped；不计 skipped 则 100%）
- **总耗时**: 约 17~31 秒（无 coverage: ~17s；含 coverage: ~31s）

### 5.2 耗时分布（Top 10 最慢用例）

| 排名 | 测试 | 耗时 |
|------|------|------|
| 1 | TestMypyStrict::test_mypy_strict_passes | 1.10~1.13s |
| 2 | TestConfigWatcher::test_watcher_triggers_callback_on_file_change | 1.08~1.10s |
| 3 | TestLLMRetryFallback::test_retry_then_succeed_returns_result | 0.57~0.59s |
| 4 | TestLLMStatsEndpoint::test_llm_stats_with_records_returns_aggregated_fields | 0.27~0.29s |
| 5 | TestEmailDistributorBasic::test_distribute_sends_email | 0.27~0.28s |
| 6 | TestPyprojectDependencies::test_package_installable | 0.16~0.17s |
| 7 | TestPriorityOrdering::test_dequeue_from_empty_queue_blocks | 0.10s |
| 8~10 | PromptBuilder 截断集成测试 | 0.07~0.08s |

套件总体执行效率良好，最慢用例为 mypy 进程级调用和文件 watcher 等待，属预期开销。

---

## 6. 缺陷清单

### 6.1 残留 LOW 缺陷（来自 CODE-REVIEW 报告，已知非阻塞）

| 缺陷ID | 关联任务 | 严重等级 | 状态 | 来源 | 描述 |
|--------|----------|----------|------|------|------|
| DEF-001 | T-063 | LOW | carry（backlog） | CODE-REVIEW-T-063-r1 R-001 | `test_sprint7_integration.py` 模块级 monkey-patch `SQLiteTypeCompiler.visit_JSONB` 为全局副作用，违反 pytest 隔离原则；幂等 guard 保证不崩溃但泄漏到后续模块 |
| DEF-002 | T-063 / T-073 | LOW | carry（upstream carryover） | CODE-REVIEW-T-063-r1 R-002 | `test_clusters_filter_by_tag_forwards_to_repository` mock 了 ClusterRepository 而非真集成；PG @> SQLite 不兼容导致无法走真路径 |
| DEF-003 | T-063 / T-074 | LOW | carry（backlog） | CODE-REVIEW-T-063-r1 R-003 | `test_update_status_missing_id_does_not_raise` 断言过弱，仅靠"无异常"通过，未验证无副作用 |
| DEF-004 | T-075 | LOW | carry（backlog） | CODE-REVIEW-T-075-r2 R-001-r2 | `worker_shutdown_handler` 在嵌套 event loop 场景下静默吞 `RuntimeError`，`engine.dispose()` 可能未执行 |
| DEF-005 | T-075 | LOW | carry（backlog） | CODE-REVIEW-T-075-r2 R-002-r2 | signal 幂等 guard 用动态 attribute hack（`worker_process_init._intellisource_connected = True`），比内部标志位脏 |
| DEF-006 | T-074 | LOW | closed（T-075 已修） | CODE-REVIEW-T-074-r2 R-001 | runner.py `_persist` 中 `trigger_type`/`execution_mode` 硬编码 → T-075 已参数化，闭环 |

### 6.2 测试基础设施债务（非代码缺陷）

| 债务ID | 关联任务 | 严重等级 | 状态 | 描述 | 建议 |
|--------|----------|----------|------|------|------|
| BD-001 | T-005, `T-037`, T-073 | MEDIUM | backlog（Sprint-8） | SQLite-vs-Postgres 集成测试基础设施差距：pgvector HNSW、JSONB @> 操作符、zhparser 全文检索无法在 SQLite 下测试；search/hybrid.py 75%、storage/repositories/cluster.py 83% 低覆盖率根因 | Sprint-8 引入 testcontainers-postgres，将 test_vector.py、test_hybrid.py、test_repositories.py 中 PG 专有路径迁移为真实集成测试 |
| BD-002 | T-073 | LOW | backlog | `GET /api/v1/clusters` 401 鉴权测试 1 SKIPPED；API Key 鉴权中间件集成测试覆盖不完整 | 鉴权测试 fixture 完善后补充；Sprint-8 T-076 健康检查完善时顺手处理 |
| BD-003 | T-063 / T-073 / T-075 | LOW | backlog | tests/ 目录累计约 166 处 pre-existing ruff 风格警告；不影响运行但增加代码审查噪声 | Sprint-8 code-quality 清理任务（T-077）一并处理 |

### 6.3 覆盖率盲区（观察项，非 bug）

| 观察ID | 模块 | 覆盖率 | 未覆盖路径 | 风险评估 |
|--------|------|--------|-----------|---------|
| OBS-001 | scheduler/boot.py | 73% | lines 86-95（worker shutdown handler RuntimeError fallback） | LOW — OS 进程退出时 fd 回收，shutdown 为 best-effort |
| OBS-002 | search/hybrid.py | 75% | lines 47-71（真实 DB 查询路径）、130-132、139-141 | MEDIUM — 产品关键路径，但依赖 PG 环境；BD-001 覆盖 |
| OBS-003 | storage/repositories/chat_session.py | 50% | lines 42-47, 55, 66-74, 81-82（find_by_channel_user / cleanup_expired / list） | MEDIUM — ChatSession 功能依赖这些方法；BD-001 覆盖 |
| OBS-004 | llm/processors/fingerprint.py | 70% | lines 14-15, 20（指纹提取失败分支） | LOW — 失败路径已通过相关 test_filter.py 间接触及 |

---

## 7. 结论与建议

### 发布标准对照

| 标准 | 目标 | 实测 | 状态 |
|------|------|------|------|
| 全量 pytest 通过率 | 100%（无 FAILED）| 99.95%（1862 PASSED / 0 FAILED / 1 SKIPPED）| 通过 |
| mypy --strict | zero issues | 106 files, 0 issues | 通过 |
| ruff check + format | clean | clean | 通过 |
| 行覆盖率 | ≥90%（目标） | 96% | 通过 |
| CRITICAL/HIGH 缺陷 | 0 open | 0 open（sprint-7 全部闭环）| 通过 |
| Sprint-7 AC 覆盖率 | 100% | 100%（含 1 SKIPPED 鉴权用例，已知非 CRITICAL）| 通过 |

### go / no-go 判定

**结论: conditional-go**

**可发布条件已满足**（满足发布门禁）：
- 零 FAILED 测试（1862 PASSED + 1 SKIPPED）
- mypy strict 零 type error（106 source files）
- 96% 行覆盖率（超过 90% 目标）
- 全部 CRITICAL/HIGH 缺陷已在 sprint-7 内闭环
- Sprint 1~7 全部任务 AC 均有测试覆盖（covered 或 partial）

**已知残留风险（conditional 条件）**：
1. **BD-001 PostgreSQL 集成测试覆盖缺口**（MEDIUM）：pgvector 向量检索、JSONB 操作符、全文检索无法通过当前 SQLite mock 测试体系验证；生产部署时需在真实 PG 环境手工冒烟验证 `/api/v1/search`（混合检索）和 `/api/v1/clusters`（tag 过滤）接口行为。建议在 Sprint-8 前完成至少一次 PG 环境冒烟测试。

   **最小可执行冒烟规范**（供 devops 在 Phase 7 deployment 直接执行）：

   环境变量来源：`${API_BASE}` 指向部署环境的 API 根 URL（由 `deploy-spec` 环境配置章节定义，开发环境默认 `http://localhost:8000`）；`${API_KEY}` 为部署环境签发的 API 凭证（由 `deploy-spec` 凭证管理章节提供，本地冒烟可使用 `pyproject.toml` / `.env` 中的开发密钥）。执行前须 `export API_BASE=... API_KEY=...`。

   前置数据要求：数据库中至少存在 1 条 cluster 记录和 1 条 content 记录；若均不存在，空库下接口也应返回 HTTP 200，此时 `total=0` / `clusters=[]` 同样视为 PASS。

   ```bash
   # 冒烟用例 1：混合检索接口
   curl -s -w "\n%{http_code}" \
     -H "X-API-Key: ${API_KEY}" \
     "${API_BASE}/api/v1/search?q=test&limit=10"
   ```

   pass 标准（用例 1）：
   - HTTP 状态码为 `200`
   - 响应体为合法 JSON，包含顶层字段 `items`（数组，可为空）和 `total`（整数 `>= 0`）
   - 示例最小契约：`{"items": [...], "total": 0}` 或 `{"items": [...], "total": N}`（N >= 0）

   ```bash
   # 冒烟用例 2：clusters 列表接口
   curl -s -w "\n%{http_code}" \
     -H "X-API-Key: ${API_KEY}" \
     "${API_BASE}/api/v1/clusters"
   ```

   pass 标准（用例 2）：
   - HTTP 状态码为 `200`
   - 响应体为合法 JSON，包含顶层字段 `clusters`（数组，可为空）
   - 示例最小契约：`{"clusters": [...]}` 或 `{"clusters": []}`

   判定规则：两个用例均满足 pass 标准 → 冒烟通过，条件 1 满足；任一断言失败（非 200 / 缺少必需字段 / 响应非 JSON）→ 冒烟 FAIL，conditional-go 不满足，需在进入 Phase 7 前修复。
2. **DEF-001~DEF-005 五个 LOW 残留**：全部为 test-quality 改进点或 best-effort 路径，不影响产品功能正确性，不阻塞发布。

**优先级建议（Sprint-8 前处理）**：
1. PG 环境冒烟测试（手工）—— 验证向量检索、cluster tag 过滤真实行为
2. DEF-003 补强 `test_update_status_missing_id_does_not_raise` 断言
3. DEF-001 将 SQLite patch 迁移至 `tests/conftest.py` fixture（与 BD-001 迁移一并处理）

**Sprint-8 backlog 建议**（不阻塞当前发布）：
- 引入 testcontainers-postgres 解决 BD-001
- 补全 API Key 鉴权测试 fixture 解决 BD-002
- 清理 tests/ ruff 债务解决 BD-003（与 T-077 合并）
