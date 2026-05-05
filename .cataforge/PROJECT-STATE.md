# CataForge

> 本文件由 orchestrator 在主对话中持续维护，与 CLAUDE.md §项目状态 保持同步。两份文件中 CLAUDE.md 为人面向状态、本文件为框架内部镜像。

## 项目信息

- 项目名称: IntelliSource
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.3.1
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
- 阶段配置:
  - ui_design: N/A（backend-only 项目）
  - testing: 启用
  - deployment: 启用

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)

- 当前阶段: pre_deploy_checkpoint (HOLD — sprint-7r remediation 待 tdd-engine 执行)
- 上次完成: orchestrator — sprint-7r remediation 计划闭环 (dev-plan-intellisource-v1-s7r approved；reviewer r2 approved_with_notes；R-007 inline 修复) + 本次会话补齐 6 份 SKILL-IMPROVE 文件 + 上游 feedback 打包 (EVENT-LOG schema bug + reflector front matter 不一致)
- 下一步行动: **下次会话接续** — orchestrator 启动 tdd-engine 编排执行 T-080 → T-081 → T-082；执行完成后回到 pre_deploy_checkpoint 重新评估 GO/NO-GO 是否进入 Phase 7 deployment
  - T-080 (fix/light, S): runner.py DB_URL 环境变量化
  - T-081 (feature/standard, L): testcontainers-postgres + pgvector fixture
  - T-082 (chore/light, S): tests/ ruff 债务清理
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(跳过-backend-only), dev_planning, sprint-1, sprint-2, sprint-3, sprint-4, sprint-5, sprint-6, sprint-7, retrospective, testing]
- 当前Sprint: sprint-7r (pre-deploy remediation, 计划 approved，待 tdd-engine 执行)
- Retrospective 状态: 已完成 (2026-05-04，RETRO-intellisource-v1.md status=approved，6 EXP 已记录) + 6 份 SKILL-IMPROVE 文件已补齐 (2026-05-05 by orchestrator continuation)
- 文档状态:
  - prd: approved
  - arch: approved
  - ui-spec: N/A
  - dev-plan: approved (主卷 + s1~s7 + s7r remediation 全 approved；s8 OpenCode P2 改进保持 draft)
  - test-report: approved
  - deploy-spec: 未开始
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
- 框架升级备注 (2026-05-03): 由 0.4.6 → 0.2.0 完成结构性重构；本次会话验证版本 0.3.1
