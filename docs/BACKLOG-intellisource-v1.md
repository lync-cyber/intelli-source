---
id: backlog-intellisource-v1
doc_type: backlog
author: orchestrator
status: approved
deps: []
---

# IntelliSource v1 Backlog

> 维护：完成项请直接删除条目（闭环 prose 归档到 [HISTORY](HISTORY-intellisource-v1.md) + [CORRECTIONS-LOG](reviews/CORRECTIONS-LOG.md) + git），新增项按优先级插入。本文件只保留**仍需动作**的条目。
> release 已放行（B-031 用户 2026-05-29 签字 + 2026-06-08 大规模重构后真起栈走查全绿）；剩余全部非阻塞。

## 优先级语义

- **P0 — 阻塞**：影响生产正确性 / 安全 / 上线 go-no-go
- **P1 — 阻塞质量**：可观测性、性能边界、合规
- **P2 — 架构 / 功能完整性**：上帝类拆分、PRD 接受项功能缺口
- **P3 — 优化 / 规约**：硬编码、弱断言、风格

---

## P0 — 上线门禁（常驻 release-gate）

### B-031 执行 PRE-DEPLOY-WALKTHROUGH（pre_deploy 人工 go/no-go）
- **性质**：release-gate 而非一次性任务 —— 每次 prod 发布前或架构 / 关键模块大改后重新执行
- **关联**：[docs/deploy/PRE-DEPLOY-WALKTHROUGH.md](deploy/PRE-DEPLOY-WALKTHROUGH.md) / [deploy-spec §3.3](deploy-spec/deploy-spec-intellisource-v1.md)
- **现状**：2026-05-29 全 20 步签字 GO（B-059/B-060/B-040 等走查暴露项已闭环）；2026-06-08 大规模重构后复跑核心管线 + 受影响面全 GREEN 无回归（[CORRECTIONS-LOG 2026-06-08](reviews/CORRECTIONS-LOG.md)）
- **重新评估触发**：下次 prod 发布 / arch 大改

---

## P3 — 配置 / 规约（非阻塞）

### B-071 arch `[chat]` 配置段与实现失配 — 立项研判（B-070 follow-up）
- **现状（代码实证）**：arch §5.1 `[chat]` 配置表声明 4 参数，但**均未接入 Settings**（`core/settings.py` 无任何 chat/compaction 配置项），代码改用硬编码模块常量，且部分参数从未实现：
  - `context_token_budget`(arch=2000) ←→ 代码有**两个不同 budget**：`_DEFAULT_CONTEXT_TOKEN_BUDGET=2000`（`llm/compaction.py` 默认 / agent 路径，巧合相符）与 `CHAT_COMPACT_TOKEN_BUDGET=6000`（`api/chat_sessions.py` chat persist/replay，**与 arch 2000 失配**）。
  - `compress_after_turns`(arch=4) — **src 零引用、从未实现**（压缩按 token 预算触发，非轮次）。
  - `compress_model`(arch=廉价模型) — 未实现（压缩走 gateway 默认模型路由，函数 `model` 默认 `"gpt-4o-mini"`）。
  - `session_timeout_hours`(arch=24) — 待核实是否接入 `ChatSessionRepository.cleanup_expired`。
  - 注：doc-review [REVIEW-dev-plan-r4](reviews/doc/REVIEW-dev-plan-intellisource-v1-r4.md) 曾断言这些参数"与 arch §5.1 完全对应"，但那是 doc↔doc 校验，代码接线从未落地。
- **研判问题（立项待决，非本轮执行）**：
  1. **收敛方向**：把 arch `[chat]` 真正接入 Settings（config 驱动），还是修订 arch §5.1 使其匹配已实现的硬编码现实？doc↔code 须二选一收敛，不能两套并存制造规格幻影。
  2. **预算语义**：`context_token_budget`（replay 注入 LLM 的预算）与 chat persist 压缩触发预算是**一个**还是**两个**概念？arch 只定义一个，代码事实上有两个（2000 / 6000）；需决定统一命名取值，或显式区分两者并都纳管。
  3. **未实现参数去留**：`compress_after_turns` / `compress_model` 是补实现（轮次触发 + 廉价模型压缩），还是从 arch 删除以消除规格幻影？
