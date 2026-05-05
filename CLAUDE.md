# CataForge

## 项目信息
- 项目名称: IntelliSource
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.2.0
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
  <!-- 可选值: standard | agile-lite | agile-prototype。矩阵见 COMMON-RULES §执行模式矩阵。模式切换由 orchestrator §Mode Routing Protocol 路由 -->
- 阶段配置: 以下阶段可在 Bootstrap 时标记为 N/A 以跳过:
  - ui_design: N/A（backend-only 项目，跳过）
  - testing: 启用
  - deployment: 启用
- model 继承: AGENT.md 中 `model: inherit` 继承父会话模型；可用 `model: <model-id>` 覆盖

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)
- 当前阶段: pre_deploy_checkpoint (Phase 6→7 Manual Review)
- 上次完成: orchestrator — Phase 6 testing 闭环：test-report-intellisource-v1 approved (qa-engineer Phase 6 产出 350→394 行；reviewer r1 approved_with_notes 3 MEDIUM/3 LOW，用户 2026-05-05 选修 R-001/R-002/R-003，defer R-004/R-005/R-006；qa-engineer revision 三处闭环；reviewer r2 approved_with_notes，3 MEDIUM 全 closed + 1 LOW R-007 由 orchestrator inline 修复 §7 环境变量来源段落；最终 verdict approved)
- 下一步行动: pre_deploy Manual Review Checkpoint（COMMON-RULES §MANUAL_REVIEW_CHECKPOINTS=pre_deploy）— 用户确认 go/no-go；通过后激活 devops 进入 Phase 7 deployment（产出 deploy-spec + Dockerfile/compose 调整 + CI/CD 配置 + smoke 验证）
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(跳过-backend-only), dev_planning, sprint-1, sprint-2, sprint-3, sprint-4, sprint-5, sprint-6, sprint-7, retrospective, testing]
- 当前Sprint: — (development 阶段全部 7 个 Sprint 闭合；Phase 6 testing 不分 Sprint，已闭环)
- Retrospective 状态: 已完成 (2026-05-04，RETRO-intellisource-v1.md status=approved，6 EXP 已记录，应用决策见 §Learnings Registry)
- 文档状态:
  - prd: approved
  - arch: approved
  - ui-spec: N/A
  - dev-plan: approved
  - test-report: approved
  - deploy-spec: 未开始
  <!-- changelog 由 devops 产出但不纳入门禁追踪 -->
- Learnings Registry:
  - **RETRO-intellisource-v1** (2026-05-04, sprint-1~7, 6 EXP, **应用决策: defer to backlog (用户 2026-05-05)**)
    - EXP-001: implementer 弱测试断言 ("make-the-test-pass over update-the-test")，target=implementer/code-review SKILL — deferred
    - EXP-002: refactorer 越权 git commit/push 破坏 orchestrator 独占写权限协议，target=refactorer AGENT + tdd-engine SKILL — deferred
    - EXP-003: refactorer self-report 范围错位 + implementer self-report 阶段快照失真，target=refactorer/implementer AGENT — deferred
    - EXP-004: 上游契约漂移 (dev-plan task card AC ↔ arch API 定义不对齐)，target=tech-lead AGENT/SKILL — deferred
    - EXP-005: 生产接驳缺失 (DI/signal/lifespan 定义但无人调用)，target=code-review completeness 维度 + tech-lead task-card 模板 — deferred
    - EXP-006: 文件修改后未运行对应 lint / 全量回归，target=orchestrator lint-gate / implementer post-edit checklist — deferred
  - **缺陷 (元 EXP-003 活样本)**: reflector RETRO 自报"已产出 6 SKILL-IMPROVE-{skill_id}.md"实际只产出 RETRO 单文件；6 份 SKILL-IMPROVE 文件待补齐 → 进入 backlog；恢复时需 reflector task_type=continuation 补齐
  - **Backlog (来自 sprint-7 retrospective + sprint-review)**:
    - SR-002 SQLite→Postgres 真后端 集成测试基础设施改造 (testcontainers-postgres fixture)
    - 6 EXP 改进应用 → .cataforge/agents 与 skills 文件修订 (defer 至下次 retrospective 或用户主动触发)
    - tests/ 累积 ~166 处 pre-existing ruff 债务清理
- 框架升级备注 (2026-05-03): 由 0.4.6 → 0.2.0 完成结构性重构；旧 .claude/scripts、旧 .claude/upgrade-source.json、旧 NAV-INDEX.md 由新 cataforge CLI + .doc-index.json 替代

## 执行环境
<!-- 本节为项目运行时环境约定。每次会话作为项目指令加载，权重高于 hook 注入的 additionalContext。 -->

- 包管理器: uv（fallback: pip）
- 安装依赖: `uv sync`
- 运行测试: `uv run pytest`（全量回归）；`uv run pytest tests/unit/<path>` 单文件
- 类型检查: `uv run mypy --strict src/`
- 代码格式: `uv run ruff format .` + `uv run ruff check .`
- 容器运行时: docker / docker-compose（见 docker/）
- 数据库迁移: `uv run alembic upgrade head`

## 文档导航
- 导航索引: `docs/.doc-index.json`（机器索引，所有 Agent 通过 `cataforge docs load` 查询；缺失时运行 `cataforge docs index` 重建）
- 通用规则: .cataforge/rules/COMMON-RULES.md
- 子代理协议: .cataforge/rules/SUB-AGENT-PROTOCOLS.md
- 编排协议: .cataforge/agents/orchestrator/ORCHESTRATOR-PROTOCOLS.md (orchestrator专属)
- 状态码Schema: .cataforge/schemas/agent-result.schema.json
- 加载原则: 按任务需要通过 `cataforge docs load` 加载相关章节，不全量加载

## 全局约定
- 命名: PEP 8（snake_case 函数/变量，PascalCase 类名）
- Commit: Conventional Commits（feat/fix/docs/chore/refactor/test）
- 分支: GitHub Flow（main + feature branches）
- 设计工具: none
  <!-- 可选值: none | penpot。设为 penpot 时启用 Penpot MCP 集成 -->
- 人工审查检查点: [pre_dev, pre_deploy]
  <!-- 可选值: phase_transition | pre_dev | pre_deploy | post_sprint | none。详见 COMMON-RULES §MANUAL_REVIEW_CHECKPOINTS -->
- 文档类型命名: 小写 kebab-case（prd、arch、dev-plan、test-report、ui-spec、deploy-spec…），含工具参数和产出文件名
- 效率原则:
  - 最小传递: Agent间传递doc_id#section引用，非全文
  - 不确定时调研: 调用research skill，不猜测
  - 选择题优先: 需要用户输入时优先提供选项
  - 长文拆分: 文档超 `DOC_SPLIT_THRESHOLD_LINES` 行时按doc-gen拆分策略分卷

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
