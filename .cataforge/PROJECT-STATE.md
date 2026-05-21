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

- 当前阶段: sprint-8r 批次 1 r1 review 完成 — T-083 + T-093 verdict=needs_revision，用户决定本会话停止
- 上次完成: orchestrator (2026-05-21) — 批次 1 REFACTOR + code-review r1 一轮；T-083 REFACTOR commit `7bb224a` 抽 `_resolve_url` env-fallback helper + 模块顶层 `concurrent.futures` import；T-093 REFACTOR 推荐 skip（TDD_REFACTOR_TRIGGER 未达阈值）；reviewer 子代理产出 CODE-REVIEW-T-083-r1.md + CODE-REVIEW-T-093-r1.md（commit `1dc5613`）；本会话顺手修 test_migration.py glob 排序（多迁移场景）；全量回归 1937 passed/0 failed/29 skipped；ruff+mypy clean
- 下一步行动: **新会话 /start-orchestrator 接续 sprint-8r Revision Protocol**：
  - 步骤 1 — 批次 1 r2 revision（dispatch implementer task_type=revision，每任务卡传 REVIEW r1 路径）:
    - T-083 R-001 HIGH: `api/routers/tasks.py` `/tasks/collect` schema 对齐 arch API-007 — `source_id: str` → `source_ids: array[string]`，响应体加 `task_chain_id` / `tasks` / `message`；同步 `test_tasks_router.py` 断言
    - T-093 R-002 HIGH: `distributor/frequency.py` `is_quiet_hours` 加 `try/except (ZoneInfoNotFoundError, KeyError)` fallback → `"UTC"` + WARNING 日志
    - T-093 R-001 MEDIUM: `distributor/matcher.py` 日志 `_logger.warning("... for pattern %r", value)` 改为 hash/截断（sha256 前 8 位或前 50 字符）
    - T-093 R-003 LOW: `test_redos_pattern_does_not_block_beyond_2s` 断言收紧只允许 `result is False`
  - 步骤 2 — reviewer r2 复核（dispatch reviewer task_type=revision）；二次 needs_revision 进 Adaptive Review Protocol 收紧
  - 步骤 3 — 批次 2 RED+GREEN（5 任务并行，sprint_group 并发上限 3，分 2 轮）: T-084 / T-085 / T-086 / T-090 / T-091
  - 步骤 4 — 批次 3 (4 任务并行): T-087 / T-088 / T-089 / T-092
  - 步骤 5 — 批次 4: T-094 集成测试与冷启动 e2e
  - 步骤 6 — pre_deploy 二次 GO/NO-GO 评估（重跑 P0 audit 验证 9 项 broken 消除）
  - **关键路径**: T-083 r2 → T-084 → T-087 → T-094，权重 10
  - **r2 残留 R-013/R-014**: R-013 经核实已修（pyproject.toml 已在 T-093 affected_files）；R-014 已 orchestrator 内联修 T-090 security_sensitive=true
  - **批次 2 backlog**: T-083 R-002 init_celery 双实例分叉 / R-003 factory.py 死参数 / R-004 lifespan shutdown finally 无异常屏蔽 — 转 backlog 在 T-094 集成测试前一并清理（不进 r2 范围，避免范围漂移）
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(跳过-backend-only), dev_planning, sprint-1, sprint-2, sprint-3, sprint-4, sprint-5, sprint-6, sprint-7, retrospective, testing, sprint-7r]
- 当前Sprint: sprint-8r (in-progress — 2/12 任务卡 GREEN 完成，10 张待启动)
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
