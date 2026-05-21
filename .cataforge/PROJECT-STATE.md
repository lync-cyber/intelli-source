# CataForge

> 本文件由 orchestrator 在主对话中持续维护，与 CLAUDE.md §项目状态 保持同步。两份文件中 CLAUDE.md 为人面向状态、本文件为框架内部镜像。

## 项目信息

- 项目名称: IntelliSource
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.4.0
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
- 阶段配置:
  - ui_design: N/A（backend-only 项目）
  - testing: 启用
  - deployment: 启用

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)

- 当前阶段: sprint-8r 批次 3 RED+GREEN 完成 — code-review r1 全部落账（T-087 / T-088 / T-089 / T-092 = 全部 needs_revision，待 implementer 统一修订）
- 上次完成: orchestrator — 批次 2 收尾：T-084 r3 approved（374e8ef + 49d6d1b + df7b24d + c7a9ed9）/ T-085 r2 approved（8d6b075 + 2511a8e）/ T-086 r2 approved_with_notes 用户接受（5f40f4e + 9fd0204）/ T-090 r2 approved（55ea9b0 + dca8be9 + c78e90a）/ T-091 r2 approved_with_notes 用户全修后 orchestrator inline approve（e91d444 + a3caef2 + 74f093a）；全量回归 2154 passed/0 failed/29 skipped；ruff+mypy --strict clean
- 下一步行动: **新会话 /start-orchestrator 接续 sprint-8r 批次 3**
  - 步骤 1 — 批次 3 RED+GREEN（4 任务，按 dev-plan-s8r 实际任务卡定义，sprint_group 并发上限 3，分 2 轮）:
    - T-087 F-005 LLM 智能处理链路接驳（B-04）
    - T-088 CircuitBreaker + PriorityQueue 接驳 LLMGateway（B-05）
    - T-089 Agent 工具 6 个 execute stub 真实实现（B-08）
    - T-092 Celery task_routes 配置 + boot.py worker_init 修复 + 幂等三组件串入（B-12 + B-13）
  - 步骤 2 — 批次 4: T-094 Sprint-8r 集成测试与冷启动 e2e
  - 步骤 3 — pre_deploy 二次 GO/NO-GO 评估（重跑 P0 audit 验证 9 项 broken 消除）
  - **关键路径**: T-087 → T-088 → T-094，权重 10
  - **批次 2 backlog（延续）**: T-083 R-002 init_celery 双实例分叉 / R-003 factory.py 死参数 / R-004 lifespan shutdown finally 无异常屏蔽 — 仍在 T-094 集成测试前一并清理
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(N/A), dev_planning, sprint-1, sprint-2, sprint-3, sprint-4, sprint-5, sprint-6, sprint-7, retrospective, testing, sprint-7r]
- 当前Sprint: sprint-8r (in-progress — 批次 1 + 批次 2 全 approved 7/12；待批次 3-4)
- Retrospective 状态: 已完成 (2026-05-04，RETRO-intellisource-v1.md status=approved，6 EXP 已记录) + 6 份 SKILL-IMPROVE 文件已补齐 (2026-05-05 by orchestrator continuation)
- 文档状态:
  - prd: approved
  - arch: approved
  - ui-spec: N/A
  - dev-plan: approved (主卷 + s1~s7 + s7r + s8r remediation 全 approved；s8 OpenCode P2 改进保持 draft)
  - test-report: approved
  - deploy-spec: 未开始
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
- 批次 3 r1 检查点（全部 needs_revision，待 implementer 统一修订）:
  - T-087 status=needs_revision r1（1 HIGH + 2 MEDIUM + 1 LOW；报告 CODE-REVIEW-T-087-r1.md）
    - R-001 HIGH structure：pipeline/processors/tools.py 两处异步调用缺少 await
    - R-002 MEDIUM error-handling：LLMExtractor schema 验证失败且无 fallback 时静默返回 None
    - R-003 MEDIUM test-quality：测试文件 ruff 违规较多，MagicMock/AsyncMock 问题影响测试质量
    - R-004 LOW test-quality：AC-6 ContentCluster 实例化测试仅验证类存在性，未验证调用路径
  - T-088 status=needs_revision r1（2 HIGH，reviewer 报告 commit 3008bce；等待 implementer 修订）
  - T-089 status=needs_revision r1（2 HIGH + 2 MEDIUM + 1 LOW；报告 CODE-REVIEW-T-089-r1.md）
    - R-001 HIGH structure：runner.py run_flexible LLM 驱动工具调用时 tool_deps 从未注入
    - R-002 HIGH structure：factory.py build_agent_runner — session_factory/llm_gateway 被接受但丢弃，ToolDeps 从未构建（与 T-092 R-002 同"装配缺口"反模式）
    - R-003 MEDIUM test-quality：test_agent_runner_execute_with_tool_deps 仅验证签名，不验证转发行为
    - R-004 MEDIUM convention：测试文件 ruff 违规
    - R-005 LOW completeness：_*_execute 降级分支返回 `{"status": "ok"}` 占位结果，调用方无法区分真实执行与降级
  - T-092 status=needs_revision r1（3 HIGH + 3 MEDIUM + 4 LOW；reviewer 子代理 task-notification 截断 → orchestrator 主线程内联 L1+L2；CORRECTIONS-LOG 2026-05-21 备案）
    - R-001 HIGH structure：boot.py 未 import celery_app 单例，`worker_init_handler(*, celery_app=None)` kwarg 永远为 None，`@None.task(...)` 在 worker_init signal 时抛 AttributeError → 模块级 `run_pipeline` stub 恒走 `{"status": "queued"}` 死路；fix=boot.py 顶部 `from intellisource.scheduler.celery_app import celery_app as _module_celery_app`
    - R-002 HIGH structure：`boot.build_celery_tasks` 未构造与注入 IdempotencyGuard / FingerprintChecker / ContentRepository，CeleryTasks 生产实例三守卫恒 None → AC-3/4/5 logic prod 失效（PROJECT-STATE.md Backlog ③ 已预警的"测试通过、生产失效"反模式再现）
    - R-003 HIGH test-quality：`test_content_repository_create_not_called_on_duplicate_fingerprint` 空套——run_pipeline 任何分支都不调 `self._content_repository.create(...)`，删 fingerprint 检查测试仍 PASS
    - R-004~R-006 MEDIUM：双 run_pipeline 注册并存 / task_routes 仅 priority 未覆盖 trigger / TaskRepository 占位死代码
    - R-007~R-010 LOW：2 个 test 文件 ruff format / celery_app.py noqa E402 import / shutdown 静默 RuntimeError / 设计阶段 TODO 注释残留
  - **批次 3 共性反模式**: T-089 R-001/R-002 + T-092 R-001/R-002/R-003 五处独立指向 EXP-005（生产接驳缺失：DI / signal / lifespan 定义但无人调用）；本批次必须根治，否则 T-094 冷启动 e2e 必然失败
  - 批次 3 阶段测试: 108 new tests passing（commit ace6b99）；mypy --strict clean
