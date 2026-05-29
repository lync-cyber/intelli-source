---
id: backlog-intellisource-v1
doc_type: backlog
author: orchestrator
status: approved
deps: []
---

# IntelliSource v1 Backlog

> 维护：本文件梳理 PR #53 / #54 audit 闭环之后的剩余工作。完成项请直接删除条目，新增项按优先级插入。
> 最后更新：2026-05-29 (PR #72 ✅ 闭环 P3 功能项 B-043 / B-046 / B-047 / B-049 + B-011 弱断言批量强化；unit baseline 2948→2970 PASS @ main HEAD eff264e；CI 6/6 绿。另核对 B-015 ✅ 早已闭环 — promtool check rules 自 commit 9c118b8 起在 CI Lint job 运行，回填 closeout 标记)

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

### B-059 Celery broker/result-store 宕机时任务派发挂起（无 fast-fail）✅
- **优先级**：P1（HIGH — 生产稳定性风险）
- **关联**：B-031 阶段 7 步骤 20 真起栈走查暴露；[src/intellisource/scheduler/celery_app.py](../src/intellisource/scheduler/celery_app.py) / [src/intellisource/scheduler/dispatch.py](../src/intellisource/scheduler/dispatch.py) / [src/intellisource/api/routers/tasks.py](../src/intellisource/api/routers/tasks.py)
- **现状（修复前）**：redis 宕机时 `POST /api/v1/tasks/collect` → 客户端 **HTTP 000（>30s 挂起）**。**真起栈复测修正了根因**：阻塞主因不是 broker publish（已加 socket 超时后 ≈5s 抛 kombu OperationalError），而是 **Celery redis result 后端在派发期重连重试约 100s 后抛 `builtins.RuntimeError`**（"Retry limit exceeded while trying to reconnect to the Celery result store backend"）—— 该 RuntimeError 不属连接错误类型，原 broker-only 修复无法覆盖。非 redis 查询路径不受影响，`/health` 正确标 `checks.redis=unhealthy`+`celery=unhealthy`
- **修复（已落地）**：
  - `celery_app`：**broker + result-backend 双侧** `socket_connect_timeout`/`socket_timeout=5`；`redis_retry_on_timeout=False` + `result_backend_always_retry=False` + `result_backend_max_retries=0`（构造期设置，缓存后端生效）
  - `dispatch.send_task_with_trace`：`retry=False` + 包装 `(kombu OperationalError / redis ConnectionError / OSError)` → `BrokerUnavailableError`；安全网捕获后端重连耗尽的 `RuntimeError`（match "result store backend"/"reconnect"）
  - `tasks.collect`：捕获 `BrokerUnavailableError` → `HTTPException(503)`；`get_db_session` 异常回滚丢弃刚建的 `task_chain`+`task` 行（不留 orphan pending）
- **验证（真起栈复测 PASS）**：stop redis → collect **503/7.9s**（非 HTTP 000 挂起）+ 行数不变（回滚生效）；start redis → **202/0.04s** 自愈。14 新单测 GREEN（broker/backend config + 错误包装 + 503/rollback）；mypy --strict + ruff + lint-imports 8/8 clean。fix 分支 `fix/b059-broker-fast-fail`
- **依赖**：无

> B-003 / B-004 / B-005 / B-006 已闭环（详见 [docs/reviews/code/CODE-REVIEW-backlog-p1-r1.md](reviews/code/CODE-REVIEW-backlog-p1-r1.md)，含 R-001 修订）

> B-058 follow-up 已闭环 (本次会话) — router-service 完全收敛对齐 subscription 模板 + ReloadRequest.config_name 死字段彻底拆除。[`sources.py`](../src/intellisource/api/routers/sources.py) 5 端点全部走 `Depends(_get_service)`，body 类型直接为 `SourceConfig` / `SourcePatchRequest`，无嵌套 DTO + helper 转换层；POST 语义变为 idempotent upsert by name（删除 409 IntegrityError 处理）。SourceConfigService 扩展：`list_paginated` 接受 `type/status/tag` 过滤，`patch` 内部处理 `metadata → metadata_` ORM 列名映射。删除 3 个 mock-driven 假象测试文件（`test_sources_reload.py` / `test_sources_reload_writes_version.py` / `test_sources_rollback_restores_db.py` 共 17 测试，全部被 [`tests/unit/source/test_service.py`](../tests/unit/source/test_service.py) 用 real SQLite 在 service 层完整覆盖）。`test_sources.py` 改为 `dependency_overrides[_get_service]` 模式 + 删 4 个假象测试（`test_create_source_conflict_409` + 3 个 `test_reload_*config_name*`）+ 新增 2 个 rollback router smoke 测试。`test_deps_integration.py::test_sources_router_uses_deps_get_db_session` 改为 `inspect.signature(_get_service)` 间接 dep chain 验证（参 subscription 同名测试模板）。Unit 2879→2862 PASS 净 -17。mypy strict + ruff + lint-imports 8/8 clean。`on_config_change` (main.py lifespan) 路径未触碰 — 保留 sync record_version 路径不动符合"only what task requires"原则。

> B-058 已闭环 (前次会话, TDD standard mode RED→GREEN) — `SourceConfigService` 抽象（[src/intellisource/source/service.py](../src/intellisource/source/service.py) + 包 init）参 [`subscription/service.py`](../src/intellisource/subscription/service.py) 形态：`list_paginated / create / patch / delete`（软删 status=paused）+ `bulk_sync_with_version`（**additive** bulk_upsert 不软删 API-created sources）+ `rollback_to_version`（**full sync** bulk_sync_from_configs 精确匹配 snapshot）+ `build_source_version_manager()` factory（table_name=config_versions / config_cls=SourceConfig）。`SourceRepository.bulk_sync_from_configs` update 分支补 `existing.status='active'`（rollback 重激活语义）。**B-058a 漂移**修复 → reload 写 version snapshot；**B-058b real bug** 修复 → rollback 真写回 DB。

### B-058 sources reload/rollback 版本对齐 + rollback real bug 修复 ✅
- **优先级**：P1（含 real bug，rollback 端点不实际写 DB）
- **关联**：B-054+B-055 闭环遗留 / [src/intellisource/api/routers/sources.py:212-249](../src/intellisource/api/routers/sources.py) / [src/intellisource/subscription/service.py:101-149](../src/intellisource/subscription/service.py) / [src/intellisource/main.py:81-115](../src/intellisource/main.py)
- **现状（两个问题，b 是 real bug）**：
  - **B-058a 漂移**：[`/sources/reload`](../src/intellisource/api/routers/sources.py:212) → `reload_source_configs` 只跑 `bulk_upsert`，**不调 `record_version`**；与 file-watcher `on_config_change`（[main.py:113](../src/intellisource/main.py)）路径行为不一致（同一业务动作两条代码路径）；与 subscription 侧 `bulk_sync_with_version` 不对齐
  - **B-058b real bug**：[`/sources/rollback/{version}`](../src/intellisource/api/routers/sources.py:224) 调 `rollback_by_label` 拿到 snapshot 后**直接 return，没 `bulk_upsert` 把数据写回 DB**；端点名为 rollback 实际只是 "preview snapshot"。subscription 侧 [`rollback_to_version`](../src/intellisource/subscription/service.py:132) 已正确实现（rollback_by_label + bulk_sync_from_configs）
  - **影响**：rollback 端点被使用时 DB 状态不变，可能造成生产事故（用户以为已回退实际未生效）
- **修复方向**：
  - 参 [subscription/service.py](../src/intellisource/subscription/service.py) 抽 `SourceConfigService` 集中 validator + repository + version 调度：
    - `bulk_sync_with_version(configs, author)` — validate → bulk_upsert → record_version_async（B-058a）
    - `rollback_to_version(version_label)` — rollback_by_label → bulk_upsert（B-058b）
    - `list_paginated / create / patch / delete` — 单条 CRUD 不写版本（与 subscription 对齐，hot edits）
  - router 退化为薄 HTTP 转发；`reload_source_configs` 函数下沉到 service
  - `on_config_change` path 改走 service（消除两条代码路径分叉）
  - 兼容：保留 `record_version` 同步 wrapper（main.py lifespan 早期 import 时点的 sync 路径依赖）；或 lifespan 改走 async
- **测试**：
  - `tests/unit/api/test_sources_reload_writes_version.py` — reload 后 `config_versions` 表 +1 行
  - `tests/unit/api/test_sources_rollback_restores_db.py` — rollback 后 sources 行真按 snapshot 恢复（不是只返 JSON）
  - `tests/unit/source/test_service.py` 仿 [tests/unit/subscription/test_service.py](../tests/unit/subscription/test_service.py)
  - 现有 reload/rollback 测试适配新 service factory（deps_integration 模仿 B-054+B-055 fixture）
- **验证**：单测全绿 + 真起栈走查（B-031 步骤 5+ 信源 CRUD 章节可补 rollback 验证子步）
- **依赖**：B-054+B-055 ✅（SubscriptionService 模板已就绪可直接借鉴）

---

## P2 — 架构 / 功能完整性

> B-007 已闭环（详见 [docs/reviews/code/CODE-REVIEW-B-007-r1.md](reviews/code/CODE-REVIEW-B-007-r1.md)）— `gateway/__init__.py` 732 → 120 行，拆为 `_complete/_chat/_stream/_queue/_metrics/_protocols` 6 mixin，Protocol 自洽，2820 PASS 不退化
>
> B-009 已闭环（decision-only，reaffirm 选项 ②）— PRD AC-063 [ASSUMPTION] 在 sprint-9 已锁定 YAML-as-source-of-truth；`src/intellisource/api/routers/pipelines.py` 现状即决策实现（list/detail/run，无 CRUD）。完整 workflow CRUD（DB 存储 + 历史版本）保留为 v2+ 范畴，本 backlog 不立项。
>
> B-008 已闭环 — `truncate_summary` 接入 LLM summarizer（`summarizer.structured` 模板 + `gateway.complete` + `response_format: json_object`），产出 `{title, summary, timeline, key_points}` 结构化摘要；LLM 失败 / 返回非法 JSON / 缺字段 → 回退字符串截断；PRD AC-023 [ASSUMPTION] 已移除、标 `[x]`；2834 PASS (+7 测试) 不退化
>
> B-010 已闭环 — `docs/deploy-spec/deploy-spec-intellisource-v1.md` (755 行 + changelog) 产出并通过 r1+r2 双轮审查；4 模板必填段全覆盖；dev/staging/prod 三环境矩阵；zhparser DB 镜像要求 + 11 项指标家族 (B-014) + promtool check rules (B-015) + SBOM + trivy/grype 门禁 + git checkout+rebuild 回滚方案 + run_pipeline 唯一注册任务 smoke + queue.priority.* 实际队列名 + webhook token 轮换。reviewer r1 needs_revision (2 HIGH + 4 MEDIUM + 3 LOW)；devops r2 修订全部闭环；orchestrator inline r2 audit approved。详见 [docs/reviews/doc/REVIEW-deploy-spec-intellisource-v1-r2.md](reviews/doc/REVIEW-deploy-spec-intellisource-v1-r2.md)

> B-057 已闭环 (本次会话, light TDD inline) — [matcher.py](../src/intellisource/distributor/matcher.py) `_matches` 加 `source_names` 强约束维度：rules 设置后必须命中 content 的 source name 否则整条订阅丢弃；命中也视为正向 match 信号（允许 source_names 单独成立无需 keywords/tags）。新增静态 helper [`_resolve_source_name`](../src/intellisource/distributor/matcher.py) 双路径：先读 `content.source_name` 直列、空则 fallback `content.raw_content.source.name` ORM relation chain。[facade.py](../src/intellisource/distributor/facade.py) `_load_content_and_subscriptions` 改用 `session.get(..., options=[selectinload(ProcessedContent.raw_content).selectinload(RawContent.source)])` eager-load source 关系链，避免 matcher 跨 session lazy-load 触发 greenlet 错误；保留 `session.get` 调用形态（不切到 `session.scalars` 以兼容现有 facade mock 测试）。[config/subscriptions.example.yaml](../config/subscriptions.example.yaml) 加 source_names 注释示例 + 说明字符串比对不耦合 yaml 加载顺序。**测试**：tests/unit/distributor/test_matcher_source_names.py 12 tests（5 alone + 3 conjunction + 3 legacy preserve + 1 orphan + 2 multiple + 1 chain resolve 实际 12）— 2926→2938 PASS。lint-imports 8/8 contracts KEPT。**架构注意已落地**：不引入 source_ids UUID 字段；matcher 注入路径走 eager-load。**真起栈验证待**：B-031 步骤 13 推送链路加"按 source_names 订阅"子步。

### B-057 subscriptions ↔ sources 关联（match_rules.source_names）✅
- **优先级**：P2（B-054+B-055 闭环时 P3 候选，按"按信源订阅是 IT 资讯产品基础能力"升级 P2）
- **关联**：B-054+B-055 闭环遗留 / [src/intellisource/distributor/matcher.py:34-73](../src/intellisource/distributor/matcher.py) / [config/subscriptions.example.yaml](../config/subscriptions.example.yaml)
- **现状**：subscription `match_rules` 仅按内容属性（`keywords` / `tags` / `discipline_tags` / `min_score`）过滤，**无 source-level 过滤**。用户想"仅订阅 HN RSS 内容"必须把 source 名作为关键词写 `keywords`，间接且易错（不命中 title 就丢，也无法对 source 元数据精确比对）
- **B-054+B-055 时跳过的真实理由**：示例 yaml 一度考虑加 `source: <name>` 字段，但担心 subscriptions.yaml 与 sources.yaml **加载顺序耦合**。重新评估：把字段定为 `match_rules.source_names: list[str]` 后，**校验阶段不做引用检查**（接受任意字符串），仅 matcher 运行时按 `content.source.name` 字符串比对，orphan 引用（source 已删）= 无匹配，无需 cross-yaml 解析，耦合担忧消除
- **修复方向**：
  - `match_rules.source_names: list[str]`（可选字段，向后兼容）
  - [`SubscriptionMatcher._matches`](../src/intellisource/distributor/matcher.py:34) 增加 `has_source_match` 分支：从 `content.source.name`（需 ORM relation 已 eager-load）或注入 source_id → name 映射读取
  - 与现有 keywords/tags/discipline_tags 合取保持 disjunction 语义（任一匹配即 True；若 `source_names` 设置但不匹配则**整条订阅丢弃**，作为强约束维度——避免 source filter 与 tag filter 互相绕过）
  - schema 兼容：仅新增字段，无破坏
  - [config/subscriptions.example.yaml](../config/subscriptions.example.yaml) 加 `match_rules.source_names: ["HN RSS"]` 示例 + 注释说明字符串比对不做加载顺序耦合
- **测试**：
  - matcher unit tests +N 个：仅 source_names 匹配 / source_names + tags 合取 / orphan source_names = 无匹配 / source_names 设置但 content.source.name 不在列表 = 强拒绝
  - SubscriptionValidator 兼容性：source_names 字段透传，不强约束 source 存在
  - 真起栈：步骤 13 推送链路加"按 source_names 订阅"子步（指定 HN RSS 的 subscription 不应收到 GitHub Trending 的 content）
- **架构注意**：
  - **不引入** `source_ids: list[UUID]` 字段 — name-based 字符串足够支撑订阅语义，UUID 引用会与 yaml 配置形成强耦合（source 重建后 UUID 变 → 订阅失联）
  - matcher 注入路径：facade.distribute 触发 matcher 前，从 content.source_id 加载 source.name（或预先 eager-load `joinedload(ProcessedContent.source)`）
- **依赖**：无（match_rules 是 jsonb 已可承载任意 schema 扩展；matcher 路径独立）

---

## P3 — 优化 / 规约

### B-011 263 处弱断言 `assert .* is not None`（持续项）
- **关联**：原 audit F-49 / D6-7
- **现状**：跨 79 个测试文件，大量 `assert result is not None` 不验证语义；PR #72 (commit e3e7607) 已强化 11 个测试文件（integration 多数 + `test_app_entry.py`）为语义断言，余量待新增测试时增量收敛
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

> B-032 已闭环 (本次会话, path A1) — research skill 调研确认公开域不存在 pgvector + zhparser 复合镜像（[docs/research/b032-pgvector-zhparser-image-options.md](research/b032-pgvector-zhparser-image-options.md)）；选 A1 (pgvector 基底 + 加 zhparser 层) 实施。新增 [docker/db.Dockerfile](../docker/db.Dockerfile)（SCWS 1.2.3 源码编译 + amutu/zhparser master 编译，参考 abcfy2/docker_zhparser）；[docker/docker-compose.yml](../docker/docker-compose.yml) db 服务 image→build；[alembic/versions/001_initial_schema.py](../alembic/versions/001_initial_schema.py) 移除 DO/EXCEPTION 包裹 + 新增 CREATE TEXT SEARCH CONFIGURATION zhparser + ALTER ADD MAPPING；[storage/vector.py](../src/intellisource/storage/vector.py) `'simple'` → `'zhparser'` 4 处；[tests/integration/conftest.py](../tests/integration/conftest.py) 删 zhparser monkeypatch + 改用 `intellisource/db:pg16-pgvector-zhparser` + lazy `docker build` 兜底；[tests/unit/storage/test_migration.py](../tests/unit/storage/test_migration.py) +2 守卫测试（防 EXCEPTION 包裹回归 / 验证 TS CONFIG 创建）。2792 PASS unit 不退化 / mypy --strict + ruff + lint-imports 8/8 clean / docker compose config 解析通过。**真起栈验证待 user**：首次 `make up` 会 build 镜像（1-2 min）后跑 `SELECT extname FROM pg_extension WHERE extname='zhparser'` 应返 1 行；中文 query `/search` 走分词路径。

> B-033 已闭环 (本次会话, B-051 Phase D 子集) — `build_distributor_facade()` 改为 soft-disable：每个渠道 `from_env()` 单独 try/except，`ValueError` 时 `_logger.warning("distribution channel X disabled: ...")` + 该渠道从 channels dict 中剔除；空 channels dict 时额外 warning "no distribution channels configured"。`DistributorFacade.distribute()` 原有路径已正确处理 `channel is None` 分支（增 skipped 计数），无需改动。docker/.env 清空所有渠道凭据后 api lifespan 不再 raise；orphan 占位 `disabled-walkthrough-placeholder` 可从 docker/.env 移除。**测试**：新增 [tests/unit/distributor/test_b033_soft_disable.py](../tests/unit/distributor/test_b033_soft_disable.py) 5 tests + 改造 [tests/unit/distributor/test_facade.py](../tests/unit/distributor/test_facade.py) 2 个 hard-fail 测试为 soft-disable 断言（验证 warning log + facade._channels 不含该渠道）。详见 [composition.py:120](../src/intellisource/composition.py)。

### B-034 PRE-DEPLOY-WALKTHROUGH 文档订正
- **优先级**：P3
- **关联**：CORRECTIONS-LOG 修正 #5-#7 影响 / walkthrough 步骤 2 期望与实际偏差 / 阶段 2 步骤 6-8 暴露 3 项新 drift / 阶段 5 步骤 13 暴露 4 项新 drift
- **现状**：步骤 2 "Pass 标准: /health.status == healthy" 与 celery 健康依赖 worker（步骤 12 才起）冲突；OpenAPI 端点假设公开但实际 X-API-Key 中间件保护；步骤 6 期望 `content-process.mode=strict` 实际 `batch` + manual-collect.steps 期望含 `params` 实际 `{}`；步骤 7 期望 trace_id 进 worker log 但 stdlib formatter 不渲染 contextvar（实际机制 OK，见 B-040）；步骤 8 期望 `/llm/stats` 不需 API key 实际需要；步骤 13 channel_config 示例字段名 + 验证 SQL 列名 + 推送入口 + auth header 全错
- **修复方向**：
  - 步骤 2 改 `Pass 标准: /health.status in {"healthy", "degraded"}` + 注释 "celery 在步骤 12 worker 起栈后转 healthy"
  - 步骤 2 OpenAPI curl 加 `-H "X-API-Key: $IS_API_KEY"`，§0.2 增加 "IS_API_KEY 必填，对 /openapi.json + /docs + /api/v1/* 全部生效"
  - §0.2 新增 "若 docker/.env 留空分发渠道凭据，须等 B-033 闭环；当前应至少填 wechat/wework/email 占位值"（B-033 闭环后该段删除）
  - 步骤 6 期望 JSON 同步实际值：`content-process.mode=batch` / manual-collect 详情 steps `params:{}`（修正 #15 后）
  - 步骤 7 trace_id 子项加注 "依赖 B-040 闭环后生效；当前可跳过此项，专项验证留给步骤 17 F-23 回归"
  - 步骤 8 修正 "`/llm/stats` 不带 API key 也能查" → "所有 /api/v1/* 端点均需 X-API-Key（webhooks/health/metrics/openapi/docs/redoc 除外）"
  - 步骤 13 channel_config 示例 `"to":"test@example.com"` → `"to_addr":"test@example.com"`（_extract_recipient 读 to_addr）
  - 步骤 13 验证 SQL #3 `WHERE message_preview ~ '...'` → `WHERE recipient_id ~ '@.+\\.'`（push_records 表无 message_preview 列，PII 落 recipient_id 由 facade._record_push → _mask_recipient 路径 mask 后存）
  - 步骤 13 推送入口 `POST /pipelines/push-optimize/run` → 改为 `POST /pipelines/manual-collect/run` 走完整 collect→process→distribute 链路；或注 "push-optimize.yaml steps: [] 是 flexible LLM agent 入口，本地走查可改为在 worker 容器内直调 `from intellisource.composition import build_worker_composition; ...; await wc.distributor.distribute(content_id=..., subscription_id=...)` 验证 facade 真路径"
  - 步骤 13 所有 curl 把 `-H 'Authorization: Bearer $IS_API_KEY'` → `-H "X-API-Key: $IS_API_KEY"`
  - 步骤 13 §0.2 增加 "若用 mailhog 做本地 SMTP receiver，须设 `IS_SMTP_HOST=mailhog / IS_SMTP_PORT=1025 / IS_SMTP_USE_TLS=false`，并启 walkthrough profile：`docker compose -f docker/docker-compose.yml --profile walkthrough up -d mailhog`"
  - 步骤 15（2026-05-29 暴露）指标路径巡检 `for path in /metrics /api/v1/metrics /api/v1/system/metrics` → 删 `/metrics`（根路径未挂路由，实测 404；仅 `/api/v1/metrics` + `/api/v1/system/metrics` 提供指标，Prometheus 也只 scrape `/api/v1/metrics`）；同步建议 `middleware.py` auth-exempt 名单移除并不存在的根 `/metrics` 条目（归 B-040 旁支或单独 chore）
  - 步骤 15 关键指标家族巡检 `grep -E "^(collector_|pipeline_|llm_|task_queue_|push_)"` → 改为实际存在的家族：`llm_calls_total`/`llm_call_failures_total`/`llm_call_latency_seconds`/`pushes_total`/`celery_tasks_total`/`http_requests_total`/`intellisource_health_status`（`collector_`/`pipeline_`/`task_queue_` 家族代码中不存在；`push_` 应为 `pushes_total`）
  - 步骤 17 + 步骤 19 所有业务 curl（collect / pipelines run / search）补 `-H "X-API-Key: $IS_API_KEY"`（缺则 401；步骤 17 取 trace_id 的 curl 尤其需要）
  - 步骤 18 Pass 标准 "DB 停时 status=unhealthy" → 改 "status=degraded（仅 db check unhealthy，redis/celery 仍 up 的部分降级语义）"，health 端点本身仍 200 不变

> B-035 已闭环 (本次会话) — `.github/workflows/ci.yml` 改造：(1) `integration-tests` job 用 `docker/setup-buildx-action@v3` + `docker/build-push-action@v5` 预 build `intellisource/db:pg16-pgvector-zhparser`（cache type=gha,scope=db-image 跨 job/run 复用）→ 设 `IS_FORCE_DOCKER_TESTS=1` + `IS_TEST_DB_IMAGE=intellisource/db:pg16-pgvector-zhparser` 让 conftest 不 deselect docker 测试且用 composite image；(2) 新增 `docker-compose-smoke` job — 复用 cached image，`cp .env.example .env` + sed 填 channel 占位（兼 B-033 hard-fail），`docker compose up -d --wait db redis migrate api` 借 compose 自身 healthcheck + service_completed_successfully 等待，三个 SQL 探针验证 zhparser 真路径活：`SELECT extname FROM pg_extension WHERE extname='zhparser'` / `SELECT cfgname FROM pg_ts_config WHERE cfgname='zhparser'` / `to_tsvector('zhparser', '北京天安门搜索引擎')` 返多 lexeme（防 'simple' 回退）；(3) failure 时 dump db/migrate/api logs；(4) `if: always()` 跑 down -v 清理。预期 CI 首次 1-2 min build 镜像，二次 cache hit secs；smoke job 与 integration-tests job 并行跑独立 stack 互不干扰。**CI 真跑验证 PASS** (run 26564322038 on main)：integration-tests 163 passed / 1 skipped / 0 deselected（`IS_FORCE_DOCKER_TESTS=1` + composite image）；docker-compose-smoke 三 SQL 探针全绿（`pg_extension`/`pg_ts_config` 返 zhparser，`to_tsvector('zhparser','北京天安门搜索引擎')` → `'北京':1 '天安门':2 '搜索引擎':3` 多 lexeme 非 simple 回退）。

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

### B-043 chat() path 接入 LLMCache ✅
> 已闭环 (PR #72, commit 6beb94a) — `_chat.py` 加 cache get/set 路径（`if self._cache is not None and cache_key_parts is not None`），`flexible.py` 透传 cache_key_parts，`_metrics.py` 计 chat cache hit/miss。`/search/chat` 二次执行命中缓存。+ `test_gateway_chat_cache.py` 覆盖。
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
> **已闭环** (本地分支 `fix/observability-b040-b060`, commit bb1d1e5, 真栈验证)：真因三重——① Celery `worker_hijack_root_logger` 未关 ② `worker_redirect_stdouts=True` 把 sys.stderr 换成 LoggingProxy（早于 setup_logging 吞行）③ `boot.worker_init_handler` setup_logging 在 `_celery_tasks` guard 之后（forked child 短路不配置 root）。修：两 conf 关闭 + setup_logging 提到 guard 前 + signals prerun/middleware inbound 各发语义 INFO 承载行。真栈：`POST /tasks/collect` → 同一 trace_id 现于 api inbound + worker prerun。+6 单测（含 boot-guard + redirect 回归）。
- **优先级**：P3
- **关联**：CORRECTIONS-LOG 2026-05-26 B-031 阶段 2 步骤 7 trace_id 一项延后；走查暴露
- **现状**：[scheduler/signals.py](../src/intellisource/scheduler/signals.py) `_on_task_prerun` 已通过 Celery message header `x-trace-id` 把 contextvar 正确 set/reset（F-23 已闭环，单测覆盖）；middleware 也正确返回 `x-trace-id` 响应头。但 walkthrough 步骤 7+17 的 `grep -oE 'trace_id=[a-f0-9-]+'` 命中 0，**给人 propagation 失效的假错觉**，实际机制工作。**真起栈复核（2026-05-29 步骤 17）修正根因双重**：
  - worker 端：`setup_logging()` 其实已在 `worker_process_init` 装了 `TraceIdFormatter`（非"root logger 无 formatter"），但 **Celery 默认 `worker_hijack_root_logger=True` 未关**，celery 自有 formatter 覆盖了它 → worker log 形如 `[ts: LEVEL/Pool] msg` 无 `trace_id=`
  - api 端：热路径无业务日志发射 — `tasks.py` collect 路由 0 处 log 语句、`signals.py` prerun 仅 bind contextvar 不 log；api 容器仅 uvicorn access log（无 structlog 输出）。故即便 formatter 生效也无承载 trace_id 的业务 log line
- **修复方向**：
  - 关 Celery hijack：`scheduler/celery_app.py` 设 `worker_hijack_root_logger=False`（让 setup_logging 的 TraceIdFormatter 生效）
  - 热路径补 INFO 日志：请求入站（middleware 或 collect 路由）+ task prerun（signals.py）各发射一条带语义的 INFO log，使 trace_id 有承载行
  - 或（退路）改 walkthrough 步骤 17 验证手段为 `x-trace-id` 响应头 + 单测引用，不依赖 log-grep
- **验证**：worker + api 日志 grep `trace_id=<同一 uuid>` 各 ≥1 命中；步骤 17 F-23 回归 PASS

---

### B-060 失败 LLM 调用未落 `llm_call_logs`
> **已闭环** (本地分支 `fix/observability-b040-b060`, commit 77b3fae, 真栈验证)：`LLMCallRecord` 加 `error_message` + `CostTracker.log_call` 透传；`_unified_call_with_retry` 中央失败 emit（熔断 OPEN→`circuit_open` / 重试耗尽→`timeout`|`error`），覆盖 complete/chat/stream/embed 四路径。真栈：注入坏 LLM key → `llm_call_logs` 非 success 行 **0→20**（5 `error` 带真 msg + 15 `circuit_open`）。+7 单测。
- **优先级**：P3（MEDIUM-LOW — 审计/可观测缺口）
- **关联**：B-031 阶段 7 步骤 19 真起栈走查暴露；B-042 闭环遗留（仅保证 success 落表）/ [src/intellisource/llm/gateway/](../src/intellisource/llm/gateway/) `_RetryMixin._emit_call_log`
- **现状**：步骤 19 注入无效 LLM key 后，summarize 走 truncation fallback、熔断器正确 OPEN，但 `llm_call_logs` 仍仅 `success|49` — **失败调用 0 行**。walkthrough 步骤 19 检查 #3 期望 `status='error'/'timeout'` 行。根因：B-042 的 `_emit_call_log` 只在成功路径 emit；失败在 litellm 调用抛出后被上层（compaction.py summarize fallback）捕获前未写入审计表
- **修复方向**：
  - `_RetryMixin` 失败路径（重试耗尽 / 熔断 OPEN / 上游异常）也 `_emit_call_log(status='error'|'timeout', error_message=...)`
  - 注意与熔断器 `CircuitOpenError` 短路路径协调：熔断拒绝也应留一条 record（status='circuit_open' 或计数）
- **验证**：注入 LLM 故障 → `SELECT count(*) FROM llm_call_logs WHERE status != 'success'` ≥ 1，error_message 非空；步骤 19 检查 #3 Pass
- **依赖**：无

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

### B-046 collector + HTMLParser 填 `processed_contents.published_at` ✅
> 已闭环 (PR #72, commit abc0adc) — `agent/tools/executes/process.py` `repo.create(published_at=ctx.get("published_at"))`，缺数据 fallback raw_contents.created_at。+ `test_process_published_at.py` 覆盖。
- **优先级**：P3
- **关联**：B-031 阶段 4 步骤 10c carryover 修正 #21；CORRECTIONS-LOG 2026-05-27 条目
- **现状**：`SELECT COUNT(*) FROM processed_contents WHERE published_at IS NULL` = 20/20（B-039 重跑后所有行该列 NULL）；date filter SQL contract 已闭环（B-002 datetime 类型转换 + 422 拦截非法值），但用户视角 0 结果 → /search date_from/date_to 功能不可见
- **修复方向**：
  - collector 层（HN RSS / 通用 RSS）从 feed entry 解析 `pubDate` / `dc:date` → raw_contents.published_at
  - HTMLParser processor 透传 raw_contents.published_at → ctx.published_at
  - `_process_execute` `repo.create(published_at=ctx.get("published_at"))`
  - 缺数据时 fallback 用 raw_contents.created_at 而非保持 NULL
- **验证**：重跑 manual-collect 后 `published_at IS NOT NULL` ≥ 18/20；步骤 10c date filter 真路径返回非 0 items

### B-047 sync `/search/chat` sources 提取 + LLM answer 整形 ✅
> 已闭环 (PR #72, commit b3a38ab) — `api/routers/search.py` sync chat 修正 `_extract_sources` walk 路径 + 强制 LLM answer 整形（不再 dict.repr）；`agent/response_utils.py` 提取逻辑对齐。+ `test_search_chat_b047.py` 覆盖（sources count ≥ 1 + 自然语言 answer）。
- **优先级**：P3
- **关联**：B-031 阶段 4 步骤 11a carryover 修正 #22 + #23；CORRECTIONS-LOG 2026-05-27 条目
- **现状**：
  - **修正 #22**：sync `/search/chat` `_extract_sources(flex_result)` 返回 count=0，而 stream `/search/chat/stream` `done.metadata.results` 含完整 search items + get_content_detail 全文。两条路径对 flex_result.results 的解析逻辑不一致 — sync `_extract_sources` 在 `flex_result["results"]` 上 walk `step.get("tool") != "search"` 未命中（实际结构可能是嵌套或字段命名漂移）。
  - **修正 #23**：sync chat 当 search 命中 ≥1 行时，`extract_answer` 把 search step output 直接 dict.repr() 当 final answer 返回（如 `{'id': 'd90d9026-...', 'title': 'Eagle 3.1...', 'body_text': '...', 'summary': '...'}`），未走 LLM 整形成自然语言回答。
- **修复方向**：
  - 调试 `flexible.py` 的 `tool_results` 结构与 `_persist` 后的 `flex_result["results"]` shape，确认 _extract_sources 的 walk 路径正确
  - 重写 sync chat path 的 prompt 工程：search step 后强制再调一次 LLM 用 system="基于检索结果回答，引用 sources" + user_message 整形 answer
  - 或：复用 stream 路径的 done.metadata.results 提取逻辑作为 sync sources 的事实来源
- **验证**：curl `/search/chat` RAG-trigger query → response.sources count ≥ 1 + answer 是自然语言（非 raw dict repr）

> B-048 已闭环 — F-01~F-07 + E-01 在 commit 1b38f7b 一次性修复（F-01 FK 移除 task_id kwarg / F-02 暂标 xfail / F-03 patch→app.dependency_overrides / F-04 skipif no-key / F-05/F-06/F-07 `_make_pg_db_manager(pg_session=...)` API 切换 / E-01 sqlite fixture 加 JSONB+ARRAY→JSON coercion）+ commit 5efc6ba 后续（F-01 mask-email 断言 + E-01 ARRAY 列补 coercion）。剩余 F-02 cross-loop xfail 在本次会话闭环：test_run_pipeline_marks_raw_content_as_processed 从 pg_session SAVEPOINT-isolated fixture 切到独立 `async_sessionmaker + poolclass=NullPool`（与生产 worker B-037 路径同型）—— `_run_sync` 子线程 loop 每次 factory() 都拿到全新 asyncpg 连接，不再触发 "another operation in progress"。**CI 验证**：main 上 run 26505614731 (commit 7ef17bf) Integration Tests = 162 passed / 1 skipped / 1 xfailed in 74.41s；本次 xfail 转 pass 后预期 163 passed / 1 skipped / 0 xfailed（F-04 仍 skip 因 CI 无 LLM API key）

> B-054 + B-055 已闭环 (本次会话, 三入口对齐重构 Layer 1+2 + CLI 薄壳) — subscriptions 配置三入口（yaml / API / CLI）行为对齐，单一 Pydantic schema + service layer 集中业务逻辑。
>
> **Phase 1 (yaml + reload MVP)**：
> - `config/subscriptions.example.yaml`（3 渠道示例：wework / email / wechat + 注释"API changes will be overwritten on next reload"）
> - `src/intellisource/config/subscription_models.py` 新增 `SubscriptionConfig` Pydantic model（name / channel Literal / channel_config / match_rules / frequency / quiet_hours / timezone / discipline_tags）
> - `src/intellisource/config/subscription_validator.py` 新增 `SubscriptionValidator` 按 channel 分支校验：email 必填 to_addr、wework user_id+msg_type ∈ {text,markdown,news}、wechat any shape
> - `src/intellisource/config/subscription_loader.py` 新增 `SubscriptionConfigLoader`（独立 `IS_SUBSCRIPTION_CONFIG_DIR` env，默认 `config/subscriptions`）
> - `SubscriptionRepository` 加 `upsert(by-name)` + `bulk_sync_from_configs`（yaml 缺失即 status='paused' 软删，保留 push_records FK 历史）
> - `docker/.env.example` 加 `IS_SUBSCRIPTION_CONFIG_DIR`；Makefile bootstrap 建 `config/subscriptions` 目录
>
> **Phase 2 (subscription_config_versions + rollback)**：
> - alembic migration `d4e5f6a7b8c9_add_subscription_config_versions.py`（schema 对齐 `config_versions`）
> - `ConfigVersionManager` 泛化（**删除向后兼容**）：`table_name` + `config_cls` 强制 kwarg，删除 `session_factory`，`record_version_async` / `rollback_by_label` `session` 必传；sources rollback router + composition.py wiring 同步升级新签名
> - reload 端点成功后调 `record_version_async` 写 snapshot；新增 `POST /api/v1/subscriptions/config/rollback/{version}` 端点
>
> **Layer 1+2 三入口对齐重构**（用户决策：repair real bugs + 抽 service）：
> - 删 `SubscriptionCreateRequest` / `SubscriptionUpdateRequest`；`POST /subscriptions` 直接接 `SubscriptionConfig`（修复 API 缺 `frequency` / `quiet_hours` / `timezone` / `discipline_tags` 字段的漂移）；`PATCH` 用 `SubscriptionPatchRequest`（全 Optional）
> - 修真 bug：旧 API 不跑 `SubscriptionValidator` —— 同样输入"email 缺 to_addr"在 yaml reload 报错而 API 接受。现在统一在 service 层强制
> - 新增 `src/intellisource/subscription/service.py` `SubscriptionService`：`list_paginated` / `create` / `patch` / `delete`（soft → status='paused'）/ `bulk_sync_with_version` / `rollback_to_version`；validator 在 create + bulk_sync 路径强制
> - router 退化为薄 HTTP 转发层（仅参数解析 + 序列化 + 错误码映射），所有写入路径 → service
>
> **Phase 3 (B-055 CLI 薄壳)**：
> - `intellisource subscriptions list / add / patch / rm / reload / rollback` 子命令
> - `add` 交互式 prompt 按 channel 分支收集 `channel_config`（wework → user_id+msg_type / email → to_addr / wechat → 空）
> - 全部 HTTP 自调本地 `/api/v1/subscriptions/*`（复用 `_get_headers` IS_API_KEY 注入），与 sources / pipeline / task CLI 一致
>
> **三入口对齐结果**（重复消除 + 一致性）：
> - **Pydantic schema 单一来源**：`SubscriptionConfig` 唯一定义；API request body + yaml loader + CLI 构造 dict 共用
> - **业务逻辑单一来源**：`SubscriptionService` 集中 validator+repository+version snapshot 调度；router / loader / CLI 仅作为 transport adapter
> - **校验对齐**：API create / yaml reload / CLI add 三条路径全跑 `SubscriptionValidator` (修 bug)
> - **版本快照触发点显式**：reload + rollback 经 service 写 `subscription_config_versions`；单条 create/patch/delete 不写（保持 history 表不暴涨，"snapshot = deploy 单位"语义清晰）
> - **审计一致**：CLI HTTP 自调 → 经过 API middleware + metrics + log，与 curl / postman 等价；不绕过 DB 直连
>
> **测试**：74 新增 tests GREEN（19 validator + 7 loader + 8 repository sync + 9 router (reload+rollback+CRUD) + 13 CLI + 4 generic ConfigVersionManager + 12 service + 5 旧 SubscriptionCRUD 重写 + 1 deps_integration 适配）；**2903 PASS unit (+74)** 守住 baseline；mypy --strict + ruff + lint-imports 8/8 clean。
>
> **验收**：用户 `make bootstrap` → 编辑 `config/subscriptions/subscriptions.yaml` → `intellisource subscriptions reload` → `intellisource subscriptions list` 可见 → 改 yaml 删一条 → `intellisource subscriptions reload` → 列表中那条 status=paused → `intellisource subscriptions rollback 1` → 恢复 v1 状态。
>
> **未做项 / 后续可立项**：
> - Layer 3 "单条 create/patch 也写版本快照" 不做（user-decided 推荐方案不包含；history 表暴涨成本高于价值）
> - yaml `source: <name>` 关联解析（subscriptions 关联到 sources）— 当前 Phase 1 跳过避免 yaml 间加载顺序耦合，所有 yaml 订阅 source_id=NULL（按 tags 匹配全局）；如需可独立立 B-057
> - sources rollback 端点 (api/routers/sources.py:230) 当前 `manager = ConfigVersionManager(table_name="config_versions", config_cls=SourceConfig)` new in handler — 与 subscriptions 同形态但 sources reload 路径未自动写版本，是 pre-existing 设计 gap（B-058 候选）

> B-050 已闭环 (本次会话, 文档与默认值倾斜) — 依赖 B-033 channels soft-disable 已闭环，本次完成两处部署侧倾斜：
>
> - `docker/.env.example` Distribution channels 段：WeWork 块前置标 "recommended primary push channel"，WeChat 标 "optional, requires 公众号 备案 + 年审"，补全 `IS_WECOM_TOKEN` / `IS_WECOM_ENCODING_AES_KEY` / `IS_WECOM_CORP_ID` 三变量（顺带 B-034 doc drift §7）；段首注释明确未配置 channel 走 soft-disable warning 路径，不再 hard-fail
> - `docs/deploy/PRE-DEPLOY-WALKTHROUGH.md §0.2` 新增 "Distribution channels（可选 — 未配置自动 soft-disable）" 子段：三渠道矩阵列举 WeWork (推荐主路径，无 48h 窗口/markdown/通讯录派发/限流宽松) / WeChat (需备案 + 48h 窗口约束) / Email (mailhog 本地)，附 WeCom AES 三变量；§0.2 IS_API_KEY 行补 `change-me-in-production` 启动会被 lifespan 阻断的说明（B-051 startup guard 提示）
>
> **未做项**：
> - `cli init` 渠道选项顺序：B-051 已把 `WeWork (recommended)` 放第一位，`cli doctor` `_REQUIRED_CHANNEL_VARS` 也已 wework 在前，本次无需再改
> - walkthrough 步骤 13 推送示例：当前 mailhog + Gmail + WeChat webhook 已全部签字闭环（2026-05-27），切换主示例会动既有签字结论，不动
> - **PRD §F-006 / ARCH M-007 主路径标记**：PRD "v1 优先支持微信公众号/企业微信" 与 ARCH M-007 `WeChatDistributor` (AC-040) / `WeWorkDistributor` (AC-041) 保持平等列举。决策：不做 "主路径 wework / 备选 wechat" 的 requirement 倾斜 amendment（部署侧 .env.example + walkthrough 已含 wework 优先标注，PRD/ARCH 契约层不收窄）
> - `config/subscriptions.example.yaml`：当前不存在，订阅创建走 API 不依赖 yaml，本次不新增
>
> **验证**：新用户首次 `make bootstrap` → 编辑 `.env` 时阅读到 WeWork 优先标注 + 仅需配 WeWork 三变量即可跑通推送（其他 channel 全空时 lifespan warning 但不阻塞），symmetry 与 `intellisource init` CLI 与 `_REQUIRED_CHANNEL_VARS` 一致。无业务代码改动 → 2829 PASS unit 不需重跑（baseline 守住）。

> B-051 已闭环 (本次会话, D+C+A 长期完整路径) — 配置管理与首次接入 UX 三阶段全部落地。
>
> **Phase D（短期 — Makefile + soft-fail + startup guard）**：
> - B-033 channels soft-disable 闭环（见上方 B-033 条目）
> - `Makefile` 新增 `bootstrap` target：`cp docker/.env.example docker/.env` + `mkdir -p config/sources` + `cp config/sources.example.yaml config/sources/sources.yaml`，仅在文件不存在时执行；help 段加 `Setup:` 行
> - `src/intellisource/main.py` `_lifespan()` 添加 IS_API_KEY 占位 guard：`api_key == "change-me-in-production"` 时 `raise RuntimeError` 阻断 API 启动 + 提示 `secrets.token_hex(32)` 生成命令
> - 新增 `_collect_startup_warnings()`：扫 IS_API_KEY 空 / sources dir 缺失/空 / 无 LLM key / 三渠道凭据缺失，统一 `logger.warning("startup: ...")`，结果写 `app.state.missing_config`（供 /health 暴露）
>
> **Phase C（中期 — doctor + health missing_config）**：
> - `src/intellisource/api/routers/system.py` `health_payload()` 输出加 `missing_config` 字段（条件渲染，无 warnings 时不写）
> - `src/intellisource/cli/main.py` 新增 `doctor` 子命令：解析 `docker/.env` (`_load_dotenv_file`) 与 `os.environ` 合并 → `_doctor_env()` 输出 `✓`（必填 OK）/ `✗`（必填缺失）/ `○`（可选未配）三态；支持 `--check-api` 命中 `/health` 探活 + 透传 missing_config；`--strict` 任何 `✗` 退码 1
>
> **Phase A（长期 — init 交互式 CLI）**：
> - `src/intellisource/cli/main.py` 新增 `init` 子命令：典型 `npm init` 风格 — Typer prompt 询问 API key（空则 `secrets.token_hex(32)` 自动生成）→ LLM provider 三选一（DeepSeek/OpenAI/Anthropic，推荐 DeepSeek）→ 渠道四选一（WeWork 推荐 / WeChat / Email / Skip）→ 是否加 HN RSS 起步信源；`_write_env_file()` 合并到现有 .env（保留无关行 + 覆写选中 key + 追加新 key）
>
> **测试**：21 新 tests GREEN（5 B-033 soft-disable + 16 B-051 startup guard / _collect_startup_warnings / _doctor_env / _load_dotenv_file），其中 lifespan placeholder raise 测试覆盖关键安全契约；2829 PASS unit 不退化（baseline 2808 +21）；mypy --strict + ruff + lint-imports 8/8 clean。**真起栈验证依赖**：用户 `make bootstrap` → 编辑 .env → `make up` → `uv run intellisource doctor --check-api` 验证 missing_config 透传 + /health 暴露。
>
> **carryover 立项**：B-050 wework 默认倾斜（依赖 B-033，本次已闭环，可启动）；docker/.env.example 暂未做 wework 块前置（留 B-050 实施时一并）。`config/llm_models.yaml` vs `.example.yaml` 双份的疑惑未处理（B-051 范围外，可独立小立项 B-052）。

### B-049 distributor channel 失败 silent-success — facade.distribute 误判 sent ✅
> 已闭环 (PR #72, commit 973d3e7, 采方案 B) — `facade.distribute` 检查 channel 返回 `result.get("status") == "failed"`，failed 不写 status=sent → skipped++ 写 status=failed（不改 channel 契约）。+ `test_facade_silent_failure_b049.py` 覆盖。
- **优先级**：P3
- **关联**：B-031 阶段 5 步骤 13 carryover；CORRECTIONS-LOG 修正 #29 silent-failure 说明
- **现状**：[src/intellisource/distributor/facade.py:135](../src/intellisource/distributor/facade.py)
  ```python
  try:
      await channel.distribute(push_content, sub)
      sent += 1
      _record_push_outcome("sent", channel=channel_name)
  except Exception:
      ...
      skipped += 1
  ```
  channel.distribute 内部 SMTP/WeChat/WeWork 异常被 attempt_fn 吞为 `(False, error, raw)`，channel 返 `{"status":"failed", "error":...}` 不抛 → facade try/except 看不见失败 → sent++ + push_records 写 status=sent（payload 实际未送达）。本次 walkthrough 步骤 13 因 use_tls 错配触发：mailhog total=0 但 facade 报 sent=1 / push_records 写 sent — 用户视角"成功"实际未送达
- **修复方向**：
  - A: 让 channel.distribute 在 succeeded=False 时抛 `ChannelSendError(error_msg)`，facade try/except 捕获 → skipped++ 写 status=failed；改 EmailDistributor / WeChatDistributor / WeWorkDistributor 三个 channel + 同步改 facade 单测期望
  - B: facade.distribute 检查 channel 返回 `result.get("status") == "failed"` 而非靠异常，对返 failed 的不写 status=sent；不改 channel 契约
  - 推荐 A：异常路径更清晰，silent-failure 反模式（"不抛错就当成功"）应根除；不过涉及 channel.distribute 调用方较多，需要全量审查 caller
- **验证**：mock 一个返 `{"status":"failed"}` 的 channel，调 facade.distribute，断言 push_records 写 status=failed 且 facade 返 sent=0 skipped=1（当前会断言失败）

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

### B-015 `promtool check rules` 验证 alerts.yml 语法 ✅
> 已闭环 (commit 9c118b8 引入 + ffd1c7b refine) — CI Lint job 跑 `docker run --rm --entrypoint promtool -v $PWD/docker/prometheus:/etc/prometheus prom/prometheus:v2.55.1 check rules /etc/prometheus/alerts.yml`（[.github/workflows/ci.yml](../.github/workflows/ci.yml) "Validate Prometheus alert rules"），每次 PR/push to main 无条件运行并 gate merge。`--entrypoint promtool` 必需（镜像默认 entrypoint 是 prometheus 二进制）。alerts.yml 5 组 8 规则；结构层由 `tests/unit/observability/test_alerts_yaml.py` (14 tests) 覆盖。PR #72 Lint job green 即此步通过。
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
