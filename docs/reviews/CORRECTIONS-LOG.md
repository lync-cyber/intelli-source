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
