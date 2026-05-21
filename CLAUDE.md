# CataForge

## 项目信息

- 项目名称: IntelliSource
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.3.1
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
  <!-- 可选值: standard | agile-lite | agile-prototype。矩阵见 COMMON-RULES §执行模式矩阵 -->
- 阶段配置: ui_design=N/A（backend-only），testing=启用，deployment=启用
- model 继承: AGENT.md 中 `model: inherit` 继承父会话模型

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)

- 当前阶段: sprint-8r 批次 1 r1 review 完成 — T-083 + T-093 verdict=needs_revision，用户决定本会话停止、下次会话走 Revision Protocol
- 下一步行动: **下次会话 /start-orchestrator 接续** — ① 批次 1 revision：dispatch implementer (task_type=revision) 修 T-083 R-001（/tasks/collect schema 对齐 arch API-007：`source_id: str` → `source_ids: array[string]` + 响应加 `task_chain_id / tasks / message`，对应测试同步）+ T-093 R-002（frequency.py `is_quiet_hours` ZoneInfo fallback）+ T-093 R-001（matcher.py 日志 hash/截断 regex pattern）+ T-093 R-003（test_redos_pattern_does_not_block_beyond_2s 断言收紧只允许 False）+ reviewer r2 ② 启动批次 2 RED+GREEN（5 任务并行：T-084 / T-085 / T-086 / T-090 / T-091）③ 批次 3 (T-087/088/089/092) ④ 批次 4 T-094 集成测试 ⑤ pre_deploy 二次评估
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(N/A), dev_planning, sprint-1..7, retrospective, testing, sprint-7r]
- 当前Sprint: sprint-8r (in-progress — 批次 1 GREEN+REFACTOR+r1 review 完成 2/12，verdict=needs_revision；待 revision r2 + 批次 2-4)
- 文档状态: prd / arch / dev-plan(主卷+s1~s7+s7r+s8r) / test-report = approved；ui-spec = N/A；dev-plan-s8(P2 backlog) = draft；deploy-spec = 未开始
- 批次 1 r1 检查点详情:
  - T-083 status=done（GREEN：28 RED test 全 PASS；REFACTOR commit `7bb224a` 抽 `_resolve_url` helper + 模块顶层 `concurrent.futures` import；code-review r1 verdict=needs_revision，1 HIGH R-001 /tasks/collect 与 arch API-007 schema 偏差 + 3 MEDIUM + 2 LOW；reviewer 自报 approved_with_notes，orchestrator 按 §三态判定仲裁为 needs_revision）
  - T-093 status=done（GREEN：55 RED test 全 PASS；REFACTOR 推荐 skip（TDD_REFACTOR_TRIGGER 未达阈值，reviewer 明确建议）；code-review r1 verdict=needs_revision，1 HIGH R-002 ZoneInfo 无 fallback + 1 MEDIUM R-001 日志泄漏 regex pattern + 1 LOW R-003 测试断言宽松）
  - orchestrator 本会话顺手修复：① test_migration.py `_find_migration_files` glob 顺序非确定性（多迁移文件场景 sorted）② T-083 REFACTOR 见上 ③ EVENT-LOG 追加 4 条 (tdd_phase REFACTOR + 2× review_verdict needs_revision + state_change)
  - 本会话全量回归: 1937 passed / 0 failed / 29 skipped；ruff format + check + mypy --strict 全部 clean
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
