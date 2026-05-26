---
id: backlog-intellisource-v1
doc_type: backlog
author: orchestrator
status: approved
deps: []
---

# IntelliSource v1 Backlog

> 维护：本文件梳理 PR #53 / #54 audit 闭环之后的剩余工作。完成项请直接删除条目，新增项按优先级插入。
> 最后更新：2026-05-26 (B-039 + B-042 + B-044 + B-045 闭环；步骤 9 真起栈 PASS 补签；阶段 4 vector 路径待 OPENAI_API_KEY)

## 优先级语义

- **P0 — 阻塞**：影响生产正确性 / 安全 / 上线 go-no-go
- **P1 — 阻塞质量**：可观测性、性能边界、合规
- **P2 — 架构 / 功能完整性**：上帝类拆分、PRD 接受项功能缺口
- **P3 — 优化 / 规约**：硬编码、弱断言、风格

---

## P0 — 上线门禁人工验证

### B-031 执行 PRE-DEPLOY-WALKTHROUGH 全程跑通（pre_deploy 人工 go/no-go）
- **优先级**：P0（**最高**）— 直接对应"上线 go-no-go"语义；自动化测试无法替代人工管线 + 模块端到端走查
- **关联**：[docs/deploy/PRE-DEPLOY-WALKTHROUGH.md](deploy/PRE-DEPLOY-WALKTHROUGH.md)（1009 行）/ [docs/deploy-spec/deploy-spec-intellisource-v1.md §3.3](deploy-spec/deploy-spec-intellisource-v1.md) 引用 / B-010 deploy-spec 已闭环
- **现状**：walkthrough 文档由 commit `dbbb987` 引入并就位，按管线工作流分 **8 阶段 / 20 步**，覆盖 M-001~M-011 全部模块；deploy-spec §3.3 把它作为 prod 灰度发布的第 1 步 pre_deploy 检查点。但**从未由人工实际端到端跑通**——所有 2838 PASS 单元/集成测试都是 mock/容器化自动验证，不能替代真实管线的 LLM 调用 / 渠道推送 / DB 中文全文检索 / Celery 优先队列消费等行为
- **修复方向**：
  - 用户按 [PRE-DEPLOY-WALKTHROUGH.md](deploy/PRE-DEPLOY-WALKTHROUGH.md) 0~8 阶段 20 步逐步操作，每步对照"启动 → 触发 → 期望响应 → 验证手段 → Pass 标准"并签字
  - 走查过程中遇到偏差 / NO-GO 项：登记到 `docs/reviews/CORRECTIONS-LOG.md` 或回填新 backlog 条目（B-032+）
  - 全部 20 步签字 GO 后，本任务关闭；任何 NO-GO 项必须先闭环再重新跑相应阶段
- **依赖**：B-010 deploy-spec ✅（前置就绪）
- **覆盖关系（顺带带掉的下游任务）**：
  - B-014（staging 验证 /api/v1/metrics）— 走查阶段 5「监控 SLO」自然覆盖
  - B-015（promtool check rules）— 同上
  - 部分 B-013（CI integration 真跑）— 走查会真起 PG/Redis 栈，验证不依赖 mock 路径
- **验证**：
  - walkthrough 文档末尾 20 个签字栏全部填写
  - CORRECTIONS-LOG 或新 backlog 条目记录所有 NO-GO 闭环
  - EVENT-LOG 追加 `phase_end pre_deploy walkthrough closed` 记录
- **何时重新评估**：每次 prod 发布前或 arch / 关键模块大改后，应重新执行本走查（视为 release-gate 而非一次性任务）

---

## P1 — Audit 残留质量项

> B-003 / B-004 / B-005 / B-006 已闭环（详见 [docs/reviews/code/CODE-REVIEW-backlog-p1-r1.md](reviews/code/CODE-REVIEW-backlog-p1-r1.md)，含 R-001 修订）

---

## P2 — 架构 / 功能完整性

> B-007 已闭环（详见 [docs/reviews/code/CODE-REVIEW-B-007-r1.md](reviews/code/CODE-REVIEW-B-007-r1.md)）— `gateway/__init__.py` 732 → 120 行，拆为 `_complete/_chat/_stream/_queue/_metrics/_protocols` 6 mixin，Protocol 自洽，2820 PASS 不退化
>
> B-009 已闭环（decision-only，reaffirm 选项 ②）— PRD AC-063 [ASSUMPTION] 在 sprint-9 已锁定 YAML-as-source-of-truth；`src/intellisource/api/routers/pipelines.py` 现状即决策实现（list/detail/run，无 CRUD）。完整 workflow CRUD（DB 存储 + 历史版本）保留为 v2+ 范畴，本 backlog 不立项。
>
> B-008 已闭环 — `truncate_summary` 接入 LLM summarizer（`summarizer.structured` 模板 + `gateway.complete` + `response_format: json_object`），产出 `{title, summary, timeline, key_points}` 结构化摘要；LLM 失败 / 返回非法 JSON / 缺字段 → 回退字符串截断；PRD AC-023 [ASSUMPTION] 已移除、标 `[x]`；2834 PASS (+7 测试) 不退化
>
> B-010 已闭环 — `docs/deploy-spec/deploy-spec-intellisource-v1.md` (755 行 + changelog) 产出并通过 r1+r2 双轮审查；4 模板必填段全覆盖；dev/staging/prod 三环境矩阵；zhparser DB 镜像要求 + 11 项指标家族 (B-014) + promtool check rules (B-015) + SBOM + trivy/grype 门禁 + git checkout+rebuild 回滚方案 + run_pipeline 唯一注册任务 smoke + queue.priority.* 实际队列名 + webhook token 轮换。reviewer r1 needs_revision (2 HIGH + 4 MEDIUM + 3 LOW)；devops r2 修订全部闭环；orchestrator inline r2 audit approved。详见 [docs/reviews/doc/REVIEW-deploy-spec-intellisource-v1-r2.md](reviews/doc/REVIEW-deploy-spec-intellisource-v1-r2.md)

