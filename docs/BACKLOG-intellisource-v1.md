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

## 剩余项目级真债（非阻塞，保留跟踪）

- **[P2·部署] Windows Docker Desktop BuildKit stale COPY cache 根治**（D1，2026-06-11 走查暴露）：`docker compose build`（带 cache）对 `COPY src/ ./src/` 的 build-context checksum 检测在 Windows Docker Desktop 下失效——镜像时间戳更新但容器内 src 仍是旧代码（PR #107 合并后普通 rebuild 未真正纳入新代码，致 `fallback_models` schema 校验崩溃、api 起不来）。当前规避 = 部署强制 `docker compose build --no-cache`。根治候选：Dockerfile 在 `COPY src/` 前加 cache-bust `ARG GIT_SHA` ENV / 部署脚本固定 `--no-cache` / CI 用 `--pull --no-cache`。详见 [CORRECTIONS-LOG 2026-06-11](reviews/CORRECTIONS-LOG.md)。

---

## agentloop-hardening 后续（非阻塞，保留跟踪）

> 本批 R-001~R-010 + R-005 余量 + R-011/R-012 + P11/P12 已闭环，详见 [code-review r1](reviews/code/CODE-REVIEW-agentloop-hardening-r1.md) 与 [burndown r1](reviews/code/CODE-REVIEW-agentloop-burndown-r1.md)。以下为唯一保留的延后设计。

- **[P3] session-splitting 压缩设计（idea，待定）**：以"分裂新 session + parent 血缘"替代当前 `compact_agent_messages` 就地压缩，换取可追溯压缩历史与并行分支。落地才需要 `ChatSession.parent_session_id`（就地压缩下无生产者也无消费者，属死 schema，未建列）。是否值得取决于是否需要审计压缩链路。

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
