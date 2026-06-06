---
id: code-scan-arch-20260605-r1
doc_type: code-review
author: reviewer
status: draft
deps: [arch-intellisource-v1-modules, backlog-intellisource-v1]
---

# IntelliSource 架构重构诊断报告 (CODE-SCAN-arch-20260605-r1)

> 本报告在自动化治理全绿（import-linter 8/8 KEPT + mypy --strict + ruff + vulture + deptry）的基线上，聚焦静态工具与既往 D-1~D-8 扫描都捕捉不到的"剩余语义层深债"。所有 finding 已对抗核验、剔除假阳；本会话另对核心断言（god module 行数、`TaskChainPersister(` 零实例化、13 个 storage.models 跨包导入、版本号漂移、`self: Any` 计数）做了二次实测复核，全部成立。

## 1. 现状评估

按评审维度组织。严重度三档：高 / 中 / 低。

### 1.1 包结构与分层边界 (package-structure / layering-boundaries)

| 位置 | 问题 | 严重度 | 影响 |
|------|------|--------|------|
| `composition.py:81` + `pyproject.toml:298` (3×ignore_imports) | composition.py 双角色：既是组合根又导出下层消费的 `SOURCE_TYPE_TO_PIPELINE`/`CompositionError`/`get_agent_runner_holder`，逼出 scheduler.boot / scheduler.beat_sync / agent.factory 三条反向边，靠 ignore_imports 豁免。BACKLOG B-023 标 ✅ 但 `composition.py` 仍是 746 行单文件，修复从未落地 | 高 | 全项目唯一 3 处官方豁免的分层缺口集中于此；import-linter 对这三条边永久失明，新增反向 import 会被顺带放过；BACKLOG ✅ 制造"债已还"假象 |
| 多模块直接 `import storage.models`（13 个 storage 包外模块） | facade._load_content_and_subscriptions 内联 `select+selectinload`；boot._RawContentResultRepo.create 内联 `select(RawContent)`+直改 `row.status` + `commit()`；source/subscription service.delete() 取 ORM 后直改属性 + `session.flush()`。repository 层被绕过 | 高 | 同一种"读 ProcessedContent+订阅"/"回填 RawContent.status"逻辑在 facade、boot、ContentRepository 三处各写一遍，无法统一测试/切换实现；ORM 惰性加载散落各层；正是 B-061（subscription_id='' 误判）、B-062（MissingGreenlet）类缺陷温床 |
| `config/loader.py:209-297` (ConfigVersionManager) | config 横切层用 `text(f"INSERT INTO {self._table_name} ...")` f-string 拼表名跑裸 SQL，绕过 ORM/repository；sync_to_db 在 config 层函数体内 import SourceRepository 驱动 ORM 写 | 中 | 横切层与 storage schema 强耦合，列名变更要改 config 层裸 SQL；表名插值模式是 latent 注入面（当前调用点全是固定字面量，故非可利用，但模式本身是边界破口） |
| `scheduler/boot.py` (8×PLC0415 + 4×E402) + `celery_app.py:101`↔`tasks.py:21` | scheduler 是全仓 import 顺序最脆弱处：celery_app 末尾反向 import tasks、tasks 顶层 import celery_app 形成初始化顺序敏感循环，靠 noqa 压制而非结构解耦 | 低 | 改任一 import 顺序/拆 boot.py/换 Celery 初始化都可能触发隐蔽 partial-init 崩溃；linter 被 noqa 屏蔽，回归只能靠真起栈（历史 trace_id 不传播 bug 根因正是此类） |

### 1.2 耦合与抽象 (coupling-abstraction)

| 位置 | 问题 | 严重度 | 影响 |
|------|------|--------|------|
| `runner.py:374-443` vs `flexible.py:846-918` | `_filter_tools`/`_build_tool_descriptors`/`_analyze_denied_tools` 在 AgentRunner 与 FlexibleLoop 字节级重复；runner.py:16-21 还顶层 import flexible 的 5 个下划线私有函数做转发。**实测 runner 自身这套方法在 src/ 零调用，仅被单测拉活** | 高 | 工具权限是安全敏感逻辑（决定 LLM 能调哪些改外部状态的工具）。两份副本漂移会导致"同一工具在不同入口权限不同"；单测验证的是死副本，FlexibleLoop 真实路径回归时测试照样绿（测试盲区） |
| `runner.py:460-513` vs `persistence.py:25-69` | `AgentRunner._persist` 与 `TaskChainPersister.persist` 逐字相同（含相同 ValueError 串）。**`TaskChainPersister(` 全仓零实例化**（已二次实测），却在 `executors/__init__.__all__` 导出 | 高 | 持久化逻辑双真相源；Persister 是导出的死类，误导后人以为"改 Persister 就够"；TaskChain 构造逻辑泄漏到 agent 层 |
| `channels/wework.py:161` / `wechat.py:82` / `base_cs_client.py:57` | get_access_token 三套并行实现，WeWorkDistributor 与 CS client 共用同一 Redis key `wework:access_token`，但 distributor 用 `set`+`expire` 两步非原子、CS client 用原子 `set(ex=ttl)` | 高 | 同一 corp token 两路径写同一 key：非原子 set+expire 在崩溃时留永不过期 key，或两路径互相覆盖 token/TTL；现成正确的 BaseCustomerServiceClient 抽象被弃用重造轮子 |
| `api/routers/` (32 处 getattr) + `composition.py`/`main.py` (写入侧) | 13 个 app.state 服务句柄靠字符串键 `getattr(request.app.state, 'agent_runner', None)` 读取，写入分散在 composition 与 main 两模块，无类型化 AppState | 中 | 改注册键名读侧静默回落 None → 端点降级 503 而非编译期错误；mypy --strict 完全看不见；是 api 层覆盖最广的隐式无类型契约 |
| `source/service.py` vs `subscription/service.py` (整体) | 两 service 约 60% 平行实现（list_paginated/get/list_versions/diff/create/patch/delete/bulk_sync/rollback 一一对应），缺共同基类；delete() 双份绕过 repository 改 ORM | 中 | 版本快照/回滚/软删除复杂逻辑维护两份，易漂移；topic.service 同依赖二者放大耦合 |
| `facade.py:254-309` | facade 业务方法体内拼 SQLAlchemy select/selectinload，绕过 Repository | 中 | selectinload eager-load 契约散落 facade；B-057 source_names 匹配依赖此 eager-load，他处遗漏即触发会话外惰性加载 |
| `boot.py:238,330` + `composition.py:502` setattr / `tasks.py:323` getattr | 用 setattr/getattr 把 Celery app 当无类型进程注册表（`_celery_tasks_instance`/`_scheduler_manager`/`_periodic_digest_runner`） | 中 | 生产者消费者仅靠私有属性名字符串对齐；属性名改动/挂载顺序错则 getattr 静默 None → 任务内崩溃而非装配期失败 |
| `digest_dispatch.py:25` / `frequency.py:32` / `periodic.py:39` (`_Clock`)；`embedder.py:65` / `summarizer.py:73` (`_run_coro`)；`manage.py:81` / `run.py:22` (`_wiring`) | 三组纯工具 Type-1 克隆分散多文件 | 中/低 | sync/async 桥接是并发敏感代码（曾致 event-loop 崩溃），两份副本漂移引入难复现崩溃；时钟/接线抽象无单一事实来源 |