---

## P3 — 优化 / 规约

### B-011 263 处弱断言 `assert .* is not None`
- **关联**：原 audit F-49 / D6-7
- **现状**：跨 79 个测试文件，大量 `assert result is not None` 不验证语义
- **修复方向**：不批量改；新增测试时由 reviewer code-review Layer 1 检查命中
- **规约**：在 `.cataforge/rules/COMMON-RULES.md §通用 Anti-Patterns` 加一条"禁止单纯 `is not None` 断言无语义检查"

### B-012 `keyword_tag` 默认值硬编码 `"未分类"`
- **关联**：原 audit F-50 / D6-8
- **现状**：[`src/intellisource/pipeline/processors/tools.py:305,310`](src/intellisource/pipeline/processors/tools.py:305) 硬编码中文字符串
- **修复方向**：抽常量 `DEFAULT_KEYWORD_TAG: str = "未分类"` 至模块顶层；i18n 非 v1 范围
- **成本**：单点改动

> B-029 + B-030 已闭环 — LLM/Push alert 按 model/channel 拆分 (annotations 模板化引用 label) + R-002 注释 + R-003 精确路径匹配 + R-004 register 集中化 (facade __init__)；2827 PASS (+7 测试)。

---

## B-031 走查暴露的部署破口 (2026-05-26)

> 来源：B-031 PRE-DEPLOY-WALKTHROUGH 阶段 0 步骤 1+2 触发 7 项 NO-GO，部分 inline 修复（修正 #1~#6 已落地），部分需要架构/文档层面跟进。完整修正记录见 [CORRECTIONS-LOG 2026-05-26 阶段 0 步骤 1/2](reviews/CORRECTIONS-LOG.md)。

### B-032 制作 pgvector + zhparser 复合 DB 镜像
- **优先级**：P1
- **关联**：CORRECTIONS-LOG 修正 #5；deploy-spec §2 R-005 "zhparser DB 镜像要求"
- **现状**：当前 docker-compose 用裸 `pgvector/pgvector:pg16`，不含 zhparser。migration 001 的 `CREATE EXTENSION IF NOT EXISTS zhparser` 已包入 `DO ... EXCEPTION` 块优雅降级，FTS 退到 `to_tsvector('simple', ...)`。代码层面（storage/vector.py）**目前从未引用 zhparser**，但 deploy-spec 把 zhparser 作为中文分词目标。
- **修复方向**：
  - 选 A：新建 `docker/db.Dockerfile` 基于 `pgvector/pgvector:pg16` + 编译安装 SCWS + zhparser；docker-compose `db` 服务改为 `build: { context: .., dockerfile: docker/db.Dockerfile }`
  - 选 B：寻找现成 pgvector+zhparser 公开镜像（社区 fork）
  - 修完后把 migration 001 的 `EXCEPTION` 包裹去掉，让 zhparser 重新成为硬约束；同步把 storage/vector.py FTS configuration 从 `simple` 切到 `zhparser`
- **验证**：步骤 1 `SELECT extname FROM pg_extension` 输出含 `zhparser`；步骤 10 中文 query 走分词路径

### B-033 composition 对未配置渠道容忍
- **优先级**：P2
- **关联**：CORRECTIONS-LOG 修正 #7；walkthrough §0.2 与 composition.py:127 "hard-fail by design" 矛盾
- **现状**：`build_distributor_facade()` 对 wechat/wework/email 任一缺失即 `raise ValueError`；与 walkthrough 允许 "分发渠道 key 暂可全部留空" + 步骤 14 标 N/A 直接冲突。当前 walkthrough 用 `disabled-walkthrough-placeholder` 占位绕过。
- **修复方向**：
  - 改 `*Distributor.from_env()` 返回 `None` 或抛 `ChannelDisabledError`（细分异常）当全部凭据缺失
  - `build_distributor_facade()` 捕获并 `log.warning("channel X disabled: missing env Y")`，从 channels dict 中跳过
  - `DistributorFacade.distribute()` 路由时若收到 `channel=wechat` 但 channels 不含 wechat，返回明确错误
- **验证**：docker/.env 清空 wechat/wework/email 后 api lifespan 不再 fail；wechat push 调用返回 `ChannelUnavailable` 错误而非 KeyError
- **回滚**：移除占位值；保留 hard-fail 也是合理设计选项（取决于"渠道是部署前提" vs "渠道是运行时能力"）

