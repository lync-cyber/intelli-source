# CataForge

## 项目信息
- 项目名称: IntelliSource
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.4.0
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
  <!-- 可选值: standard | agile-lite | agile-prototype。矩阵见 COMMON-RULES §执行模式矩阵 -->
- 阶段配置: ui_design=N/A（backend-only），testing=启用，deployment=启用
- model 继承: AGENT.md 中 `model: inherit` 继承父会话模型

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)
- 当前阶段: sprint-9 批次 1 — T-095 code-review r1 = approved_with_notes（2 MEDIUM R-001/R-002 + 4 LOW R-003~R-006，无 HIGH/CRITICAL）；Approved-with-Notes Protocol 待用户裁决
- 下一步行动: ① 用户裁决 T-095 r1 接受范围（全接受 / 指定修 / 全修） ② 按裁决推进：全接受 → 批次 2 (T-096/097/098/099) 并行调度规划；指定修/全修 → implementer r2
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(N/A), dev_planning, sprint-1..7, retrospective, testing, sprint-7r, sprint-8r 批次 1-3]
- 当前Sprint: sprint-9 (in-progress — T-095 r1 approved_with_notes 主线程接手 inline 完成；sprint-8r 批次 4 T-094 暂挂，与 sprint-9 完成后一并 sprint-review)
- 文档状态: prd / arch / dev-plan(主卷+s1~s7+s7r+s8r+s9) / test-report = approved；ui-spec = N/A；dev-plan-s8(P2 backlog) = draft；deploy-spec = 未开始
- sprint-9 任务清单:
  - T-095 [standard] composition.py + Celery 单例统一 + PipelineLoader + tasks API 契约 — 批次 1，无前置
  - T-096 [standard] PROCESSOR_REGISTRY + _process_execute 契约 + _RawContentResultRepo 持久化 — 批次 2，依赖 T-095
  - T-097 [standard, security_sensitive] CollectorRegistry + DistributorFacade — 批次 2，依赖 T-095
  - T-098 [standard, security_sensitive] /search/chat + AgentRunner.run_flexible + Webhook + 微信/企微 CS — 批次 2，依赖 T-095
  - T-099 [light] Pipelines API + System 可观测性 + ConfigVersion — 批次 2，依赖 T-095
  - T-100 [light] Celery Beat 同步 + push-optimize 触发 + ChatSession DB — 批次 3，依赖 T-097/T-098
  - MVP 里程碑: T-095 + T-096 + T-098 完成
- sprint-9 锁定决策（2026-05-22 用户确认）:
  - HybridSearchEngine.chat() echo stub → 直接删除，逻辑上提到 router 走 AgentRunner.run_flexible
  - Pipelines API → 只读 + run 触发（合 arch 移除 API-010/011 决策）
  - Webhook 回调 → 本批接入微信客服消息回调 + 企微镜像
  - PRD AC-063 灵活组合 → flexible mode + YAML tool palette（不引入 workflow CRUD）
  - 微信凭证策略 → IS_WECHAT_APP_ID/SECRET env 缺失时启动期硬失败
- 批次 1 闭环检查点:
  - T-083 status=approved（r1→r2→r3。final: f567ad1 + 74a7252。报告 r1/r2/r3）
  - T-093 status=approved（r1→r2。final: b567e46。报告 r1/r2）
- 批次 2 闭环检查点:
  - T-084 status=approved（GREEN+REFACTOR → r1 approved_with_notes（2 MEDIUM 用户全修）→ r2 approved_with_notes（1 MEDIUM ctx errors schema + 2 LOW 用户全修）→ r3 approved。final: 374e8ef + 49d6d1b + df7b24d + c7a9ed9。报告 r1/r2/r3）
  - T-085 status=approved（r1 needs_revision（2 HIGH: search_mode kwarg drop, ChatResponse schema） → r2 approved。final: 8d6b075 + 2511a8e。报告 r1/r2）
  - T-086 status=approved_with_notes（r1 needs_revision（1 HIGH LLMResult shape ≠ runner consumer） → r2 approved_with_notes（1 LOW N-001 silent downgrade log），用户接受并继续。final: 5f40f4e + 9fd0204。报告 r1/r2）
  - T-090 status=approved（GREEN+REFACTOR → r1 needs_revision（1 HIGH security: pii.py 未接入 record_push） → r2 approved。final: 55ea9b0 + dca8be9 + c78e90a。报告 r1/r2）
  - T-091 status=approved（GREEN → r1 needs_revision（1 HIGH security: validator no-op） → r2 approved_with_notes（1 MEDIUM allowed-types drift + 2 LOW 测试缺口），用户全修无 r3 reviewer → orchestrator inline approve。final: e91d444 + a3caef2 + 74f093a。报告 r1/r2）
  - 全量回归: 2154 passed / 0 failed / 29 skipped; ruff + mypy --strict clean
