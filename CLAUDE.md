# CataForge

## 项目信息
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.4.1
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
  <!-- 可选值: standard | agile-lite | agile-prototype。矩阵见 COMMON-RULES §执行模式矩阵 -->
- 阶段配置: ui_design=N/A（backend-only），testing=启用，deployment=启用
- model 继承: AGENT.md 中 `model: inherit` 继承父会话模型

- 项目名称: IntelliSource
## 执行环境 (Bootstrap 时由 `cataforge setup --emit-env-block` 填入)
<!-- 本节在 Bootstrap 步骤中生成。每次会话都会作为项目指令加载，
     权重高于 hook 注入的 additionalContext。项目生命周期内保持稳定。 -->
{执行环境检测结果 — 未填入时 orchestrator 应在 Bootstrap 时调用:
 cataforge setup --emit-env-block}

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)
- 当前阶段: backlog-burndown；release gate = approved（B-031 走查 GO）。pre-deploy 走查 15-20 已补跑全 GO（orchestrator 真起栈 2026-06-11，步骤 16 N/A）；B-069 version 缺陷闭环；确认 PR #107 已闭环 B-040/B-059/B-060
- 当前回归基线: main HEAD 13c16d2（[PR #106](https://github.com/lync-cyber/intelli-source/pull/106) + [PR #107](https://github.com/lync-cyber/intelli-source/pull/107) 已合并）。B-069 修复在 [PR #108](https://github.com/lync-cyber/intelli-source/pull/108)（分支 `fix/b069-version-pyproject-fallback`，待合并 main）：`version.py` pyproject fallback + `test_version.py` + `Dockerfile` COPY pyproject→ /health version `0.0.0+unknown`→`0.4.6`；门禁 version 3/3 + 全量 unit PASS + mypy --strict 267 files + ruff(format+check) 绿，`--no-cache` rebuild 真起栈复验。前次全门禁基线 integration 160 PASS/1 skip + lint-imports 12/12（本轮未重跑）
- 文档状态: prd / arch（含 API-030）/ dev-plan(主卷+s1~s9+s10) / test-report / deploy-spec（PRE-DEPLOY-WALKTHROUGH 步骤 15-20 已签字）/ backlog = approved；ui-spec = N/A；dev-plan-s8 = draft
- 剩余项目级真债（非阻塞）: 详见 [BACKLOG](docs/BACKLOG-intellisource-v1.md)。开放项 — D1 Windows Docker Desktop BuildKit stale COPY cache 根治（部署强制 `--no-cache` 规避中）；P3 session-splitting 压缩设计(idea，待定)
- 详情索引: 闭环历史 → [HISTORY](docs/HISTORY-intellisource-v1.md)｜走查/订正记录 → [CORRECTIONS-LOG](docs/reviews/CORRECTIONS-LOG.md)｜剩余 backlog → [BACKLOG](docs/BACKLOG-intellisource-v1.md)｜学习沉淀 → [docs/reviews/retro/](docs/reviews/retro/)
- 上游反馈: [docs/feedback/](docs/feedback/) — 框架级条目已移交 CataForge 上游

## 文档导航
- 导航索引: `docs/.doc-index.json`（机器索引，所有 Agent 通过 `cataforge docs load` 查询；缺失时运行 `cataforge docs index` 重建）
- 通用规则: .cataforge/rules/COMMON-RULES.md
- 子代理协议: .cataforge/rules/SUB-AGENT-PROTOCOLS.md
- 编排协议: .cataforge/agents/orchestrator/ORCHESTRATOR-PROTOCOLS.md (orchestrator专属)
- 状态码Schema: .cataforge/schemas/agent-result.schema.json
- 加载原则: 按任务需要通过 `cataforge docs load` 加载相关章节，不全量加载

## 全局约定
- 命名: PEP 8（snake_case / PascalCase）
- Commit: Conventional Commits（feat/fix/docs/chore/refactor/test）
- 分支: GitHub Flow（main + feature branches）
- 设计工具: none
- 人工审查检查点: [pre_dev, pre_deploy]
- 文档类型命名: 小写 kebab-case
- 效率原则: 最小传递 (doc_id#section)、不确定调研、选择题优先、长文按 `DOC_SPLIT_THRESHOLD_LINES` 拆分

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
## 工具使用规范
- 优先使用 LSP 工具（go_to_definition, find_references, hover）查找符号定义和引用
- 避免用 grep/ripgrep 搜索代码符号，除非是搜索字符串字面量

## 执行环境
- 包管理器: uv（fallback: pip）
- 安装: `uv sync`
- 测试: `uv run pytest`（全量）；`uv run pytest tests/unit/<path>` 单文件
- 类型: `uv run mypy --strict src/`
- 格式: `uv run ruff format . && uv run ruff check .`
- 容器: docker / docker-compose（docker/）
- 迁移: `uv run alembic upgrade head`
