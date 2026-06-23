# CataForge

## 项目信息

- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.14.0
  <!-- 由 cataforge deploy 自动盖入已安装包版本。SemVer: MAJOR=不兼容变更, MINOR=新功能, PATCH=修复 -->
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
  <!-- 可选值: standard | agile-lite | agile-prototype。矩阵见 COMMON-RULES §执行模式矩阵 -->
- 阶段配置: ui_design=N/A（backend-only），testing=启用，deployment=启用
- model 继承: AGENT.md 中 `model: inherit` 继承父会话模型

- 项目名称: IntelliSource

## 执行环境 (Bootstrap 时由 `cataforge setup env-block` 填入)

<!-- 本节在 Bootstrap 步骤中生成。每次会话都会作为项目指令加载，
     权重高于 hook 注入的 additionalContext。项目生命周期内保持稳定。 -->
- 包管理器: uv（fallback: pip）
- 安装: `uv sync`
- 测试: `uv run pytest`（全量）；`uv run pytest tests/unit/<path>` 单文件
- 类型: `uv run mypy --strict src/`
- 格式: `uv run ruff format . && uv run ruff check .`
- 容器: docker / docker-compose（docker/）
- 迁移: `uv run alembic upgrade head`

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)
- 当前阶段: backlog-burndown；release gate = approved；框架 **0.14.0**；doctor all-pass，KG drift-check=0
- 当前回归基线: main HEAD **9a70ec3**（PR [#106](https://github.com/lync-cyber/intelli-source/pull/106) ~ [#132](https://github.com/lync-cyber/intelli-source/pull/132) 已合并；详情见 [HISTORY](docs/HISTORY-intellisource-v1.md)）。无在途特性 PR，工作树干净且与 origin/main 同步
- 文档状态: prd / arch / dev-plan(主卷+s1~s10) / test-report / deploy-spec / backlog = approved；ui-spec = N/A；dev-plan-s8 = draft。KG store 已 gitignore（派生数据，`cataforge kg repair` / `kg rollback` 可重建）
- 剩余项目级真债: **清零**（末项 B-074 远端 infra 全闭环；KG WARN 76 已清零，详见 [HISTORY](docs/HISTORY-intellisource-v1.md) / [BACKLOG](docs/BACKLOG-intellisource-v1.md)）。延后跟踪（非债）：P3 session-splitting（NO-GO）｜起栈 1GB Vultr embedding 会 OOM，需 ≥2-4GB 或 swap
- 详情索引: 闭环历史 → [HISTORY](docs/HISTORY-intellisource-v1.md)｜走查/订正记录 → [CORRECTIONS-LOG](docs/reviews/CORRECTIONS-LOG.md)｜剩余 backlog → [BACKLOG](docs/BACKLOG-intellisource-v1.md)｜学习沉淀 → [docs/reviews/retro/](docs/reviews/retro/)

## 文档导航

- 导航索引: `docs/.doc-index.json`（机器索引，所有 Agent 通过 `cataforge context read` 查询；缺失时运行 `cataforge context index` 重建）
- 通用规则: .claude/rules/COMMON-RULES.md
- 子代理协议: .claude/rules/SUB-AGENT-PROTOCOLS.md
- 编排协议: .cataforge/agents/orchestrator/ORCHESTRATOR-PROTOCOLS.md (orchestrator专属)
- 状态码Schema: .cataforge/schemas/agent-result.schema.json
- 加载原则: 按章节/条目粒度按需通过 `cataforge context read` 加载，不全量加载

## 全局约定

- 命名: PEP 8（snake_case / PascalCase）
- Commit: Conventional Commits（feat/fix/docs/chore/refactor/test）
- 分支: GitHub Flow（main + feature branches）
- 设计工具: none
  <!-- 由 cataforge deploy 从 framework.json#project.design_tool 盖入。切换用 `cataforge setup --with-penpot`，勿手改本行 -->
  <!-- 可选值: none | penpot。penpot 时启用 Penpot MCP 集成 -->

- 人工审查检查点: [pre_dev, pre_deploy]
- 文档类型命名: 小写 kebab-case
- 效率原则: 最小传递 (doc_id#section)、不确定调研、选择题优先、长文按 `DOC_SPLIT_THRESHOLD_LINES` 拆分

## 框架机制

- Agent编排: orchestrator 通过 agent-dispatch skill 激活子代理
- DEV阶段: orchestrator 通过 tdd-engine skill 编排 RED/GREEN/REFACTOR 三个子代理（独立上下文）
- Skill调用: Agent按SKILL.md步骤式指令执行工作流
- 状态持久化: 项目指令文件（CLAUDE.md/AGENTS.md）§项目状态 + docs/ 目录
- 子代理通信: 通过文件系统(docs/和src/)传递产出物路径
- 运行时: 由 framework.json runtime.platform 决定（deploy 自动适配）
- **写权限**: 项目指令文件 §项目状态 由 orchestrator 独占写入；其他Agent只写 docs/ 或 src/ 下的产出文件
- 统一配置 `.cataforge/framework.json`:
  - `upgrade.source` — 远程升级源配置。升级时保留用户已配置值，仅补充新字段
  - `upgrade.state` — 本地升级状态。升级时始终保留
  - `features` — 功能注册表。升级时全量覆盖
  - `migration_checks` — 迁移检查声明。升级时全量覆盖

## 工具使用规范
- 优先使用 LSP 工具（go_to_definition, find_references, hover）查找符号定义和引用
- 避免用 grep/ripgrep 搜索代码符号，除非是搜索字符串字面量
