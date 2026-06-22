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

## 部署/分发 新手友好度评估（DEPLOY-UX-EVAL 20260617）

> 全部已闭环（B-072~B-079 + B-074），见「已闭环」段。B-074 五条真实环境验证全过（①②⑤ CI、③④ Vultr Debian13 真机）。

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

- **[P3] KG 摄取残留 WARN 76（框架口径噪声，非阻塞）**：doctor `KG ingestion completeness` 的 dangling 检查用完整 entity-prefix 正则扫引用，但 TC/CR/SR 是纯关系 class、KG 从不建实体节点，故 active docs 里的 TC-/CR-/SR- 提及（76 = TC×71 + CR×4 + SR×1）结构性恒 dangling。根因在框架侧（dangling 候选集应限于会实体化的 class）。上游 [CataForge#292](https://github.com/lync-cyber/CataForge/issues/292) 已 COMPLETED 关闭（含代码定位 + 修复方向 A/B），但 **0.13.0 doctor 仍复现 WARN 76 → 修复未在该包生效，待框架升级复验**。详见 [feedback](feedback/feedback-suggest-kg-dangling-scan-relation-only-persists-20260616.md)。

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
- **PR #102 / T-MCP-GW**：BGE-M3 本地 embedding（TEI 路由 + 向量列 1536→1024 迁移 + RAG semantic 接线）+ MCP 搜索 keyword-only→semantic/hybrid
- **PR #106 / #107**：B-067/B-068 embedding backfill（arch API-030 + CLI）+ agentloop-hardening（flexible loop / model failover / scheduler idempotency，R-001~R-012/P11/P12）
- **B-069 + 框架 0.4.1→0.12.0**（#109~#125）：pre-deploy 走查 15-20 GO（B-069 health version 修）+ scaffold 刷新 + KG 全量重建 + KG dangling WARN 处理 + D1 Docker 缓存根治
- **B-070 / B-071**：Chat 压缩兑现 AC-053 token-aware（#118）+ arch §5.1 `[chat]` 配置精简混合收敛（接入 `IS_CHAT_*` 两 knob + 退役 vestigial 2000 + 删 2 幽灵参数，#126）
- **deploy-ux 评估批 B-072 ~ B-079**（[CODE-SCAN-deploy-ux-20260617-r1](reviews/code/CODE-SCAN-deploy-ux-20260617-r1.md)）：失败推送审计 / 订阅 reload WARN（#122）+ 模板可发现性 CLI / 推送渠道可观测性 / 冷启动预检 G-010（#123）+ init key 幂等 / doctor 鉴权探针（#124）
- **B-074 远端 infra**（远端就绪文档 + provision-remote.sh + systemd 模板 + GHCR 推送工作流 + registry compose；deploy-spec §1.4/§2.2/§3.1/§3.6）：镜像 CVE 加固 + trivy `ignore-unfixed:true` + gosu `skip-files`（#130/#131）；5 条真实环境验证全过 —— ①GHCR push·②app+DB trivy·⑤DB 构建经 CI，③provision 脚本端到端·④GHCR pull 鉴权经 Vultr Debian13 真机
