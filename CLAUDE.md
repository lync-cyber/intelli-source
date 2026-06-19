# CataForge

## 项目信息

- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.12.0
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
- 当前阶段: backlog-burndown；release gate = approved（B-031 走查 GO，pre-deploy 15-20 全 GO）。框架已升级至 **0.12.0**（0.4.1→0.9.1 [PR #110](https://github.com/lync-cyber/intelli-source/pull/110) → 0.11.0 [PR #113](https://github.com/lync-cyber/intelli-source/pull/113) → 0.11.2 + KG 全量重建 [PR #115](https://github.com/lync-cyber/intelli-source/pull/115) → 0.12.0 scaffold 同步 [PR #125](https://github.com/lync-cyber/intelli-source/pull/125) 均已合并，doctor all-pass）；KG dangling WARN 处理 [PR #111](https://github.com/lync-cyber/intelli-source/pull/111) + D1 Docker 缓存根治 [PR #109](https://github.com/lync-cyber/intelli-source/pull/109) 已闭环
- 当前回归基线: main HEAD **e90fd84**（[PR #106](https://github.com/lync-cyber/intelli-source/pull/106) ~ [PR #125](https://github.com/lync-cyber/intelli-source/pull/125) 已合并；工作树 clean，无 in-flight 任务）。deploy-ux backlog 批次全部落地：#122 = B-072/B-073 TDD + B-074/B-075/B-077 文档面 + 两轮清理；[#123](https://github.com/lync-cyber/intelli-source/pull/123) = B-076/B-075/B-077 代码闭环（推送可观测性 + 模板可发现性 CLI + 冷启动预检 G-010）；[#124](https://github.com/lync-cyber/intelli-source/pull/124) = B-078/B-079（init `_resolve_api_key` 幂等 + doctor `--check-api` 鉴权探针，真实漂移栈活体验证通过）；[#125](https://github.com/lync-cyber/intelli-source/pull/125) = 框架 scaffold 0.11.2→0.12.0 同步。当前会话 branch `feat/b071-chat-config-settings`（off main e90fd84）：状态对账（#123/#124/#125 收口陈旧修正）+ B-071 chat 配置「精简混合」收敛 TDD light 闭环（见剩余真债行）→ [PR #126](https://github.com/lync-cyber/intelli-source/pull/126) 待合并；门禁绿（ruff + mypy --strict 268 + 全量 unit 3705 PASS/5 deselected + chat/webhook integration 23 PASS + doctor all-pass）。另：用户本机 Docker registry-mirror 已改 `~/.docker/daemon.json`（删对 `docker/*` 命名空间 403 的 `docker.xuanyuan.me`、留 `docker.m.daocloud.io`，备份 `daemon.json.bak.20260618`，待用户重启 Docker 引擎生效）
- 文档状态: prd / arch（含 API-030）/ dev-plan(主卷+s1~s9+s10) / test-report / deploy-spec（PRE-DEPLOY-WALKTHROUGH 步骤 15-20 已签字）/ backlog = approved；ui-spec = N/A；dev-plan-s8 = draft。test-report + dev-plan-s8r 经 KG 摄取门禁 inline-code 修复（跨文档裸 entity-id 包裹），doctor all-pass；KG store 已 gitignore（派生数据，`cataforge kg import` 可重建）
- 剩余项目级真债（非阻塞）: 详见 [BACKLOG](docs/BACKLOG-intellisource-v1.md)。部署/分发新手友好度评估批（[CODE-SCAN-deploy-ux-20260617-r1](docs/reviews/code/CODE-SCAN-deploy-ux-20260617-r1.md)，用户 2026-06-17 决策 Q1=B+C/Q2=A/Q3=A/Q4=A）B-072/B-073/B-075/B-076/B-077/B-078/B-079 **均已 TDD 闭环并合并**；唯一未动开放 = **B-074**（P2 远端 infra 面 ②③ 置备脚本 + registry 镜像，本沙盒难全验；① 远端主机就绪文档已交付）；**B-071**（P3 arch `[chat]` 配置段与实现失配）已「精简混合」收敛闭环（本 branch：接入 `IS_CHAT_COMPACT_TOKEN_BUDGET=6000`/`IS_CHAT_SESSION_TTL_DAYS=30` 两 knob + 退役 vestigial 2000 + 删 2 幽灵参数 + arch/.env 同步，code-review approved_with_notes）；P3 session-splitting 压缩设计（2026-06-16 NO-GO，重评触发见 BACKLOG）；P3 KG dangling WARN 76 个（TC/CR/SR 纯关系 class 框架口径噪声，修复点在 CataForge 框架侧，escalate [CataForge#292](https://github.com/lync-cyber/CataForge/issues/292)）
- 详情索引: 闭环历史 → [HISTORY](docs/HISTORY-intellisource-v1.md)｜走查/订正记录 → [CORRECTIONS-LOG](docs/reviews/CORRECTIONS-LOG.md)｜剩余 backlog → [BACKLOG](docs/BACKLOG-intellisource-v1.md)｜学习沉淀 → [docs/reviews/retro/](docs/reviews/retro/)
- 上游反馈: [docs/feedback/](docs/feedback/) — 框架级条目已移交 CataForge 上游；[KG 摄取门禁](docs/feedback/feedback-suggest-kg-ingest-gate-legacy-docs-20260612.md)（裸 entity-id 误判定义 + 大版本升级无迁移路径 + dangling 扫描含 relation-only 前缀）已移交 [CataForge#252](https://github.com/lync-cyber/CataForge/issues/252)（COMPLETED 关闭；其 item(3) dangling 扫描含 relation-only 前缀在 0.11.2 仍复现，已附 [docs/feedback/feedback-suggest-kg-dangling-scan-relation-only-persists-20260616.md](docs/feedback/feedback-suggest-kg-dangling-scan-relation-only-persists-20260616.md) 聚焦再 escalate [CataForge#292](https://github.com/lync-cyber/CataForge/issues/292)）

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
