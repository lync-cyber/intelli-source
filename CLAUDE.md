# CataForge

## 项目信息
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.4.1
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
  <!-- 可选值: standard | agile-lite | agile-prototype。矩阵见 COMMON-RULES §执行模式矩阵 -->
- 阶段配置: ui_design=N/A（backend-only），testing=启用，deployment=启用
- model 继承: AGENT.md 中 `model: inherit` 继承父会话模型

- 项目名称: IntelliSource
## 执行环境 (Bootstrap 时由 `cataforge setup --emit-env-block` 填入)
<!-- 本节在 Bootstrap 步骤中生成。每次会话都会作为项目指令加载，
     权重高于 hook 注入的 additionalContext。项目生命周期内保持稳定。 -->
{执行环境检测结果 — 未填入时 orchestrator 应在 Bootstrap 时调用:
 cataforge setup --emit-env-block}

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)
- 当前阶段: backlog-burndown → **release gate = approved + 物理闭环（B-031 用户 2026-05-29 签字）**；PR #71/#72/#73/#74/#75 已合入 main；**PR #76 已合入 main (merge ae379f8)：codebase 架构审查 + 深层重构 — [CODE-SCAN-arch-r1](docs/reviews/code/CODE-SCAN-arch-20260529-r1.md) D-1~D-8 全闭环 + B-020~B-028 架构治理债闭环**
- 下一步行动: **wework 通道部署就绪度核对完成（出站 GO / 入站 GO-with-condition）；R-001/R-002 文档缺口已修（分支 `docs/wework-deploy-readiness-r001-r002`，未 push），待用户决定 commit/PR + 可选用真实凭据走出站投递验证（walkthrough 步骤 13 wework 分支）。** release 已放行，无阻塞项。框架级 backlog 全部移交上游并本地闭环（B-016/B-017/B-018/B-036/B-038 + B-019 → [feedback bundle](docs/feedback/feedback-suggest-framework-batch-20260529.md)，issue 待用户提交至 CataForge 上游）。**B-013/B-040/B-060 + B-020~B-028 均已闭环**（后者经 PR #76：lint-imports/deptry/vulture 退出码 0 + CI lint job 已移除 continue-on-error，违规阻塞 merge）。**B-014 ✅ 已闭环**（本会话，分支 `chore/claude-md-state-sync-pr76`）：跨进程 worker 指标暴露 + API 侧 eager 注册。**剩余项目级真债 = 仅 BGE-M3 本地 embedding 暂缓**（无其他开放真债）
- 当前回归基线（本会话实测）: **2991 PASS unit / 0 FAIL** (`make test-unit` = `-m "not slow" -n auto`，31s；B-014 +19 测试，base 2972 @ main HEAD ae379f8) + **163 PASS / 1 skip integration**（CI 验证，含 zhparser migration e5f6a7b8c9d0）；mypy --strict clean (177 files) + ruff clean + lint-imports 8/8 KEPT。**main 已含 B-014 + 状态回填**（merge 06ed3ce / PR #77）。本会话分支 = `docs/wework-deploy-readiness-r001-r002`（wework 就绪度核对 + R-001/R-002 文档修复 + cli prompt 串订正；2991 unit 基线无逻辑改动不退化，cli 单测全绿；未 push）
- 文档状态: prd / arch / dev-plan(主卷+s1~s7+s7r+s8r+s9) / test-report / deploy-spec = approved；ui-spec = N/A；dev-plan-s8 = draft；backlog = approved
- 历史闭环索引: 详见 [docs/HISTORY-intellisource-v1.md](docs/HISTORY-intellisource-v1.md) — audit-fix-pr53/54 + backlog 闭环（b001-b059 全系列）+ B-031 走查阶段 0-7（步骤 1-20，16 N/A，PR #69/#70）+ 编码可移植性修复 + 修正 #1-#29；**近期 PR：#72 (B-043/B-046/B-047/B-049 + B-011) · #73 (B-034/B-012) · #74/#75 (B-011 + 框架 feedback bundle + B-013/B-040/B-060 回填) · #76 (架构审查 D-1~D-8 + B-020~B-028)**
- 最近闭环:
  - **wework 部署就绪度核对 + R-001/R-002 文档缺口修复 (本会话, orchestrator 主线程 inline, 分支 `docs/wework-deploy-readiness-r001-r002`)** — 用户要求"核对 wework 企业微信通道部署就绪度（不起栈）"。全链路静态审计（凭据/Settings → docker-compose `env_file:.env` 三服务透传 → composition `build_distributor_facade` soft-disable 装配 → facade 按 `sub.channel` 派发 → 出站 [wework.py](src/intellisource/distributor/channels/wework.py) text/markdown/news → 入站 `/webhooks/wework` AES-CBC + CS 回话）：**出站推送 = GO 完全就绪**（仅需填 3 个 `IS_WEWORK_*` corp 变量 + 建 `channel="wework"` 订阅）；**入站客服回话 = GO-with-condition**（另需 `IS_WECOM_*` AES 三件套，缺则 `app.state.wecom_crypto=None` → `/webhooks/wework` 全 503，可独立后补不影响出站）。代码层零功能缺口（排除两处疑似破口：`api.webhook_crypto` 是 `core.webhook_crypto` 纯再导出 → `except WeComCryptoError` 正确捕获不会 500；soft-disable 不拖垮 lifespan）。暴露并修 **2 文档缺口**：**R-001 MEDIUM** deploy-spec §2.3/§2.4 完全缺失 `IS_WECOM_*` 三变量（B-034 doc-drift 只覆盖 .env.example+walkthrough，漏正卷）→ 补全；**R-002 LOW** `IS_WEWORK_WEBHOOK_TOKEN` 为 wework webhook 死配置（路由读 `wecom_crypto` 用 `IS_WECOM_TOKEN` 验签，从不读 `wework_webhook_token`，仅 composition.py:579 警告条件引用），deploy-spec/walkthrough §0.2/CLI setup 提示均误标 → 三处订正 + §2.4 敏感度降 LOW 移出轮换表。changelog `1.0.0-rc3` 记录。门禁：deploy-spec/changelog doc-review Layer 1 **PASS**；cli ruff+format+mypy strict + cli 单测全绿（prompt 串无测试断言）。walkthrough「缺少[NAV]块」FAIL 为既有（`status:draft` 运维清单历来无 NAV，HEAD 版本 NAV 计数=0），非本次回归。**未 push，未 PR**。
  - **B-014 跨进程 worker 指标暴露 + API eager 注册 (本会话, standard TDD inline, 分支 chore/claude-md-state-sync-pr76)** — 验证"/api/v1/metrics 暴露所有新 metric"时暴露两类真实破口并修复：① **lazy 注册**：`http_requests_total`（首个非-metrics 请求后）/ `llm_circuit_open`（熔断器首次 transition 后）→ 冷启动 scrape 抓不到 → `RequestLoggerMiddleware.__init__` + `CircuitBreaker.__init__` eager 注册（API 启动 build_llm_gateway 必建 breaker）。② **worker 跨进程不可达**：prefork 多进程每子进程独立 collector 不暴露 HTTP，`celery_*` 永进不到 API collector，而 prometheus.yml worker job 却指 api:8000（失效假设）→ 新增 [observability/shared_metrics.py](src/intellisource/observability/shared_metrics.py) `RedisMetricStore`（跨进程 Redis hash，sync client，Redis 宕机 graceful no-op）；`signals` postrun/failure 写 celery_* + `boot.worker_init` seed 0；`system.metrics_response` 读 store merge 进 exposition；prometheus.yml 收敛单一 scrape job（删重复 worker job 消除双标签）。deploy-spec §3.5 指标表 label 订正（MetricsCollector 无 labeled-histogram；http/celery counter 实为 unlabeled）。**+19 单测**（store 11 / 端点 5 族 present 3 / signals 3 / circuit eager 2），端点测试即 staging curl grep 的永久 CI 替代。2972→**2991 PASS**；mypy --strict 177 + ruff + lint-imports 8/8 clean。
  - **PR #76 codebase 架构审查 + 深层重构 (merge ae379f8, CI 绿)** — 在自动化治理全绿基线上扫描工具检测不到的语义层债务，[CODE-SCAN-arch-r1](docs/reviews/code/CODE-SCAN-arch-20260529-r1.md) D-1~D-8 全闭环：① SSOT 常量收敛（`config/constants.py` MAX_NAME_LENGTH / `distributor/channels/constants.py` MAX_RETRY·RETRY_INTERVAL·TOKEN_EXPIRE_BUFFER）② push-result 骨架上移 `BaseDistributor._build_result`（数据等价）③ 统一配置中心 `core/settings.py`（pydantic-settings 收敛 14 文件 ~35 处 env 读取 + 修复 main.py 模块级 env import 期缓存污染 latent bug）④ 47 业务模块 → structlog `get_logger`（JSON Lines；signals/middleware 刻意留 stdlib 作 B-040 载体；16 处 caplog→capture_logs）⑤ 删死代码 `ModelConfig` ⑥ `strict._retry_step` 静默重试补 debug 日志。**B-020~B-028 架构治理债同批闭环**。本会话实测 2972 PASS / 全 gates 绿不退化
  - **PR #75 (merge e3fd5d3, docs-only)** — B-011 弱断言闭环 + 框架级 backlog 打包上游 bundle + B-013/B-040/B-060 回填为 main 已闭环
  - **B-011 弱断言强化增量 (orchestrator 主线程 inline + 1 子代理 stall 后自驱, PR #74)** — 用户裁定"避免修饰断言绕过规则，允许真正有用的断言暴露缺陷"。AST 检测器精确筛出"真正修饰性"弱断言（`assert X is not None` 为某测试唯一验证、无同测试兄弟断言引用 X）：`test_repositories.py` 21→13（剩余 13 全为类型收窄 guard）+ 跨 23 文件 64→18。共强化 **46 处 + repositories 圈**：class import→`isinstance(X,type)`、dataclass→`dataclasses.is_dataclass`、pydantic schema→`issubclass(BaseModel)`、module import→`hasattr(mod,symbol)`、package 再导出→对 canonical 定义 `is` 同一性、实例化→`isinstance(inst,Cls)`、值测试→具体内容（state_machine `to_state=="paused"`+`revoked_subtasks` list 契约 / registry `get().name` / pipeline config `name` / `celery_app.main` / metrics 再导出同一性 / repo create 全字段 round-trip + update re-fetch 持久化 + cursor 编码末项 id）。**18 处刻意保留**为合法 guard（mock.assert_awaited 前置 / alert-rule expr·annotations dereference / cli call_args 后续使用 / pool NullPool / RED-marker pytest.raises 内 / 字面 AC 断言带 message）——非修饰性，不churn。2976 PASS unit 不退化 / ruff clean。本轮未暴露 src 缺陷（强化断言全部成立）。**子代理不可靠教训**：dispatch 的 refactorer 烧 49k token / 30 tool-use 后 0 edit（git clean / 检测器仍 64）即 stall，改主线程自驱完成——以 git status + 检测器实测为准，勿信子代理 self-report。
  - **B-034 PRE-DEPLOY-WALKTHROUGH 全量文档订正 (本次会话, devops 子代理×2 + orchestrator 复核, 分支 claude/start-orchestrator-zJJPz)** — 逐条对照当前代码核实后订正 [PRE-DEPLOY-WALKTHROUGH.md](docs/deploy/PRE-DEPLOY-WALKTHROUGH.md)：步骤 2 health `{healthy,degraded}` + OpenAPI X-API-Key；§0.2 渠道 soft-disable（B-033 闭环）+ mailhog profile；步骤 6 content-process `mode:batch`；步骤 7 trace_id 改"已生效"（B-040 闭环）；步骤 8 `/llm/stats` 需 key；步骤 13 `to_addr` + 推送入口改 manual-collect 完整链路 + PII SQL `recipient_id`（无 message_preview 列）；步骤 15 删根 `/metrics`(404) + 指标家族正则改实存家族；步骤 18 DB 停 `degraded`（非 unhealthy）。**复核拦下子代理两处不实细节**：mask 示例 `a***`(虚构)→真值 `t***@example.com`、`build_worker_composition()` 无参调用（实需 session_factory+redis_client）改准确指针。**系统性补齐**全文 **33 处** 业务 curl 的 X-API-Key（块级校验 0 遗漏；豁免端点保持公开）。**子代理 self-report 不可靠**（第二个 agent 声称仅加 3 处，实测 +33）——以块级 grep 实测为准。
  - **B-012 keyword_tag 缺陷修复 + 测试强化 (本次会话, light TDD inline RED→GREEN, 分支 claude/start-orchestrator-zJJPz)** — 常量 `DEFAULT_KEYWORD_TAG` 早在 commit a35fa31 抽取（backlog 未回填）；强化测试时暴露并修复 [tools.py](src/intellisource/pipeline/processors/tools.py) `keyword_tag` 三真实缺陷：① LLM 供给的 tag_library 含空串 → `"" in combined` 恒真匹配所有内容污染 `['']` ② 空白 tag 匹配双空格文本输出垃圾 ③ 重复 tag 直通。修复：跳过 `not tag.strip()` + 按库序去重；substring 匹配保留为 Chinese 刻意契约（加 pin 测试）。`TestKeywordTag` 4→10（含常量耦合：原硬编码 `["未分类"]` 断言改引用常量）。unit 2970→2976。**另核对 B-015 已闭环**（promtool 在 CI Lint job）。
  - **PR #72 backlog P3 burndown 合入 main (merge eff264e, CI 6/6 绿)** — 4 功能项 + 1 持续项强化，无阻塞：
    - **B-046 (P3)**: `processed_contents.published_at` 永 NULL → `agent/tools/executes/process.py` `repo.create(published_at=ctx.get("published_at"))`，缺数据 fallback created_at。+1 测试文件
    - **B-043 (P3)**: `chat()` 无缓存路径 → `_chat.py` 加 cache get/set + `flexible.py` 透传 cache_key_parts + `_metrics.py` 计 hit/miss；`/search/chat` 二次执行命中。+1 测试文件
    - **B-047 (P3)**: sync `/search/chat` sources count=0 + answer 返 dict.repr → `search.py` 修正 `_extract_sources` walk + 强制 LLM answer 整形；`response_utils.py` 对齐。+1 测试文件
    - **B-049 (P3)**: distributor silent-success（channel 返 failed 仍记 sent）→ `facade.distribute` 检查 `result.status == "failed"`（方案 B，不改 channel 契约）→ 写 status=failed + skipped++。+1 测试文件
    - **B-011 (持续项)**: 11 个测试文件弱断言 `assert x is not None` 强化为语义断言（integration 多数 + `test_app_entry.py`）
  - **前次会话闭环（详见 HISTORY 索引）**:
  - **B-040 + B-060 observability 闭环 + zhparser 搜索修复 + pytest-xdist** (standard/light TDD inline + 真起栈验证, 本地分支 `fix/observability-b040-b060` 4 commits 未 push): 用户裁定"先修 observability 再放行"。
    - **B-060 (P3)**: 失败 LLM 调用此前 0 落表。`LLMCallRecord` 加 `error_message` + `CostTracker.log_call` 透传；`_unified_call_with_retry` 中央失败 emit（熔断 OPEN→`circuit_open` / 重试耗尽→`timeout`(Timeout 名)|`error`），覆盖 complete/chat/stream/embed 四路径。真栈：注入坏 LLM key → `llm_call_logs` 非 success 行 **0→20**（5 `error` 带真 `litellm.BadRequestError` msg + 15 `circuit_open`），熔断 OPEN。+7 单测
    - **B-040 (P3)**: trace_id 传播成立但 grep 0 命中，**真因三重**——① Celery `worker_hijack_root_logger` 未关（自有 formatter 覆盖）② `worker_redirect_stdouts=True` 把 sys.stderr 换成 LoggingProxy（早于 `setup_logging`，吞掉行）③ `boot.worker_init_handler` 的 `setup_logging()` 在 `_celery_tasks` 幂等 guard 之后（forked child 短路则不配置 root）。修：两 conf 关闭 + setup_logging 提到 guard 前 + signals prerun/middleware inbound 各发一条语义 INFO 承载行。真栈：`POST /tasks/collect` → 同一 trace_id 同时现于 api inbound + worker prerun。+6 单测（含 boot-guard + redirect 回归）
    - **zhparser 搜索 500 修复（pre-existing）**: `storage/vector.py` `to_tsvector('zhparser',...)` 在 001 早于 zhparser 加入前迁移的库上 500（"text search configuration zhparser does not exist"）；alembic 不重放已应用的 001 → 新增幂等前向 migration `e5f6a7b8c9d0`（`CREATE EXTENSION IF NOT EXISTS` + 守卫式 TS config，downgrade no-op）。真栈：从缺 ext 的库 `upgrade head` 重建 ext+config，`POST /search` **500→200**；integration 163 pass 验证迁移
    - **pytest-xdist**: `test-unit` 加 `-n auto`（unit 进程隔离安全）；不入全局 addopts / integration（testcontainers session-scoped 容器会按 worker 倍增）。2948 pass，36.6s→26.0s
  - **编码可移植性修复 (PR #70 已合入)**: 非 utf-8 locale（Windows gbk）下 `read_text()`/`open()` 无 `encoding=` → UnicodeDecodeError，致 `test_project_structure.py` 20 例失败（CI Linux/utf-8 不受影响）。修 [test_project_structure.py](tests/unit/test_project_structure.py) 3 处 pyproject read + 生产 read-side 3 处加固（[filter.py](src/intellisource/llm/processors/filter.py) 敏感词配置 open / [model_config.py](src/intellisource/llm/model_config.py) / [pipelines.py](src/intellisource/api/routers/pipelines.py) yaml read 均补 `encoding="utf-8"`）。全 src read-side 复扫无残留。20 fail→0，全量在 gbk locale 亦全绿
  - **B-059 (P1/HIGH，PR #69 已合入)** (standard TDD inline, RED→GREEN→真栈验证): Celery broker/result-store 宕机时 collect 派发快速失败。真栈复测修正根因——主阻塞是 result 后端重连重试 ~100s 抛 RuntimeError（非 broker publish）。`celery_app` broker+backend 双侧 socket 超时 + `result_backend_always_retry=False`/`max_retries=0`；`dispatch` retry=False + 包装连接错误/后端 RuntimeError → `BrokerUnavailableError`；`tasks.collect` catch → 503 + get_db_session 回滚 task 行。真栈：stop redis → 503/7.9s（非挂起）+ 行数不变 + start redis 202/0.04s 自愈。+14 测试
  - **B-031 阶段 6-7 步骤 15-20 自动驱动真起栈走查** (orchestrator 主线程 + Bash，步骤 16 N/A): 冷栈 bootstrap（13 表 / vector+pg_trgm / api+worker+beat+prometheus healthy / 2 sources）。**步骤 15** GO（Prometheus healthy + 8 alerts + scrape target up）+ 2 doc-staleness（根 `/metrics` 404 / `collector_/pipeline_/task_queue_` 家族不存在）；**步骤 17** 偏差（trace_id 功能成立 + `x-trace-id` 头返回，但 log-grep 0 命中 → 归 B-040，真因 Celery hijack + 热路径无 log）；**步骤 18** GO（db down→checks.db unhealthy + health 200 + 业务 500 + 4s 自愈，top=degraded 措辞 note）；**步骤 19** GO 3/3（熔断 OPEN + truncation 降级 + processed_contents 34→40 + 客户端无 5xx + HALF_OPEN 恢复；偏差：失败未落 llm_call_logs→B-060）；**步骤 20** 核心 GO（redis down→checks.redis unhealthy + 非 redis 路径 200 + 9s 自愈）+ **1 HIGH 偏差 B-059**（collect 派发 broker 宕时 HTTP 000 挂起无 fast-fail）。**无代码改动**（仅 .env 临时注入已还原）；详见 [CORRECTIONS-LOG 2026-05-29](docs/reviews/CORRECTIONS-LOG.md)。新立 **B-059 (P1/HIGH)** + **B-060 (P3)** + **B-040 增补** + doc-staleness 并入 B-034
  - **B-058 follow-up** (REFACTOR-only, inline): router-service 完全收敛 + ReloadRequest.config_name 死字段拆除。[sources.py](src/intellisource/api/routers/sources.py) 5 端点全部走 `Depends(_get_service)`，body 类型直接为 `SourceConfig` / `SourcePatchRequest`，无嵌套 DTO + helper 转换层；POST 改 idempotent upsert by name（删 409 IntegrityError 处理）。[service.py](src/intellisource/source/service.py) `list_paginated` 接 `type/status/tag` 过滤、`patch` 内部 `metadata → metadata_` ORM 列名映射。删除 3 个 mock-driven 假象测试文件（共 17 测试，已被 [test_service.py](tests/unit/source/test_service.py) real SQLite 完整覆盖）；[test_sources.py](tests/unit/api/test_sources.py) 改 `dependency_overrides[_get_service]` 模式 + 删 4 假象测试 + 新增 2 个 rollback router smoke。[test_deps_integration.py](tests/unit/api/test_deps_integration.py) `test_sources_router_uses_deps_get_db_session` 改 `inspect.signature(_get_service)` 间接 dep chain 验证。Unit 2879→2862 PASS 净 -17。mypy strict + ruff + lint-imports 8/8 clean
  - **B-058 P1** (前次会话, TDD standard, RED→GREEN sub-agent dispatch): 新增 `SourceConfigService` + reload 补 record_version_async (B-058a) / rollback 真调 bulk_sync_from_configs 写回 DB (B-058b real bug 修复) + bulk_sync_from_configs update 分支补 `status='active'` 重激活语义。+23 测试
  - **B-057 P2** (前次会话, light TDD inline): [matcher.py](src/intellisource/distributor/matcher.py) `_matches` 加 `source_names` 强约束维度。+12 测试
- Learnings Registry（详见各 RETRO 报告）: [RETRO sprint-1~7 / sprint-8 / sprint-9](docs/reviews/retro/) 9 EXP — EXP-005 装配缺口 → B-017 / EXP-006 truncation → 跨角色 / EXP-007 Mid-Progress Drop Contract → B-018；**EXP-CONTRACT-DRIFT (PR #64)**：改 `api/routers/` 返回类型 / `search.*` dataclass / `storage.*` SQL SELECT / `llm/gateway/_stream` 等"契约文件"必须 push 前跑 `make test-integration`（mock fixtures 常用旧契约 shape）；强制门禁通过 `make contract-check` + `make check-all`
- 上游反馈: [docs/feedback/](docs/feedback/) — 1 bug + 1 suggest (B-019 未闭环)
- Backlog 总入口: [docs/BACKLOG-intellisource-v1.md](docs/BACKLOG-intellisource-v1.md) — **release 已放行；剩余全部非阻塞** / 框架级 B-016~B-018/B-036/B-038/B-019 已移交上游闭环 / B-011/B-013/B-014/B-020~B-028/B-040/B-060 已闭环 / **项目级真债剩余（保留跟踪）: 仅 BGE-M3 本地 embedding 暂缓**

## 文档导航
- 导航索引: `docs/.doc-index.json`（机器索引，所有 Agent 通过 `cataforge docs load` 查询；缺失时运行 `cataforge docs index` 重建）
- 通用规则: .cataforge/rules/COMMON-RULES.md
- 子代理协议: .cataforge/rules/SUB-AGENT-PROTOCOLS.md
- 编排协议: .cataforge/agents/orchestrator/ORCHESTRATOR-PROTOCOLS.md (orchestrator专属)
- 状态码Schema: .cataforge/schemas/agent-result.schema.json
- 加载原则: 按任务需要通过 `cataforge docs load` 加载相关章节，不全量加载

## 全局约定
- 命名: PEP 8（snake_case / PascalCase）
- Commit: Conventional Commits（feat/fix/docs/chore/refactor/test）
- 分支: GitHub Flow（main + feature branches）
- 设计工具: none
- 人工审查检查点: [pre_dev, pre_deploy]
- 文档类型命名: 小写 kebab-case
- 效率原则: 最小传递 (doc_id#section)、不确定调研、选择题优先、长文按 `DOC_SPLIT_THRESHOLD_LINES` 拆分

## 框架机制
- Agent编排: orchestrator 通过 agent-dispatch skill 激活子代理
- DEV阶段: orchestrator 通过 tdd-engine skill 编排 RED/GREEN/REFACTOR 三个子代理（独立上下文）
- Skill调用: Agent按SKILL.md步骤式指令执行工作流
- 状态持久化: PROJECT-STATE.md + docs/ 目录
- 子代理通信: 通过文件系统(docs/和src/)传递产出物路径
- 运行时: 由 framework.json runtime.platform 决定（deploy 自动适配）
- **写权限**: PROJECT-STATE.md 由 orchestrator 独占写入；其他Agent只写 docs/ 或 src/ 下的产出文件
- 统一配置 `.cataforge/framework.json`:
  - `upgrade.source` — 远程升级源配置。升级时保留用户已配置值，仅补充新字段
  - `upgrade.state` — 本地升级状态。升级时始终保留
  - `features` — 功能注册表。升级时全量覆盖
  - `migration_checks` — 迁移检查声明。升级时全量覆盖
## 工具使用规范
- 优先使用 LSP 工具（go_to_definition, find_references, hover）查找符号定义和引用
- 避免用 grep/ripgrep 搜索代码符号，除非是搜索字符串字面量

## 执行环境
- 包管理器: uv（fallback: pip）
- 安装: `uv sync`
- 测试: `uv run pytest`（全量）；`uv run pytest tests/unit/<path>` 单文件
- 类型: `uv run mypy --strict src/`
- 格式: `uv run ruff format . && uv run ruff check .`
- 容器: docker / docker-compose（docker/）
- 迁移: `uv run alembic upgrade head`