- **优先级理由**：P3 — 硬编码常量 + doc/code 一致性；非阻塞（B-070 已用工作默认值兑现 AC-053，配置化只关乎可调性与规格诚实度）。
- **触发**：下次动 chat 压缩 / 扩展 settings / 修订 arch §5.1 时一并处理。

---

## 部署/分发 新手友好度评估（DEPLOY-UX-EVAL 20260617，非阻塞）

> 来源：[CODE-SCAN-deploy-ux-20260617-r1](reviews/code/CODE-SCAN-deploy-ux-20260617-r1.md)（四单元 = 部署/订阅/推送/模板）。本地起栈未被硬阻断，故无新增 P0；`G-NNN` 编号见报告。修复方向已折入用户 2026-06-17 决策（Q1=B+C / Q2=A / Q3=A / Q4=A）。两个 P1（B-072/B-073）+ P2 B-076 已闭环（见「已闭环」段）；开放项为 B-074/B-075/B-077（代码/infra portion）。

### B-074 [P2] 远端主机就绪 + 置备 + registry 镜像（G-006 + G-013(registry)，决策 B+C）
- **现状（代码实证）**：`docker/docker-compose.yml:75-76` 直接 `8000:8000` 暴露且全为 `build:` 模式；deploy-spec 与 PRE-DEPLOY-WALKTHROUGH 全文 `localhost`，无 reverse proxy / TLS / 域名 / systemd / 防火墙 / 入站 webhook 公网可达性指引；仓库无 ssh/ansible/置备脚本；远端回滚强依赖目标主机重建 zhparser（`docker/db.Dockerfile` 源码编译 SCWS+zhparser）。
- **影响**：无法据现有文档完成公网可访问的远端部署，回调类渠道在远端不可用。
- **修复方向（决策 B+C）**：① 新增"远端部署主机就绪"文档（反代/TLS/防火墙/webhook 公网 URL 示例）；② 提供置备脚本或 `intellisource` 远端 target；③ 引入 prebuilt registry 镜像 + compose pull 模式（同解远端回滚重建依赖）。文档先行、自动化与镜像为中-大成本后续。
- **进度**：① 文档已交付 —— [`docs/deploy/remote-host-readiness.md`](deploy/remote-host-readiness.md)（反代/TLS/防火墙/入站 webhook 公网可达/systemd/冷启动代价 + 对 deploy-spec 交叉引用）。剩余 ②③（置备脚本 + registry 镜像）= 代码/infra，待续。
- **触发**：规划首次远端/生产部署时。

### B-075 [P2] 模板可发现性 + 变量文档 + CLI validate/preview（G-004 + G-005，决策 A=文件覆盖为主）
- **现状（代码实证）**：渲染唯一注入 `bundle`（`distributor/templates/render.py:39`），字段仅存在于 `distributor/templates/schemas.py:16-41`；`config/templates/README.md`（9 行）只说"放同名文件"不提字段。CLI `template list/add/rm`（`cli/commands/template.py`）只操作 DB `templates` 表，`config/templates/` 文件覆盖（`render.py:21,29`）永不出现在 list、无法 preview/validate；文件名拼错（kebab/snake 混淆，如 `daily_brief` vs `daily-brief`）→ FileSystemLoader 静默回落 builtin。
- **影响**：写自定义模板须逆向读源码；不知该放文件还是敲命令；拼错文件名静默失效。
- **修复方向（决策 A）**：① `config/templates/README.md` 补 `bundle` 字段表 + 端到端覆盖示例；② 文档明确"文件覆盖为主、DB 模板为辅"分工；③ CLI `template list` 增列扫描 `config/templates/` file override + 新增 `template validate`/`preview`。文档低成本，CLI 增强中等成本。
- **进度**：①② 文档已交付 —— `config/templates/README.md` 重写（bundle/DigestItem/DigestSection 字段表 + 文件覆盖↔DB 分工 + 端到端覆盖示例 + 内置模板×格式矩阵含 json_feed + 缺失格式静默回落说明）。剩余 ③（CLI `template list` 增列 file override + `validate`/`preview`）= 代码，待续。
- **触发**：下次动模板分发 / template CLI 时。