### 1.3 类型契约 (typing-contracts)

| 位置 | 问题 | 严重度 | 影响 |
|------|------|--------|------|
| `llm/gateway/*.py` (7 处 `self: Any`) | LLMGateway 6-Mixin 继承全用 `self: Any` 绕过 mypy；方法体内对 `self._routing_config`/`circuit_breaker` 等共享属性访问全退化 Any。`_RetryMixin` 已有正确的类级属性声明范式却未推广 | 高 | LLM 网关是熔断/重试/回退/成本中枢，是全系统稳定性最敏感代码；self:Any 让这里成为 strict 检查盲区——属性拼错、协议不匹配、返回类型错全不报，是"mypy 绿但不安全"最大单点 |
| `agent/tools/results.py` + `step_params.py` + execute 函数 | agent tool 结果是裸 `dict[str, Any]`，真实负载键（raw_content_ids/content_id/...）自由拼装无 schema；merge_step_output 逐 tool_name 字符串解码 + 多处 isinstance 守卫；process 的 result 字段单/多态（dict vs list） | 高 | 这是"触发→查结果"链路反复断裂的同类根因（历史 collect→process→distribute content_id 传递缺陷、B-061 断链）；改键名 merge 静默拿 None → 0 推送，mypy 全绿，mock 用旧形状无法暴露 |
| `agent/deps.py:25-36` (12 字段全 Any) + 31 处 `tool_deps: Any` | ToolDeps 依赖注入容器 12 字段全 Any，所有 execute 首参 `tool_deps: Any`，属性/方法访问不受检查 | 中 | agent 工具层是 LLM 实际驱动执行面；字段拼错、工厂签名不匹配、漏返回 status 全放过，只在真起栈暴露（历史"mock 覆盖致漏网"多次记录） |
| `api/composition.py`+`main.py` (13 句柄) / 32 getattr | app.state 13 服务句柄无类型化 AppState 契约（与 coupling 维度重叠，类型视角强调 mypy 不可见） | 中 | 同上：键名错误/缺失只能端到端起栈发现 |
| `agent/dto.py:12-32` | ProcessedContentDTO 全 9 字段声明 Any + arbitrary_types_allowed，docstring 明言"为让 MagicMock 通过校验"——测试驱动倒逼生产 DTO 放弃全部 pydantic 校验 | 中 | DTO 存在价值（结构化+校验 ORM 行）被自身抽空；id 可任意类型、tags 可非 list，pydantic 不再拦截；model_dump 还得手写 _coerce 兜底 |
| `config/pipeline_models.py:30` + `strict.py:56` | PipelineConfig.steps 是 `list[dict[str, Any]]`，执行器 `step['tool']` 字符串键访问无 StepSpec | 中 | step 来自 YAML/DB（用户/LLM 可控输入），缺 'tool' 键直接 KeyError 而非受控校验 |
| `executors/strict.py:28` / `flexible.py:32` (9 处 `Callable[...]`) | AgentRunner↔执行器的 emit_*/persist 回调全 `Callable[..., Coroutine]`，实参个数/类型无编译期校验 | 低 | 回调签名漂移不被 mypy 捕获，只运行时 TypeError |

### 1.4 死代码与冗余 (dead-code-redundancy / pythonic-quality)

| 位置 | 问题 | 严重度 | 影响 |
|------|------|--------|------|
| `agent/executors/persistence.py` (TaskChainPersister) | 提取后零实例化的死类（已实测 `TaskChainPersister(` 全仓 0 命中），仍在 __all__ 导出 | 高 | 见 1.2；__all__ 导出制造虚假公共 API |
| `agent/runner.py:374-443` (工具过滤方法) | 生产零调用、仅单测拉活的死副本 | 高 | 见 1.2；vulture 因测试 import 失明 |
| `search/chat_session.py:39-41` (_find_session 死桩) | 永返 None，get_or_create 永远新建不从 DB 恢复；生产仅用 maybe_compact，get_or_create/add_message 仅测试调用 | 高 | 整条会话恢复状态机不可达却看似完整，与 api/chat_sessions.py 真实路径职责重复+认知误导 |
| `matcher.py:156` (DeliveryTracker) / `adaptive.py:62` (RetryPolicy) / `formatter.py:9` (FormatConverter) | 三类 src 零生产调用，仅 tests import 逃过 vulture | 中 | 死代码携带各自测试制造"已实现"假象（RetryPolicy 对应 AC-012 自动重试，实则采集层 0 重试，与 B-063 一致） |
| `runner.py:445-458` (3 staticmethod 转发) + `runner.py:16-21` import | 转发 flexible 私有函数为 src+tests 零调用的死 staticmethod | 中 | 死方法 + 跨模块私有符号泄漏，固化 runner↔flexible 紧耦合 |
| `distributor/webhooks.py:123-135` (WeWorkWebhookHandler.handle_message) | docstring 自述 "Legacy no-op stub"，路由已移至 api.routers.webhooks，无调用方 | 低 | 误导性抽象 |
| `agent/compaction.py:44` (_PROTECTED_TOOL_COUNT) | 纯再导出薄壳 + agent 包内零引用的死常量 | 低 | 误导性间接层 |
| `agent/pipelines/paths.py` (PIPELINES_DIR) | 全仓零引用 | 低 | 包结构噪音 |
| `collector/sources/` (空 __init__) | auto_discover 仍扫空目录，三个真实适配器在 adapters/ | 低 | 双目录职责割裂，auto_discover 当前是死路径 |
| `llm/priority_queue.py:48-64` | dequeue 用 asyncio.Queue 全量 drain→sort→回填反惯用法；**特性当前 dormant（enqueue/dequeue 零生产调用方）** | 低 | 当前无运行时影响；接入后背景队列变长退化 + drain/refill 竞态 |

### 1.5 依赖与技术债 (dependencies-techdebt)