### B-034 PRE-DEPLOY-WALKTHROUGH 文档订正
- **优先级**：P3
- **关联**：CORRECTIONS-LOG 修正 #5-#7 影响 / walkthrough 步骤 2 期望与实际偏差 / 阶段 2 步骤 6-8 暴露 3 项新 drift
- **现状**：步骤 2 "Pass 标准: /health.status == healthy" 与 celery 健康依赖 worker（步骤 12 才起）冲突；OpenAPI 端点假设公开但实际 X-API-Key 中间件保护；步骤 6 期望 `content-process.mode=strict` 实际 `batch` + manual-collect.steps 期望含 `params` 实际 `{}`；步骤 7 期望 trace_id 进 worker log 但 stdlib formatter 不渲染 contextvar（实际机制 OK，见 B-040）；步骤 8 期望 `/llm/stats` 不需 API key 实际需要
- **修复方向**：
  - 步骤 2 改 `Pass 标准: /health.status in {"healthy", "degraded"}` + 注释 "celery 在步骤 12 worker 起栈后转 healthy"
  - 步骤 2 OpenAPI curl 加 `-H "X-API-Key: $IS_API_KEY"`，§0.2 增加 "IS_API_KEY 必填，对 /openapi.json + /docs + /api/v1/* 全部生效"
  - §0.2 新增 "若 docker/.env 留空分发渠道凭据，须等 B-033 闭环；当前应至少填 wechat/wework/email 占位值"（B-033 闭环后该段删除）
  - 步骤 6 期望 JSON 同步实际值：`content-process.mode=batch` / manual-collect 详情 steps `params:{}`（修正 #15 后）
  - 步骤 7 trace_id 子项加注 "依赖 B-040 闭环后生效；当前可跳过此项，专项验证留给步骤 17 F-23 回归"
  - 步骤 8 修正 "`/llm/stats` 不带 API key 也能查" → "所有 /api/v1/* 端点均需 X-API-Key（webhooks/health/metrics/openapi/docs/redoc 除外）"

### B-035 CI 强制跑 docker integration
- **优先级**：P1
- **关联**：B-013（已有任务，本任务是其升级）；CORRECTIONS-LOG 全部 7 项 NO-GO 的根因之一
- **现状**：本地无 Docker → 47 docker integration tests deselect；CI 当前路径也不真跑（B-013 carryover）。**所有 NO-GO 都因 docker compose 真起栈从未在 CI 跑通而隐藏**
- **修复方向**：
  - GitHub Actions workflow 加 `services: { docker: { ... } }` 或用 `setup-docker` action
  - 加 `IS_FORCE_DOCKER_TESTS=1` env 变量，让 conftest 不再 deselect docker 测试
  - 加专门的 "docker compose smoke" job：真跑 `docker compose up -d db redis migrate api` + curl /health
  - fail 时阻塞 merge
- **验证**：CI 输出 `162 collected, 0 deselected, 47+ docker PASS`；smoke job 显示 api 健康

### B-038 framework-feedback: 提议框架默认采用 CLAUDE.md 单一事实来源
- **优先级**：P3（项目本地已落地，feedback 是为防止 upgrade 漂移）
- **关联**：本次会话用户决策"删除 PROJECT-STATE.md，CLAUDE.md 为单一事实来源"
- **现状**：CataForge 框架默认双文件状态机制 — CLAUDE.md（人面向）+ .cataforge/PROJECT-STATE.md（框架镜像）。两份内容必须手工同步，是真实的双写负担 + 不一致风险源。本项目已删除 PROJECT-STATE.md 并改写 4 处硬引用（framework.json migration_checks / scaffold-manifest.json / self-update SKILL.md / 状态持久化机制说明）。
- **风险**：下次 `cataforge upgrade apply` 会从上游 scaffold 重新引入 PROJECT-STATE.md + migration_checks 改回，本地决策被覆盖。`cataforge upgrade rollback --from <ts>` 可救但需要每次 upgrade 后手动回滚 4 处。
- **修复方向（feedback 内容）**：
  - CataForge framework 改成 CLAUDE.md / AGENTS.md 单一事实来源（去 PROJECT-STATE.md 双写）
  - 或：把 PROJECT-STATE.md 改为可选（migration_checks 不强制 + scaffold-manifest 标 `optional: true`），项目可按需启用
- **执行路径**：
  - `uv run cataforge feedback --type=suggest --title="..." --body="..."`（framework-feedback skill）
  - 或直接在上游 CataForge repo 开 issue + PR
- **验证**：上游接受后，本项目下次 `cataforge upgrade apply` 不再重新引入 PROJECT-STATE.md

---

> B-037 已闭环 — 用户选 A: per-task lazy + NullPool。新增 [scheduler/lazy_redis.py](../src/intellisource/scheduler/lazy_redis.py) `LazyLoopRedis` 包装类（按 running event loop 缓存 `aioredis.Redis`，通过 `__getattr__` 透明转发）；[scheduler/boot.py](../src/intellisource/scheduler/boot.py) `_build_redis_client` 返回 LazyLoopRedis，`init_worker_session_factory` 加 `poolclass=NullPool`。新增 [tests/unit/scheduler/test_b037_loop_bridge.py](../tests/unit/scheduler/test_b037_loop_bridge.py) 14 tests GREEN；scheduler/composition/worker 整组 264 PASS 不退化；ruff + mypy clean。**B-031 阶段 1 步骤 4 walkthrough rerun 全 Pass GREEN：** worker 真消费 run_pipeline 2.68s succeeded / 20 raw_contents 落库 / fingerprint 复跑去重 / priority queue 路由全活；走查中途修复 NO-GO #13（collect_execute **kwargs 透传契约违例），立 B-039 P3 处理 `_collect_execute` 双副本去重。详见 [CORRECTIONS-LOG B-037 + walkthrough rerun 条目](reviews/CORRECTIONS-LOG.md)。