### B-077 [P3] 冷启动预检 + match_rules 语义文档 + 杂项（G-010 + G-012 + G-013 杂项）
- **现状（代码实证）**：`init`/`up` 不检测 Docker daemon / `.env` 存在（`cli/commands/stack.py:56-60` 只捕 FileNotFoundError），手动 copy `.env.example` 绕过 init → 弱口令（占位非空，compose `:?` 不拦，`.env.example:18,27,36`）；match_rules 语义（AND/OR、大小写、keywords `+`/`!`/`/regex/`、source_names 强约束）仅在 `distributor/matcher.py` 与内部 dev-plan，`config/examples/subscriptions.example.yaml` 只演示 tags；embedding `start_period:1200s`（`docker-compose.yml:181`）无进度提示；`config/templates/README.md:3` 漏列 `json_feed`；j2 覆盖度不全（weekly-roundup 仅 html、push-card 无 html）→ 静默回落 default_format（`distributor/templates/base.py:42-44`）。
- **影响**：各为小摩擦，单独不阻断。
- **修复方向**：`up` 前置检查 daemon + `.env` 友好提示；example.yaml 补全匹配维度 + README 加 match_rules 语义小节；`up` 输出 embedding 首拉等待提示；补 README `json_feed` 与缺失 j2 说明。
- **进度**：文档面（G-012 + G-013 文档部分）已交付 —— 根 `README.md` 新增「订阅匹配规则 match_rules 语义」小节（5 个识别键 + keywords `+`/`!`/`/regex/` 操作符 + AND/OR 判定顺序）；`config/examples/subscriptions.example.yaml` 补全匹配维度示例 + quiet_hours 时区/跨午夜注释；`config/templates/README.md` 补 json_feed + 缺失格式静默回落说明。剩余 = G-010（`up`/`init` daemon+`.env` 预检 + 弱口令拦截）+ embedding 首拉进度提示 = 代码，待续。
- **触发**：穿插在 `B-074` / `B-075` 落地时顺手处理。

---

## agentloop-hardening 后续（非阻塞，保留跟踪）

> 本批 R-001~R-010 + R-005 余量 + R-011/R-012 + P11/P12 已闭环，详见 [code-review r1](reviews/code/CODE-REVIEW-agentloop-hardening-r1.md) 与 [burndown r1](reviews/code/CODE-REVIEW-agentloop-burndown-r1.md)。以下为唯一保留的延后设计。