| 位置 | 问题 | 严重度 | 影响 |
|------|------|--------|------|
| `pyproject.toml:29` (opentelemetry-api) | 完全幽灵依赖：全库零引用零 OTEL_* env，tracing 实际用 uuid+structlog；靠 DEP002 ignore（注释失真）+ test_project_structure.py:47 断言虚假坐实 | 中 | 供应链无谓扩大；deptry 虚假注释误导后人不敢删；结构测试把幽灵依赖固化为契约 |
| `pyproject.toml:31` (aioredis) | 冗余且废弃：代码用 `import redis.asyncio as aioredis` 别名（真实 `aioredis` 包 import = 0），而独立 `aioredis` 已停止维护、2.0.1 为末版、功能早已并入 redis-py 的 `redis.asyncio`（现代 Python 下 import 亦不可靠） | 中 | 声明一个零代码路径使用、已废弃无人维护的包；给安全扫描制造无主条目 |
| `main.py:333`(0.1.0) / `health.py:99,141`(0.3.0) / `pyproject:3`(0.4.6) / changelog(1.1.0) | 版本号 SSOT 断裂四处不一致且对外可见（OpenAPI/health 响应体），无一处读 importlib.metadata，无 git tag | 中 | API 消费方从 OpenAPI 看 0.1.0、/health 看 0.3.0，与实际 1.1.0 脱节，运维排障无法凭版本定位；每次发版手改 ≥4 处必然继续漂移 |
| `pyproject.toml:233` (regex DEP002) | regex 被错标为 litellm 间接依赖（litellm requires 列表无 regex），实为 matcher/scorer 一线 ReDoS 防护直接依赖（`regex.search(..., timeout=1.0)`，stdlib re 无此能力） | 低 | 误导维护者随 litellm 升级误删 → ReDoS 防护静默失效（恶意订阅 regex 触发 worker CPU 挂死） |
| `pyproject.toml:14` (litellm>=1.0 等) | 核心依赖下限过松无上界，litellm（高频破坏性变更）下限 1.0 vs 实装 1.83.2 跨数百版本 | 低 | 无 lock 新环境解析到不兼容版本，难复现运行时差异 |
| `pyproject.toml:224-234` (9 条 DEP002) | deptry 零问题靠 9 条 ignore 撑起，其中 aioredis/opentelemetry-api/regex 三条失真/错误 | 低 | ignore 清单是治理盲区，"已豁免=已审查"假象掩盖真实依赖债 |

### 1.6 测试质量 (tests)

| 位置 | 问题 | 严重度 | 影响 |
|------|------|--------|------|
| `tests/unit/storage/test_vector.py` + `vector.py:304-349` | hybrid/semantic SQL（zhparser + `<=>`）单测全 mock，SQL 从不被 PG 解析；行覆盖 98% 但 SQL 正确性零验证；集成层仅跑 keyword，唯一真 PG 向量测试手写 raw SQL 绕过 VectorStore。生产默认 search_mode='hybrid' | 高 | 生产最高频 RAG 路径（hybrid/semantic 融合 SQL）无任何层真 PG 覆盖；正是历史 zhparser 500 进生产的同类盲区；98% 行覆盖给虚假安全感 |
| `tests/unit/api/` (16+ 文件) | 约 25 个 api 路由测试仅 3 个走真 SQLite，其余 dependency_overrides 换 mock；裸 MagicMock 376 处 vs spec-guarded 37 处（~10:1）；手搓 ORM-mock 永不 expire/lazy-load | 高 | 凡"DB 写入后→路由序列化 ORM"的 seam（onupdate/selectinload）单测全盲；B-062 MissingGreenlet 正因 mock 掉 _get_service 漏网；下一个同类 500 仍会漏到生产 |
| `tests/unit/search/test_chat_session.py:78-95` | 把死桩 _find_session mock 成"返回真实会话"再断言 get_or_create 返回它——把唯一坏掉的环节 mock 掉 | 中 | 会话恢复在生产不工作但测试绿；多轮对话静默退化为每次新建空会话，测试无预警 |
| 死代码组件测试（TestDeliveryTracker 等） | DeliveryTracker/RetryPolicy/FormatConverter/WeWork stub 被专门测试钉死提供虚假覆盖 | 中 | 死代码在覆盖率上"看起来是活系统的一部分"，阻碍清理；有人见有测试拿去用会埋雷 |
| `pyproject.toml:58,257` + Makefile + CI | pytest-cov 已声明却零接入：addopts 无 --cov、Makefile 无 cov、无 .coveragerc、CI 无 coverage/fail_under | 中 | 覆盖率漂移完全不可见，重构高发区（flexible/facade/gateway/vector）引入的未覆盖分支无预警 |
| `tests/unit/distributor/test_facade.py` + `facade.py:359-396` | PushRecord 写错误路径（IntegrityError 幂等 skip）、wechat/wework recipient 提取、phone 掩码未覆盖（facade 81%） | 低 | 幂等写冲突容错、非 email 渠道收件人、电话掩码无回归保护 → PII 泄漏或重复推送/500 |

---

## 2. 目标架构

### 2.1 目标包结构（含与现状差异）

