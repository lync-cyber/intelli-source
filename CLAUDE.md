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
- 当前阶段: backlog-burndown — **B-031 步骤 15-20 自动驱动走查完成；待 pre_deploy go/no-go 用户签字（受 B-059 HIGH 阻塞）**
- 下一步行动: 用户裁定 B-031 release gate go/no-go（B-059 broker 派发挂起 = HIGH NO-GO 候选）→ 优先修 B-059 / 然后 B-040 + B-060 observability / BGE-M3 本地 embedding 暂缓
- 当前回归基线: **2862 PASS unit** (HEAD baseline 2879; 净 -17 来自删除 mock-driven 假象测试) / 1 deselected / 0 NEW FAIL；mypy --strict + ruff + lint-imports 8/8 clean
- 文档状态: prd / arch / dev-plan(主卷+s1~s7+s7r+s8r+s9) / test-report / deploy-spec = approved；ui-spec = N/A；dev-plan-s8 = draft；backlog = approved
- 历史闭环索引: 详见 [docs/HISTORY-intellisource-v1.md](docs/HISTORY-intellisource-v1.md) — audit-fix-pr53/54 + backlog 36 项闭环（b001-b002 / b003-b006 / b007-b010 / b029-b030 / b032 / b033 / b035 / b037 / b039-b042 / b044-b045 / b048 / b050-b055 / b057-b058）+ B-031 走查阶段 0-5（步骤 1-14）+ 修正 #1-#29
- 最近闭环 (本次会话):
  - **B-031 阶段 6-7 步骤 15-20 自动驱动真起栈走查** (orchestrator 主线程 + Bash，步骤 16 N/A): 冷栈 bootstrap（13 表 / vector+pg_trgm / api+worker+beat+prometheus healthy / 2 sources）。**步骤 15** GO（Prometheus healthy + 8 alerts + scrape target up）+ 2 doc-staleness（根 `/metrics` 404 / `collector_/pipeline_/task_queue_` 家族不存在）；**步骤 17** 偏差（trace_id 功能成立 + `x-trace-id` 头返回，但 log-grep 0 命中 → 归 B-040，真因 Celery hijack + 热路径无 log）；**步骤 18** GO（db down→checks.db unhealthy + health 200 + 业务 500 + 4s 自愈，top=degraded 措辞 note）；**步骤 19** GO 3/3（熔断 OPEN + truncation 降级 + processed_contents 34→40 + 客户端无 5xx + HALF_OPEN 恢复；偏差：失败未落 llm_call_logs→B-060）；**步骤 20** 核心 GO（redis down→checks.redis unhealthy + 非 redis 路径 200 + 9s 自愈）+ **1 HIGH 偏差 B-059**（collect 派发 broker 宕时 HTTP 000 挂起无 fast-fail）。**无代码改动**（仅 .env 临时注入已还原）；详见 [CORRECTIONS-LOG 2026-05-29](docs/reviews/CORRECTIONS-LOG.md)。新立 **B-059 (P1/HIGH)** + **B-060 (P3)** + **B-040 增补** + doc-staleness 并入 B-034
  - **B-058 follow-up** (REFACTOR-only, inline): router-service 完全收敛 + ReloadRequest.config_name 死字段拆除。[sources.py](src/intellisource/api/routers/sources.py) 5 端点全部走 `Depends(_get_service)`，body 类型直接为 `SourceConfig` / `SourcePatchRequest`，无嵌套 DTO + helper 转换层；POST 改 idempotent upsert by name（删 409 IntegrityError 处理）。[service.py](src/intellisource/source/service.py) `list_paginated` 接 `type/status/tag` 过滤、`patch` 内部 `metadata → metadata_` ORM 列名映射。删除 3 个 mock-driven 假象测试文件（共 17 测试，已被 [test_service.py](tests/unit/source/test_service.py) real SQLite 完整覆盖）；[test_sources.py](tests/unit/api/test_sources.py) 改 `dependency_overrides[_get_service]` 模式 + 删 4 假象测试 + 新增 2 个 rollback router smoke。[test_deps_integration.py](tests/unit/api/test_deps_integration.py) `test_sources_router_uses_deps_get_db_session` 改 `inspect.signature(_get_service)` 间接 dep chain 验证。Unit 2879→2862 PASS 净 -17。mypy strict + ruff + lint-imports 8/8 clean
  - **B-058 P1** (前次会话, TDD standard, RED→GREEN sub-agent dispatch): 新增 `SourceConfigService` + reload 补 record_version_async (B-058a) / rollback 真调 bulk_sync_from_configs 写回 DB (B-058b real bug 修复) + bulk_sync_from_configs update 分支补 `status='active'` 重激活语义。+23 测试
  - **B-057 P2** (前次会话, light TDD inline): [matcher.py](src/intellisource/distributor/matcher.py) `_matches` 加 `source_names` 强约束维度。+12 测试
- Learnings Registry（详见各 RETRO 报告）: [RETRO sprint-1~7 / sprint-8 / sprint-9](docs/reviews/retro/) 9 EXP — EXP-005 装配缺口 → B-017 / EXP-006 truncation → 跨角色 / EXP-007 Mid-Progress Drop Contract → B-018；**EXP-CONTRACT-DRIFT (PR #64)**：改 `api/routers/` 返回类型 / `search.*` dataclass / `storage.*` SQL SELECT / `llm/gateway/_stream` 等"契约文件"必须 push 前跑 `make test-integration`（mock fixtures 常用旧契约 shape）；强制门禁通过 `make contract-check` + `make check-all`
- 上游反馈: [docs/feedback/](docs/feedback/) — 1 bug + 1 suggest (B-019 未闭环)
- Backlog 总入口: [docs/BACKLOG-intellisource-v1.md](docs/BACKLOG-intellisource-v1.md) — **next: B-059 (P1/HIGH broker fast-fail，B-031 release gate 阻塞项)** / P1: B-059 / P2: B-036 / P3: B-040 + B-060 (observability) / B-011 / B-012 / B-014 / B-015 / B-034 / B-043 / B-046 / B-047 + B-016~B-019；B-031 release gate go/no-go 待用户签字

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