> B-039 已闭环 (本次会话, 选 A 升级版) — 走查 B-031 步骤 9 时发现真起栈跑 manual-collect 后 `processed_contents.summary` 仍 NULL，根因：B-044/B-045 的 `summary`/`embedding` kwarg 只加到了 `tools/executes/process.py` 孤儿副本，**registry 实际调用的是 `tools/__init__.py:457` 那份**。同型双副本在 `_collect_execute` / `_process_execute` / `_distribute_execute` / `_search_execute` / `_get_content_detail_execute` / `_summarize_for_user_execute` / `_llm_complete_execute` 全部 7 个 atomic execute 函数 + `_serialize_search_response` helper 上都存在。**重构方向**：(1) `tools/executes/{collect,process,distribute,search_and_content,llm}.py` 5 个文件升级为单一事实来源（用 __init__.py 历史漂移最新版本覆盖，含 B-044/B-045 的 summary/embedding kwarg）；(2) 新增 `tools/registry.py` (453 行) 集中 `PermissionLevel`/`ToolDefinition`/`AgentToolRegistry`/`_atomic_tool_defs`/`_default_tool_defs` 业务实现，`_*_execute` 通过 `from intellisource.agent.tools.executes.* import` 引用真源；(3) `tools/__init__.py` 974→55 行 facade，仅保留 `__all__` + re-export + `load_pipeline_config` helper；(4) `executes/__init__.py` 剩 1 行 docstring。**真起栈验证**：truncate processed_contents + 重跑 manual-collect → 20/20 summary 非空 + 20/20 llm_call_logs success（B-042/B-044 同时活路径 PASS）。**测试侧**：tests/unit/agent/test_tools_fanout_and_dto.py 修一处 monkeypatch 路径（`tools_mod.asyncio` → `executes.process.asyncio`）；2790 PASS 不退化；mypy --strict + ruff + lint-imports 8/8 clean。

---

> B-042 已闭环 (本次会话, 选 C) — `LLMGateway.__init__` 新增 `session_factory` kwarg；`_RetryMixin._emit_call_log()` 统一 cost_tracker（legacy）+ session_factory（生产）双源；chat/stream 切到 helper，**complete 补 log_call**（之前缺失）；`composition.build_llm_gateway(redis, session_factory=None)` 经 `_build_deps_bundle` 注入；worker + api 进程 singleton 现具 per-call 会话能力。新增 [tests/unit/llm/test_gateway_session_factory.py](../tests/unit/llm/test_gateway_session_factory.py) 10 tests / 7 class GREEN（覆盖构造 / 三入口 emit / 异常吞噬 / 显式 cost_tracker 优先 / 复合 wiring）；test_cache.py 单测重命名 `test_cache_miss_logs_success_not_cached` 适配新契约。真起栈验证（步骤 9 补签）：`SELECT count(*) FROM llm_call_logs WHERE status='success'` ≥ 1，input/output_tokens > 0 — 待用户跑。

### B-043 chat() path 接入 LLMCache
- **优先级**：P3
- **关联**：CORRECTIONS-LOG 2026-05-26 B-041 carryover；walkthrough 步骤 9 期望 "二次执行命中缓存（增量显著减少或 cache_hit=true）"
- **现状**：[llm/gateway/_chat.py](../src/intellisource/llm/gateway/_chat.py) `chat()` **无 cache 路径**，仅 [_complete.py](../src/intellisource/llm/gateway/_complete.py) 走 `if self._cache is not None and cache_key_parts is not None: cached = await self._cache.get(...)`。`/search/chat` 走 `chat()` → 永远不命中缓存。
- **修复方向**：
  - chat() 加 `cache_key_parts` 可选参数；key 构造需含 messages 全文 hash + tools schema hash + model（多轮历史变了缓存就 miss，是预期）
  - 仅 finish_reason='stop' 且无 tool_calls 时才入缓存（中间 tool-loop 步不缓存）
  - LLMResult 缺少 finish_reason 字段直接命中（cache 复用）
- **验证**：连续两次相同 `/search/chat` 请求 — 第二次响应 latency 显著低（缓存返回不走 LLM API）；prometheus `llm_cache_hits_total` 计数 +1

> B-044 已闭环 (本次会话, 选 B) — 新增 [src/intellisource/pipeline/processors/summarizer.py](../src/intellisource/pipeline/processors/summarizer.py) `LLMSummarizer(BaseProcessor)`：读 ctx.title/body_text → `truncate_summary(cluster, tool_deps=_GatewayDeps(gw))` 经 `asyncio.run` 调度（无 loop 直 / 有 loop 走 ThreadPoolExecutor）→ ctx.set("summary",...)；全异常路径写 "" 不抛。`PROCESSOR_REGISTRY` 注册 + 类级 `_NEEDS_LLM_GATEWAY=True` 标记。`_build_processors_from_config(config, llm_gateway=None)` 看标记按需注入；`build_agent_runner` 把 llm_gateway 透到 factory。`config/pipelines/content-process.yaml` 追加末步骤；[agent/tools/executes/process.py:`_process_execute`](../src/intellisource/agent/tools/executes/process.py) `repo.create(summary=str(ctx.get("summary") or ""))` 持久化。新增 [tests/unit/pipeline/test_llm_summarizer.py](../tests/unit/pipeline/test_llm_summarizer.py) 11 tests / 5 class GREEN（registry / process behavior / factory injection / yaml drift guard / _process_execute persistence）。真起栈验证（步骤 9 补签）：truncate processed_contents 后重跑 content-process → `SELECT summary FROM processed_contents WHERE summary <> ''` ≥ 1 — 待用户跑。