```
src/intellisource/
├── core/                          # 横切原语（无变化，但承接新增 SSOT）
│   ├── settings.py
│   ├── version.py            ◀NEW 单一版本事实来源（读 importlib.metadata）
│   └── ...
├── composition/             ◀拆包（现状：单文件 746 行）
│   ├── __init__.py               # 仅再导出 build_* 供过渡（最终调用点直引）
│   ├── constants.py         ◀NEW 最底层无依赖：SOURCE_TYPE_TO_PIPELINE /
│   │                              CompositionError / CompositionNotInitialisedError /
│   │                              AgentRunnerHolder / get_agent_runner_holder
│   ├── builders.py          ◀ build_llm_gateway / build_collector_registry / ...
│   ├── api.py               ◀ build_api_composition（仅 main import）
│   ├── worker.py            ◀ build_worker_composition（仅 scheduler.boot import）
│   └── app_state.py         ◀NEW class AppState(Protocol/dataclass) 13 句柄类型化
├── agent/
│   ├── runner.py                 # 瘦身：删死副本与转发器
│   ├── tool_gating.py       ◀NEW ToolPermissionResolver（filter/descriptors/analyze_denied 单实现）
│   ├── tool_call_utils.py   ◀NEW _parse/_serialize_tool_call/_session_messages 公共纯函数
│   ├── tool_results.py      ◀NEW ToolResult/CollectResult/ProcessResult TypedDict 契约
│   ├── deps.py                   # 字段从 Any → Protocol/Callable 具体类型
│   ├── executors/
│   │   ├── flexible.py           # 压到 ~500 行：抽 resolve_tool_call_action 共享
│   │   ├── persistence.py        # TaskChainPersister 真正被 runner 注入（或删除）
│   │   └── strict.py
│   └── (compaction.py / pipelines/paths.py 删除)
├── llm/gateway/
│   ├── _proto.py            ◀NEW class _GatewayProto(Protocol) 共享属性+方法签名
│   ├── _routing.py               # +_resolve_model() 收敛四路径路由解析
│   ├── _types.py                 # +_provider_of() 收敛 split('/') 兜底
│   └── _*.py                     # self:Any → self:_GatewayProto
├── pipeline/
│   ├── _async_bridge.py     ◀NEW run_coro（embedder/summarizer 共享）
│   └── processors/
├── distributor/
│   ├── clock.py             ◀NEW Clock Protocol + DefaultClock（三文件共享）
│   ├── token_cache.py       ◀NEW TokenCache（distributor+cs_client 共用，原子 set(ex=)）
│   └── (DeliveryTracker / handle_message stub 删除)
├── storage/repositories/         # 承接 facade/boot/service 下沉的 ORM 逻辑
│   └── content.py                # +get_with_source_and_subscriptions / mark_processed
├── config/
│   └── (ConfigVersion ORM + ConfigVersionRepository 承接裸 SQL)
├── api/
│   ├── schemas/                  # 承担序列化（from_attributes），消除手写 _serialize_*
│   └── routers/                  # 删 _serialize_* + getattr → state.<typed>
├── cli/                     ◀拆包（现状：单文件 1584 行）
│   ├── main.py                   # 仅 app 组装 + callback + add_typer
│   ├── commands/{source,task,pipeline,subscriptions,topic,config,template}.py
│   ├── wizard.py / doctor.py / stack.py / http.py / format.py
└── mcp_server/             ◀拆包（现状：单文件 815 行）
    ├── __init__.py               # build_mcp_server 遍历 register_*
    └── tools/{pipeline,source,subscription,template,search}.py
```

### 2.2 分层与单向依赖方向

权威分层不变（顶→底）：

```
main | cli | mcp_server
        ↓
       api
        ↓
  composition (拆包后：composition.api / composition.worker 为顶层装配)
        ↓
agent → pipeline | collector | search | distributor | scheduler
        ↓
       llm
        ↓
     storage
        ↓
  config | core | observability   (横切，被所有层依赖，自身仅依赖 core)
```

**与现状的主要差异：**

1. **composition.constants 成为最底层可被任意层 import 的常量模块** → 消除 scheduler/agent → composition 的反向边，删除 3 条 ignore_imports，分层契约恢复全覆盖。
2. **storage.models 的合法直接消费者收敛到白名单**（storage 自身 + cost_tracker），其余层只能 import storage.repositories → 新增 import-linter forbidden 契约让边界机器可守。
3. **config 横切层不再持有 ORM/裸 SQL** → ConfigVersion 升级为正式 ORM + Repository，sync_to_db 的 repo 调用上移到 service/composition。
4. **类型契约从"裸 dict/Any 字符串键"升级为"TypedDict/Protocol/具名字段"** → mypy --strict 真正覆盖 gateway 内部、tool 结果、app.state、ToolDeps。
5. **令牌缓存收敛单一 TokenCache** → 消除三套并行实现与跨路径 Redis key 竞态。

---

## 3. 重构方案

> 每组可独立提交、独立验证、独立回滚。破坏性改动单独标注并附迁移策略。**硬边界（HTTP API 契约 / DB schema / 序列化格式 / Python 3.11 下限）默认不破坏**。

### G1 — agent 执行层去重与持久化收口【非破坏 / 跨多文件 / 需改测试】
- **目标**：消除 runner↔flexible 字节级重复与死类，单一工具门控/持久化实现。
- **改动**：
  1. 新建 `agent/tool_gating.py` 的 `ToolPermissionResolver`（构造注入 tool_registry，暴露 `filter_tools(config, agent_mode)` / `build_tool_descriptors(names)` / `analyze_denied(name)`），AgentRunner 与 FlexibleLoop 共享同一实例。
  2. 删除 `runner.py:374-443` 四个死副本方法 + `runner.py:445-458` 三个 staticmethod 转发器 + `runner.py:16-21` 对 flexible 私有符号的 import；把 `_parse_tool_call/_serialize_tool_call/_session_messages` 移到 `agent/tool_call_utils.py`，两执行器各自 import 公共模块。
  3. AgentRunner 在 `__init__` 持有 `self._persister = TaskChainPersister(self._event_logger)`，`_persist` 改单行委托或直接把 `persister.persist` 注入 FlexibleLoop/StrictExecutor，删 `runner.py:460-513` 副本。
  4. flexible.py run/run_stream 抽 `resolve_tool_call_action(tc, config, agent_mode, approved_calls) -> Action` 纯函数，仅在"执行后反馈"（yield event vs 收集 result）处分叉，目标压到 ~500 行。
- **涉及文件**：`agent/runner.py`、`agent/executors/{flexible,strict,persistence}.py`、`agent/executors/__init__.py`、新增 `agent/tool_gating.py`+`tool_call_utils.py`。
- **收益**：安全敏感的工具权限逻辑单一真相源，消除"同工具不同入口权限不同"风险；runner 瘦身；TaskChainPersister 真正上线。
- **风险**：低-中。改前用 `tests/unit/agent` 现有 run/run_stream 测试做回归锚点；按 standard TDD（安全敏感+跨双路径）。

### G2 — composition 拆包 + 删除 3 条反向边【破坏（导入路径）/ 跨包 / 风险中】
- **目标**：解开组合根双角色，让分层契约恢复全覆盖。
- **改动**：拆 `composition/` 包（见 §2.1）；`SOURCE_TYPE_TO_PIPELINE`/`CompositionError`/`CompositionNotInitialisedError`/`get_agent_runner_holder`/`AgentRunnerHolder` 入 `composition/constants.py`；改 scheduler.boot/beat_sync、agent.factory、api.routers.tasks 的 import 指向 `composition.constants`；删 `pyproject.toml:299-301` 三条 ignore_imports 验证契约仍 KEPT。
- **迁移策略**：`composition/__init__.py` 可保留再导出过渡；但 MEMORY 偏好"不留 back-compat wrapper"，故**直接改全部调用点**（已 grep 出全部 import 点：scheduler.boot/beat_sync、agent.factory、api.routers.tasks、main、tests），迁移面可控。先 lint-imports 基线，改后逐条删 ignore 验证。
- **涉及文件**：`composition.py` → `composition/`、`scheduler/{boot,beat_sync}.py`、`agent/factory.py`、`api/routers/tasks.py`、`pyproject.toml`、对应 tests import 行。
- **收益**：消除全项目唯一 3 处分层豁免；常量与重型装配代码解耦，下层 import 常量不再拖入组合根导入开销。
- **破坏性**：所有 `from intellisource.composition import X` 路径变更。**必须同步把 BACKLOG B-023 的 ✅ 改回未闭环，纠正状态漂移。**
- **风险**：中。独立分支；改后 `make check-all` + `make test-integration`。

