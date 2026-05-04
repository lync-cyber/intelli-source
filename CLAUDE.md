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
- 当前阶段: development
- 上次完成: orchestrator — T-063 done (CODE-REVIEW-T-063-r1 approved；3 LOW non-blocking：R-001 模块级 SQLiteTypeCompiler.visit_JSONB monkey-patch 副作用 / R-002 cluster tag filter mock 为 PG @> SQLite 不兼容 carryover 延续 / R-003 update_status missing-id 弱断言)；22 target integration tests + 1862 全量回归 PASSED + 1 SKIPPED + 0 FAILED；mypy strict + ruff clean；sprint-7 全部 11 任务实施闭环
- 下一步行动: Sprint-7 sprint-review (sprint-review skill；任务数 11 > SPRINT_REVIEW_MICRO_TASK_COUNT=3 不可短路；全任务 approved/approved_with_notes，需聚合 AC 覆盖 + 范围偏移检测) → reflector retrospective (RETRO 阈值远超，**必须激活**，EXP 候选 a/e/f/h/i 5 组优先) <!-- 用户 /start-orchestrator 选 Option 2 (2026-05-04)：严格按主线箭头 -->
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(跳过-backend-only), dev_planning, sprint-1, sprint-2, sprint-3, sprint-4, sprint-5, sprint-6]
- 当前Sprint: sprint-7 (approved, 11/11 done: T-057 ✅, T-058 ✅, T-059 ✅, T-060 ✅, T-061 ✅, T-062 ✅, T-072 ✅, T-073 ✅, T-074 ✅, T-075 ✅, T-063 ✅；下一: sprint-review + retrospective)
- Retrospective 阈值监控: **极度超过 RETRO_TRIGGER_SELF_CAUSED=5**——T-072 (3 轮 7 self-caused) + T-074 (2 轮 6 self-caused) + T-073 (3 轮 6 self-caused) + T-075 (2 轮 4 self-caused：r1 R-001 MEDIUM signal connect 缺失重蹈 T-074 r2 同模式 + R-002/R-003/R-004 LOW)。叠加 T-058/T-059/T-060 历史 8+，累计远超阈值。**EXP 候选清单（高优先级）**: (a) implementer "make-the-test-pass over update-the-test"——T-072 r1 / T-074 r1 / T-073 r1 同模式；(b) implementer "修改文件未运行对应 lint"——T-072 r2 R-001-r2；(c) tests/ 累积 ~166 处 pre-existing ruff 债务；(d) orchestrator 时序观察（T-062）：implementer 收尾期间运行验证导致快照不一致；(e) refactorer 自行 git commit + push 违反 orchestrator 独占写权限协议（T-074 d0cb454）；(f) refactorer self-report 范围错位（T-074 第二次 REFACTOR 报"无修改"但实际 diff 40 行新增）；(g) "implementer self-report 阶段快照"不一致；(h) 上游契约漂移：T-073 task card AC 字面与 arch API-016 字段多点不一致；(i) **新增** **"DI 已改但生产路径无人调用"反复模式**——T-074 r2 (CeleryTasks 实例化无人触发) → T-075 创建专门修该 gap → T-075 r1 (signal handler 已定义但 connect 缺失) 同模式重现一次；属 implementer 对"production wiring 完整性"理解偏差，需要在 tech-lead/implementer prompt 中加入"production entry-point exists and is invoked"硬清单。Sprint-7 末尾 retrospective 必须激活 reflector 优先提炼 (a)+(e)+(f)+(h)+(i) 五组 EXP。
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
