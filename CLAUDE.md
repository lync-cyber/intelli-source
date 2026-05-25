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
- 当前阶段: backlog-burndown — B-011~B-028 架构治理 + CI 闭环；B-010 Deploy spec + B-016~B-018 框架学习待启动
- 下一步行动: B-010 Deploy spec（devops 子代理产出 deploy-spec 文档）；B-016~B-018 框架学习 EXP 应用
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(N/A), dev_planning, sprint-1..7, retrospective, testing, sprint-7r, sprint-8r, sprint-9, sprint-8 P2, audit-fix-pr53, audit-fix-pr54, backlog-b001-b002, backlog-b003-b006, backlog-b007, backlog-b009-decision, backlog-b029-b030-polish, backlog-b008, backlog-arch-governance]
- 当前回归基线: 2838 PASS / 0 FAIL / 0 skip / 0 xfail / 51 deselected；mypy --strict + ruff + lint-imports 8/8 + deptry + vulture clean
- 文档状态: prd / arch / dev-plan(主卷+s1~s7+s7r+s8r+s9) / test-report = approved；ui-spec = N/A；dev-plan-s8 = draft；deploy-spec = 未开始 (B-010)；backlog = approved
- audit-fix-pr53 闭环 (commit 7e10e77): F-01~F-11 P0 + F-12~F-27 P1 + F-28~F-48 P2/P3 — 39 项，详见 PR #53 描述
- audit-fix-pr54 闭环 (commit 31bddde): F-11 receiver_id / F-25 health 豁免 / F-42 PG /search 真链路 / idempotency RuntimeWarning / F-20+F-21 health 并发 / F-22 metrics 4 路径 / F-23 trace_id 跨 worker / F-24 alerts.yml / F-26 priority queue / F-27 content_not_found / 2 xfail (HybridIndex tags/date) / 1 placeholder skip 删 / 46 docker skip 转 deselect — 14 项
- backlog-b001-b002 闭环: B-001 `/search/chat/stream` 切 `AgentRunner.run_flexible_stream` (新增 RAG-aware 流式入口 + LLMGateway.stream_complete 支持 messages 参数 + FlexibleLoop.run_stream) + B-002 `SearchRequest.date_from/to: str → datetime`（非法值 422 而非 500）；SSE 事件契约 step/sources/token/done/error
- backlog-b003-b006 闭环 (inline 批次，3 batch): B-006 storage fixture ARRAY→JSON conftest mutation (单跑 PASS) / B-003 `intellisource_health_status` labeled gauge + HealthDegradedFor5m alert / B-004 `scheduler.dispatch.send_task_with_trace()` facade + guardrail (src/ 范围) / B-005 MetricsCollector labeled counter (pushes_total{channel,status} + llm_calls_total{model})；code-review verdict approved_with_notes → R-001 inline 修订 (counter+gauge 子系统 labelnames 强约束对齐) → 最终 approved；详见 [docs/reviews/code/CODE-REVIEW-backlog-p1-r1.md](docs/reviews/code/CODE-REVIEW-backlog-p1-r1.md)
- backlog-b007 闭环: LLMGateway 单类 732 行拆为 6 mixin (`_complete` 200 / `_chat` 200 / `_stream` 185 / `_queue` 54 / `_metrics` 44 / `_protocols` 80) + facade `__init__.py` 120 行；`_GatewayProtocol` mypy --strict self-type 兜底；公共 API (complete/chat/stream_complete) 零破坏；2820 PASS 不退化；code-review verdict approved 0 issue；详见 [docs/reviews/code/CODE-REVIEW-B-007-r1.md](docs/reviews/code/CODE-REVIEW-B-007-r1.md)
- backlog-b009-decision 闭环 (decision-only, reaffirm 选项 ②): PRD AC-063 [ASSUMPTION] 已在 sprint-9 锁定 YAML-as-source-of-truth；pipelines router 现状即决策实现 (list/detail/run, 无 HTTP CRUD)；完整 workflow CRUD (DB 存储 + 历史版本) 保留 v2+ 范畴，不立项；无代码改动；BACKLOG B-009 删除
- backlog-b008 闭环: `truncate_summary` 接入 LLM summarizer（`summarizer.structured` 模板 + `gateway.complete(response_format=json_object)` + `tool_deps` 注入）；产出 `{title, summary, timeline[], key_points[]}` 结构化摘要；3 层 fallback（LLM 异常 / JSON 解析失败 / 缺必要字段 → 回退字符串截断）；PRD AC-023 [ASSUMPTION] 移除；2834 PASS (+7 测试)
- backlog-b029-b030-polish 闭环: B-029 alerts.yml `LLMCallFailureRateHigh` + `PushFailureRateHigh` 按 `model`/`channel` label 拆分 (`sum by (model)` / `sum by (channel)` + annotations `{{ $labels.* }}` 模板化) / B-030 R-002 guardrail 注释显式化范围 + R-003 `_ALLOWED_POSIX` 精确路径匹配 + R-004 `DistributorFacade.__init__` + `LLMGateway.__init__` 集中 `register_labeled_counter` (hot-path 重复 register 移除)；2827 PASS (+7 测试)
- Learnings Registry:
  - [RETRO-intellisource-v1.md](docs/reviews/retro/RETRO-intellisource-v1.md) — 6 EXP (sprint-1~7)，应用决策 deferred → backlog B-016
  - [RETRO-intellisource-v1-sprint-9.md](docs/reviews/retro/RETRO-intellisource-v1-sprint-9.md) — 2 EXP 强制立项 (EXP-005 装配缺口 5 次复发 → B-017 / EXP-006 truncation 4/4 跨 3 角色)
  - [RETRO-intellisource-v1-sprint-8.md](docs/reviews/retro/RETRO-intellisource-v1-sprint-8.md) — 1 正向 EXP-007 立项 (Mid-Progress Drop Contract 通用化 → B-018)
  - [SKILL-IMPROVE-*.md](docs/reviews/retro/) — 8 份建议
- 上游反馈: [docs/feedback/](docs/feedback/) — 1 bug + 1 suggest (B-019 未闭环)
- Backlog 总入口: [docs/BACKLOG-intellisource-v1.md](docs/BACKLOG-intellisource-v1.md) — 12 条 (B-010~B-028)，按 P2/P3 + PR #54 验证 + 框架学习 + 上游反馈 + 架构治理 分组

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