### G3 — repository 边界回收（ORM 下沉）【非破坏 / 跨多文件 / 需改测试】
- **目标**：让 repository 层真正承担数据访问，消除 B-061/B-062 类温床。
- **改动**：
  1. `ContentRepository` 新增 `get_with_source_and_subscriptions(content_id, subscription_id)`（收 selectinload 契约）+ `mark_processed(raw_id)`；facade._load_content_and_subscriptions、boot._RawContentResultRepo 改调 repo。
  2. source/subscription service.delete() 改调 `repo.update(id, status='paused')`，flush/commit 由 repo 持有。
  3. 新增 import-linter forbidden 契约：`storage.models` 直接消费者收敛白名单（storage 自身 + cost_tracker），其余层只能 import storage.repositories。
- **涉及文件**：`storage/repositories/content.py`、`distributor/facade.py`、`scheduler/boot.py`、`source/service.py`、`subscription/service.py`、`pyproject.toml`（新契约）。
- **收益**：查询/回填逻辑统一可测；ORM 惰性加载行为收口；MissingGreenlet 类缺陷有机器可守边界。
- **风险**：中。按 EXP-CONTRACT-DRIFT 纪律，改后必跑 `make test-integration`。

### G4 — config 横切层去 ORM/裸 SQL【非破坏 / 跨包 / 风险中】
- **目标**：横切层不依赖 storage，消除 f-string 表名注入面。
- **改动**：ConfigVersion 建正式 ORM 模型 + `ConfigVersionRepository`，ConfigVersionManager 改调 repository；sync_to_db 的 repo 调用上移 service/composition 注入。**短期最小修**：即使保留裸 SQL，也把表名从 f-string 改为模块级常量白名单 dict 查表，先消除 latent 注入面。
- **涉及文件**：`config/loader.py`、`config/subscription_loader.py`、`storage/models.py`、新增 `storage/repositories/config_version.py`、`source/service.py`、`subscription/service.py`、`composition.py`。
- **DB schema 影响**：ConfigVersion 已有物理表（config_versions / subscription_config_versions），仅是把裸 SQL 访问换成 ORM 映射，**不改表结构** → 非破坏。
- **风险**：中。

### G5 — 类型契约加固【非破坏（纯类型层）/ 跨多文件 / 风险低】
- **目标**：恢复 mypy --strict 对最敏感路径的真实守护。
- **改动**：
  1. `llm/gateway/_proto.py` 定义 `_GatewayProto(Protocol)`（声明 `_routing_config`/`_cache`/`_cost_tracker`/`circuit_breaker`/`_session_factory` + `_unified_call_with_retry`/`_emit_call_log`/`estimate_tokens`/`complete`），7 处 `self: Any` → `self: _GatewayProto`；`_RetryMixin` 类级声明迁入 Protocol。从 `gateway/__init__.__all__` 移除 `_classify_error`/`_load_routing_config`/`_record_llm_call`。
  2. `agent/tool_results.py` 定义 `ToolResult`/`CollectResult`/`ProcessResult` TypedDict，results.py 返回该类型，merge_step_output 入参改 ToolResult；process 多态 result 拆为永远 list 的 results。
  3. ToolDeps 12 字段 Any → 具体 Protocol/Callable（TYPE_CHECKING import 避免分层环）。
  4. `app_state.py` 定义 `AppState(Protocol)` + `get_app_state(request) -> AppState`，router 改属性访问；新增启动期断言校验必填键已注册（漏注册 → 启动 fail-fast）。
  5. DTO 字段恢复真实类型（`id: uuid.UUID`/`tags: list[str]`/`created_at: datetime | None`），测试侧改用真实 ProcessedContent 或 model_validate，删 arbitrary_types。
  6. PipelineConfig.steps → `list[StepSpec]`（TypedDict）；回调 `Callable[...]` → Protocol（优先 emit_tool_call/persist）。
- **涉及文件**：`llm/gateway/*`、`agent/{deps,dto,tool_results}.py`、`agent/tools/results.py`、`agent/step_params.py`、`config/pipeline_models.py`、`agent/executors/*`、新增 `composition/app_state.py`、`api/routers/*`。
- **收益**：网关/工具/app.state/DTO 的拼写错、类型错、漏键在 mypy 暴露，关闭"mypy 绿但不安全"盲区。
- **风险**：低（无运行时行为变化），但改动面广，建议分子提交（gateway 一个、tool 结果一个、app.state 一个）。

### G6 — 令牌缓存收敛【非破坏 / 涉及多文件 / 风险低】
- **目标**：单一 TokenCache，消除跨路径 Redis key 竞态。
- **改动**：抽 `distributor/token_cache.py` 的 `TokenCache(redis, cache_key, fetch_fn)`，统一原子 `set(ex=ttl)`，distributor 与 cs_client 共用；至少先把 WeWorkDistributor 两步 set+expire 改原子。
- **涉及文件**：`distributor/channels/{wework,wechat}.py`、`distributor/base_cs_client.py`、新增 `distributor/token_cache.py`。
- **收益**：消除永不过期 key / token 互相覆盖风险。
- **风险**：低。

### G7 — 小工具克隆收敛【非破坏 / 涉及多文件 / 风险低】
- **目标**：消除 _Clock/_run_coro/_wiring/degraded-dict 散布克隆。
- **改动**：`distributor/clock.py`（三文件 import）；`pipeline/_async_bridge.py` 的 run_coro（embedder/summarizer import）；`_wiring` 提到 `agent/tools/executes/_deps.py`；results.py 新增 `tool_degraded(tool, reason)`，14 处手写 degraded dict 收敛。
- **风险**：低（纯结构性重构）。

### G8 — god module 拆包（cli / mcp_server）【非破坏 / 跨包 / 风险中】
- **目标**：顺已有边界拆分，分离关注点。
- **改动**：cli 顺 7 个已有 sub-Typer 拆 `cli/commands/*.py` + wizard/doctor/stack/http/format（`_state` → Typer Context.obj 消除模块级全局）；mcp_server 把 24 个 @mcp.tool 拆 `mcp_server/tools/*.py` 各 export `register_*(mcp, services)`，并复用 composition 的 session_factory 消除第二套连接池与 _db_manager 命名歧义。
- **涉及文件**：`cli/main.py` → `cli/`、`mcp_server.py` → `mcp_server/`。
- **收益**：命令路径不变；handler 可单测；消除 EXP-005 装配缺口温床。
- **风险**：中（导入面大）。改后跑 cli 单测 + mcp 单测。

