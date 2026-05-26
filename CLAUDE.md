# CataForge

## 项目信息
- 项目名称: IntelliSource
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.4.1
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
  <!-- 可选值: standard | agile-lite | agile-prototype。矩阵见 COMMON-RULES §执行模式矩阵 -->
- 阶段配置: ui_design=N/A（backend-only），testing=启用，deployment=启用
- model 继承: AGENT.md 中 `model: inherit` 继承父会话模型

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)
- 当前阶段: backlog-burndown — **B-031 阶段 0 + 阶段 1 步骤 3 PASS / 步骤 4 partial（阻塞于 B-037 worker async 设计缺陷）**，累计 12 项 NO-GO 修复 inline + 6 项 carryover 立项 (B-032~B-037)
- 下一步行动: **B-037 P0 worker async/sync bridge hardening 优先**（阻塞 walkthrough 大半剩余步骤）；B-037 闭环后从 B-031 阶段 1 步骤 4 重启 walkthrough
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(N/A), dev_planning, sprint-1..7, retrospective, testing, sprint-7r, sprint-8r, sprint-9, sprint-8 P2, audit-fix-pr53, audit-fix-pr54, backlog-b001-b002, backlog-b003-b006, backlog-b007, backlog-b009-decision, backlog-b029-b030-polish, backlog-b008, backlog-arch-governance, backlog-b010, b031-walkthrough-phase-0-1-partial]
- 当前回归基线: 2838 PASS / 0 FAIL / 0 skip / 0 xfail / 51 deselected；mypy --strict + ruff + lint-imports 8/8 + deptry + vulture clean
- 文档状态: prd / arch / dev-plan(主卷+s1~s7+s7r+s8r+s9) / test-report / deploy-spec = approved；ui-spec = N/A；dev-plan-s8 = draft；backlog = approved
- audit-fix-pr53 闭环 (commit 7e10e77): F-01~F-11 P0 + F-12~F-27 P1 + F-28~F-48 P2/P3 — 39 项，详见 PR #53 描述
- audit-fix-pr54 闭环 (commit 31bddde): F-11 receiver_id / F-25 health 豁免 / F-42 PG /search 真链路 / idempotency RuntimeWarning / F-20+F-21 health 并发 / F-22 metrics 4 路径 / F-23 trace_id 跨 worker / F-24 alerts.yml / F-26 priority queue / F-27 content_not_found / 2 xfail (HybridIndex tags/date) / 1 placeholder skip 删 / 46 docker skip 转 deselect — 14 项
- backlog-b001-b002 闭环: B-001 `/search/chat/stream` 切 `AgentRunner.run_flexible_stream` (新增 RAG-aware 流式入口 + LLMGateway.stream_complete 支持 messages 参数 + FlexibleLoop.run_stream) + B-002 `SearchRequest.date_from/to: str → datetime`（非法值 422 而非 500）；SSE 事件契约 step/sources/token/done/error
- backlog-b003-b006 闭环 (inline 批次，3 batch): B-006 storage fixture ARRAY→JSON conftest mutation (单跑 PASS) / B-003 `intellisource_health_status` labeled gauge + HealthDegradedFor5m alert / B-004 `scheduler.dispatch.send_task_with_trace()` facade + guardrail (src/ 范围) / B-005 MetricsCollector labeled counter (pushes_total{channel,status} + llm_calls_total{model})；code-review verdict approved_with_notes → R-001 inline 修订 (counter+gauge 子系统 labelnames 强约束对齐) → 最终 approved；详见 [docs/reviews/code/CODE-REVIEW-backlog-p1-r1.md](docs/reviews/code/CODE-REVIEW-backlog-p1-r1.md)
- backlog-b007 闭环: LLMGateway 单类 732 行拆为 6 mixin (`_complete` 200 / `_chat` 200 / `_stream` 185 / `_queue` 54 / `_metrics` 44 / `_protocols` 80) + facade `__init__.py` 120 行；`_GatewayProtocol` mypy --strict self-type 兜底；公共 API (complete/chat/stream_complete) 零破坏；2820 PASS 不退化；code-review verdict approved 0 issue；详见 [docs/reviews/code/CODE-REVIEW-B-007-r1.md](docs/reviews/code/CODE-REVIEW-B-007-r1.md)
- backlog-b009-decision 闭环 (decision-only, reaffirm 选项 ②): PRD AC-063 [ASSUMPTION] 已在 sprint-9 锁定 YAML-as-source-of-truth；pipelines router 现状即决策实现 (list/detail/run, 无 HTTP CRUD)；完整 workflow CRUD (DB 存储 + 历史版本) 保留 v2+ 范畴，不立项；无代码改动；BACKLOG B-009 删除
- backlog-b008 闭环: `truncate_summary` 接入 LLM summarizer（`summarizer.structured` 模板 + `gateway.complete(response_format=json_object)` + `tool_deps` 注入）；产出 `{title, summary, timeline[], key_points[]}` 结构化摘要；3 层 fallback（LLM 异常 / JSON 解析失败 / 缺必要字段 → 回退字符串截断）；PRD AC-023 [ASSUMPTION] 移除；2834 PASS (+7 测试)
- backlog-b029-b030-polish 闭环: B-029 alerts.yml `LLMCallFailureRateHigh` + `PushFailureRateHigh` 按 `model`/`channel` label 拆分 (`sum by (model)` / `sum by (channel)` + annotations `{{ $labels.* }}` 模板化) / B-030 R-002 guardrail 注释显式化范围 + R-003 `_ALLOWED_POSIX` 精确路径匹配 + R-004 `DistributorFacade.__init__` + `LLMGateway.__init__` 集中 `register_labeled_counter` (hot-path 重复 register 移除)；2827 PASS (+7 测试)
- backlog-b010 闭环: devops 子代理产出 `docs/deploy-spec/deploy-spec-intellisource-v1.md` (755 行 + changelog-intellisource-v1.md) — 4 模板必填段 (构建流程 / 环境配置 / CI/CD 流水线 / 发布检查清单) 全覆盖；§2 含 dev/staging/prod 三环境矩阵 + zhparser DB 镜像要求 (R-005) + 11 项指标家族 (B-014 全覆盖) + queue.priority.* 实际队列名；§3 含 promtool check rules 步骤 (B-015) + SBOM (syft/buildx) + trivy/grype 漏洞门禁 + run_pipeline 唯一注册任务 smoke + Prometheus rules grep；§4 8 段签字含 zhparser/pgvector 双扩展验证 + webhook token 轮换。reviewer r1 = needs_revision (2 HIGH + 4 MEDIUM + 3 LOW)；devops r2 修订 9 项全部闭环 (R-001 回滚改 git checkout+rebuild 方案 B / R-002 smoke 删 collect_source+distribute_content 假名 / R-003 指标 grep 7→11 / R-004 metrics auth 描述对齐 _EXEMPT_EXACT 已豁免 / R-005 zhparser 落地 / R-006 队列名落地 / R-007 计数同步 / R-008 webhook 双 token / R-009 §4.5 内联 promtool)。orchestrator inline r2 audit = approved；详见 [docs/reviews/doc/REVIEW-deploy-spec-intellisource-v1-r2.md](docs/reviews/doc/REVIEW-deploy-spec-intellisource-v1-r2.md)。B-014/B-015 在 deploy-spec 中已显式覆盖，待 staging 真实部署后实测验证
- Learnings Registry:
  - [RETRO-intellisource-v1.md](docs/reviews/retro/RETRO-intellisource-v1.md) — 6 EXP (sprint-1~7)，应用决策 deferred → backlog B-016
  - [RETRO-intellisource-v1-sprint-9.md](docs/reviews/retro/RETRO-intellisource-v1-sprint-9.md) — 2 EXP 强制立项 (EXP-005 装配缺口 5 次复发 → B-017 / EXP-006 truncation 4/4 跨 3 角色)
  - [RETRO-intellisource-v1-sprint-8.md](docs/reviews/retro/RETRO-intellisource-v1-sprint-8.md) — 1 正向 EXP-007 立项 (Mid-Progress Drop Contract 通用化 → B-018)
  - [SKILL-IMPROVE-*.md](docs/reviews/retro/) — 8 份建议
