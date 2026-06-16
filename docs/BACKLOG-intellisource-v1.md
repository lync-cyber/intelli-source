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

## P2 — 功能完整性（非阻塞，release 已放行）

### B-070 Chat 会话压缩与写入截断未协调 → AC-053 未兑现
- **根因**：`api/chat_sessions.py:_persist_chat_turn` 每轮无条件 `history[-(MAX_HISTORY_TURNS*2):]` 删最旧轮次（与 token 预算 / LLM 可用性无关），早期历史在读取端 `compact_history` 摘要前即从库删除；且 `compact_history` 对 `prepare_session` 关闭后 detached 的 `stored_session` 改 `context["messages"]` 从不 commit，摘要仅服务本次请求 replay、请求结束即丢，库里恒为原始 ≤20 条。结果 [prd AC-053](prd/prd-intellisource-v1.md)「超 token 限制时自动摘要历史对话」实际未兑现：第 11 轮后压缩永远看不到第 1 轮，且每请求从同一 ≤20 条窗口重复重算摘要（既无积累也浪费 LLM 调用）。
- **次生**：实现常量 `MAX_HISTORY_TURNS=10` / `CHAT_COMPACT_TOKEN_BUDGET=6000` 与 arch `[chat]` 段 `context_token_budget=2000` / `compress_after_turns=4`（[arch §5.1](arch/arch-intellisource-v1.md)）失配，且 persist 路径不读 `[chat]` 配置。
- **修复方向**：写入端以 token-aware compaction 替代固定条数硬截断 —— append 新轮后若库存历史超 `context_token_budget` 则 `compact_messages_for_chat` 并**持久化** summary+recent（库存自界、旧上下文以结构化摘要存活）；读取端压缩降为安全网或移除冗余；常量改读 settings `[chat]`。新测试覆盖「>N 轮后早期上下文以摘要形式存活且持久化」。
- **来源**：session-splitting 评估（见下）副产暴露；定性见上游反馈无关，纯本项目实现债。

---

## agentloop-hardening 后续（非阻塞，保留跟踪）

> 本批 R-001~R-010 + R-005 余量 + R-011/R-012 + P11/P12 已闭环，详见 [code-review r1](reviews/code/CODE-REVIEW-agentloop-hardening-r1.md) 与 [burndown r1](reviews/code/CODE-REVIEW-agentloop-burndown-r1.md)。以下为唯一保留的延后设计。

- **[P3] session-splitting 压缩设计（已评估 2026-06-16：NO-GO）**：提案以"分裂新 session + parent 血缘"替代 `compact_agent_messages` / `compact_messages_for_chat` 就地压缩，换可追溯压缩历史 + 对话分支；落地需 `ChatSession.parent_session_id`（死 schema，未建列）。**评估结论 NO-GO**，四条代码/文档实证：
  1. **agent-loop 压缩纯内存**：`compact_agent_messages` 仅经 gateway `compress_if_needed` 被 `agent/executors/flexible.py:_compress_history` 调用，对内存 message 列表 best-effort 压缩，无 `ChatSession` 行、不落库 → 该侧无行可分支，提案结构性不适用。
  2. **唯一持久的 Chat 路径每次 persist 无条件硬截断最近 10 轮**（`MAX_HISTORY_TURNS=10` / `history[-20:]`），早期历史在读取端摘要前即从库删除 → "父会话留全量供审计" 无从谈起。**注**：该写入截断本身是与压缩特性未协调的残留、架空 AC-053（非"刻意产品边界"——已订正并单列为 **B-070 / P2**，见下），但其存在与否都不改变 session-splitting 结论：审计/分支收益无 PRD 消费者，且 AC-053 留存目标经就地写入端压缩即可达成（见 B-070），无需 parent 血缘。
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