> B-045 已闭环 (本次会话, 选 B 立即闭环) — `processed_contents.embedding` 列恒 NULL 的死代码 BLOCKER 修复（`VectorStore.upsert()` 在整个代码库零调用者；vector/hybrid mode 实际只跑 keyword fallback）。新增 [src/intellisource/pipeline/processors/embedder.py](../src/intellisource/pipeline/processors/embedder.py) `EmbeddingProcessor(BaseProcessor)`：读 ctx.body_text / fallback title → `llm_gateway.embed(text)` 经 `_run_coro` 调度 → ctx.set("embedding", vec)；空文本 / 无 gateway / 异常路径全 graceful 写 None 不抛。新增 [src/intellisource/llm/gateway/_embed.py](../src/intellisource/llm/gateway/_embed.py) `_EmbedMixin.embed(text)`：经 `ModelRoutingConfig.get_model("embed")` 路由 → `litellm.aembedding` (静态 hook `_aembedding` 可测) → 取 `response.data[0].embedding`；与 B-042 一致复用 `_emit_call_log` 写 `llm_call_logs` (`call_type='embed'`)。`PROCESSOR_REGISTRY` 注册 + `_NEEDS_LLM_GATEWAY=True` 共享 B-044 factory 注入；`config/pipelines/content-process.yaml` 末段追加 `- processor: EmbeddingProcessor`；[agent/tools/executes/process.py:`_process_execute`](../src/intellisource/agent/tools/executes/process.py) `repo.create(embedding=embedding_arg)` 持久化（None 时透传保留 DB NULL）。`config/llm_models.yaml` 加 `embed: openai/text-embedding-3-small` 路由。新增 [tests/unit/pipeline/test_embedding_processor.py](../tests/unit/pipeline/test_embedding_processor.py) 12 tests + [tests/unit/llm/test_gateway_embed.py](../tests/unit/llm/test_gateway_embed.py) 7 tests = 19 GREEN（registry / process / factory / yaml drift / _process_execute persistence + None-pass-through / embed method / happy path / failure paths / call_log emission）。真起栈验证（B-031 阶段 4 步骤 10/11）：需配置 `OPENAI_API_KEY`，无 key 时 embedding 列保持 NULL，vector/hybrid mode 走 keyword fallback；有 key 时 `SELECT count(*) FROM processed_contents WHERE embedding IS NOT NULL` ≥ 1，且 `/search { search_mode: "semantic" }` 真出向量相似度排序结果 — 待用户跑。

---

### B-040 worker stdlib log → structlog/formatter migration（trace_id 可见性）
- **优先级**：P3
- **关联**：CORRECTIONS-LOG 2026-05-26 B-031 阶段 2 步骤 7 trace_id 一项延后；走查暴露
- **现状**：[scheduler/signals.py](../src/intellisource/scheduler/signals.py) `_on_task_prerun` 已通过 Celery message header `x-trace-id` 把 contextvar 正确 set/reset（F-23 已闭环，单测覆盖）；但 worker 大多数业务模块用 stdlib `logging.getLogger(__name__)`，root logger 仅挂默认 `StreamHandler`（无 formatter），log line 形如 `[ts: LEVEL/Pool] msg` 无 `trace_id=` 子串。结果：walkthrough 步骤 7 + 步骤 17 的 `grep -oE 'trace_id=[a-f0-9-]+'` 都会命中 0，**给人 propagation 失效的假错觉**，实际机制是工作的。
- **修复方向**：
  - 选 A：root logger 装一个 `structlog.stdlib.ProcessorFormatter` + `structlog.contextvars.merge_contextvars`，让 trace_id contextvar 自动出现在 log line（key=trace_id value=<uuid>）
  - 选 B：自定义 `logging.Formatter` 子类，`format()` 内读 `trace_context.get_trace_id()` 拼接到 msg 前；改动小、零依赖
  - 选 C：业务代码全量迁移到 `structlog.get_logger()`，contextvar 通过 `merge_contextvars` 自动注入（最重，符合 arch 长期方向，logging.py 已有 NOTE 提到 "mypy --strict 类型不兼容" 阻塞）
  - 推荐：选 B 最快闭合 walkthrough 期望；选 C 留给独立 sprint
- **验证**：worker 日志 grep `trace_id=` 至少命中一个 uuid；同一 task 内多条 log 共享同一 trace_id；步骤 17 F-23 回归 PASS

---

