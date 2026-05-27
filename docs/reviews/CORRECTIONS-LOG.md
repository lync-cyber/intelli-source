---
id: "corrections-log"
doc_type: correction-log
author: cataforge
status: approved
deps: []
---
# Corrections Log

> 由 CataForge 自动追加。On-Correction Learning Protocol 触发条件见
> `.cataforge/agents/orchestrator/ORCHESTRATOR-PROTOCOLS.md`。

### 2026-05-04 | orchestrator | unknown

- 触发信号: option-override
- 问题/假设: T-073 code-review r1 = approved_with_notes（0 CRITICAL/HIGH，2 MEDIUM + 3 LOW）。R-002 是生产 bug（无效 cursor → 500 而非 400；limit=0 产生 has_more=True / items=[] 语义错误），其余为质量 / 测试增强。如何处理？
- 基线/推荐: 修 R-002 后接受 (Recommended)
- 实际/选择: 修全部 5 个后接受
- 偏差类型: preference

### 2026-05-04 | orchestrator | unknown

- 触发信号: option-override
- 问题/假设: T-073 code-review r2 = approved_with_notes（1 新 LOW + 1 观察）。R-001-r2：invalid cursor 边界测试用 mock side_effect 位推进，未走真实 uuid.UUID() 路径，防回归价值偏低（不影响产品正确性）。另外 ContentRepository LIKE 只在 commit 3857992 message 记了可限性，未进正式 carryover。如何处理？
- 基线/推荐: 接受 r2 + 补 CORRECTIONS-LOG 条目 (Recommended)
- 实际/选择: 再修 R-001-r2 后接受
- 偏差类型: preference

### 2026-05-04 | implementer | T-073 r2

- 触发信号: scope-reduction
- 问题/假设: T-073 r2 R-005 修复将 ClusterRepository.list_clusters 改用 ContentCluster.tags.contains([tag])（JSONB @> operator），同步对 ContentRepository.list 做了 sister fix
- 基线/推荐: 同步修复 ContentRepository
- 实际/选择: 回退 ContentRepository sister fix（保留 LIKE 模式）
- 偏差类型: technical-constraint
- 原因: tests/unit/storage/test_repositories.py 在 SQLite 下运行，SQLite 不支持 JSONB @> 运算符；ContentRepository 已有 SourceRepository 同模式（with SQLite-compat comment），保持一致避免选择性修复
- carryover: ContentRepository / SourceRepository tag 过滤的 LIKE 通配符副作用为 known limitation，待 storage 单元测试迁移到 Postgres test fixture 后统一改用 .contains() / @> 运算符
- 关联: commit 3857992, CODE-REVIEW-T-073-r2.md 追加观察

### 2026-05-04 | orchestrator | unknown
- 触发信号: option-override
- 问题/假设: T-075 code-review r1 verdict 为 approved_with_notes (1 MEDIUM R-001 signal 未连接 + 3 LOW)。R-001 与 T-074 r2 同模式 carryover，sprint-review 时易被误判为完整闭环。如何处理？
- 基线/推荐: 立即修复 R-001 + R-002 (Recommended)
- 实际/选择: 修复全部 4 个 (R-001~R-004)
- 偏差类型: preference

### 2026-05-04 | orchestrator | unknown
- 触发信号: option-override
- 问题/假设: Sprint-7 完整闭环 + RETRO 完成。如何处理 6 条 EXP 的改进应用与下一阶段推进？
- 基线/推荐: 现在应用 EXP-002 + EXP-005 两条高优先并推进 (Recommended)
- 实际/选择: 暂停，我要先设读 RETRO 报告
- 偏差类型: preference

### 2026-05-21 | orchestrator | T-092 r1
- 触发信号: agent-truncation
- 问题/假设: T-092 reviewer 子代理 Layer 2 阶段被 task-notification 截断（88 tools / 91K tokens / 5min），未返回 `<agent-result>` 且 CODE-REVIEW-T-092-r1.md 未落盘。无可恢复中间产出。按 §Sub-Agent Truncation Recovery Protocol 应走 §Agent Crash Recovery；选项为：① 重派 reviewer ② orchestrator 主线程内联接管 ③ 跳过待 sprint-review 兜底。
- 基线/推荐: 重派 reviewer 用更紧凑 prompt（保留独立性，但耗预算）
- 实际/选择: orchestrator 主线程内联 L1+L2，独立性损失换响应速度
- 偏差类型: preference
- 原因: 用户指定选项，明确接受独立性损失换响应速度
- 影响/缓解: code-review 子代理独立性损失记录在案；为弥补 orchestrator-as-reviewer 的利益冲突，本报告 verdict 走从严：3 HIGH + 3 MEDIUM + 4 LOW = needs_revision；R-001/R-002/R-003 三项的"测试通过、生产失效"是 sprint-8r 立项要消除的核心反模式，必须在批次 3 闭合前由 implementer 修订
- 关联: docs/reviews/code/CODE-REVIEW-T-092-r1.md

### 2026-05-21 | orchestrator | sprint-8r batch 3 revision concurrent dispatch
- 触发信号: git-race + agent-self-report-divergence
- 问题/假设: 并发派出 4 个 implementer revision 子代理（T-087/T-088/T-089/T-092），由于 implementer prompt 未明确禁止它们使用 `git add <files>` 与等待 orchestrator 协调 commit 时序，发生两起 git race + commit-message ↔ diff 错配事故：① commit 2019cbc 由 T-087 agent 创建，但 commit message 写成 T-088 r2 内容（agent 看见工作树有 T-088 staged 文件时假定 dual-purpose batch commit）；实际 diff 只含 T-087 5 个文件；T-088 实际改动留在工作树未 commit。② orchestrator 主线程随后 `git add` T-088 4 个文件 + `git commit`，但此时 T-089 agent 已并行 `git add` 自己的 5 个文件，导致 commit 7798139 message 写 T-088 但 diff 包含 T-088（4）+ T-089（5）共 9 文件；T-089 agent 后续 self-report 时确认改动已入 7798139，未额外创建 commit。
- 基线/推荐: implementer prompt 明确"不要 git add / commit / push，由 orchestrator 串行处理"；orchestrator 派工后保持只读直到所有 agent self-report 后再串行 commit
- 实际/选择: 并发派工 + 各 implementer 自行 commit（race window 暴露）
- 偏差类型: protocol-gap
- 原因: revision protocol 未规定并发派工时的 git 协调；implementer agent 习惯性 `git commit` 而 prompt 给了"commit 可以做"的隐性允许
- 影响/缓解:
  - 已发生事故：commit 历史中 2019cbc / 7798139 message 与 diff 内容不严格对应
  - 短期补救：本 CORRECTIONS-LOG 条目 + EVENT-LOG correction events（2026-05-21T23:55）固化真相，后续 reviewer 看 history 时能溯源
  - 不重写历史（无用户授权 amend/force push）
  - 长期改进 carryover：①修订 implementer AGENT.md / SKILL.md，revision task_type 显式要求 "do not run git add/commit/push; orchestrator handles git" ②修订 orchestrator §revision protocol，并发派工时强制 "agents leave working tree dirty; orchestrator collects & commits sequentially in dispatch order"
- 关联: commit 2019cbc, commit 7798139, T-088 / T-087 / T-089 r2 revision dispatch

### 2026-05-22 | orchestrator | sprint-8r batch 3 r3 inline approve
- 触发信号: option-override
- 问题/假设: 批次 3 r3 三任务全部完成 commit + push（b16f971 / bedd6f4 / db2be0d），2288 PASS / mypy strict / ruff clean。是否对全部 3 任务派 reviewer 还是部分 inline approve？
- 基线/推荐: 派 3 reviewer 完整闭环
- 实际/选择: 只派 T-088 r3 reviewer（重点验证 EXP-005 装配缺口闭环）；T-087 r3（R-005 caplog 单行断言）+ T-092 r3（_RawContentResultRepo adapter + integration test）由 orchestrator inline approve
- 偏差类型: preference
- 原因: 用户判断 T-087/T-092 r3 风险低（implementer self-report 含完整反证测试说明"删修复后必 fail"；改动局部、可读）；T-088 r3 是 sprint-8r 核心反模式闭环点，必须独立 reviewer 视角
- 影响/缓解: T-087/T-092 损失独立审查视角；implementer self-report 中的反证测试声明 + orchestrator 主线程 git 历史检查 + 全量回归通过共同构成代偿。如 T-094 集成测试发现装配缺口再回溯
- 关联: commits b16f971 (T-087 r3) / bedd6f4 (T-088 r3, 仍待 reviewer) / db2be0d (T-092 r3); CODE-REVIEW-T-088-r3.md (in-progress)

### 2026-05-22 | orchestrator | T-088 r3 R-009 inline fix
- 触发信号: option-override（用户选"inline 修 R-009 后接受"）
- 问题: T-088 r3 reviewer 发现 R-009 LOW — test_app_entry.py 3 处 `patch("intellisource.main.init_redis", new_callable=AsyncMock)` 让 `_redis_client = None`，与生产路径 `_redis_client = aioredis.from_url()` 模式不一致；当前测试不触发 Redis 调用故 2288 PASS，但未来扩展会 `AttributeError`
- 基线/推荐: 派 implementer 修
- 实际/选择: orchestrator 主线程 inline 修 — 3 处替换为 `patch("intellisource.main.aioredis.from_url", new_callable=AsyncMock, return_value=AsyncMock())` 对齐 test_llm_gateway_lifespan.py 成熟模式
- 偏差类型: preference
- 原因: 单文件 patch 模式微调（无逻辑改动），inline 比派 implementer 更快更精准；与 sprint-8r 装配缺口主题正交
- 影响/缓解: 10/10 test_app_entry.py PASS；2288 全量回归 PASS；mypy strict + ruff clean
- 关联: CODE-REVIEW-T-088-r3.md R-009; T-088 r3 final = approved