- Learnings Registry:
  - **RETRO-intellisource-v1** (2026-05-04, sprint-1~7, 6 EXP, **应用决策: defer to backlog (用户 2026-05-05)**)
    - EXP-001: implementer 弱测试断言，target=implementer/code-review SKILL — deferred；建议见 [SKILL-IMPROVE-implementer.md](../docs/reviews/retro/SKILL-IMPROVE-implementer.md)、[SKILL-IMPROVE-code-review.md](../docs/reviews/retro/SKILL-IMPROVE-code-review.md)
    - EXP-002: refactorer 越权 git commit/push，target=refactorer AGENT + tdd-engine SKILL — deferred；建议见 [SKILL-IMPROVE-refactorer.md](../docs/reviews/retro/SKILL-IMPROVE-refactorer.md)、[SKILL-IMPROVE-tdd-engine.md](../docs/reviews/retro/SKILL-IMPROVE-tdd-engine.md)、[SKILL-IMPROVE-orchestrator.md](../docs/reviews/retro/SKILL-IMPROVE-orchestrator.md)
    - EXP-003: refactorer/implementer self-report 失真，target=refactorer/implementer AGENT — deferred；建议同上 implementer/refactorer/tdd-engine
    - EXP-004: 上游契约漂移 (dev-plan AC ↔ arch API 不对齐)，target=tech-lead AGENT/SKILL — deferred；建议见 [SKILL-IMPROVE-tech-lead.md](../docs/reviews/retro/SKILL-IMPROVE-tech-lead.md)
    - EXP-005: 生产接驳缺失 (DI/signal/lifespan 定义但无人调用)，target=code-review completeness 维度 + tech-lead task-card 模板 — deferred；建议见 [SKILL-IMPROVE-code-review.md](../docs/reviews/retro/SKILL-IMPROVE-code-review.md)、[SKILL-IMPROVE-tech-lead.md](../docs/reviews/retro/SKILL-IMPROVE-tech-lead.md)
    - EXP-006: 文件修改后未运行对应 lint / 全量回归，target=orchestrator lint-gate / implementer post-edit checklist — deferred；建议见 [SKILL-IMPROVE-implementer.md](../docs/reviews/retro/SKILL-IMPROVE-implementer.md)、[SKILL-IMPROVE-tdd-engine.md](../docs/reviews/retro/SKILL-IMPROVE-tdd-engine.md)、[SKILL-IMPROVE-orchestrator.md](../docs/reviews/retro/SKILL-IMPROVE-orchestrator.md)
  - **元 EXP-003 活样本 (closed 2026-05-05)**: reflector RETRO 自报"已产出 6 SKILL-IMPROVE-{skill_id}.md"实际只产出 RETRO 单文件 → orchestrator 在 main thread 补齐 6 份 (skill-improve-implementer / refactorer / code-review / tech-lead / tdd-engine / orchestrator)，doctor + docs validate 全部 PASS
  - **Backlog (来自 sprint-7 retrospective + sprint-review)**:
    - SR-002 SQLite→Postgres 真后端 集成测试基础设施改造 (testcontainers-postgres fixture) — 已转 T-081
    - 6 EXP 改进应用 → .cataforge/agents 与 skills 文件修订 (defer 至下次 retrospective 或用户主动触发；SKILL-IMPROVE 文件已就位)
    - tests/ 累积 ~166 处 pre-existing ruff 债务清理 — 已转 T-082
- 上游反馈 (2026-05-05 本次会话):
  - [feedback-bug-eventlog-session-end-20260505.md](../docs/feedback/feedback-bug-eventlog-session-end-20260505.md) — EVENT-LOG schema 缺 'session_end' 枚举
  - [feedback-suggest-reflector-frontmatter-20260505.md](../docs/feedback/feedback-suggest-reflector-frontmatter-20260505.md) — reflector AGENT.md vs cataforge doctor 对 SKILL-IMPROVE front matter 要求不一致
- 框架升级备注 (2026-05-03): 由 0.4.6 → 0.2.0 完成结构性重构；当前 framework.json 版本 0.4.0