### B-036 deploy-spec 审查模板强化
- **优先级**：P2
- **关联**：CORRECTIONS-LOG 修正 #1~#7 根因；B-010 deploy-spec r1+r2 审查未覆盖 "本地真起栈" 维度
- **现状**：deploy-spec 审查模板 ([.cataforge/skills/doc-review/](.cataforge/skills/doc-review/)) 关注 SBOM / promtool / 回滚方案 / 灰度策略，但 r1+r2 都没强制要求 "本地最小栈 docker compose up -d db redis migrate api 必须真跑通"
- **修复方向**：
  - doc-review skill 的 deploy-spec 维度加一条强约束 "审查前必须由人工在本地真起最小栈，截图或 log 附在审查报告"
  - 模板增 `## §X 本地最小栈验证证据` 段，作为 reviewer 必填项
  - 失败案例：B-031 暴露 7 项部署破口，其中 5 项（Dockerfile 路径 / README / 依赖声明 / shebang / uvicorn）在 "本地真起栈" 5 分钟内必被发现
- **验证**：下次 deploy-spec 审查时模板自动 prompt 这条；framework-review skill 检查 deploy-spec 报告含 "本地最小栈验证证据" 段

---

## PR #54 后续验证

### B-013 CI 在 ubuntu-latest 跑 integration（docker available 路径）
- **现状**：本地无 Docker 时 47 个 PG 集成测试 deselect；CI 必须真跑
- **修复方向**：GitHub Actions workflow 设 `IS_FORCE_DOCKER_TESTS=1` 或确保 docker daemon 启动；fail 时阻塞 merge
- **验证**：CI 输出显示 162 collected，0 deselected，47+ PASS

### B-014 staging 验证 /api/v1/metrics 暴露所有新 metric
- **现状**：本次新增 metric（http_/llm_/celery_/pushes_/llm_circuit_open）单测覆盖通过，但未在真实 deploy 验证 Prometheus scrape 抓得到
- **修复方向**：deploy staging 后 `curl /api/v1/metrics | grep -E "(http_requests_total|llm_calls_total|pushes_total|celery_tasks_total|llm_circuit_open)"`
- **依赖**：B-010 deploy-spec

### B-015 `promtool check rules` 验证 alerts.yml 语法
- **现状**：`test_alerts_yaml.py` 校验 YAML shape + metric 名引用一致，但未跑 `promtool check rules`
- **修复方向**：CI workflow 加一步 `docker run --rm -v $PWD/docker/prometheus:/etc/prometheus prom/prometheus:v2.55.1 promtool check rules /etc/prometheus/alerts.yml`
- **依赖**：B-013 CI 升级

---

## 框架学习应用（来自 RETRO）

### B-016 应用 6 EXP (sprint-1~7) 到 `.cataforge`
- **关联**：CLAUDE.md 原 backlog ①
- **现状**：[`docs/reviews/retro/RETRO-intellisource-v1.md`](docs/reviews/retro/RETRO-intellisource-v1.md) 列了 6 个改进点，应用决策 deferred
- **修复方向**：逐条评估 → 改 `.cataforge/skills/<id>/SKILL.md` 或 `agents/<role>/AGENT.md`

### B-017 应用 EXP-005 (sprint-9) 装配缺口 framework-level lint
- **关联**：CLAUDE.md 原 backlog ②
- **现状**：[`RETRO-intellisource-v1-sprint-9.md`](docs/reviews/retro/RETRO-intellisource-v1-sprint-9.md) — assembly-gap 5 次复发
- **修复方向**：`.cataforge/skills/code-review/scripts/lint_assembly.py` 检查 build_*_composition 必须把所有声明依赖注入下游 facade

### B-018 应用 EXP-006 / EXP-007 anti-truncation 协议到全角色
- **关联**：CLAUDE.md 原 backlog ② / RETRO-sprint-8
- **现状**：EXP-007 Mid-Progress Drop Contract 在 implementer / refactorer 见效；扩展到 reviewer / test-writer / debugger 未做
- **修复方向**：`.cataforge/agents/{reviewer,test-writer,debugger}/AGENT.md` 加 4 步契约 prompt 段

---

## 架构治理工具链首扫 (2026-05-24)

> 扫描报告全文见 [docs/reviews/code/CODE-SCAN-arch-20260524-r1.md](reviews/code/CODE-SCAN-arch-20260524-r1.md)
> 工具集：`uv run lint-imports` / `uv run deptry src` / `uv run vulture` / `uv run pydeps`（配置在 [`pyproject.toml`](../pyproject.toml) `[tool.importlinter|deptry|vulture|pydeps]`）；本地一键 `make check`
> 基线：
> - **import-linter**: 147 文件 / 296 依赖边 / 4 kept / 4 broken / 8 violation groups → B-020~B-024
> - **deptry**: 30 issues (6 DEP002 + 24 DEP003) → B-026 / B-027
> - **vulture**: 3 dead variables → B-028
> - **pydeps**: 渲染依赖图 SVG（CI nightly artifact）
> - **CI 集成**: 已加入 lint job + nightly `arch-graph` job，**当前观察模式** (`continue-on-error: true`) → B-025 升级为强制门禁

### B-020 抽 `pipeline.base` + `pipeline.processors.tools` 出新 `intellisource.tools/` 包
- **关联**：CODE-SCAN-arch V1 + V6
- **现状**：
  - `llm.processors.filter` 顶层 import `pipeline.base.BaseProcessor` / `pipeline.context.PipelineContext` ([src/intellisource/llm/processors/filter.py:7-8](../src/intellisource/llm/processors/filter.py))
  - `distributor.push_optimizer` 顶层 import `pipeline.processors.tools.{filter_sensitive,truncate_for_push}` ([src/intellisource/distributor/push_optimizer.py:12](../src/intellisource/distributor/push_optimizer.py))