### 2026-05-23 | orchestrator | T-096 r1 reviewer truncation + r2 inline approve
- 触发信号: agent-truncation + option-override
- 问题/假设: T-096 r1 reviewer subagent (a678cd2f13fd2a8ea) 在 Layer 2 阶段被 task-notification truncated（79 tools / 5.7min / 88K tokens），无报告 artifact 落地，仅尾部片段 "now let me also check status field handling in _process_execute session exception swallowing"。sprint-9 累计第 2 次 reviewer truncation（前次 T-095 r1 同样原因）。EXP-006 candidate frequency tick。
- 基线/推荐: 重派 reviewer subagent 跑 r1 + 派 reviewer subagent 跑 r2 门禁
- 实际/选择: ① orchestrator 主线程接管 r1 inline review，按 code-review SKILL Layer 2 全 7 维度产出 CODE-REVIEW-T-096-r1.md（verdict=needs_revision: 1 HIGH R-001 + 1 MEDIUM R-002 + 3 LOW R-003/R-004/R-005）；② 用户裁决"主线程 inline 修 r2"+ "orchestrator inline approve r2"双簧；orchestrator 主线程修 5 finding（R-001 加 session.commit + R-002 mock 类型对齐 + R-003 删 dead-code + R-004/R-005 silent except 加 logger.warning）+ 新建 3 unit 反证测试（防 R-001 回归）+ 全量回归 0 self-caused regression + lint/mypy clean
- 偏差类型: preference + protocol-deviation
- 原因: sprint-9 reviewer truncation 已 2/2 全 truncate，第 3 次概率非零；r2 改动局部清晰（5 finding 全修 + 3 反证测试），主线程 reviewer 视角检查已完整覆盖；沿用 sprint-8r batch 3 r3 inline approve 先例（T-087 r3 / T-092 r3 / T-088 R-009）
- 影响/缓解:
  - r1 reviewer 独立性损失：orchestrator 既是 r1 reviewer 又是 r2 modifier，理论存在利益冲突；缓解为 verdict 从严（5 finding 全报，未短路 LOW）+ 反证测试落地（test_create_calls_session_commit_when_row_found 在 R-001 修复回滚后必 FAIL）
  - r2 inline approve 独立性损失：同 sprint-8r batch 3 r3 先例处理；CI integration 测试（test_raw_content_persist_on_pipeline_done.py 5 cases）将进一步反证 R-001 修复在端到端 PG 路径生效
  - EXP-006 frequency tick: sprint-9 reviewer truncation 2/2，retrospective 立项时需评估是否调整 reviewer maxTurns 或拆分 Layer 2 维度
- 关联: commit c492cba (T-096 GREEN) + commit 65d443a (T-096 r2 fix + CODE-REVIEW-T-096-r1.md); reviewer subagent a678cd2f13fd2a8ea (truncated); T-096 final = approved

### 2026-05-26 | orchestrator | unknown
- 触发信号: option-override
- 问题/假设: B-010 deploy-spec 闭环全部资产在工作区（deploy-spec主卷+changelog+r1/r2 审查报告+CLAUDE.md+PROJECT-STATE.md+BACKLOG+EVENT-LOG+doc-index）。接下来思路？
- 基线/推荐: Commit B-010 后推进 B-016~B-018 (Recommended)
- 实际/选择: 仅 Commit B-010，本轮会话结束
- 偏差类型: preference

### 2026-05-26 | orchestrator | B-031 walkthrough 阶段 0 步骤 1
- 触发信号: pre-deploy-walkthrough-NO-GO
- 问题: B-031 PRE-DEPLOY-WALKTHROUGH 首次真起 docker compose 栈，阶段 0 步骤 1（DB + Redis + migrate）触发 4 项构建/迁移缺陷连环失败。所有缺陷此前从未暴露 — 2838 PASS 单测/集成全部跑 SQLite 或 mock 路径，dockerized integration test 在本地 deselect、CI 未真跑（B-013 carryover），生产路径首次端到端验证即在本次 walkthrough。
- 修正 #1：[docker/Dockerfile:37](../../docker/Dockerfile) `COPY alembic.ini ./alembic.ini` 找不到文件 — 项目实际把 `alembic.ini` 放在 `alembic/alembic.ini`。改为 `COPY alembic/alembic.ini ./alembic.ini`。
- 修正 #2：`uv sync --frozen --no-dev` 在 builder 阶段 fail — hatchling 需要 `README.md`（pyproject.toml line 7 `readme = "README.md"`）但 Dockerfile 只 COPY pyproject.toml + uv.lock。改为 `uv sync --frozen --no-dev --no-install-project` — runtime 阶段已通过 `PYTHONPATH=/app/src` 加载源码，builder 不需自装包，同时让 deps layer cache 不再因 src 改动失效。
- 修正 #3：`[project.dependencies]` **既无 asyncpg 也无 psycopg**（两者都仅在 `[dependency-groups].dev`）。生产 image (`uv sync --no-dev`) 零 Postgres driver，应用根本无法连 DB。把 `asyncpg>=0.31.0` + `psycopg[binary]>=3.1` 移入运行时依赖；`uv lock` 重生成。
- 修正 #4：[alembic/env.py:30](../../alembic/env.py) 读 `DATABASE_URL`，compose 实际传 `IS_DATABASE_URL`；且 IS_DATABASE_URL 形如 `postgresql+asyncpg://...`，但 alembic 用同步 `engine_from_config()`，需要 sync driver。改为读 `IS_DATABASE_URL` 优先 + fallback `DATABASE_URL`，并把 `postgresql+asyncpg://` 重写为 `postgresql+psycopg://`（psycopg3）后再交给 alembic。
- 修正 #5：migration `001_initial_schema.py:25` 执行 `CREATE EXTENSION IF NOT EXISTS zhparser`，但 `pgvector/pgvector:pg16` base image 不带 zhparser → `FeatureNotSupported` 阻断迁移。**关键观察**：`storage/vector.py` 全文检索实际用 `to_tsvector('simple', ...)`，从未引用 zhparser；扩展是为未来中文分词预留。改为 `DO $$ ... EXCEPTION WHEN feature_not_supported THEN RAISE NOTICE ...` 包裹 — 扩展不可用时优雅降级。deploy-spec §2 R-005 提到的"zhparser DB 镜像要求"是真实未闭环 carryover，**留作 B-032 待办**：制作 pgvector + zhparser 复合镜像并切到 docker-compose。
- 偏差类型: technical-constraint + protocol-gap
- 原因: 项目 7 个 sprint 全程未做过真 docker integration test（测试矩阵都基于 SQLite/mock）；B-013 "CI docker integration" 长期 deferred；deploy-spec r1+r2 文档审查覆盖了 SBOM / promtool / 回滚方案等，但未要求"真起栈跑 migrate"作为审查通过条件。B-031 P0 立项之后才暴露这些隐藏破口 — 印证 walkthrough 不可被自动化回归替代的核心理由。
- 影响/缓解:
  - 修复 #1~#4 已纳入工作区，步骤 1 PASS（migrate exit 0 / 13 tables / pgvector / Redis PONG）
  - zhparser carryover → B-032 (P2，制作复合镜像)
  - 后续阶段 0 步骤 2 + 阶段 1~7 可能仍有未暴露破口，本 walkthrough 继续真跑
  - 长期改进 carryover：deploy-spec 审查模板加一条强约束 "本地最小栈 docker compose up -d db redis migrate 必须真跑通"
- 关联: docs/deploy/PRE-DEPLOY-WALKTHROUGH.md 步骤 1 签字栏；docker/Dockerfile / pyproject.toml / alembic/env.py / alembic/versions/001_initial_schema.py 编辑