- backlog-b031-walkthrough-phase-0-1-partial 闭环 (本次会话):
  - 阶段 0 (步骤 1-2) PASS — 步骤 1 DB+Redis+migrate exit 0 / 13 tables / pgvector + pg_trgm / Redis PONG / zhparser 优雅降级；步骤 2 api healthy / /health 200 (degraded — celery pending worker step 12) / OpenAPI 27 paths / x-trace-id / logs clean
  - 阶段 1 步骤 3 PASS — POST /api/v1/sources 创建 HN RSS 201 / DB 落库 / 列表 API 可查 / POST /sources/reload `loaded_count=2 errors=[]`
  - 阶段 1 步骤 4 ⚠ partial — dispatch link OK (POST 202 / task_chain + collect_task 写入 / worker run_pipeline 注册 / message 入 queue.priority.normal)；consume link 阻塞于 #12 worker async/sync bridge 设计缺陷
  - **12 项 NO-GO 修复 inline**: 阶段 0 #1-#7 (Dockerfile alembic.ini 路径 / uv sync README 缺失 → --no-install-project / asyncpg+psycopg 未声明运行时依赖 / env.py 错环境变量名 + sync driver URL 重写 / zhparser DO-EXCEPTION 优雅降级 / uvicorn 未声明 + venv 跨路径 shebang 破口 / distributor hard-fail 占位绕过)；阶段 1 #8-#11 (celery_app 不 import tasks 致 worker 零任务注册 / /tasks/collect FK 违反 parent task_chains 行未创建 / worker entry 用 celery_app 而非 boot 致 worker_process_init 不触发 / GET /tasks/{id} 序列化引用不存在字段 pipeline_name+execution_mode)
  - **NO-GO #12 立项 B-037** (设计级，不 inline 修): worker `_run_sync(asyncio.run(coro))` + `worker_process_init` 创建的 aioredis client 跨 loop 失效 → `RuntimeError: Event loop is closed`
  - 详见 [CORRECTIONS-LOG B-031 阶段 0/1 entries](docs/reviews/CORRECTIONS-LOG.md) + [PRE-DEPLOY-WALKTHROUGH 步骤 1-4 签字栏](docs/deploy/PRE-DEPLOY-WALKTHROUGH.md)
  - **6 项 carryover 立项**: B-032 P1 pgvector+zhparser 复合镜像 / B-033 P2 composition 渠道可禁用 / B-034 P3 walkthrough 文档订正 / B-035 P1 CI 强制跑 docker integration / B-036 P2 deploy-spec 审查模板要求"本地真起栈" / **B-037 P0 worker async/sync bridge hardening**
