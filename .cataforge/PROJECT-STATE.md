# CataForge

## 项目信息

- 项目名称: IntelliSource
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.2.0
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
- 阶段配置:
  - ui_design: N/A（backend-only 项目）
  - testing: 启用
  - deployment: 启用

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)

- 当前阶段: development
- 上次完成: reviewer — Sprint 6 Review approved (SPRINT-REVIEW-s6-r2, 1642 tests passed, mypy strict 零错误，SR-001~SR-008 全部闭环)
- 下一步行动: Sprint 7 LLM 韧性增强与配置治理 (T-057 ~ T-063)，需先对 dev-plan-s7 执行 doc-review
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(跳过-backend-only), dev_planning, sprint-1, sprint-2, sprint-3, sprint-4, sprint-5, sprint-6]
- 当前Sprint: sprint-7 (draft, 7 tasks: T-057~T-063)
- 文档状态:
  - prd: approved
  - arch: approved
  - ui-spec: N/A
  - dev-plan: approved
  - test-report: 未开始
  - deploy-spec: 未开始
- Learnings Registry: (首次 retrospective 后填充)
- 框架升级备注 (2026-05-03): 由 0.4.6 → 0.2.0 完成结构性重构