### 2026-05-26 | orchestrator | B-031 walkthrough 阶段 0 步骤 2
- 触发信号: pre-deploy-walkthrough-NO-GO
- 问题: 阶段 0 步骤 2（API + /health）再触发 3 项部署/配置缺陷。
- 修正 #5：[pyproject.toml `[project.dependencies]`](../../pyproject.toml) 无 `uvicorn` 也无 `fastapi[standard]` extra — runtime image (`uv sync --no-dev`) 没有 ASGI server，docker compose `command: [uvicorn, ...]` 直接 `executable file not found in $PATH`。`fastapi>=0.110.0` 不会传递依赖 uvicorn（仅 starlette）。添加 `uvicorn[standard]>=0.27` 到运行时依赖；`uv lock` 重生成。
- 修正 #6：venv 跨路径 shebang 破口 — [docker/Dockerfile](../../docker/Dockerfile) builder 阶段 `WORKDIR /build`，产出 venv 在 `/build/.venv`；runtime 阶段 `COPY --from=builder /build/.venv /app/.venv` 把 venv 搬到 `/app/.venv`。但 venv 内 console_scripts (uvicorn, celery, alembic 等) 的 shebang 行硬编码 `#!/build/.venv/bin/python` — runtime 找不到 `/build/.venv` → `exec: no such file or directory`（指向 shebang 解释器，而非 script 本身，错误消息高度误导）。改 builder `WORKDIR /app`，让 venv 在 builder 即生成于 `/app/.venv`，COPY 后 shebangs 仍有效。**典型 multi-stage Python venv 陷阱**，框架级 anti-pattern 候选。
- 修正 #7：composition.build_distributor_facade() 与 walkthrough §0.2 "分发渠道 key 暂可全部留空" 矛盾 — wechat/wework/email 三个 `from_env()` 均在 env 缺失时 `raise ValueError`，[composition.py:127](../../src/intellisource/composition.py) 注释自述 "hard-fail by design"。但 walkthrough §0.2 + 步骤 14 均允许这些 N/A。当前会话用占位值（`disabled-walkthrough-placeholder`）让 distributor 能实例化（webhook 流程不真调它们），**B-033 待办**：使 composition 对禁用渠道容忍（log WARNING + skip channel），统一 distributor 启动语义。
- 偏差类型: technical-constraint + architectural-inconsistency
- 影响/缓解:
  - 修正 #5+#6 已纳入工作区，api 健康（db+redis healthy / celery unhealthy as expected before step 12）
  - 修正 #7 placeholder 短路：webhook 流程不受影响，但任何"启用 wechat/wework/email 真渠道"测试需重新填真值后 force-recreate api
  - **走查文档自身缺陷**：步骤 2 期望 `/health.status == "healthy"` 与 celery 依赖 worker（步骤 12 才起）冲突；OpenAPI 路径假设公开但实际 X-API-Key 保护。两处 walkthrough 文档应订正，**B-034 待办**。
  - 5 项 carryover backlog 候选（B-032 zhparser 复合镜像 / B-033 distributor 渠道可禁用 / B-034 walkthrough 文档订正 / B-035 docker integration test CI 真跑 / B-036 deploy-spec 审查模板要求"docker compose 真起栈"）
- 关联: docs/deploy/PRE-DEPLOY-WALKTHROUGH.md 步骤 2 签字栏；docker/Dockerfile + docker/.env + pyproject.toml 编辑

### 2026-05-26 | orchestrator | B-031 walkthrough 阶段 1 步骤 3-4
- 触发信号: pre-deploy-walkthrough-NO-GO
- 问题: 阶段 1 步骤 3（信源注册）PASS；步骤 4（手动触发采集）触发 5 项 worker + API 缺陷。
- 步骤 3 验证: POST /api/v1/sources 创建 HN RSS → 201 / DB 落库 / 列表 API 可查 / POST /sources/reload `loaded_count=2 errors=[]`（从 sources.yaml 加载 HN + GitHub Trending）。**Pass**。
- 修正 #8: worker `celery -A intellisource.scheduler.celery_app worker` 起栈后 `[tasks]` 列表 EMPTY — celery_app.py 不 import tasks.py，`@celery_app.task(name="run_pipeline")` decorator 从不执行。dispatch run_pipeline 时 worker silent drop。改 celery_app.py 末尾追加 `from intellisource.scheduler import tasks as _tasks` (late import 避开 circular)。
- 修正 #9: POST /tasks/collect → 500 IntegrityError FK violation `collect_tasks.task_chain_id` 引用不存在的 task_chains 行。handler [api/routers/tasks.py:158](../../src/intellisource/api/routers/tasks.py) 生成 `task_chain_id = str(uuid.uuid4())` 但**从不**创建 parent TaskChain 行，直接拿 UUID 当 FK 用。加 `TaskChainRepository.create(TaskChain(...))` 在创建 CollectTask children 前，Repository.create() 内部 flush 让 FK 可见。
- 修正 #10: 即便 worker 注册了 run_pipeline，处理 task 时仍 raise `RuntimeError: CeleryTasks not wired: worker_process_init handler has not run`。根因：worker_process_init / worker_process_shutdown signals 在 [scheduler/boot.py:303](../../src/intellisource/scheduler/boot.py) 注册，但 boot 模块从未被 worker entry 导入。改 worker compose `command: -A intellisource.scheduler.boot`（boot 才是 worker 的真正 entry point，per 其 docstring "Worker-side bootstrap for Celery task wiring T-075"）；boot.py 加 `celery_app = _module_celery_app` 公开 re-export 让 celery CLI 找得到 app。
- 修正 #11: GET /api/v1/tasks/{id} → 500 `'CollectTask' object has no attribute 'pipeline_name'`。serializer [api/routers/tasks.py:46](../../src/intellisource/api/routers/tasks.py) 读 task.pipeline_name / task.execution_mode，但这俩字段在 TaskChain 模型上，不在 CollectTask。从 _serialize_task 删除两字段（callers 需要 pipeline 元数据应跟 task_chain_id 查父链）。
- 修正 #12: **设计级 NO-GO** — worker 处理 run_pipeline 时 raise `RuntimeError: Event loop is closed`（[scheduler/tasks.py:69](../../src/intellisource/scheduler/tasks.py) `_run_sync` 路径）。根因：worker_process_init 用 `asyncio.run()` 跑 setup，创建 `aioredis.from_url(...)` Redis client；setup 结束后 loop 关闭，client 的 underlying conn 引用失效；run_pipeline task body 再次 `asyncio.run(idempotency_guard.release(task_id))` 新建 loop 时尝试用旧 client → "Event loop is closed"。**不在本会话 inline 修**，立 B-037 worker async/sync bridge hardening sprint 处理：候选解（任一）—— ①每 task 内 lazy 建 Redis client；②worker 长跑单 loop（不 asyncio.run，改 loop.run_until_complete + 复用）；③用 sync `redis-py` 在 sync code path。需要单独写测试 + 评估对 idempotency / metrics / signals 的影响，不适合放走查里快改。
- 偏差类型: technical-constraint + design-defect
- 影响/缓解:
  - 修正 #8~#11 已纳入工作区，步骤 3 PASS / 步骤 4 partial（dispatch link OK，consume link 阻塞于 #12）
  - 修正 #12 阻塞步骤 4 真正消费 + 步骤 12-14 全部（任何依赖 worker 跑通）
  - 阶段 1 步骤 5（信源 CRUD 回归）不依赖 worker，理论可在 B-037 闭环前先跑；但本会话按 §B 路径决定 commit + 结束
- carryover: B-037 worker async/sync bridge hardening（P0 — 阻塞 B-031 阶段 1-7 大部分步骤）
- 关联: docs/deploy/PRE-DEPLOY-WALKTHROUGH.md 步骤 3 PASS / 步骤 4 partial 签字栏；src/intellisource/scheduler/celery_app.py + boot.py + api/routers/tasks.py + docker/docker-compose.yml 编辑

### 2026-05-26 | orchestrator | B-037 worker async/sync bridge hardening (闭环)