- **根因**：`BaseProcessor` 与原子工具被困在 pipeline 包内，导致任何复用方都"被迫"反向依赖 pipeline；ARCH 文档把 `pipeline.processors.tools` 定义为 M-004 "原子化工具"但物理位置归属 M-003
- **修复方向**：
  - 抽 `BaseProcessor` / `PipelineContext` 出来到 `intellisource.tools.processor_base` (或 `core/processor_base`)
  - 抽 `filter_sensitive` / `truncate_for_push` / `tfidf_keywords` / `truncate_summary` / `keyword_tag` 等纯函数到 `intellisource.tools.text/`
  - pipeline.processors.tools 改为再导出薄层兼容旧路径（一个 deprecation 周期后删除）
- **验证**：`lint-imports` 中 V1 + V6 消失；distributor/llm 不再依赖 pipeline

### B-021 `compact_messages_for_chat` 从 `agent.compaction` 抽到中性命名空间
- **关联**：CODE-SCAN-arch V5
- **现状**：[src/intellisource/search/chat_session.py:16](../src/intellisource/search/chat_session.py) 反向依赖 `agent.compaction`；该函数实质是"对话历史 token 压缩工具"，与 agent 编排无关
- **修复方向**：迁到 `intellisource.tools.conversation` 或 `intellisource.llm.prompt_builder`（与 PromptBuilder 同包，语义贴近）；agent 与 search 都改 import 新位置
- **成本**：单文件移动 + 2 处 import 路径更新
- **验证**：`lint-imports` V5 消失

### B-022 `api.routers.search` 单点直接 import `storage.models.ChatSession`
- **关联**：CODE-SCAN-arch V7
- **现状**：[src/intellisource/api/routers/search.py:225](../src/intellisource/api/routers/search.py) 函数内 `from intellisource.storage.models import ChatSession` 用 `db_session.get(ChatSession, ...)`
- **修复方向**：复用同文件 l.250 已有的 `ChatSessionRepository.get_by_id()`，删除函数内 ORM 直引
- **成本**：~5 行
- **验证**：`lint-imports` V7 消失；现有 chat session 单测仍 PASS

### B-023 拆分 `composition.py` 解耦 wiring root 与共享常量
- **关联**：CODE-SCAN-arch V2 + V3 + V4
- **现状**：[`composition.py`](../src/intellisource/composition.py) 同时承担 wiring root（依赖一切）和共享常量提供者（`SOURCE_TYPE_TO_PIPELINE`、`CompositionError`、`get_agent_runner_holder`），导致 scheduler.{boot,tasks,beat_sync}（3 处顶层 import）+ agent.factory（lazy import）反向依赖
- **修复方向**：拆为 `composition/` 包：
  - `composition/constants.py` — `SOURCE_TYPE_TO_PIPELINE` / `CompositionError` / `get_agent_runner_holder`（最底层）
  - `composition/api.py` — `build_api_composition`（顶层，仅被 `main` import）
  - `composition/worker.py` — `build_worker_composition`（顶层，仅被 `scheduler.boot` import）
  - 顺带把 `WeComCrypto` (l.515) 抽到 `intellisource.tools.wecom_crypto`（V3）
- **影响范围**：composition / agent.factory / scheduler.{boot,tasks,beat_sync} / api.routers.tasks
- **验证**：`lint-imports` V2/V3/V4 全部消失；现有装配测试 PASS

### B-024 `config.loader` 返回 `SourceConfig` 而非 `Source` ORM
- **关联**：CODE-SCAN-arch V8
- **现状**：[src/intellisource/config/loader.py:19](../src/intellisource/config/loader.py) 顶层 import `storage.models.Source`；loader 直接生产 ORM 实例传给 `bulk_upsert`
- **修复方向**：
  - loader 返回 `list[SourceConfig]` (`config.models.SourceConfig` 已存在)
  - `SourceRepository.bulk_upsert(configs: list[SourceConfig])` 内部做 Pydantic → ORM 转换
  - config 包不再依赖 storage，符合架构图分层
- **验证**：`lint-imports` V8 消失；source CRUD / reload 路径单测 PASS

### B-025 架构治理工具链 CI 升级为强制门禁
- **关联**：架构契约首扫 + 依赖卫生 + 死代码扫描的执行保障
- **现状（已落地一半）**：
  - `pyproject.toml` 已注册 4 工具配置：`[tool.importlinter]` / `[tool.deptry]` / `[tool.vulture]` / `[tool.pydeps]`
  - `Makefile` 新增 `arch` / `deps` / `deadcode` / `deps-graph` / `check` 目标
  - `.github/workflows/ci.yml` 已加 3 步（import-linter / deptry / vulture），**当前 `continue-on-error: true`** 观察模式；并新增 nightly `arch-graph` job 渲染依赖图为 artifact
- **未完成（待 baseline 清零再设强制）**：
  - 移除 `continue-on-error: true`，使违规阻塞 merge
  - 新增 `.pre-commit-config.yaml` 挂钩 import-linter + deptry