- 上游反馈: [docs/feedback/](docs/feedback/) — 1 bug + 1 suggest (B-019 未闭环)
- Backlog 总入口: [docs/BACKLOG-intellisource-v1.md](docs/BACKLOG-intellisource-v1.md) — **P0 next: B-037 worker async/sync bridge hardening（阻塞 B-031 阶段 1 步骤 4 + 阶段 5 步骤 12-14 等）；之后 B-031 阶段 1 步骤 4 重启 → 阶段 2-7** / P1: B-032 / B-035 / P2: B-033 / B-036 / P3: B-011 / B-012 / B-014 / B-015 / B-034 + B-016~B-019

## 执行环境
- 包管理器: uv（fallback: pip）
- 安装: `uv sync`
- 测试: `uv run pytest`（全量）；`uv run pytest tests/unit/<path>` 单文件
- 类型: `uv run mypy --strict src/`
- 格式: `uv run ruff format . && uv run ruff check .`
- 容器: docker / docker-compose（docker/）
- 迁移: `uv run alembic upgrade head`

## 文档导航
- 索引: `docs/.doc-index.json`（通过 `cataforge docs load` 查询；缺失时 `cataforge docs index` 重建）
- 通用规则: .cataforge/rules/COMMON-RULES.md
- 子代理协议: .cataforge/rules/SUB-AGENT-PROTOCOLS.md
- 编排协议: .cataforge/agents/orchestrator/ORCHESTRATOR-PROTOCOLS.md
- 状态码 Schema: .cataforge/schemas/agent-result.schema.json
- 加载原则: 按需通过 `cataforge docs load` 加载章节，不全量加载

## 全局约定
- 命名: PEP 8（snake_case / PascalCase）
- Commit: Conventional Commits（feat/fix/docs/chore/refactor/test）
- 分支: GitHub Flow（main + feature branches）
- 设计工具: none
- 人工审查检查点: [pre_dev, pre_deploy]
- 文档类型命名: 小写 kebab-case
- 效率原则: 最小传递 (doc_id#section)、不确定调研、选择题优先、长文按 `DOC_SPLIT_THRESHOLD_LINES` 拆分

## 框架机制
- Agent 编排: orchestrator 通过 agent-dispatch skill 激活子代理
- DEV 阶段: orchestrator 通过 tdd-engine 编排 RED/GREEN/REFACTOR
- 状态持久化: CLAUDE.md（单一事实来源，orchestrator 专属写入区） + docs/
- 写权限: 项目状态由 orchestrator 独占；其他 Agent 只写 docs/ 或 src/
- 统一配置 `.cataforge/framework.json`：`upgrade.source` 保留 / `upgrade.state` 保留 / `features` `migration_checks` 全量覆盖
