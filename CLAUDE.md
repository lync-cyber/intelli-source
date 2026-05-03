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

## 执行环境

<!-- 本节为项目运行时环境约定。每次会话作为项目指令加载，权重高于 hook 注入的 additionalContext。 -->

- 包管理器: uv（fallback: pip）
- 安装依赖: `uv sync`
- 运行测试: `uv run pytest`（全量回归）；`uv run pytest tests/unit/<path>` 单文件
- 类型检查: `uv run mypy --strict src/`
- 代码格式: `uv run ruff format .` + `uv run ruff check .`
- 容器运行时: docker / docker-compose（见 docker/）
- 数据库迁移: `uv run alembic upgrade head`

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)

- 当前阶段: development
- 上次完成: orchestrator — T-060 done (CODE-REVIEW-T-060-r3 approved_with_notes，r1 needs_revision → r2 approved_with_notes → r3 approved_with_notes 三轮修订；R-001/R-002/R-003/R-004/R-005/R-007 全闭环；R-006 MEDIUM 升级 → retrospective EXP；架构 amendment 已闭环 arch#API-017 字段命名偏差；19 target tests + 1739 全量回归 PASSED；mypy strict src/ + ruff clean across 6 changed files)
- 下一步行动: tdd-engine 调度 T-062 模型特化 Prompt 变体 (tdd_mode 待 tech-lead 任务卡确认)
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(跳过-backend-only), dev_planning, sprint-1, sprint-2, sprint-3, sprint-4, sprint-5, sprint-6]
- 当前Sprint: sprint-7 (approved, 5/7 done: T-057 ✅, T-058 ✅, T-059 ✅, T-060 ✅, T-061 ✅；下一: T-062)
- Retrospective 阈值监控: 已达 RETRO_TRIGGER_SELF_CAUSED=5（T-060 r1 R-001+R-002+R-003+R-004+R-006，r2 R-006 升级 MEDIUM；外加历史 T-058 N-001 + T-059 r1 R-003/R-004 + r2 R-010）。新增 EXP 候选: implementer self-report 范围与实际范围错位（连续两轮：r1 router self-report "无需变更" 但 git diff 实有改动；r2 ruff scope 声称 src/ clean 但 tests/ 含 16 处 E501）。Sprint-7 末尾 retrospective 必须激活 reflector 提炼对应 EXP。
- 文档状态:
  - prd: approved
  - arch: approved
  - ui-spec: N/A
  - dev-plan: approved
  - test-report: 未开始
  - deploy-spec: 未开始
  <!-- changelog 由 devops 产出但不纳入门禁追踪 -->
- Learnings Registry: (首次 retrospective 后填充)
- 框架升级备注 (2026-05-03): 由 0.4.6 → 0.2.0 完成结构性重构；旧 .claude/scripts、旧 .claude/upgrade-source.json、旧 NAV-INDEX.md 由新 cataforge CLI + .doc-index.json 替代

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