### G9 — 版本号 SSOT【非破坏 / 单点 / 风险低】
- **目标**：单一版本事实来源。
- **改动**：`core/version.py` 用 `importlib.metadata.version('intellisource')` 读取，注入 create_app(version=...) 与 HealthChecker；删 main.py:333 / health.py:99,141 硬编码；pyproject 与 changelog 对齐到真实发布版本 + 补 git tag；加测试断言 OpenAPI version == importlib.metadata.version。
- **API 契约影响**：OpenAPI/health 的 version 字段值会从 0.1.0/0.3.0 变为真实版本 — 这是修正失真而非破坏消费契约（字段名/结构不变），属可接受的对外修正。
- **风险**：低。

### G10 — 依赖清理【非破坏 / 单点 / 风险低】
- **目标**：删幽灵/损坏依赖，校准 DEP002。
- **改动**：删 opentelemetry-api（+ DEP002 + test_project_structure.py:47 断言）；删 aioredis（别名 `import redis.asyncio as aioredis` 不变）；regex 移出 DEP002 作直接依赖识别 + 补 ReDoS WHY 注释；litellm 抬区间 `>=1.50,<2`（sqlalchemy>=2.0.20 / pydantic>=2.5）；重生成 uv.lock；删除前 CI 跑 import 冒烟。
- **风险**：低。删除前 `uv run python -c 'import intellisource.main'` 冒烟。

---

## 4. 测试改造计划

| 操作 | 用例 | 理由 / 等价性保证 |
|------|------|------------------|
| **新增** | `tests/integration/` testcontainers-PG：直接调 `HybridIndex.search(mode='hybrid'/'semantic', query='中文词', query_vector=[...])` + HTTP `/search` search_mode='hybrid' 端到端 | 覆盖 `_HYBRID_SQL_TMPL`/`_SEMANTIC_SQL_TMPL` 真 PG 执行，封堵 zhparser 500 同类盲区；单测层保留接口契约验证但 docstring 标注"SQL 正确性由 integration 保证"，删/弱化虚假 SQL 断言 |
| **新增** | 每个有写端点的路由补 ≥1 条真 SQLite 贯通测试：真 Service + 真 AsyncSession 跑 POST/PATCH upsert，断言 201 且响应体 updated_at 非 null | 覆盖"DB 写入→路由序列化 onupdate 列"链路（B-062 真实 500 发生处）；先覆盖 sources/subscriptions/tasks 三个写最重路由 |
| **改写** | api 路由测试统一裸 `MagicMock` → `MagicMock(spec=Source)`/`spec=AsyncSession` | 访问未声明属性即报错，缩小 mock 与真 ORM 行为漂移（376→显著降低裸 mock 占比） |
| **改写** | `test_chat_session.py::test_get_or_create_returns_existing_session` | 不再 mock 死桩 _find_session；改真 SQLite persist 一行再调 get_or_create 断言同 session_id（立即 RED 暴露死桩，驱动修复或确认删除） |
| **改写** | G1/G5 工具门控测试 | `test_agent_mode.py:477/509`、`test_tool_permissions.py:142/235` 从调 `runner._filter_tools` 改为针对 `ToolPermissionResolver` 或经 FlexibleLoop 真实路径 |
| **新增** | facade 补 3 条：IntegrityError 幂等 skip / 非 IntegrityError 上抛；参数化 `_extract_recipient`/`_mask_recipient` 覆盖 email/wechat/wework/phone | 覆盖 facade.py:359-396 幂等容错 + PII 掩码（直接对纯函数单测，成本低） |
| **废弃** | `TestDeliveryTracker` / `TestRetryPolicy*` / FormatConverter 用例 / WeWork stub 测试 | 随 §6 死代码删除同步移除，停止给死代码虚假覆盖背书 |
| **废弃** | `test_runner_persist.py` 针对 _persist 死副本的断言 | 改为针对 G1 收口后单一 TaskChainPersister 路径 |

**覆盖率目标**：引入 `[tool.coverage.run]`（source=src/intellisource, branch=true）+ `[tool.coverage.report]` 初始 `fail_under=80`（与当前实测水位 flexible 86%/facade 81%/runner 83% 对齐，避免一上来红）。高风险模块（facade/flexible/gateway/_retry/vector）目标 85-90%，但**须配套真 PG 集成而非靠 mock 刷行覆盖**。注意 pytest-cov 的 C 追踪器与本机 numpy reimport 冲突，CI 设 `COVERAGE_CORE=sysmon` 或 `pytrace`。

---

## 5. 执行计划

按依赖与优先级分阶段；每步标验证方式与回滚点。破坏性步骤标风险等级。

**阶段 A — 低风险纯加固（无破坏，可并行，建立后续锚点）**
- A1 G9 版本 SSOT（单点）→ 验证：`make check` + 新增 OpenAPI version 断言测试。回滚点：单 commit revert。
- A2 G10 依赖清理（删 opentelemetry-api/aioredis、校准 DEP002）→ 验证：`uv run deptry src` + `import intellisource.main` 冒烟 + `make test-unit`。回滚点：pyproject + uv.lock revert。
- A3 G7 小工具克隆收敛（_Clock/_run_coro/_wiring/tool_degraded）→ 验证：`make test-unit` + ruff。回滚点：各克隆独立 commit。
- A4 G6 令牌缓存收敛 → 验证：distributor 单测 + ruff。
- A5 G5 类型加固（分子提交：gateway _proto / tool 结果 TypedDict / app.state Protocol / DTO / StepSpec）→ 验证：`mypy --strict` + `make test-unit`（DTO 改动须跑 test-integration）。回滚点：每子模块独立 commit。

**阶段 B — agent 执行层收口（依赖 A5 的 ToolResult/Protocol）**
- B1 G1 工具门控提取 + TaskChainPersister 接线 + flexible 双路径合流 → 验证：standard TDD，`tests/unit/agent` 全绿做回归锚点 + mypy + ruff。回滚点：分支独立。