- 批次 3 r3 闭环检查点:
  - T-087 status=approved（r1 needs_revision (1 HIGH await) → r2 approved_with_notes (1 LOW R-005 warning 日志测试未覆盖) → r3 orchestrator inline approve (caplog 断言落地)。final: 2019cbc + b16f971。报告 r1/r2 + CORRECTIONS-LOG 2026-05-22 inline approve）
  - T-088 status=approved（r1 needs_revision (2 HIGH auth + status 桩) → r2 approved_with_notes (1 MED R-007 EXP-005 lifespan 未注入 + 1 LOW) → r3 reviewer approved_with_notes (1 LOW R-009 patch 模式漂移) → orchestrator inline R-009 fix + approve。final: 7798139 + bedd6f4 + b864c30。报告 r1/r2/r3 + CORRECTIONS-LOG 2026-05-22 inline approve）
  - T-089 status=approved（r1 needs_revision (2 HIGH tool_deps 未注入 + ToolDeps 未构建) → r2 approved (5 R-ID 全修 + tools.py 6 execute 真消费 tool_deps 独立确认)。final: 7798139。报告 r1/r2，无 r3）
  - T-092 status=approved（r1 needs_revision (3 HIGH，reviewer 截断 → orchestrator inline L1+L2) → r2 approved_with_notes (1 MED N-001 + 2 LOW EXP-005 carryover: build_celery_tasks 漏传 content_repository) → r3 orchestrator inline approve (_RawContentResultRepo adapter + 集成测试去 mock)。final: 1d8e24f + db2be0d。报告 r1/r2 + CORRECTIONS-LOG inline approve）
  - **EXP-005 装配缺口闭环**: T-088 R-007 + T-092 N-001 两端 r3 真正闭环；T-089 r2 独立 reviewer 已确认 tools 真消费 tool_deps；sprint-8r 立项核心目标在本批次根治
  - 批次 3 阶段测试: 108 new tests passing (ace6b99) + r3 后新增 11 反证/集成测试 → 全量 2288 PASS / 29 skip / 0 fail；mypy --strict clean；ruff check + format clean
- Learnings Registry:
  - [RETRO-intellisource-v1.md](docs/reviews/retro/RETRO-intellisource-v1.md) — 6 EXP，应用决策 deferred to backlog
  - [SKILL-IMPROVE-*.md](docs/reviews/retro/) — 6 份建议（implementer / refactorer / code-review / tech-lead / tdd-engine / orchestrator）
- 上游反馈: [docs/feedback/](docs/feedback/) — 1 bug (EVENT-LOG `session_end` schema), 1 suggest (reflector front matter 不一致)
- Backlog: ① 6 EXP 改进应用到 .cataforge/agents 与 skills（待用户触发）② sprint-8 (T-064~T-079) 因 P0 audit 重新定位为 post-deploy P2 改进 backlog，与 sprint-8r 阻断项修复解耦 ③ test-report-intellisource-v1 approved 状态需在 sprint-8r 完成后重新评估（当前测试套件未拦截装配缺口）

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
- 状态持久化: CLAUDE.md（人面向） + .cataforge/PROJECT-STATE.md（框架镜像） + docs/
- 写权限: 项目状态由 orchestrator 独占；其他 Agent 只写 docs/ 或 src/
- 统一配置 `.cataforge/framework.json`：`upgrade.source` 保留 / `upgrade.state` 保留 / `features` `migration_checks` 全量覆盖
