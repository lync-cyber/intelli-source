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

## 部署/分发 新手友好度评估（DEPLOY-UX-EVAL 20260617，非阻塞）

> 来源：[CODE-SCAN-deploy-ux-20260617-r1](reviews/code/CODE-SCAN-deploy-ux-20260617-r1.md)（四单元 = 部署/订阅/推送/模板）。本地起栈未被硬阻断，故无新增 P0；`G-NNN` 编号见报告。修复方向已折入用户 2026-06-17 决策（Q1=B+C / Q2=A / Q3=A / Q4=A）。B-072/B-073/B-075/B-076/B-077/B-078/B-079 已闭环（见「已闭环」段）；唯一开放项：B-074（远端 infra portion ②③ 置备脚本 + registry 镜像）。

### B-074 [P2] 远端主机就绪 + 置备 + registry 镜像（G-006 + G-013(registry)，决策 B+C）
- **现状（代码实证）**：`docker/docker-compose.yml:75-76` 直接 `8000:8000` 暴露且全为 `build:` 模式；deploy-spec 与 PRE-DEPLOY-WALKTHROUGH 全文 `localhost`，无 reverse proxy / TLS / 域名 / systemd / 防火墙 / 入站 webhook 公网可达性指引；仓库无 ssh/ansible/置备脚本；远端回滚强依赖目标主机重建 zhparser（`docker/db.Dockerfile` 源码编译 SCWS+zhparser）。
- **影响**：无法据现有文档完成公网可访问的远端部署，回调类渠道在远端不可用。
- **修复方向（决策 B+C）**：① 新增"远端部署主机就绪"文档（反代/TLS/防火墙/webhook 公网 URL 示例）；② 提供置备脚本或 `intellisource` 远端 target；③ 引入 prebuilt registry 镜像 + compose pull 模式（同解远端回滚重建依赖）。文档先行、自动化与镜像为中-大成本后续。
- **进度**：① 文档已交付 —— [`docs/deploy/remote-host-readiness.md`](deploy/remote-host-readiness.md)（反代/TLS/防火墙/入站 webhook 公网可达/systemd/冷启动代价 + 对 deploy-spec 交叉引用）。剩余 ②③（置备脚本 + registry 镜像）= 代码/infra，待续。
- **触发**：规划首次远端/生产部署时。

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
- **B-070（[PR #118](https://github.com/lync-cyber/intelli-source/pull/118)）**：Chat 会话压缩兑现 [AC-053](prd/prd-intellisource-v1.md)「超 token 自动摘要历史对话」—— 写入端 `_bounded_history`→`compact_messages_for_chat` token-aware 压缩替代每轮 `history[-20:]` 硬截断，**持久化** summary+recent（旧上下文以结构化摘要存活）；webhooks 同源 persist 路径一并迁移；`compact_history` 改纯函数（不污染 detached `stored_session.context`）；compaction sizing 抽 `_chat_compaction_context_window` helper 收口（同 PR 第二 commit 修 AC-T071-9 集成 parity 回归）。由 session-splitting 评估（[PR #117](https://github.com/lync-cyber/intelli-source/pull/117) NO-GO）副产暴露；code-review approved_with_notes（R-001 MEDIUM budget 收口 + R-002 webhooks + R-003 测试隔离 + R-004 读写解耦 全整改）；全门禁含 integration（ruff+mypy --strict 267+全量 unit+全量 integration exit 0）全绿。配置对齐次生项拆为 **B-071**（见下）。
- **B-071（精简混合收敛，P3，B-070 follow-up）**：arch §5.1 `[chat]` 配置段 ↔ 实现失配收敛。研判实证：arch 5 参数中 `compress_after_turns`/`compress_model` 从未实现（src 零引用）、`session_timeout_hours=24` 与代码 `CHAT_SESSION_TTL_DAYS=30` 单位+值双失配、`context_token_budget=2000` 实为 vestigial 库默认（persist+replay 实际共用 `CHAT_COMPACT_TOKEN_BUDGET=6000`，无生产调用点落到 2000）、配置引用的 `settings.example.toml [chat]` 文件不存在且 TOML 非本项目机制（实为 `IS_*` env）。用户决策**精简混合**（Q1=混合精简 / TTL=30 天）：① 接入 2 个运维 knob `IS_CHAT_COMPACT_TOKEN_BUDGET=6000` + `IS_CHAT_SESSION_TTL_DAYS=30`（app 层 caller 读 Settings 下传，`compaction.py` 纯库不 import Settings；扁平 `IS_CHAT_*` 字段；`ge=1` 守 footgun）；② `MAX_HISTORY_TURNS=10` 保留为常量；③ 退役 vestigial 2000（去 docstring 的 arch 伪装，留库内 fallback）；④ 删 2 幽灵参数；⑤ arch §5.1 表 + arch-data 清理策略 + `docker/.env.example` 同步。新增 `test_b071_chat_config.py`（7 用例）+ 改 `test_cleanup_chat_sessions.py`；TDD light，[code-review r1](reviews/code/CODE-REVIEW-B-071-r1.md) approved_with_notes（R-003 MEDIUM `ge=1` + R-001 LOW 测试冗余 整改，R-002 LOW 校准保留）；门禁绿（ruff+mypy --strict 268+全量 unit 3705 PASS/5 deselected+chat/webhook integration 23 PASS+doctor all-pass）。
- **B-072（G-001）**：失败推送审计落库 —— `facade.py` 失败两分支（渠道抛异常 / 渠道返回 `{"status":"failed"}`）补 `_record_push(status="failed", error_message=...)`，带与成功路径同口径脱敏 `recipient_id` + email/phone 脱敏 `error_message`，消除 `PushRecord.status=failed/error_message` 死列；落库统一在 facade 层（持有 session_factory），不走渠道 `from_env` 注入（与 session-per-request 不契合）；两失败分支去重抽 `_record_failed_push` helper。翻转 B-049 旧测试（失败时 `_record_push` 现以 `status="failed"` 被调用而非 `assert_not_called`）。新增 `test_facade_push_record_failed_b072.py`（AC1~AC6）；TDD light + REFACTOR(duplication)；全门禁绿（ruff+mypy --strict 267+全量 unit 3605 PASS+push-record integration 8 PASS）。
- **B-073（G-002+G-003，决策 A）**：订阅静默失配 reload WARN —— `subscription_validator._warn_silent_misconfig` 在 `validate_subscriptions_file` 校验通过路径对四类静默错配发非阻塞 WARN：match_rules 未知键、无有效匹配维度（永不匹配）、非法 frequency、非法 timezone（`zoneinfo` try/except）；`VALID_FREQUENCIES` 定义在 `config/constants.py` 避免 config→distributor 反向导入（lint-imports 12 kept/0 broken）。WARN 不改 `validate_subscriptions_file` 成功/失败语义。新增 `test_subscription_reload_warn_b073.py`（AC1~AC6）；TDD light，无需 REFACTOR；全门禁绿。
- **B-075（G-004+G-005，决策 A=文件覆盖为主，CLI portion）**：模板可发现性 CLI —— 文档面（README bundle 字段表 + 文件覆盖↔DB 分工）此前已交付；本批补代码：新增 `distributor/templates/discovery.py`（`list_file_overrides` 扫 `*.{fmt}.j2` + `sample_bundle` + `validate_overrides`（试渲染捕 TemplateSyntaxError/SecurityError，未知名→warning，`only=` 可按名过滤）+ `render_preview`）；`template list` 增「文件覆盖」小节 + 服务不可达降级（仍列覆盖、exit 0）；新增 `template validate [name]`（error→exit 1，仅 warning→exit 0）+ `template preview <name> -f <fmt>`（未知名→exit 1）。新增 `test_b075_template_discovery.py`（cli + distributor 两文件，30 用例）；TDD light，无需 REFACTOR；全门禁绿（ruff+mypy --strict 268+全量 unit 3654 PASS/5 deselected）。
- **B-076（G-007+G-008+G-009+G-011，SMTP 默认改 A）**：推送渠道排障可观测性 —— ① `email.from_env` 端口↔TLS 一致性 WARN（465↔implicit TLS、587↔STARTTLS、1025/25↔plain），`.env.example` 默认 `IS_SMTP_USE_TLS=false`（配 587）；② facade.distribute 返回体新增 `disabled_channels`（软禁用/未注册渠道被跳过的去重列表，渠道 `failed` 不计入）；③ doctor 识别占位 LLM key（尾随 `...`）+ 为 `not set` 项（IS_DATABASE_URL/IS_REDIS_URL/IS_CELERY_BROKER_URL/LLM key）附 `.env` 修复指引。G-008（token errmsg 真实上浮）经核实早已实现，本批仅补 wechat/wework 回归护栏。新增 `test_b076_email_smtp_warn.py` / `test_b076_token_errmsg.py` / `test_b076_facade_disabled_channels.py` / `test_b076_doctor_placeholder.py`（共 19 用例）；TDD light，无需 REFACTOR；全门禁绿（ruff+mypy --strict 267+全量 unit 3624 PASS/5 deselected）。
- **B-077（G-010 + G-012/G-013 文档部分，P3）**：冷启动预检 —— 文档面（match_rules 语义小节 + example.yaml 匹配维度 + README json_feed/静默回落）此前已交付；本批补 G-010 代码：`stack.py` 新增 `_env_path` / `_docker_daemon_running`（`docker info`）/ `_weak_credential_vars`（值含 `change-me` 判定）/ `_preflight_up`，`up` 启动前依次校验 `.env` 存在 → 无占位弱口令 → Docker daemon 可达（任一失败友好提示 + exit 1），并在阻塞式 `--wait` 前打印 embedding(TEI) 首拉等待提示。同步更新 `test_stack.py` 6 个 + `test_main.py` 3 个 up 测试旁路预检。新增 `test_b077_up_preflight.py`（13 用例）；TDD light，无需 REFACTOR；全门禁绿（ruff+mypy --strict 268+全量 unit 3667 PASS/5 deselected）。
- **B-078 + B-079（[PR #124](https://github.com/lync-cyber/intelli-source/pull/124)，P2，2026-06-18 真实冷启动会话新立）**：deploy-ux 第一公里两缺陷 —— B-078 `init` API key 非幂等（re-init 每次 `secrets.token_hex` 重生成、静默作废运行栈鉴权）改 `_resolve_api_key`（优先级 `os.environ` > `.env` 现有真实值 > 生成，过滤 `change-me-in-production` 占位符，交互留空沿用现有 key）；B-079 `doctor --check-api` 无鉴权探针致 key 漂移假绿，新增 `_probe_api_auth`（带 `X-API-Key` 探 `GET /sources`，401 → `[FAIL]` + 重建指引，仅 health ok 且 key 非占位时探）。[code-review r1](reviews/code/CODE-REVIEW-B-078-B-079-r1.md) approved（R-001 MEDIUM 占位符过滤 + R-002/003/004 同分支 4 项整改）；B-079 对**真实漂移栈**活体验证通过（旧 doctor 假绿 → 新 doctor 正确报 401 key drift）；TDD light，门禁绿（ruff+mypy --strict 268+全量 unit exit 0）。