**阶段 C — 边界回收（破坏性 / 高价值，须真起栈）**
- C1 G3 repository 边界回收 + storage.models 白名单契约 → 验证：`lint-imports`（新契约 KEPT）+ `make test-integration`（EXP-CONTRACT-DRIFT 纪律）。**风险等级：中**（行为不变但跨 facade/boot/service）。回滚点：独立分支，集成测试失败即回滚。
- C2 G4 config 去 ORM/裸 SQL（先做表名白名单最小修，再 ConfigVersion ORM 化）→ 验证：`lint-imports` + config 单测 + test-integration。**风险等级：中**。
- C3 G2 composition 拆包 + 删 3 条 ignore_imports + 改 BACKLOG B-023 状态 → 验证：`lint-imports`（逐条删 ignore 后契约仍 8/8 KEPT）+ `make check-all` + `make test-integration`。**风险等级：中**（导入路径破坏）。回滚点：独立分支，契约不 KEPT 即回滚。

**阶段 D — god module 拆包（破坏性 / 须真起栈）**
- D1 G8 cli + mcp_server 拆包 → 验证：cli 单测全绿 + mcp 单测 + `cataforge` CLI 冒烟。**风险等级：中**。回滚点：独立分支。
- D2（独立高风险，建议单列）scheduler 初始化顺序结构解耦（打破 celery_app↔tasks 循环 + WorkerRuntime typed 注册表替代 setattr/getattr）→ 验证：worker 真起栈复测（manual-collect 全链路 + beat schedule 同步）。**风险等级：高**。回滚点：独立分支 + 真起栈门禁，任一链路断裂即回滚。

**阶段 E — 死代码清理 + 测试改造（依赖各组件改完）**
- E1 §6 死代码批量清理 + 对应测试移除 → 验证：`vulture` + `make test-unit` + `lint-imports`。回滚点：合并为单一 dead-code commit，按类逐项 grep 零引用确认。
- E2 §4 测试改造（真 PG hybrid/semantic、api 真 SQLite 写端点、spec-guarded mock、覆盖率门禁接入）→ 验证：`make test-unit` + `make test-integration` + 新覆盖率 target。

**关键依赖序**：A5（类型）→ B1（agent 收口需 ToolResult）；C3（composition 拆包）独立但建议在 C1/C2 后（边界先清）；E1 死代码清理须在引用方改完后（G1 删 runner 死副本、G8 拆包后再清 compaction/paths）。

---

## 6. 死代码清理清单

> ⚠️ **处置状态以 §8 执行进度跟踪为准**。本清单是诊断时点的原始判定；其中 `RetryPolicy` / `FormatConverter` / `TaskChainPersister` 已按"接线而非删除"处置（接入生产链路），**勿再按本表删除**。`DeliveryTracker` / `webhooks.handle_message` / `compaction.py` / `pipelines/paths.py` / `search/chat_session.py` 已删除。

| 目标 | 判定依据（引用计数/调用链） | 破坏性 |
|------|---------------------------|--------|
| `agent/executors/persistence.py` 的 `TaskChainPersister`（若选不接线方案） | `TaskChainPersister(` 全仓（src+tests）**零实例化**（已二次实测）；仅 `executors/__init__.py:6,9` 定义+导出 | 否（接线方案 G1 则保留并启用） |
| `agent/runner.py:374-443` 四个工具过滤方法 | src/ 零调用，仅 `test_agent_mode.py:477/509`、`test_tool_permissions.py:142/235` 拉活；`_build_tool_descriptors` src+tests 全仓零调用；生产走 FlexibleLoop 副本 | 否（随 G1 删除，测试迁移） |
| `agent/runner.py:445-458` 三个 staticmethod 转发器 + `runner.py:16-21` 对应 import | `runner._serialize_tool_call`/`_parse_tool_call`/`_session_messages` src+tests 零调用 | 否 |
| `agent/compaction.py`（整文件薄壳 + `_PROTECTED_TOOL_COUNT`）| 死常量 agent 包内零引用（llm/compaction.py 同名常量是活的，勿混淆）；薄壳须先 grep `from intellisource.agent.compaction import` 确认零下游（仅 tests 4 处） | 是（测试 import 路径改指 llm.compaction） |
| `agent/pipelines/paths.py`（PIPELINES_DIR）| 全仓零引用 | 否 |
| `distributor/matcher.py:156-195` 的 `DeliveryTracker` | src 仅 matcher.py docstring+定义；真去重走 facade + PushRepository.exists | 是（删 `test_matcher.py::TestDeliveryTracker`） |
| `collector/adaptive.py:62-73` 的 `RetryPolicy` | src 零 import/实例化；AC-012 重试在任何 adapter 未接线（与 B-063 一致） | 是（删 `test_adaptive.py::TestRetryPolicy*`；更新 adaptive.py AC-012 注释或归 B-063） |
| `pipeline/processors/formatter.py` 的 `FormatConverter` | 未注册 `PROCESSOR_REGISTRY`（registry.py 仅 5 处理器）；get_processor 取不到；仅 test_processors.py 引用 | 是（删用例，或注册进 registry 若确需） |
| `distributor/webhooks.py:123-135` `WeWorkWebhookHandler.handle_message` | docstring 自述 "Legacy no-op stub"；路由已移 api.routers.webhooks；无调用方 | 是（确认无 import 后移除存根） |
| `collector/sources/`（空 __init__）+ registry.auto_discover 对它的扫描 | 0 字节空文件；三适配器在 adapters/ 无 SOURCE_TYPE 属性；auto_discover 当前是死路径 | 否（删目录或统一 auto_discover 机制） |
| `search/chat_session.py` 死桩子系统（`_find_session`/`get_or_create`/`add_message`/`cleanup_inactive`）| `_find_session` 永返 None；生产仅 `api/chat_sessions.py:177` 用 maybe_compact；get_or_create/add_message 仅测试调用 | 否（瘦身为 compaction 工具，或落实 DB 查询；二选一） |
| 依赖 `opentelemetry-api` | src/tests/docker/alembic 零 import 零 OTEL_* env；tracing 用 uuid+structlog | 否（删 pyproject + DEP002 + test_project_structure.py:47） |
| 依赖 `aioredis`（独立包）| 扫描 src 真实 `aioredis` 包 import = 0（全是 `import redis.asyncio as aioredis` 本地别名）；独立 `aioredis` 已停维护、功能并入 redis-py | 否（删 pyproject + DEP002，别名写法不变） |

---

## 7. 工具与门禁建议