- **强制门禁的前置条件**：B-020 ~ B-024（import-linter）+ B-026 ~ B-028（deptry / vulture）全部闭环 → 三工具退出码 = 0
- **验证**：故意提交一处违规 → CI 红 → merge 阻塞

### B-026 显式声明 transitive 运行时依赖（deptry DEP003 × 24）
- **关联**：架构治理工具链首扫 (deptry, 2026-05-24)
- **现状**：5 个包被项目直接 import，但依赖于 fastapi/sqlalchemy/celery/litellm 等间接引入：
  - `pydantic`（9 处 import — agent.dto / api.routers.* / config.* / llm.gateway._routing / llm.model_config / push_optimizer / api.schemas.search）
  - `pyyaml` / `yaml`（6 处 — agent.pipeline / api.routers.pipelines / config.loader / config.resolver / config.validator / llm.model_config）
  - `starlette`（3 处 — api.middleware × 2 + main.py）
  - `jsonschema`（1 处 — llm.gateway._types）
  - `kombu`（1 处 — scheduler.celery_app）
- **风险**：上游升级时 transitive 链路可能改变，例如 fastapi 移除 pydantic v1 fallback，本项目无版本约束 → 静默漂移
- **修复方向**：把 `pydantic / pyyaml / starlette / jsonschema / kombu` 加入 [`pyproject.toml`](../pyproject.toml) `[project] dependencies`，每个加合理的 `>=` 版本下限
- **验证**：`uv run deptry src` DEP003 计数 = 0；`uv sync --upgrade` 不破坏现有测试

### B-027 dev deps 统一到 `[dependency-groups]`（deptry DEP002 × 6）
- **关联**：架构治理工具链首扫 (deptry, 2026-05-24)
- **现状**：[`pyproject.toml`](../pyproject.toml) 同时存在两套 dev 配置 — 旧 PEP 621 的 `[project.optional-dependencies] dev = [...]` 与新 PEP 735 的 `[dependency-groups] dev = [...]`；deptry 把前者当 extras 看，对 `pytest / pytest-asyncio / mypy / ruff / testcontainers / pydantic-settings` 报 DEP002
- **修复方向**：
  - 合并：把 `[project.optional-dependencies] dev` 的所有条目迁到 `[dependency-groups] dev` 后删除前者
  - `pydantic-settings` 单独评估：grep 全库确认是否仍有 import；如无则连同删除
  - `uv sync --all-extras` 改为 `uv sync` 或 `uv sync --group dev`（CI 同步更新）
- **验证**：`uv run deptry src` DEP002 计数 = 0；CI `uv sync` 步骤仍能拉齐 dev deps

### B-028 删除 `_unified_call_with_retry` 三个未使用参数（vulture × 3）
- **关联**：架构治理工具链首扫 (vulture, 2026-05-24)
- **现状**：[src/intellisource/llm/gateway/_retry.py:44-47](../src/intellisource/llm/gateway/_retry.py) `_unified_call_with_retry` 签名包含 `operation_id` / `enable_fallback` / `fallback_input`，但函数体只在 docstring 提到，未在逻辑中引用；三处调用方（[gateway/__init__.py:385,469,580](../src/intellisource/llm/gateway/__init__.py)）都按位传参 — 是删了实现忘了同步签名的残留
- **修复方向**：
  - 选 A（推荐）：删除三个参数与对应 docstring；调用方相应去掉关键字参数
  - 选 B：在函数体内实际消费它们（如把 `operation_id` 用于 log 关键字 / 把 `enable_fallback` 接入 fallback 分支判断 / 把 `fallback_input` 转发给 `_fallback_manager.execute_fallback`），这是 sprint-8 拆 Gateway 时遗失的语义
- **验证**：`uv run vulture` 退出码 = 0；gateway chat/complete/stream 三个调用路径单测仍 PASS

---

## 上游反馈跟进

### B-019 [`docs/feedback/`](docs/feedback/) 1 bug + 1 suggest 未闭环
- **关联**：CLAUDE.md 原"上游反馈"段
- **现状**：feedback 目录有 2 条未处理
- **修复方向**：逐条 triage → 关联到现有 backlog 项或新开

---

## 已完成（PR #53 + PR #54 历史档案）

完整闭环参见 commit `7e10e77` (PR #53) 与 `31bddde` (PR #54) — 共 39 + 14 项 audit 修复：
- P0：F-01 ~ F-11（数据正确性 + agent/LLM + docker + 企微加密 + receiver_id + /metrics 鉴权 + PG 真链路）
- P1：F-12 ~ F-27（LLM 治理 + 采集真链路 + health 并发 + 4 路径埋点 + trace_id + priority queue + content_not_found + alerts）
- P2：F-28 ~ F-29 / F-31 ~ F-37 / F-39 / F-41 ~ F-48（上帝类拆分 + 持久化 + 杂项清理）
- P3：F-46 / F-47 / F-48
- 测试质量：2 xfail 修复 + 1 placeholder skip 删除 + 46 docker skip 转 deselect
- 框架基础：EXP-006 mid-narration recovery 多次实战 + EXP-007 Mid-Progress Drop Contract 验证有效

回归基线：2766 PASS / 0 FAIL / 0 skip / 0 xfail / 51 deselected；mypy --strict + ruff clean。
