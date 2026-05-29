# CataForge

## 项目信息
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.4.1
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
  <!-- 可选值: standard | agile-lite | agile-prototype。矩阵见 COMMON-RULES §执行模式矩阵 -->
- 阶段配置: ui_design=N/A（backend-only），testing=启用，deployment=启用
- model 继承: AGENT.md 中 `model: inherit` 继承父会话模型

- 项目名称: IntelliSource
## 执行环境 (Bootstrap 时由 `cataforge setup --emit-env-block` 填入)
<!-- 本节在 Bootstrap 步骤中生成。每次会话都会作为项目指令加载，
     权重高于 hook 注入的 additionalContext。项目生命周期内保持稳定。 -->
{执行环境检测结果 — 未填入时 orchestrator 应在 Bootstrap 时调用:
 cataforge setup --emit-env-block}

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)
- 当前阶段: backlog-burndown → **B-031 release gate = approved + 物理闭环（用户 2026-05-29 签字；PR #71 已合入 main, merge 6c7beb7）**；observability(B-040+B-060) + zhparser 搜索 500 修复 + pytest-xdist 全部 on main
- 下一步行动: release 已放行，无阻塞项；后续 backlog P2 B-036 / P3 B-011/B-012/B-014/B-015/B-034/B-043/B-046/B-047 + B-016~B-019 非阻塞；BGE-M3 本地 embedding 暂缓
- 当前回归基线: **2948 PASS unit** (`-n auto` 并行 / 0 FAIL) + **163 PASS / 1 skip integration**（含 zhparser migration e5f6a7b8c9d0）；mypy --strict + ruff + lint-imports 8/8 clean。main HEAD 6c7beb7（CI 全绿）
- 文档状态: prd / arch / dev-plan(主卷+s1~s7+s7r+s8r+s9) / test-report / deploy-spec = approved；ui-spec = N/A；dev-plan-s8 = draft；backlog = approved
- 历史闭环索引: 详见 [docs/HISTORY-intellisource-v1.md](docs/HISTORY-intellisource-v1.md) — audit-fix-pr53/54 + backlog 闭环（b001-b002 / b003-b006 / b007-b010 / b029-b030 / b032 / b033 / b035 / b037 / b039-b042 / b044-b045 / b048 / b050-b055 / b057-b058 / **b059**）+ B-031 走查阶段 0-7（步骤 1-20，16 N/A，PR #69/#70 合入）+ 编码可移植性修复 + 修正 #1-#29
- 最近闭环 (本次会话):
  - **B-040 + B-060 observability 闭环 + zhparser 搜索修复 + pytest-xdist** (standard/light TDD inline + 真起栈验证, 本地分支 `fix/observability-b040-b060` 4 commits 未 push): 用户裁定"先修 observability 再放行"。
    - **B-060 (P3)**: 失败 LLM 调用此前 0 落表。`LLMCallRecord` 加 `error_message` + `CostTracker.log_call` 透传；`_unified_call_with_retry` 中央失败 emit（熔断 OPEN→`circuit_open` / 重试耗尽→`timeout`(Timeout 名)|`error`），覆盖 complete/chat/stream/embed 四路径。真栈：注入坏 LLM key → `llm_call_logs` 非 success 行 **0→20**（5 `error` 带真 `litellm.BadRequestError` msg + 15 `circuit_open`），熔断 OPEN。+7 单测
    - **B-040 (P3)**: trace_id 传播成立但 grep 0 命中，**真因三重**——① Celery `worker_hijack_root_logger` 未关（自有 formatter 覆盖）② `worker_redirect_stdouts=True` 把 sys.stderr 换成 LoggingProxy（早于 `setup_logging`，吞掉行）③ `boot.worker_init_handler` 的 `setup_logging()` 在 `_celery_tasks` 幂等 guard 之后（forked child 短路则不配置 root）。修：两 conf 关闭 + setup_logging 提到 guard 前 + signals prerun/middleware inbound 各发一条语义 INFO 承载行。真栈：`POST /tasks/collect` → 同一 trace_id 同时现于 api inbound + worker prerun。+6 单测（含 boot-guard + redirect 回归）
    - **zhparser 搜索 500 修复（pre-existing）**: `storage/vector.py` `to_tsvector('zhparser',...)` 在 001 早于 zhparser 加入前迁移的库上 500（"text search configuration zhparser does not exist"）；alembic 不重放已应用的 001 → 新增幂等前向 migration `e5f6a7b8c9d0`（`CREATE EXTENSION IF NOT EXISTS` + 守卫式 TS config，downgrade no-op）。真栈：从缺 ext 的库 `upgrade head` 重建 ext+config，`POST /search` **500→200**；integration 163 pass 验证迁移
    - **pytest-xdist**: `test-unit` 加 `-n auto`（unit 进程隔离安全）；不入全局 addopts / integration（testcontainers session-scoped 容器会按 worker 倍增）。2948 pass，36.6s→26.0s
  - **编码可移植性修复 (PR #70 已合入)**: 非 utf-8 locale（Windows gbk）下 `read_text()`/`open()` 无 `encoding=` → UnicodeDecodeError，致 `test_project_structure.py` 20 例失败（CI Linux/utf-8 不受影响）。修 [test_project_structure.py](tests/unit/test_project_structure.py) 3 处 pyproject read + 生产 read-side 3 处加固（[filter.py](src/intellisource/llm/processors/filter.py) 敏感词配置 open / [model_config.py](src/intellisource/llm/model_config.py) / [pipelines.py](src/intellisource/api/routers/pipelines.py) yaml read 均补 `encoding="utf-8"`）。全 src read-side 复扫无残留。20 fail→0，全量在 gbk locale 亦全绿
  - **B-059 (P1/HIGH，PR #69 已合入)** (standard TDD inline, RED→GREEN→真栈验证): Celery broker/result-store 宕机时 collect 派发快速失败。真栈复测修正根因——主阻塞是 result 后端重连重试 ~100s 抛 RuntimeError（非 broker publish）。`celery_app` broker+backend 双侧 socket 超时 + `result_backend_always_retry=False`/`max_retries=0`；`dispatch` retry=False + 包装连接错误/后端 RuntimeError → `BrokerUnavailableError`；`tasks.collect` catch → 503 + get_db_session 回滚 task 行。真栈：stop redis → 503/7.9s（非挂起）+ 行数不变 + start redis 202/0.04s 自愈。+14 测试
  - **B-031 阶段 6-7 步骤 15-20 自动驱动真起栈走查** (orchestrator 主线程 + Bash，步骤 16 N/A): 冷栈 bootstrap（13 表 / vector+pg_trgm / api+worker+beat+prometheus healthy / 2 sources）。**步骤 15** GO（Prometheus healthy + 8 alerts + scrape target up）+ 2 doc-staleness（根 `/metrics` 404 / `collector_/pipeline_/task_queue_` 家族不存在）；**步骤 17** 偏差（trace_id 功能成立 + `x-trace-id` 头返回，但 log-grep 0 命中 → 归 B-040，真因 Celery hijack + 热路径无 log）；**步骤 18** GO（db down→checks.db unhealthy + health 200 + 业务 500 + 4s 自愈，top=degraded 措辞 note）；**步骤 19** GO 3/3（熔断 OPEN + truncation 降级 + processed_contents 34→40 + 客户端无 5xx + HALF_OPEN 恢复；偏差：失败未落 llm_call_logs→B-060）；**步骤 20** 核心 GO（redis down→checks.redis unhealthy + 非 redis 路径 200 + 9s 自愈）+ **1 HIGH 偏差 B-059**（collect 派发 broker 宕时 HTTP 000 挂起无 fast-fail）。**无代码改动**（仅 .env 临时注入已还原）；详见 [CORRECTIONS-LOG 2026-05-29](docs/reviews/CORRECTIONS-LOG.md)。新立 **B-059 (P1/HIGH)** + **B-060 (P3)** + **B-040 增补** + doc-staleness 并入 B-034
  - **B-058 follow-up** (REFACTOR-only, inline): router-service 完全收敛 + ReloadRequest.config_name 死字段拆除。[sources.py](src/intellisource/api/routers/sources.py) 5 端点全部走 `Depends(_get_service)`，body 类型直接为 `SourceConfig` / `SourcePatchRequest`，无嵌套 DTO + helper 转换层；POST 改 idempotent upsert by name（删 409 IntegrityError 处理）。[service.py](src/intellisource/source/service.py) `list_paginated` 接 `type/status/tag` 过滤、`patch` 内部 `metadata → metadata_` ORM 列名映射。删除 3 个 mock-driven 假象测试文件（共 17 测试，已被 [test_service.py](tests/unit/source/test_service.py) real SQLite 完整覆盖）；[test_sources.py](tests/unit/api/test_sources.py) 改 `dependency_overrides[_get_service]` 模式 + 删 4 假象测试 + 新增 2 个 rollback router smoke。[test_deps_integration.py](tests/unit/api/test_deps_integration.py) `test_sources_router_uses_deps_get_db_session` 改 `inspect.signature(_get_service)` 间接 dep chain 验证。Unit 2879→2862 PASS 净 -17。mypy strict + ruff + lint-imports 8/8 clean
  - **B-058 P1** (前次会话, TDD standard, RED→GREEN sub-agent dispatch): 新增 `SourceConfigService` + reload 补 record_version_async (B-058a) / rollback 真调 bulk_sync_from_configs 写回 DB (B-058b real bug 修复) + bulk_sync_from_configs update 分支补 `status='active'` 重激活语义。+23 测试
  - **B-057 P2** (前次会话, light TDD inline): [matcher.py](src/intellisource/distributor/matcher.py) `_matches` 加 `source_names` 强约束维度。+12 测试
- Learnings Registry（详见各 RETRO 报告）: [RETRO sprint-1~7 / sprint-8 / sprint-9](docs/reviews/retro/) 9 EXP — EXP-005 装配缺口 → B-017 / EXP-006 truncation → 跨角色 / EXP-007 Mid-Progress Drop Contract → B-018；**EXP-CONTRACT-DRIFT (PR #64)**：改 `api/routers/` 返回类型 / `search.*` dataclass / `storage.*` SQL SELECT / `llm/gateway/_stream` 等"契约文件"必须 push 前跑 `make test-integration`（mock fixtures 常用旧契约 shape）；强制门禁通过 `make contract-check` + `make check-all`
- 上游反馈: [docs/feedback/](docs/feedback/) — 1 bug + 1 suggest (B-019 未闭环)
- Backlog 总入口: [docs/BACKLOG-intellisource-v1.md](docs/BACKLOG-intellisource-v1.md) — **next: B-031 release gate go/no-go 用户签字（HIGH 阻塞项 B-059 已合入消除）** / P2: B-036 / P3: B-040 + B-060 (observability) / B-011 / B-012 / B-014 / B-015 / B-034 / B-043 / B-046 / B-047 + B-016~B-019

## 文档导航
- 导航索引: `docs/.doc-index.json`（机器索引，所有 Agent 通过 `cataforge docs load` 查询；缺失时运行 `cataforge docs index` 重建）
- 通用规则: .cataforge/rules/COMMON-RULES.md
- 子代理协议: .cataforge/rules/SUB-AGENT-PROTOCOLS.md
- 编排协议: .cataforge/agents/orchestrator/ORCHESTRATOR-PROTOCOLS.md (orchestrator专属)
- 状态码Schema: .cataforge/schemas/agent-result.schema.json
- 加载原则: 按任务需要通过 `cataforge docs load` 加载相关章节，不全量加载

## 全局约定
- 命名: PEP 8（snake_case / PascalCase）
- Commit: Conventional Commits（feat/fix/docs/chore/refactor/test）
- 分支: GitHub Flow（main + feature branches）
- 设计工具: none
- 人工审查检查点: [pre_dev, pre_deploy]
- 文档类型命名: 小写 kebab-case
- 效率原则: 最小传递 (doc_id#section)、不确定调研、选择题优先、长文按 `DOC_SPLIT_THRESHOLD_LINES` 拆分

## 框架机制
- Agent编排: orchestrator 通过 agent-dispatch skill 激活子代理
- DEV阶段: orchestrator 通过 tdd-engine skill 编排 RED/GREEN/REFACTOR 三个子代理（独立上下文）
- Skill调用: Agent按SKILL.md步骤式指令执行工作流
- 状态持久化: PROJECT-STATE.md + docs/ 目录
- 子代理通信: 通过文件系统(docs/和src/)传递产出物路径
- 运行时: 由 framework.json runtime.platform 决定（deploy 自动适配）
- **写权限**: PROJECT-STATE.md 由 orchestrator 独占写入；其他Agent只写 docs/ 或 src/ 下的产出文件
- 统一配置 `.cataforge/framework.json`:
  - `upgrade.source` — 远程升级源配置。升级时保留用户已配置值，仅补充新字段
  - `upgrade.state` — 本地升级状态。升级时始终保留
  - `features` — 功能注册表。升级时全量覆盖
  - `migration_checks` — 迁移检查声明。升级时全量覆盖
## 工具使用规范
- 优先使用 LSP 工具（go_to_definition, find_references, hover）查找符号定义和引用
- 避免用 grep/ripgrep 搜索代码符号，除非是搜索字符串字面量

## 执行环境
- 包管理器: uv（fallback: pip）
- 安装: `uv sync`
- 测试: `uv run pytest`（全量）；`uv run pytest tests/unit/<path>` 单文件
- 类型: `uv run mypy --strict src/`
- 格式: `uv run ruff format . && uv run ruff check .`
- 容器: docker / docker-compose（docker/）
- 迁移: `uv run alembic upgrade head`