| 工具/门禁 | 建议 | 防回流目标 |
|----------|------|-----------|
| **import-linter** | 新增 forbidden 契约：`storage.models` 直接消费者收敛白名单（storage 自身 + cost_tracker）；G2 后删除 3 条 `ignore_imports` 让 layers 契约恢复全覆盖 | 防 repository 绕过回流（G3）+ 消除 composition 反向边盲区（G2） |
| **mypy --strict** | G5 落地后 gateway/tool 结果/app.state/DTO 不再有 Any 逃逸；可加 `disallow_any_explicit` 局部开启（gateway/agent 包）逼出残留 self:Any | 防"mypy 绿但不安全"盲区 |
| **vulture** | 把 §6 死代码删除后，复核 `.vulture_whitelist.py` 移除对应豁免；考虑加 CI 检查 whitelist 不无限增长 | 防 test-import 维持死代码（vulture 当前对此失明） |
| **deptry** | 把 DEP002 ignore 清单当技术债清单定期审计：清理后从 9 条降到 6 条（asyncpg/psycopg/pgvector/alembic/lxml/uvicorn），每条注释校准；CI 加轻量检查 ignore 不增长 | 防失真注释掩盖依赖债 |
| **pytest-cov** | 接入 `[tool.coverage.run]`（branch=true）+ Makefile `test-cov` target（`--cov=intellisource --cov-branch --cov-fail-under=80`）纳入 CI；高风险模块 per-package 85-90% 但须真 PG | 防覆盖率漂移与重构引入未覆盖分支（当前完全不可见） |
| **ruff** | 维持现状；新增规则可选 `PLC0415`（函数内 import）作 warning 引导 deferred import 收敛（不强制，scheduler 例外） | 引导减少 deferred import 掩盖的架构耦合 |
| **pre-commit** | 把 lint-imports + mypy --strict + ruff + deptry + vulture 固化为 pre-commit hooks（若尚未）；新增一条版本一致性检查（OpenAPI version == importlib.metadata） | 防版本号再漂移 + 把门禁前移到提交期 |
| **真起栈门禁（CI 化）** | 对 hybrid/semantic SQL 与 scheduler 初始化顺序（D2）这类静态工具守不住的债，testcontainers-PG 集成 + worker 真起栈 manual-collect 链路应纳入 CI required check | 防 zhparser 500 / trace_id 不传播 / MissingGreenlet 类只在真起栈暴露的缺陷回流 |

---

## 8. 执行进度跟踪（截至 commit 0c189ef）

§5 阶段计划的落地状态。✅ = 已落地并过门禁；🔶 = 部分落地（剩余子项见备注）；⏳ = 待办。门禁基线：3470 单测 PASS / mypy --strict 236 files / ruff + ruff format clean / lint-imports 12/12 KEPT / deptry 0 / vulture clean。

| 组 | 目标 | 状态 | 落地证据 / 剩余 |
|----|------|------|----------------|
| G1 | agent 执行层去重 + 持久化收口 | ✅ | `agent/tool_gating.py` 单一工具门控；`TaskChainPersister` 已接线（`runner.py` `__init__` 实例化）；runner 死副本/转发器删除（瘦身至 386 行） |
| G2 | composition 拆包 + 删反向边 | 🔶 | 反向边 3→1（仅剩 `scheduler.boot -> composition` 这条 Celery `worker_process_init` inherent 边，靠 1 条 `ignore_imports`）；**composition.py 仍单文件未拆包**（B-023 待办） |
| G3 | repository 边界回收（ORM 下沉） | ✅ | `storage.models` 白名单 forbidden 契约（仅 storage + cost_tracker）；facade/boot/service 内联 ORM 下沉 repository |
| G4 | config 横切层去 ORM/裸 SQL | 🔶 | 表名 f-string → 白名单常量查表（注入面消除，最小修）；**完整 ConfigVersion ORM + Repository 待办** |
| G5 | 类型契约加固 | 🔶 | `llm/gateway/_proto.py` `_GatewayProto` 收敛 `self: Any`；`agent/dto.py` 真类型；`agent/deps.py` ToolDeps Protocol/Callable；`agent/tool_results.py` TypedDict + process 结果归一 `results`；**G5-4 app.state Protocol 待办（依赖 G2 拆包）** |
| G6 | 令牌缓存收敛 | ✅ | `distributor/token_cache.py` 单一 `TokenCache`，原子 `set(ex=)`，wework/wechat/cs_client 共用 |
| G7 | 小工具克隆收敛 | ✅ | `distributor/clock.py` + `pipeline/_async_bridge.py` 消除 _Clock/_run_coro 散布克隆 |
| G8 | god module 拆包 | 🔶 | `cli/` 已拆包；**`mcp_server.py`（815 行）仍单文件未拆** |
| G9 | 版本号 SSOT | ✅ | `core/version.py` `get_version()` 读 importlib.metadata；main.py 注入 `create_app(version=)`，health/OpenAPI 读 `app.version`，硬编码 0.1.0/0.3.0 消除 |
| G10 | 依赖清理 | ✅ | opentelemetry-api / aioredis 已删；DEP002 校准 |
| E1 | 死代码清理 + 接线 | ✅ | **删除**：DeliveryTracker / webhooks.handle_message（整模块）/ compaction.py 薄壳 / pipelines/paths.py / search/chat_session.py（ChatSessionManager 解散，compaction 内联 api/chat_sessions.py）。**接线（勿删）**：FormatConverter 注册进 PROCESSOR_REGISTRY + content-process.yaml；RetryPolicy 经 `collect_with_retry` 接入采集链路（B-063 闭环 / AC-012 落地） |
| E2 | 测试改造 + 覆盖率门禁 | ⏳ | 真 PG hybrid/semantic SQL 集成 + api 真 SQLite 写端点 + pytest-cov 门禁接入待办 |
| D2 | scheduler 初始化顺序解耦 | ⏳ | 高风险独立项（打破 celery_app↔tasks 循环 + typed WorkerRuntime）待办 |

**剩余结构债（按依赖序）**：G2 composition 包拆分（解锁 G5-4 app.state Protocol）→ G8 mcp_server 拆包 → G4 完整 ConfigVersion ORM 化 → D2 scheduler 解耦 → E2 真 PG 测试 + 覆盖率门禁。次要项：`collector/sources/` 空目录 + auto_discover 死路径清理。

---

> **报告结论**：本库自动化治理表象全绿，但语义层仍有结构性深债集中在 agent 执行层重复、composition 双角色、repository 边界失守、类型契约空洞、测试虚假覆盖五处。这些债共同的危险特征是——**静态工具看不见、单测因 mock 而绿、行覆盖给虚假安全感**，恰好覆盖系统最敏感的执行路径（LLM 网关、工具权限、RAG 搜索 SQL、ORM 写入序列化）。建议按 §5 阶段序推进，优先做低风险类型加固（建立 mypy 守护锚点）与 agent 收口，再做边界回收与拆包，破坏性步骤（G2/D2）独立分支 + 真起栈门禁。