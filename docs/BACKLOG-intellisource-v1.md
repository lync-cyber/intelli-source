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

## PR #102 待合并 — BGE-M3 本地 embedding（feat/bge-m3-local-embedding）

> T-EMB-1/2/3 全部 done + code-review approved；全门禁绿（unit 3421 PASS + mypy --strict 263 + ruff + lint-imports 12/12）。已提交（commit d9ffeec），[PR #102](https://github.com/lync-cyber/intelli-source/pull/102) 待合并。合入后整块归档到「已闭环」。
> 选型：BGE-M3 经 **HuggingFace TEI** 容器（OpenAI 兼容 /v1/embeddings），litellm 走 `openai/bge-m3` + 显式 api_base；CPU 默认、GPU 经 env 可切换。维度 1536→1024（arch 钦定的换模型路径，[arch-data §E-004](arch/arch-intellisource-v1-data.md)）。api_base/key/dimension 走 `Settings`（`ModelTaskConfig` 是 extra=forbid，yaml 装不下）。

- **T-EMB-1** ✅ done（standard TDD + code-review approved）：embed 路由 + 配置 + 1024 迁移 —— `_embed.py` 从 settings 读 `embedding_api_base`/`embedding_api_key`，api_base 非空才显式传 litellm（`api_key or "tei"` 兜底 keyless TEI）；`Settings` +`embedding_dimension(1024)`/`embedding_api_base`/`embedding_api_key`；`storage/models.py` `EMBEDDING_DIM=1024` 两列 `Vector(EMBEDDING_DIM)` + 迁移 `g0h1i2j3k4l5`（down_revision=a2b3c4d5e6f7，重建 HNSW，NULL 无回填）。降级契约保留：api_base 空 → embed 返回 None 不发请求。⚠️ `config/llm_models.yaml` 的 `embed:` 条目顺延到 T-EMB-3 随部署接线一起加。审查：[CODE-REVIEW-T-EMB-1-r1](reviews/code/CODE-REVIEW-T-EMB-1-r1.md)
- **T-EMB-2** ✅ done（light-dispatch + code-review approved）：`HybridSearchEngine` 加可选 `llm_gateway` 注入，`search()` 在 `mode∈{semantic,hybrid}` 且 query_vector 缺失且 gateway 存在时 embed query（try/except 吞错 → 既有 keyword 降级兜底）。已接线入口：HTTP `/search`（`app.state.llm_gateway`）+ RAG 路径（`deps.py` builder 工厂 → agent `_search_execute`）。MCP `_default_search_engine_factory` 维持无 gateway（stdio 无 app.state，可由调用方注入）。审查：[CODE-REVIEW-T-EMB-2-r1](reviews/code/CODE-REVIEW-T-EMB-2-r1.md)
- **T-EMB-3** ✅ done（config/docs，L2 短路）：`config/examples/llm_models.example.yaml` +`embed:{model:openai/bge-m3, provider:openai}`（提交侧模板；运行时 `config/llm_models.yaml` 被 gitignore）；`docker/docker-compose.yml` 加 `embedding`(TEI cpu-1.6 默认，`--model-id BAAI/bge-m3`，healthcheck，软依赖) + api/worker 注入 `IS_EMBEDDING_API_BASE=http://embedding/v1`/KEY/DIMENSION；`docker/docker-compose.gpu.yml`（nvidia device override）；`docker/.env.example` 四项；deploy-spec + arch data/modules 维度假设同步 1024/BGE-M3-via-TEI。真实起栈验证归 PRE-DEPLOY-WALKTHROUGH（B-031）

---

## 剩余项目级真债（非阻塞，保留跟踪）

- 无项目级真债。已知 scope 限制（非阻塞）：MCP `_default_search_engine_factory` 无 gateway → MCP 搜索 keyword-only（stdio 无 app.state，可由 `build_mcp_server(search_engine_factory=...)` 调用方注入）。

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