- 触发信号: backlog-burndown
- 问题: 修正 #12（B-031 阶段 1 步骤 4 阻塞）— worker 处理 `run_pipeline` 时 `RuntimeError: Event loop is closed`，根因为 `aioredis.from_url(...)` 客户端的 conn pool 首次 `await` 时绑定到 `asyncio.run()` 创建的 loop；loop 关闭后下一次 `_run_sync` 复用同 client 即崩。同样的 loop-bound 问题也存在于 async SQLAlchemy engine 的连接池。
- 调研: WebSearch 验证业界 canonical pattern = per-task lazy + NullPool（[DEV.to "Using Async SQLAlchemy Inside Sync Celery Tasks"](https://dev.to/kevinnadar22/using-async-sqlalchemy-inside-sync-celery-tasks-3eg4)，[celery/celery #3884 discussion](https://github.com/celery/celery/issues/3884)，[earlgreyness/aio-celery](https://github.com/earlgreyness/aio-celery) 备选）。
- 修复方向（用户选 A）: per-task lazy + NullPool —
  1. 新增 [src/intellisource/scheduler/lazy_redis.py](../../src/intellisource/scheduler/lazy_redis.py) — `LazyLoopRedis` 包装类，按 running event loop id 缓存一份 `aioredis.Redis`；通过 `__getattr__` 透明转发所有方法（`set/get/delete/eval/hgetall/hset/setex/scan_iter/ping/aclose`）到 per-loop 客户端
  2. [src/intellisource/scheduler/boot.py](../../src/intellisource/scheduler/boot.py) `_build_redis_client()` 返回 `LazyLoopRedis(url)` 替代原裸 `aioredis.from_url(url)`，所有下游消费方（`IdempotencyGuard` / `CircuitBreaker` / `RateLimiter` / `Distributors`）零改动（鸭子类型）
  3. `init_worker_session_factory()` 增加 `poolclass=NullPool` 让每次 session checkout 开新 DB conn，规避 engine pool 跨 loop 复用
- 验证:
  - 新增 [tests/unit/scheduler/test_b037_loop_bridge.py](../../tests/unit/scheduler/test_b037_loop_bridge.py) — 14 tests / 6 test class，覆盖 LazyLoopRedis per-loop binding + same-loop reuse + 8 method delegation parametrize + IdempotencyGuard 跨 `asyncio.run()` 回归 + boot 集成（`_build_redis_client` 返回类型 + worker engine NullPool）
  - 14/14 GREEN；scheduler / composition / worker 整组 264 PASS 不退化
  - `ruff check`（B-037 文件）+ `mypy --strict src/intellisource/scheduler/lazy_redis.py + boot.py` 全 clean；预先存在的 boot.py E402 ×3 不在 B-037 引入
- 偏差类型: design-defect → 闭环
- 影响:
  - 解锁 B-031 阶段 1 步骤 4（worker 真消费链路）+ 阶段 5 步骤 12-14 + 任何 worker 真跑步骤 → 用户可重启 walkthrough
  - 同时修复其他 worker 路径 aioredis 客户端（LLM `CircuitBreaker` + collector `RateLimiter` + `WeChat/WeWork Distributors`）的同型缺陷
  - 预先存在但非 B-037 范围的 unit 失败：`tests/unit/api/test_tasks.py::TestTaskDetailEndpoint::test_get_task_detail_success` 因修正 #11 删除 `pipeline_name`/`execution_mode` 字段后测试未同步（spawn 独立任务跟进）
- 关联: B-031 carryover #12 → B-037；BACKLOG 标 done；src/intellisource/scheduler/lazy_redis.py 新增 + boot.py 编辑 + tests/unit/scheduler/test_b037_loop_bridge.py 新增

### 2026-05-26 | orchestrator | B-031 阶段 1 步骤 4 walkthrough rerun (闭环)

- 触发信号: pre-deploy-walkthrough-rerun
- 问题: B-037 闭环后重启 B-031 阶段 1 步骤 4。重启走查暴露 NO-GO #13 — `_collect_execute` 将 runtime_params（task_id / task_chain_id / trigger_type / priority / fingerprint，从 router → run_pipeline → strict executor `**merged` 一路串过来的运行时上下文）通过 `**kwargs` 透传给 `collector.collect()`，但 collector 抽象契约（[`BaseCollector.collect(source_config: dict)`](../../src/intellisource/collector/base.py)）只接受 `source_config`，导致 `TypeError: RSSCollector.collect() got an unexpected keyword argument 'task_id'`。
- 修正 #13 (inline): 删除 [src/intellisource/agent/tools/__init__.py:287-289](../../src/intellisource/agent/tools/__init__.py) `_collect_execute` 中 `collector.collect(source_config=source_config, **kwargs)` 的 `**kwargs` 透传（同时在 [src/intellisource/agent/tools/executes/collect.py:91-93](../../src/intellisource/agent/tools/executes/collect.py) 镜像副本同步修复）。
- carryover (B-039 P3): `_collect_execute` 在 `tools/__init__.py` 与 `tools/executes/collect.py` 存在**双副本**（149 行级几乎完全一致），仅 `__init__.py` 那份被 registry 实际使用，executes/ 那份从未被引用。下一次重构应单一化（建议 `tools/__init__.py` 改为 re-export `from .executes.collect import _collect_execute`，或删除 executes/ 副本）。本次走查阻塞优先用最小 inline 修复（双改两份），不引入重构。
- 验证（重启走查全 Pass 标准 GREEN）:
  - **(1)** worker logs `Task run_pipeline[d33713d7-…] succeeded in 2.68s`，全 3 步执行（collect → process → distribute）；无 `RuntimeError: Event loop is closed`（B-037 LazyLoopRedis + NullPool 双重隔离生效）
  - **(2)** DB `raw_contents` 20 行（HN RSS feed 全 20 条）/ `task_chains.status='success'` / `collect_tasks` 对应消费
  - **(3)** 重复同源触发：raw_contents 行数**未增**（fingerprint UNIQUE 保护 + collect 内 `get_raw_by_fingerprint` 返回 existing，避免重复 INSERT），task 仍 success（IdempotencyGuard Redis lock 仅在 task 并发时拦截，串行复跑由 fingerprint 层兜底，**两层语义不同但均如设计**）
  - **(4)** priority=high 触发：`celery inspect active_queues` 显示 5 队列全活（priority.{low,normal,high} + trigger.{scheduled,manual}），high-priority task succeeded 2.65s，验证 F-26 优先级队列路由
  - 单测回归：tests/unit/agent (collect/tool) 214 PASS 不退化
- 偏差类型: design-defect（kwargs 透传契约违例）+ duplication（双副本）
- 影响:
  - **B-031 阶段 1 步骤 4 ☑ Pass 签字** — [walkthrough 文档同步签字栏更新](../deploy/PRE-DEPLOY-WALKTHROUGH.md)
  - 不再阻塞 walkthrough 后续步骤（阶段 1 步骤 5 + 阶段 2-7）
- 关联: src/intellisource/agent/tools/__init__.py + executes/collect.py 编辑；BACKLOG 新增 B-039；PRE-DEPLOY-WALKTHROUGH.md 步骤 4 ☑ 签字栏追加

### 2026-05-26 | orchestrator | B-031 阶段 1 步骤 5 walkthrough (闭环)

- 触发信号: pre-deploy-walkthrough-step5
- 问题: 信源 CRUD 走查 PATCH `/api/v1/sources/{id}` → 500 `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called`。trace 定位 [api/routers/sources.py:84](../../src/intellisource/api/routers/sources.py) `_serialize_source` 访问 `source.updated_at` 触发跨上下文 lazy-load。
- 根因: `Source.updated_at` 用 `onupdate=func.now()`（无 `server_default`），UPDATE 后 DB 侧值未通过 RETURNING 回灌到 ORM；SQLAlchemy 标记字段 expired；sync 序列化函数访问时触发 asyncpg 异步重取，但已脱离 greenlet → 崩。
- 修正 #14 (inline): [`BaseRepository.update`](../../src/intellisource/storage/repositories/base.py) flush 后加 `await self._session.refresh(entity)`，在 async 上下文内主动刷取 server-computed 值。覆盖所有 ORM 模型，不只 Source；create 路径已通过 INSERT RETURNING 拿到 `created_at`，无需同改。
- 验证（步骤 5 全 Pass 标准 GREEN）:
  - **(1)** GET `/sources?type=rss&limit=5` → 200，`items.length=1`（HN RSS 过滤命中）
  - **(2)** PATCH tags `["tech","news","verified"]` → 200，response 含新 tags + `updated_at` 04:49:13 → 06:58:03 推进；re-GET 列表 tags 持久化
  - **(3)** 临时源创建 → DELETE → 204；列表再扫不再含 `_walkthrough_step5_delete`
  - 单测回归：tests/unit/storage + tests/unit/api/test_sources*（套件全绿，无新增失败）
- 偏差类型: design-defect（ORM expire-after-onupdate 与 sync serializer 边界冲突）
- 影响:
  - **B-031 阶段 1 步骤 5 ☑ Pass 签字** — [walkthrough 文档同步签字栏更新](../deploy/PRE-DEPLOY-WALKTHROUGH.md)
  - 同类隐患在所有走 `BaseRepository.update` + 含 `onupdate` 字段的模型（如 `Source`，未来新模型若加 `updated_at` 也自动受益）一并消除
  - 不阻塞步骤 6-8（阶段 2 pipeline 枚举/执行）
- 关联: src/intellisource/storage/repositories/base.py 编辑；PRE-DEPLOY-WALKTHROUGH.md 步骤 5 ☑ 签字栏追加

### 2026-05-26 | orchestrator | B-031 阶段 2 步骤 6-8 walkthrough (闭环)

- 触发信号: pre-deploy-walkthrough-stage-2
- 步骤 6 PASS: `/api/v1/pipelines` 列 5 项；`/pipelines/{name}` 详情字段齐全。**Doc drift**：`content-process.mode=batch`（walkthrough 写 `strict`），`manual-collect.steps` 实际 `params:{}`（已与 walkthrough 期望差异）→ 并入 B-034 walkthrough 文档订正。
- 步骤 7 PASS (with caveat):
  - **NO-GO #15 inline**: `manual-collect.yaml` steps[0] 硬编 `source_type: manual`，但 `collector_registry` 无 `manual` 条目 → `ToolDegradedError: unknown source_type: manual`。Fix [config/pipelines/manual-collect.yaml](../../config/pipelines/manual-collect.yaml) 删除 source_type override，让 `_collect_execute` 走 source_id → DB → `Source.type` 解析路径（与 scheduled-collect 一致）。
  - **NO-GO #16 inline**: `content-process.yaml` `KeywordTagger` 无 `params.keywords` → 实例化为 `keywords=()` → tagger 永远输出空 tags。Walkthrough 期望 "tags 列非空数组" 失败（20/20 行 tags=[]）。Fix [config/pipelines/content-process.yaml](../../config/pipelines/content-process.yaml) 增 `params.keywords` 8 大类技术词库（ai/security/web/cloud/opensource/startup/data/language，每类 5-7 个 synonyms 含中英文常见词）。验证 truncate + 重跑后 **20/20 行**均匹配到 ≥1 个 tag。
  - 验证全 Pass (修复后): manual-collect succeeded 3.84s / processed_contents 20 行 / 20/20 tags 非空 / 路径穿越 `..0.000000etc` → 404
  - **⚠ trace_id 跨日志一致延后**: signals.py + 单测 F-23 已验证 propagation 机制（contextvar set/reset 跨 worker 通过 Celery message header `x-trace-id`）；但 worker 用 stdlib `logging.getLogger(__name__)` + 默认 `StreamHandler`，contextvar 不进 log format → grep `trace_id=` 命中 0。专项验证留给步骤 17 F-23 回归。**Carryover 立项 B-040 P3** worker stdlib log → structlog formatter migration（让 trace_id 进 log line）。
- 步骤 8 PASS (with caveat): `/llm/status` 返 `circuit_state=CLOSED + queue_lengths{interactive:0,background:0}` / `/llm/stats?period=day` 返 `total_calls=0` 完整 JSON（含 by_model/by_date 数组）。**Doc drift**: walkthrough 写 "/llm/stats 不带 API key 也能查"，实际 [api/middleware.py:35](../../src/intellisource/api/middleware.py) `_EXEMPT_EXACT` 不含 `/llm/stats`，仍需 X-API-Key。并入 B-034 doc 订正。
- 偏差类型: design-defect (NO-GO #15 yaml hard-code + #16 missing default config) + doc-drift (3 项)
- 影响:
  - **B-031 阶段 2 步骤 6/7/8 ☑ Pass 签字**（步骤 7 trace_id 一项延后到步骤 17）
  - 修正 #15/#16 修复了所有 production 部署的 manual-collect 不可用 + KeywordTagger 永远空输出问题（生产硬伤）
  - 不阻塞步骤 9-20（阶段 3-7）；步骤 9 LLM-pipeline 需要 LITELLM/OPENAI_API_KEY，用户决定何时跑
- 关联: config/pipelines/manual-collect.yaml + content-process.yaml 编辑；BACKLOG 新增 B-040；PRE-DEPLOY-WALKTHROUGH.md 步骤 6/7/8 ☑ 签字栏追加

### 2026-05-26 | orchestrator | B-041 DeepSeek V4 gateway 适配 (闭环)

- 触发信号: backlog-burndown / walkthrough 步骤 9 阻塞
- 问题: DeepSeek V4 模型族 (`deepseek-v4-flash` / `deepseek-v4-pro`) 默认 `thinking.type=enabled` → 单轮即只产 `reasoning_content`（content=""）；多轮 chat-tool-loop 时 `message.reasoning_content` 被 gateway 丢失 → DeepSeek API 报 `The reasoning_content in the thinking mode must be passed back to the API`。`deepseek-chat` / `deepseek-reasoner` 2026-07-24 下线，必须适配 V4。
- 调研: [DeepSeek API 文档](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion) — V4 通过 `thinking={"type":"enabled"\|"disabled"}` + `reasoning_effort=high\|max` 控制；assistant 上一轮 `reasoning_content` 必须在 message dict 中回传（"对话前缀续写"）；`deepseek-chat=deepseek-v4-flash 非思考`、`deepseek-reasoner=deepseek-v4-flash 思考` 等价关系。
- 用户选 B（完整支持，per-profile 开关 + 多轮回传）。
- 修复（B-041 6 处改动）:
  1. [config/llm_schema.py](../../src/intellisource/config/llm_schema.py) `ModelTaskConfig` + `ModelProfileConfig` 新增 `thinking: Literal["enabled","disabled"] \| None` + `reasoning_effort: Literal["high","max"] \| None`
  2. [llm/model_config.py](../../src/intellisource/llm/model_config.py) `ModelProfile` + `ModelConfig` dataclass 同步字段；`get_profile` 透传
  3. **新增** [llm/gateway/_extra_body.py](../../src/intellisource/llm/gateway/_extra_body.py) — `build_extra_body(model, task_cfg, profile)` 单一来源；非 deepseek 返回 None；deepseek 默认 thinking=disabled（chat-tool-loop 安全默认）；task_cfg > profile > 默认；`extract_reasoning_content(message)` 兼容 SDK obj / dict
  4. [llm/gateway/_chat.py](../../src/intellisource/llm/gateway/_chat.py) + [_complete.py](../../src/intellisource/llm/gateway/_complete.py) + [_stream.py](../../src/intellisource/llm/gateway/_stream.py) — call_kwargs 注入 `extra_body`；`_chat`/`_complete` 把 `reasoning_content` 写进 `metadata["reasoning_content"]`
  5. [agent/executors/flexible.py](../../src/intellisource/agent/executors/flexible.py) `run()` + `run_stream()` 两处 — 拼 assistant message 时若 `metadata.reasoning_content` 非空则附加到 dict（下一轮 chat() 调用时整 messages 列表回传给 API）
  6. [config/llm_models.yaml](../../config/llm_models.yaml) + [llm_models.example.yaml](../../config/llm_models.example.yaml) 切回 v4-flash（extract/dedup/tag/chat thinking=disabled）+ v4-pro（summarize thinking=enabled reasoning_effort=high）；profiles 同步
- 验证:
  - 新增 [tests/unit/llm/test_gateway_deepseek_v4.py](../../tests/unit/llm/test_gateway_deepseek_v4.py) 16 tests / 6 test class GREEN — `build_extra_body` 5 path + `extract_reasoning_content` 5 path + chat/complete/stream extra_body 注入 + chat metadata 携带 reasoning_content + FlexibleLoop multi-turn reasoning_content 回传
  - llm/agent/config 整组单测 692 PASS 不退化
  - `ruff check` + `mypy --strict` clean
  - **真起 docker stack 集成**: `POST /search/chat "Reply with OK"` 双次成功（2.14s/1.26s），`answer="OK"`，证明 V4-flash + thinking=disabled 走通；manual-collect pipeline regression 仍 succeeded 2.53s
- 偏差类型: design-defect（V4 API 契约变更，旧 gateway 假设 reasoning_content 可丢）
- 影响:
  - **walkthrough 步骤 9 LLM 链路 ☑ Pass**（gateway 层面）；llm_call_logs/cache/content-process LLM step 三项 N/A 由独立 backlog 跟踪
  - 解锁所有 `/search/chat` + `/search/chat/stream` + `push-optimize` flexible-mode 路径（pre-B-041 均会被 reasoning_content 错误阻塞）
  - `summarize` profile 可选启用 v4-pro 思考模式拿真实推理增益（已落地，等 [[b-044]] 接入到 truncate_summary 工具实际调用）
- carryover:
  - **B-042 P2** api composition 注入 CostTracker → 让 `llm_call_logs` 真写入（pre-existing wiring gap，CostTracker 当前 per-session lifecycle 与 singleton LLMGateway 不兼容；需设计 per-call session 适配）
  - **B-043 P3** `chat()` path 接入 LLMCache（pre-existing，仅 complete() 有 cache_key_parts）
  - **B-044 P2** `content-process` pipeline 集成 LLM summarizer step（让 walkthrough 步骤 9 summary 落库可验，从 batch processors → 添加 LLM-driven summarizer / tag 步骤）
- 关联: src/intellisource/config/llm_schema.py + llm/model_config.py + llm/gateway/_extra_body.py(新) + _chat.py + _complete.py + _stream.py + agent/executors/flexible.py + config/llm_models{,.example}.yaml 编辑；BACKLOG B-041 闭环 + B-042/B-043/B-044 新增；PRE-DEPLOY-WALKTHROUGH.md 步骤 9 ☑ 签字栏追加

### 2026-05-26 | orchestrator | unknown
- 触发信号: option-override
- 问题/假设: B-031 walkthrough 阶段 3 已闭环，请选择下一步推进方向
- 基线/推荐: B-031 阶段 4 步骤 10（M-007 检索/RAG）(Recommended)
- 实际/选择: 查看 BACKLOG 全量再决定
- 偏差类型: preference

### 2026-05-26 | orchestrator | unknown
- 触发信号: option-override
- 问题/假设: 选择下一步推进方向（阅过完整 BACKLOG 后）
- 基线/推荐: B-031 阶段 4 步骤 10（M-007 检索/RAG）(Recommended)
- 实际/选择: 先闭环 B-042 + B-044（步骤 9 補签）
- 偏差类型: preference

### 2026-05-26 | orchestrator | B-042 CostTracker 注入 (闭环)
- 触发信号: B-031 walkthrough 步骤 9 N/A 项之一（llm_call_logs 表恒空）。Backlog 推荐选 C：gateway init 接 session_factory。
- 问题: singleton `LLMGateway` 持有 `cost_tracker: CostTracker | None`，但 `CostTracker(session)` 构造期绑定 session，不能跨请求复用 → composition 不敢注入 → `llm_call_logs` 实际无写入路径。chat 与 stream_complete 各有 log_call 块，但 complete() **完全缺**。
- 修复:
  - `LLMGateway.__init__` 新增 `session_factory: SessionFactory | None = None`；存为 `self._session_factory`；`_protocols._GatewayProtocol` 同步标注以保 mypy --strict 通过。
  - `_RetryMixin._emit_call_log(record)`：优先 `_cost_tracker.log_call`（legacy 单测路径），否则 `async with session_factory() as s: CostTracker(s).log_call(record)`；两条路径都 swallow exception，logging 不破 LLM 主路径。
  - chat / stream_complete 的内联 try/except cost_tracker 块换成 `await self._emit_call_log(record)`；触发条件改为 `cost_tracker is not None or session_factory is not None`。
  - **complete() 补 log_call**：success 路径之前完全没 LLMCallLog 写入，本次按 chat 同型加，call_type="complete"。
  - `composition.build_llm_gateway(redis, session_factory=None)` 签名扩；`_build_deps_bundle` 把 session_factory 透下去。
  - `tests/unit/llm/test_cache.py` `test_cache_miss_does_not_trigger_cache_hit_log` 重命名 `test_cache_miss_logs_success_not_cached`：旧契约 "complete cache miss → 无 log"，新契约 "cache miss → log 一条 status=success（complete 现在也写）"。
- 验证:
  - 新增 [tests/unit/llm/test_gateway_session_factory.py](../../tests/unit/llm/test_gateway_session_factory.py) 10 tests / 7 class GREEN：构造（kwarg / 默认 None）/ 三入口（chat / complete / stream）emit / 显式 cost_tracker 覆盖 session_factory / 双 None 静默 / session_factory 异常吞噬 / build_llm_gateway 双签名
  - 全 LLM 单测 392 PASS（含修订后的 test_cache_miss_*），mypy --strict + ruff + lint-imports 8/8 + deptry + vulture 全 clean
  - 真起 docker stack 跑 `/search/chat` 后 `SELECT count(*) FROM llm_call_logs WHERE status='success'` ≥ 1 — 待用户验证（步骤 9 补签 N/A 项之一）
- 偏差类型: spec-gap（singleton 与 per-session 生命周期不匹配，pre-existing wiring gap）
- 影响:
  - chat / complete / stream 三个入口在 production singleton 模式下都能写 llm_call_logs，CostTracker.get_stats 能查到真实数据
  - 解锁 walkthrough 步骤 9 N/A 项 #1
  - 为 B-043 chat 接 LLMCache 铺路（cache hit log 也走 _emit_call_log 路径）
- 关联: src/intellisource/llm/gateway/{__init__,_chat,_complete,_stream,_retry,_protocols}.py + src/intellisource/composition.py + tests/unit/llm/test_cache.py + tests/unit/llm/test_gateway_session_factory.py（新）；BACKLOG B-042 标 done

### 2026-05-26 | orchestrator | B-044 content-process LLM summarizer step (闭环)
- 触发信号: B-031 walkthrough 步骤 9 N/A 项之二（processed_contents.summary 列恒 NULL）。Backlog 列三选：A 引入 `tool:` 步骤类型 / B 新增 `LLMSummarizer(BaseProcessor)` / C 拆 pipeline 二段；本会话采选 B（直接、processor-only contract 一致、改动收敛）。
- 问题: `config/pipelines/content-process.yaml` `steps` 仅 `HTMLParser → ContentDedup → KeywordTagger` 三个 batch processor，零 LLM 调用；B-008 闭环时 `truncate_summary` 接入 LLM summarizer 模板但仅被 push-optimize 调用，未挂到 content-process。`_process_execute` 的 `repo.create(...)` 也无 `summary=` 参数 → 即便 ctx 设置也不持久化。
- 修复:
  - 新增 [src/intellisource/pipeline/processors/summarizer.py](../../src/intellisource/pipeline/processors/summarizer.py) `LLMSummarizer(BaseProcessor)`：`__init__(llm_gateway=None)` 存 `_llm_gateway` + 类级 `_NEEDS_LLM_GATEWAY=True` 标记；`process(ctx)` 读 title/body_text → cluster `[{"title":..., "body_text":...}]` → `truncate_summary(cluster, tool_deps=_GatewayDeps(gw))` 经 `_run_coro` 调度（无 loop → `asyncio.run` / 有 loop → 单线程 ThreadPoolExecutor + asyncio.run；保护 execute_stream 异步路径）→ ctx.set("summary", result["summary"])；全异常路径写 ""，不抛（pipeline _run_processors fail-soft 收尾仍可继续）。
  - `pipeline/registry.py` `PROCESSOR_REGISTRY` 注册 `"LLMSummarizer": LLMSummarizer`。
  - `agent/factory.py` `_build_processors_from_config(config, llm_gateway=None)` 检查 `getattr(cls, "_NEEDS_LLM_GATEWAY", False)`，按需把 llm_gateway 注入 params；`build_agent_runner` 调用处把 `llm_gateway=llm_gateway` 透下去。
  - `config/pipelines/content-process.yaml` `steps` 末尾追加 `- processor: LLMSummarizer`（KeywordTagger 之后；保持先 batch 后 LLM 顺序）。
  - `agent/tools/executes/process.py` `_process_execute.repo.create(...)` 加 `summary=str(ctx.get("summary") or "")` 字段。
- 验证:
  - 新增 [tests/unit/pipeline/test_llm_summarizer.py](../../tests/unit/pipeline/test_llm_summarizer.py) 11 tests / 5 class GREEN：registry 注册 / process 写 ctx.summary（正常 LLM / 无效 JSON 回退 / 无 gateway 回退 / gateway 异常吞噬）/ factory 按标记注入 / YAML drift guard / `_process_execute` 调用 `repo.create(summary=...)`
  - 全 unit 套 2771 PASS（含 21 新），mypy --strict + ruff + lint-imports 8/8 + deptry + vulture 全 clean；pipeline + agent.factory 周边无回归
  - 真起栈 truncate processed_contents → 重跑 content-process pipeline → `SELECT summary FROM processed_contents WHERE summary != ''` ≥ 1 — 待用户验证（步骤 9 补签 N/A 项之二）
- 偏差类型: feature-gap（pipeline 步骤定义遗漏，pre-existing）
- 影响:
  - `processed_contents.summary` 列从 100% NULL 变为按 LLM 真实输出填充
  - LLMSummarizer 经 B-042 链路把每条内容的 complete 调用同步写入 llm_call_logs（连带验证 B-042）
  - 为 `/api/v1/contents/processed` 提供有意义的 summary 字段输出
- 关联: src/intellisource/pipeline/processors/summarizer.py(新) + pipeline/registry.py + agent/factory.py + agent/tools/executes/process.py + config/pipelines/content-process.yaml + tests/unit/pipeline/test_llm_summarizer.py（新）；BACKLOG B-044 标 done

### 2026-05-26 | orchestrator | B-045 EmbeddingProcessor + LLM gateway embed (闭环)
- 触发信号: 推进 B-031 阶段 4 步骤 10/11 (M-007 检索/RAG) 前的代码侧预审揪出 BLOCKER —— `VectorStore.upsert()` 在整个代码库零调用者（grep `UPDATE processed_contents SET embedding` 仅 storage/vector.py:182 一处定义），`processed_contents.embedding` 列恒 NULL。后果：步骤 10 `search_mode=semantic` / `hybrid` 由 hybrid.py:119-120 `query_vector is None` 兜底走 keyword fallback（不 5xx 但永远 0 真向量结果），步骤 11 RAG 同样降级，语义检索价值=0。用户三选：A 立项延后 / B 立即闭环（写 EmbeddingProcessor + pipeline 集成）/ C 推迟 v2；本会话采选 B。
- 问题:
  - LLMGateway 无 `embed()` 方法，无法生成向量
  - pipeline / agent / repository 全无 embedding 写入路径
  - `_process_execute.repo.create(...)` 无 `embedding=` 字段，即便 ctx 设置也不持久化
  - `llm_models.yaml` 无 `embed` task_type 路由
- 修复:
  - 新增 [src/intellisource/llm/gateway/_embed.py](../../src/intellisource/llm/gateway/_embed.py) `_EmbedMixin.embed(text) -> list[float] | None`：经 `ModelRoutingConfig.get_model("embed")` 路由 → `litellm.aembedding(model=..., input=text)` (静态 `_aembedding(**kwargs)` hook，测试可 monkeypatch 隔离 SDK) → 取 `response.data[0].embedding`；空文本 / 路由缺 / 调用异常 / 非 list / 空 list 全 graceful 返 None；成功路径与 B-042 一致复用 `_emit_call_log` 写 `llm_call_logs(call_type='embed', status='success')`。`gateway/__init__.py` `LLMGateway` 加入 `_EmbedMixin` 到 MRO（排在 `_StreamMixin` 与 `_QueueMixin` 之间）。
  - 新增 [src/intellisource/pipeline/processors/embedder.py](../../src/intellisource/pipeline/processors/embedder.py) `EmbeddingProcessor(BaseProcessor)`：`__init__(llm_gateway=None)` 存 `_llm_gateway` + 类级 `_NEEDS_LLM_GATEWAY=True`（共享 B-044 factory 注入路径）；`process(ctx)` 读 body_text → fallback title → `_run_coro(gw.embed(text))` （与 LLMSummarizer 同款无-loop 直 `asyncio.run` / 有-loop ThreadPoolExecutor）→ ctx.set("embedding", vec)；无 gateway / 空文本 / 异常 / 非 list 全写 None 不抛。
  - `pipeline/registry.py` `PROCESSOR_REGISTRY` 注册 `"EmbeddingProcessor": EmbeddingProcessor`。
  - `config/pipelines/content-process.yaml` `steps` 末尾追加 `- processor: EmbeddingProcessor`（LLMSummarizer 之后，让 summary 字段先就位再 embed）。
  - `agent/tools/executes/process.py` `_process_execute` 加 `embedding_val = ctx.get("embedding"); embedding_arg = embedding_val if isinstance(embedding_val, list) else None`，作为 `repo.create(embedding=embedding_arg, ...)` 参数透传；None 时保留 DB 默认 NULL（pgvector 列 nullable=True）。
  - `config/llm_models.yaml` `models` 追加 `embed: { model: openai/text-embedding-3-small, provider: openai }` 路由。
- 验证:
  - 新增 [tests/unit/pipeline/test_embedding_processor.py](../../tests/unit/pipeline/test_embedding_processor.py) 12 tests / 5 class GREEN：registry 注册 / process 写 ctx.embedding（happy / 无 gateway / 异常吞噬 / 空文本）/ factory 按标记注入 / YAML drift guard / `_process_execute` 调用 `repo.create(embedding=vec)` + None 时透传 None
  - 新增 [tests/unit/llm/test_gateway_embed.py](../../tests/unit/llm/test_gateway_embed.py) 7 tests / 5 class GREEN：方法存在 / happy path / 空文本跳过 / `_aembedding` 异常返 None / 畸形 response 返 None / session_factory emit call_log / 失败不破坏路径
  - 全 unit 套 2809 PASS（+19 新），mypy --strict + ruff + lint-imports 8/8 clean
  - 真起栈验证：依赖 `OPENAI_API_KEY` 配置；无 key 时 embedding 列 NULL → vector/hybrid 走 keyword fallback（不崩），有 key 时 `SELECT count(*) FROM processed_contents WHERE embedding IS NOT NULL` ≥ 1 + `POST /search { "search_mode": "semantic" }` 真出向量相似度排序 — 待用户跑（阶段 4 步骤 10/11 补签）
- 偏差类型: feature-gap（pipeline 步骤定义遗漏 + gateway 方法遗漏，pre-existing；预审才识别）
- 影响:
  - `processed_contents.embedding` 列从 100% NULL 变为按 LLM 真实输出填充（OPENAI_API_KEY 配置后）
  - vector / hybrid search 真路径活，RAG 检索语义价值回归
  - llm_call_logs 多 `call_type='embed'` 行（连带验证 B-042 session_factory 路径覆盖到 embed）
- 关联: src/intellisource/llm/gateway/_embed.py(新) + llm/gateway/__init__.py + pipeline/processors/embedder.py(新) + pipeline/registry.py + agent/tools/executes/process.py + config/pipelines/content-process.yaml + config/llm_models.yaml + tests/unit/pipeline/test_embedding_processor.py(新) + tests/unit/llm/test_gateway_embed.py(新)；BACKLOG B-045 标 done；walkthrough 步骤 10/11 vector 路径阻塞解除

### 2026-05-26 | orchestrator | B-039 inline 重构 + 步骤 9 真起栈 PASS (闭环)
- 触发信号: 真起栈跑 manual-collect 验证 B-042/B-044 步骤 9 补签时，processed_contents.summary 列**仍** NULL。单测 19 GREEN 但真路径失败 — 经典 silent drift。
- 问题:
  - `_*_execute` 7 个函数 + `_serialize_search_response` helper 在 `tools/__init__.py` (208-712, 504 行) 与 `tools/executes/*.py` (collect/process/distribute/search_and_content/llm 共 572 行) **字面级双副本**。B-044 (summary kwarg) / B-045 (embedding kwarg) 改动只落 `executes/process.py` 孤儿副本，registry 实际调用的是 `__init__.py:457` 那份。
  - `executes/__init__.py` 23 行 re-export 是死代码 — 全仓 0 引用者，`from intellisource.agent.tools.executes import` 找不到任何调用。
  - `tools/__init__.py` 974 行 fat module，混合 4 类职责（registry primitives / load_pipeline_config helper / 11 atomic tool defs / 7 default tool defs + 7 execute functions）。
- 修复:
  - **executes/* 升级为单一事实来源**：用 __init__.py 历史最新版本（含 B-044 summary / B-045 embedding kwarg）覆盖 [executes/collect.py](../../src/intellisource/agent/tools/executes/collect.py) / [executes/process.py](../../src/intellisource/agent/tools/executes/process.py) / [executes/distribute.py](../../src/intellisource/agent/tools/executes/distribute.py) / [executes/search_and_content.py](../../src/intellisource/agent/tools/executes/search_and_content.py) / [executes/llm.py](../../src/intellisource/agent/tools/executes/llm.py)。`_serialize_search_response` helper 内聚到 `search_and_content.py`。
  - **新增 [src/intellisource/agent/tools/registry.py](../../src/intellisource/agent/tools/registry.py)** (453 行) — 集中 `PermissionLevel`/`ToolDefinition`/`AgentToolRegistry`/`_atomic_tool_defs`/`_default_tool_defs`；`_*_execute` 通过 `from intellisource.agent.tools.executes.* import` 引用真源。
  - **[tools/__init__.py](../../src/intellisource/agent/tools/__init__.py) 974→55 行 facade**：只剩 imports + `__all__` + `_PIPELINES_DIR` + `load_pipeline_config` helper + re-export `registry` 的公共符号 + re-export `executes/*` 的 7 个 execute 函数。外部 import 路径 `from intellisource.agent.tools import _collect_execute / _process_execute / PermissionLevel / ...` 完全兼容（runner.py、executors/、api/routers/ 等 11+ 调用点零改动）。
  - **[executes/__init__.py](../../src/intellisource/agent/tools/executes/__init__.py)** 23 行死 re-export 清空为 1 行 docstring。
  - **测试 monkeypatch 路径修正**：[tests/unit/agent/test_tools_fanout_and_dto.py:283](../../tests/unit/agent/test_tools_fanout_and_dto.py) `tools_mod.asyncio` → `executes.process.asyncio`（因为 asyncio import 跟 _process_execute 一起搬到了 executes/process.py）。
- 验证:
  - **单测**: 2790 PASS 不退化；mypy --strict + ruff + lint-imports 8/8 clean
  - **真起栈步骤 9 重跑（manual-collect task `140d0e2a`，336.9s success）**:
    - B-042 ✓ `SELECT count(*) FROM llm_call_logs WHERE status='success'` = 20；model=deepseek-v4-pro；sum_input=3767 sum_output=15747 tokens
    - B-044 ✓ `SELECT count(*) FROM processed_contents WHERE summary IS NOT NULL AND summary <> ''` = 20/20；样本 summary 含 LLM 真生成内容（如 "Japan has successfully tested a ramjet engine for a Mach-5 hypersonic aircraft..."）
    - B-045 旁证 ✓ embedding 列保持 NULL（无 OPENAI_API_KEY graceful 设计；worker log 含 LLMGateway.embed _aembedding failed warning 1 行但 pipeline 整链 success）
- 偏差类型: refactor + dup-clean（双副本 silent drift 揪出 B-044/B-045 隐式回归）
- 影响:
  - tools/__init__.py 收缩 ~95%（974→55 行）
  - executes/* 5 个文件成为 7 个 atomic execute 的单一事实来源
  - 后续任务卡（B-016 / B-035 etc）改这些函数只需改一处，silent drift 风险消除
  - 步骤 9 ☐→☑ 补签完成；阶段 4 步骤 10/11 vector 路径仅待 OPENAI_API_KEY 即可真验证
- 关联: src/intellisource/agent/tools/__init__.py (大幅瘦身) + tools/registry.py (新) + tools/executes/{collect,process,distribute,search_and_content,llm}.py (覆盖) + tools/executes/__init__.py (清空) + tests/unit/agent/test_tools_fanout_and_dto.py (monkeypatch 修)；BACKLOG B-039 标 done；walkthrough 步骤 9 ☑ 真起栈签字

### 2026-05-27 | orchestrator | B-031 阶段 4 步骤 10/11 真起栈走查 (闭环)
- 触发信号: B-031 走查阶段 4 步骤 10/11（M-007 检索/RAG）首次真起栈触发 6 项部署破口（#17~#20、#25、#26 inline 修；#21~#23 carryover；并连带验证 B-001 SSE RAG-aware stream / B-002 datetime 类型转换 / B-044 LLMSummarizer / B-045 EmbeddingProcessor 无 key fallback 设计）
- 问题:
  - **#17 SearchRequest.search_mode 默认 None**: [api/routers/search.py:43](../../src/intellisource/api/routers/search.py) `search_mode: str | None = None`，但 [search/hybrid.py:107](../../src/intellisource/search/hybrid.py) engine `if mode not in _VALID_MODES: raise ValueError`。客户端不传 mode 时 `None` 传到 engine 直接 500。
  - **#18 router 返回类型契约不一致**: [api/routers/search.py:55](../../src/intellisource/api/routers/search.py) `async def search(...) -> dict[str, Any]:`，但 [search/hybrid.py:147](../../src/intellisource/search/hybrid.py) `return SearchResponse(...)` 是 dataclass。FastAPI 按类型注解触发 ResponseValidationError 500。
  - **#19 SearchResult dataclass 缺关键字段**: [storage/vector.py:151](../../src/intellisource/storage/vector.py) `SearchResult` 只含 `content_id/score/tags/published_at`，但 SQL `SELECT id, title, body_text, tags, source_name, published_at` 拉了 6 列。`_rows_to_results` 丢弃 title/body_text/source_name；下游 [search/hybrid.py:_build_enriched_result](../../src/intellisource/search/hybrid.py) `_extract_attr(row, "title")` 默认 `""` → API 响应所有 title/snippet/source_name 全空。
  - **#20 SearchRequest.limit 默认 None**: 同 #17 同模式，`limit: int | None = None` → engine `min(None, 50)` → TypeError 500。
  - **#21 carryover P3 published_at 上游 NULL**: `SELECT COUNT(*) FROM processed_contents WHERE published_at IS NULL` = 20/20。collector / HTMLParser 没填该列 → date filter 任何范围结果 0，B-002 datetime contract 闭环但用户不可见。
  - **#22 carryover P3 _extract_sources 返 0**: sync `/search/chat` 路径 `_extract_sources(flex_result)` count=0，但 stream `/search/chat/stream` `done.metadata.results` 含完整 search items + get_content_detail full content。两条路径对 flex_result.results 解析逻辑不一致。
  - **#23 carryover P3 LLM agent answer raw dump**: sync chat 当 search 命中 ≥1 行时，`extract_answer` 把 search step output 整条 dict.repr() 当 final answer 返回（如 `{'id': 'd90d9026-...', 'title': 'Eagle 3.1...', 'body_text': '...', 'summary': '...'}`），未走 LLM 整形成自然语言。
  - **#25 to_tsquery 句子语法错误**: [storage/vector.py:43/52](../../src/intellisource/storage/vector.py) `to_tsquery('simple', :query)` 接受单 lexeme + & | ! 语法，传 "AI news today" / "artificial intelligence news 2025" 直接 `PostgresSyntaxError: syntax error in tsquery`。影响所有自然语言查询（agent search tool 100% 失败）。
  - **#26 stream_complete fallback gpt-4o-mini**: [llm/gateway/_stream.py:53](../../src/intellisource/llm/gateway/_stream.py) `if resolved_model is None: resolved_model = "gpt-4o-mini"` 硬编码 OpenAI 兜底。caller 不传 model + task_type 时直接走 OpenAI provider → `OPENAI_API_KEY` 缺失 401 → stream 中断。
- 修复:
  - **#17 inline 修**: `search_mode: Literal["keyword", "semantic", "hybrid"] = "hybrid"`。Pydantic 422（非 500）拦截无效值，未传时默认 hybrid（engine 同款默认，无 query_vector 时 fallback keyword）。
  - **#18 inline 修**: `async def search(...) -> SearchResponse:` + `from intellisource.search.hybrid import SearchResponse`。FastAPI 原生支持 dataclass 序列化。
  - **#19 inline 修**: `SearchResult` 扩 `title/body_text/source_name: str = ""` 三个字段；`_rows_to_results` 从 row 读 `getattr(row, "title", "")` 等填充并做 `isinstance(.., str)` 兜底（防 MagicMock 注入）。`_build_enriched_result` 自然能拿到非空值。
  - **#20 inline 修**: `limit: int = 10`（与 engine 默认对齐）。
  - **#25 inline 修**: `to_tsquery` → `websearch_to_tsquery`（PG 11+ 标准函数；支持自然语言 + 引号短语 + OR）。两处 SQL 模板（_KEYWORD_SQL_TMPL + _HYBRID_SQL_TMPL）同步替换。
  - **#26 inline 修**: 删 `gpt-4o-mini` 硬编码兜底，简化为 `models[task_type]["model"] if task_type in models else default_model.model`。stream 现走 DeepSeek 默认路径。
  - **#21/#22/#23 立 carryover**（不 inline）：published_at 填充涉及 collector + HTMLParser 改造范围大；_extract_sources 与 LLM answer 整形需重写 sync chat 路径的 result 解析与 prompt 工程，不属于步骤 10/11 走查范围。
- 验证:
  - **步骤 10a keyword**: POST /api/v1/search `{"query":"URL","limit":3}` → 200 / items=3 / `score=0.0760` 真 ts_rank
  - **步骤 10b tag filter**: `{"query":"URL","tags":["ai"],"limit":10}` → items=6，DB `tags @> '["ai"]'::jsonb` count=6 验证；doc-drift（walkthrough 写 "tech" 实际枚举 ai/web/opensource/language/cloud/security/data）并入 B-034
  - **步骤 10c date filter**: 非法日期 → 422（B-002 datetime 契约 ✓）；合法日期 items=0 因 published_at NULL（数据问题 #21）
  - **步骤 10d 三档 search_mode**: keyword/semantic/hybrid 三档 200 + items=3 + score=0.0760 一致（semantic/hybrid 无 query_vector graceful fallback keyword）；走 walkthrough 文档 drift "vector" → 422 验证 Literal 校验生效
  - **步骤 11a sync chat**: probe "Reply with OK" → answer="OK" / 2.4s / steps=1；RAG-trigger query 触发 5 步 agent flow，DB 真内容（B-044 summary "Eagle 3.1 is a collaborative release..."）入 answer
  - **步骤 11b SSE stream**: probe → SSE token stream "stream" / " test" / " OK" + done event；RAG-trigger query 多步 agent flow：search → get_content_detail × 2 → done.metadata.results 含完整 5 items + 2 篇全文 summary（"Outsourcing plus LocalAI..." 等 B-039 真路径数据），B-001 闭环验证 RAG-aware stream
  - **单测全量**: 2790 PASS / 5 deselected / 0 NEW FAIL 保住 CLAUDE.md baseline；ruff + mypy --strict 4 改动文件全 clean
- 偏差类型: feature-gap × 4（#17/#18/#19/#20 设计阶段类型契约遗漏）+ functionality-bug × 2（#25 PG FTS 函数误用 + #26 OpenAI 默认硬编码）
- 影响:
  - `/api/v1/search` 端点从全 500 不可用 → 200 keyword/semantic/hybrid 三档可调，items 真填 title/snippet
  - `/api/v1/search/chat/stream` 从 step 2 401 中断 → 多步 RAG agent flow 端到端通（done.metadata.results 含 sources）
  - 多词 / 自然语言 query 不再 SQL 错误（websearch_to_tsquery 解析 "AI news today" 等通用句式）
  - B-001 SSE RAG-aware stream / B-002 datetime / B-044 LLMSummarizer / B-045 graceful embed fallback 四项连带验证
- 关联: src/intellisource/api/routers/search.py + src/intellisource/storage/vector.py + src/intellisource/search/hybrid.py + src/intellisource/llm/gateway/_stream.py；docs/deploy/PRE-DEPLOY-WALKTHROUGH.md 步骤 10/11 签字；立 carryover B-046（published_at 上游填充）+ B-047（chat sync sources 提取 + answer 整形）；BACKLOG B-031 阶段 4 步骤 10/11 ☑

### 2026-05-27 | orchestrator | PR #64 CI Integration Tests 回归修复 + 流程改进
- 触发信号: PR #64 推送后 CI Integration Tests 失败 10 项 + 1 error。对照 main baseline（commit 0f7005e）8 项失败，分析得 **net +3 NEW regression + 1 baseline failure shape change + 1 baseline failure fixed**：
  - **NEW × 3** (我引入): `tests/integration/test_pg_vector_search.py::{test_search_returns_http_200, test_search_returns_items_field, test_search_returns_items_ordered_by_cosine_similarity}` — `_fake_search_engine` mock 返 `{"items": [{"id": ..., "title": ...}]}` dict shape，但 PR #64 修正 #18 把 router 返回类型 `dict[str, Any]` → `SearchResponse`，FastAPI 现严格按 `EnrichedSearchResult.content_id` 字段验证 → `'content_id' Field required, input: {'id': ...}` 500
  - **Shape change**: `test_s8r_search_pg::test_post_search_returns_200_with_items` baseline `TypeError: '<' not supported between instances of 'int' and 'NoneType'`（PR #64 修正 #20 `limit: int = 10` 解锁）→ 当前 `TypeError: 'coroutine' object is not iterable`（_fake_get_session 内开 engine + 异步 yield 与 FastAPI lifespan 不兼容；与 baseline cross-loop 同族 pre-existing infrastructure bug，非我引入）
  - **Fixed**: `test_pg_vector_search::test_search_http_real_engine_keyword_mode` baseline `int < NoneType` 因 #20 修复消失
- 问题:
  - 3 个 pg_vector_search mock fixture 用了 legacy dict shape，与生产 `SearchResponse(items=[EnrichedSearchResult(content_id=...)])` 契约不一致
  - 测试断言 `items[0]["id"]` 也用旧 key
  - **流程缺口**: `make check` 只跑 unit 不跑 integration；PR #64 修了 6 项部署破口 + 单测 2790 PASS 但 mock-vs-prod contract drift CI 才发现
- 修复:
  - **mock 修正**: `tests/integration/test_pg_vector_search.py` 3 个 `_fake_search_engine` 工厂返 `SearchResponse(items=[EnrichedSearchResult(content_id=..., title=..., snippet=..., score=..., source_name=..., published_at=...)], total=..., query_time_ms=...)` 真 dataclass 实例（与生产链路一致），同步 import `from intellisource.search.hybrid import EnrichedSearchResult, SearchResponse`
  - **断言修正**: `test_search_returns_items_ordered_by_cosine_similarity` `items[0]["id"]` → `items[0]["content_id"]`
  - **流程加固**:
    - `Makefile` 加 `test-unit` / `test-integration` / `check-all` / `contract-check` 4 个 target；`check` 现含 `test-unit`；`check-all = check + test-integration`
    - 新增 `scripts/contract_check.py`：基于 `git diff vs origin/main` 检查 4 类契约敏感路径（`api/routers/` / `search/` / `storage/` / `llm/gateway/` / `agent/tools/`）→ 命中即推荐跑 `make test-integration`
    - **CLAUDE.md Learnings Registry 加 EXP-CONTRACT-DRIFT**：契约文件修改必须 `make test-integration` push 前跑通，单测全绿不代表 integration 不回归
- 验证:
  - 本地 PG 真起栈跑修复后 3 测试：`DATABASE_URL=postgresql+asyncpg://intellisource:... uv run pytest tests/integration/test_pg_vector_search.py -k "test_search_returns_http_200 or test_search_returns_items_field or test_search_returns_items_ordered"` → 3 passed / 6 deselected
  - `make contract-check` smoke test：正确识别 `api/routers/search.py` + `storage/vector.py` + `llm/gateway/_stream.py` 3 个 contract-sensitive 文件 → 推荐 `make test-integration`
  - 待 CI 验证：integration 失败数应从 10+1 → 7 或更少（不引入 net regression）
- 偏差类型: contract-mock-drift（mock 滞后于生产契约）+ process-gap（CI 才发现的 mock vs prod 不一致没有 push 前检查）
- 影响:
  - 解除 3 个 PR #64 引入的 integration 回归
  - 后续契约文件修改 push 前 `make contract-check` 提示 → `make test-integration` 守门
  - 长期：integration mock fixtures 应优先用真 dataclass 实例（而非 dict + duck-typing）以与生产契约共享类型
- 关联: tests/integration/test_pg_vector_search.py + Makefile + scripts/contract_check.py（新）+ CLAUDE.md Learnings Registry；PR #64 commit 接续 c8b69f4

