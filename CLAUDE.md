# IntelliSource

## 框架元信息
- 框架版本: 未追踪
- 可跳过阶段: ui_design (无前端UI时可跳过)

## 环境

- 始终直接运行 git 命令，无需 `cd` 前缀，当前工作目录默认已经是仓库根目录
- 所有文件操作均使用相对路径

## 效率原则

### 全局约定
- 项目名称: IntelliSource
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 命名规范: snake_case (Python), kebab-case (API路径)
- Commit格式: Conventional Commits (feat: / fix: / chore: 等)
- 分支策略: GitHub Flow (main + feature branches)

### 质量标准
- 所有文档必须通过 reviewer 门禁后才能进入下一阶段
- 代码必须通过 TDD 三阶段 (RED → GREEN → REFACTOR)
- 每个 Sprint 完成后执行 Sprint Review

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)
- 当前阶段: development
- 上次完成: tech-lead — 开发计划完成并通过审查
- 下一步行动: 开始 Sprint 1 开发，通过 tdd-engine 执行 TDD 流程
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(跳过-backend-only), dev_planning]
- 当前Sprint: Sprint 1
- 文档状态:
  - prd: approved
  - arch: approved
  - ui-spec: 未开始
  - dev-plan: approved
  - test-report: 未开始
  - deploy-spec: 未开始
