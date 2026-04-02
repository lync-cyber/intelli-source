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

- 当前阶段: development (架构重构后重新审查中)
- 上次完成: architect — 架构重构：LLM从管道内嵌提升为顶层Agent编排，新增原子操作层+MCP暴露
- 下一步行动: 对重构后的PRD/ARCH/DEV-PLAN进行文档审查，通过后开始Sprint 1
- 已完成阶段: [bootstrap, requirements, architecture(重构), ui_design(跳过-backend-only), dev_planning(重构)]
- 当前Sprint: —
- 文档状态:
  - prd: draft (重构后待审查)
  - arch: draft (重构后待审查)
  - ui-spec: 未开始
  - dev-plan: draft (重构后待审查, 5→4 Sprint)
  - test-report: 未开始
  - deploy-spec: 未开始