- **[P3] session-splitting 压缩设计（已评估 2026-06-16：NO-GO）**：提案以"分裂新 session + parent 血缘"替代 `compact_agent_messages` / `compact_messages_for_chat` 就地压缩，换可追溯压缩历史 + 对话分支；落地需 `ChatSession.parent_session_id`（死 schema，未建列）。**评估结论 NO-GO**，四条代码/文档实证：
  1. **agent-loop 压缩纯内存**：`compact_agent_messages` 仅经 gateway `compress_if_needed` 被 `agent/executors/flexible.py:_compress_history` 调用，对内存 message 列表 best-effort 压缩，无 `ChatSession` 行、不落库 → 该侧无行可分支，提案结构性不适用。
  2. **唯一持久的 Chat 路径每次 persist 无条件硬截断最近 10 轮**（`MAX_HISTORY_TURNS=10` / `history[-20:]`），早期历史在读取端摘要前即从库删除 → "父会话留全量供审计" 无从谈起。**注**：该写入截断本身是与压缩特性未协调的残留、架空 AC-053（非"刻意产品边界"——已订正并单列为 **B-070**（已闭环，[PR #118](https://github.com/lync-cyber/intelli-source/pull/118)，见「已闭环」段）），但其存在与否都不改变 session-splitting 结论：审计/分支收益无 PRD 消费者，且 AC-053 留存目标经就地写入端压缩即可达成（B-070），无需 parent 血缘。
  3. **摘要 LLM 调用经 `CostTracker` 已入 `LLMCallLog`(E-007)**（model/tokens/cost/latency/call_type 维度可观测），仅"被摘掉的原文"无处留存 → 压缩**事件+成本**已可观测，提案唯一新增的是"原文留存"。
  4. **PRD 零审计/留存/对话分支需求**（`审计/留存/回放/fork/parent_session` 全无命中；唯一"分支"是 AC-014 的 pipeline 处理器条件分支，与对话无关）→ 两个收益均无需求消费者。
  净判断：建列 + 迁移 + GC + token 解析重写全部服务一个 PRD 未提出的能力，属 YAGNI；维持死 schema 未建为正确状态。
  - **重评触发**（满足任一才重启设计）：① 出现对话审计 / 合规留存需求；② 出现对话分支 / fork 功能需求；③ 因他因已要求全量 transcript 留存（届时血缘是廉价增量）。
  - **重启时须补**（BACKLOG 原描述与提案均未覆盖）：(a) 客户端 token→head 解析需 forward / head 指针，仅 backward `parent_session_id` 不够；(b) 父链保留 / GC 策略以防无界增长；(c) `cleanup_expired` 的级联 / 血缘感知删除语义。

---

## 框架升级 0.9.1 后续（非阻塞，保留跟踪）

- **[P3] KG 摄取残留 WARN — 76 个框架口径噪声（已定性，非阻塞，修复点在 CataForge 框架侧）**：doctor `KG ingestion completeness` 的 dangling 检查用完整 entity-prefix 正则扫"引用"，但 `TestCase`(TC) / `CoverageRule`(CR) / `SprintReviewIssue`(SR) 是纯关系/元数据 class —— 只参与关系抽取（如 TestCase `cf:verifies` T/AC/F），KG store 从不为其建实体节点（实证：store 仅 T/AC/E/M/API/F 六类）。故 active docs 里任何 TC-/CR-/SR- 编号提及（test-report 覆盖矩阵单列 71 个 `TC-`）结构性恒为 dangling，与文档写法无关。剩余 76 = TC×71 + CR×4 + SR×1。根因＝doctor dangling 候选集 ⊋ KG 实体化 class 集（口径不一致），属框架检查缺陷，修复在框架侧（dangling 引用集应限制为会实体化的 class）。原 79 中的 3 个 `API-010/026/029`（arch 已删编号的 prose 历史引用）已 inline-code 豁免。详见 [上游反馈](feedback/feedback-suggest-kg-ingest-gate-legacy-docs-20260612.md) §Proposal(3)。

---

## 已闭环（归档）

完整闭环 prose 见 [HISTORY-intellisource-v1.md](HISTORY-intellisource-v1.md) + 各 PR/commit + [CORRECTIONS-LOG](reviews/CORRECTIONS-LOG.md)。已闭环 B 号（删除条目仅保留编号便于回溯）：

- **audit (PR #53/#54)**：F-01 ~ F-49
- **早期质量项**：B-001 ~ B-010 / B-029 / B-030
- **B-031 走查 + 部署破口**：B-032 ~ B-049（含 B-037 worker bridge / B-039 tools 去重 / B-041 DeepSeek V4 / B-042 CostTracker / B-044 summarizer / B-045 embedder）
- **配置 UX + 三入口对齐**：B-050 / B-051 / B-054 ~ B-058
- **observability + 架构治理**：B-011 ~ B-015 / B-020 ~ B-028 / B-040 / B-060
- **稳定性 + 走查回归**：B-059 / B-061 / B-062 / B-063
- **框架级（移交上游 CataForge）**：B-016 ~ B-019 / B-036 / B-038 — [feedback bundle](feedback/feedback-suggest-framework-batch-20260529.md)
- **PR #78 ~ #94**：大规模死代码/shim 烧毁 + C1（任务生命周期）+ S-2（chat 会话）+ ConditionalProcessor + pipeline CRUD CLI
- **PR #95 ~ #101**：B-064 / B-065 / B-066 / TaskChain 进度回填（PR #96）+ chat CLI/web 前端 + agent 控制面统一（stream/non-stream + CLI/web 收敛）+ config/prompt SSOT 治理 + P0/P1/P2 安全加固 + agent/tools 包化重构 + MCP CLI 模块拆分
- **PR #102**：BGE-M3 本地 embedding（T-EMB-1/2/3）—— `_embed.py` 经 TEI 路由（api_base/key/dimension 走 Settings）+ 向量列 1536→1024 迁移（`g0h1i2j3k4l5`）+ 查询侧/RAG semantic 接线（`HybridSearchEngine` 注入 gateway）+ docker-compose TEI 服务（CPU 默认/GPU override）+ 文档同步。code-review approved（[T-EMB-1](reviews/code/CODE-REVIEW-T-EMB-1-r1.md) / [T-EMB-2](reviews/code/CODE-REVIEW-T-EMB-2-r1.md)）。
- **T-MCP-GW**：MCP 默认 search factory 懒注入进程级 `LLMGateway` 单例（`_default_llm_gateway()`，`redis=None` + `session_factory=_default_session_factory`），MCP 搜索从 keyword-only 升级 semantic/hybrid（调用方 `build_mcp_server(search_engine_factory=...)` 覆盖优先级保留）。code-review approved（[T-MCP-GW](reviews/code/CODE-REVIEW-T-MCP-GW-r1.md)）
- **PR #106**：B-067（TEI healthcheck start_period 120s→1200s）+ B-068（embedding backfill：`list_missing_embeddings` + `backfill_embeddings` Celery 任务 + `POST /content/backfill-embeddings` 端点（arch API-030）+ `content backfill-embeddings` CLI + process.py 内联回填）。code-review 抓 1 CRITICAL（R-001 分页跳行）+ 3 HIGH，approved_with_notes（[code-review r2](reviews/code/CODE-REVIEW-T-BF-backfill-r2.md)）
- **PR #107**：agentloop-hardening — flexible loop 加固 + model failover + scheduler idempotency + agent observability（R-001~R-012 + P11/P12）。code-review approved 0 CRITICAL/HIGH（[hardening r1](reviews/code/CODE-REVIEW-agentloop-hardening-r1.md) / [burndown r1](reviews/code/CODE-REVIEW-agentloop-burndown-r1.md)）
- **B-069 + pre-deploy 走查 15-20**（2026-06-11 真起栈，[CORRECTIONS-LOG](reviews/CORRECTIONS-LOG.md)）：步骤 15-20 全 GO（16 N/A）；B-069 `/health` version `0.0.0+unknown`→`0.4.6` inline 修复（version.py pyproject fallback + Dockerfile COPY pyproject + 3 单测）；确认 PR #107 已闭环上次走查（2026-05-29）的 B-040（trace_id 跨进程）/ B-059（broker 宕 fail-fast）/ B-060（失败 LLM 落 llm_call_logs）。D1（Windows BuildKit stale cache）转剩余真债跟踪。
- **框架升级 0.4.1→0.9.1**（2026-06-12）：`cataforge bootstrap` 刷新 scaffold 162 文件 + IDE 产物重部署 + kg-first 初始化 KG store。升级激活的 `KG ingestion completeness` 门禁对 legacy approved 文档报 14 个跨文档 entity-id collision（importer 把裸 `T-`/`F-`/`AC-` 当定义）→ test-report(24) + dev-plan-s8r(3) 裸 id 改 inline-code 让定义唯一化，`kg import` + doctor all-pass；kg/store 加 gitignore。[PR #110](https://github.com/lync-cyber/intelli-source/pull/110)；上游反馈见 [feedback](feedback/feedback-suggest-kg-ingest-gate-legacy-docs-20260612.md)。
- **B-070（[PR #118](https://github.com/lync-cyber/intelli-source/pull/118)）**：Chat 会话压缩兑现 [AC-053](prd/prd-intellisource-v1.md)「超 token 自动摘要历史对话」—— 写入端 `_bounded_history`→`compact_messages_for_chat` token-aware 压缩替代每轮 `history[-20:]` 硬截断，**持久化** summary+recent（旧上下文以结构化摘要存活）；webhooks 同源 persist 路径一并迁移；`compact_history` 改纯函数（不污染 detached `stored_session.context`）；compaction sizing 抽 `_chat_compaction_context_window` helper 收口（同 PR 第二 commit 修 AC-T071-9 集成 parity 回归）。由 session-splitting 评估（[PR #117](https://github.com/lync-cyber/intelli-source/pull/117) NO-GO）副产暴露；code-review approved_with_notes（R-001 MEDIUM budget 收口 + R-002 webhooks + R-003 测试隔离 + R-004 读写解耦 全整改）；全门禁含 integration（ruff+mypy --strict 267+全量 unit+全量 integration exit 0）全绿。配置对齐次生项拆为 **B-071**（开放 P3，[PR #119](https://github.com/lync-cyber/intelli-source/pull/119) 立项）。
- **B-072（G-001）**：失败推送审计落库 —— `facade.py` 失败两分支（渠道抛异常 / 渠道返回 `{"status":"failed"}`）补 `_record_push(status="failed", error_message=...)`，带与成功路径同口径脱敏 `recipient_id` + email/phone 脱敏 `error_message`，消除 `PushRecord.status=failed/error_message` 死列；落库统一在 facade 层（持有 session_factory），不走渠道 `from_env` 注入（与 session-per-request 不契合）；两失败分支去重抽 `_record_failed_push` helper。翻转 B-049 旧测试（失败时 `_record_push` 现以 `status="failed"` 被调用而非 `assert_not_called`）。新增 `test_facade_push_record_failed_b072.py`（AC1~AC6）；TDD light + REFACTOR(duplication)；全门禁绿（ruff+mypy --strict 267+全量 unit 3605 PASS+push-record integration 8 PASS）。
- **B-073（G-002+G-003，决策 A）**：订阅静默失配 reload WARN —— `subscription_validator._warn_silent_misconfig` 在 `validate_subscriptions_file` 校验通过路径对四类静默错配发非阻塞 WARN：match_rules 未知键、无有效匹配维度（永不匹配）、非法 frequency、非法 timezone（`zoneinfo` try/except）；`VALID_FREQUENCIES` 定义在 `config/constants.py` 避免 config→distributor 反向导入（lint-imports 12 kept/0 broken）。WARN 不改 `validate_subscriptions_file` 成功/失败语义。新增 `test_subscription_reload_warn_b073.py`（AC1~AC6）；TDD light，无需 REFACTOR；全门禁绿。
- **B-076（G-007+G-008+G-009+G-011，SMTP 默认改 A）**：推送渠道排障可观测性 —— ① `email.from_env` 端口↔TLS 一致性 WARN（465↔implicit TLS、587↔STARTTLS、1025/25↔plain），`.env.example` 默认 `IS_SMTP_USE_TLS=false`（配 587）；② facade.distribute 返回体新增 `disabled_channels`（软禁用/未注册渠道被跳过的去重列表，渠道 `failed` 不计入）；③ doctor 识别占位 LLM key（尾随 `...`）+ 为 `not set` 项（IS_DATABASE_URL/IS_REDIS_URL/IS_CELERY_BROKER_URL/LLM key）附 `.env` 修复指引。G-008（token errmsg 真实上浮）经核实早已实现，本批仅补 wechat/wework 回归护栏。新增 `test_b076_email_smtp_warn.py` / `test_b076_token_errmsg.py` / `test_b076_facade_disabled_channels.py` / `test_b076_doctor_placeholder.py`（共 19 用例）；TDD light，无需 REFACTOR；全门禁绿（ruff+mypy --strict 267+全量 unit 3624 PASS/5 deselected）。
