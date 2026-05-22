---
id: code-review-T-095-r1
doc_type: code-review
author: reviewer
status: draft
deps: ["T-095"]
---

# CODE-REVIEW: T-095 统一组合根 (composition.py) + Celery 单例 + PipelineLoader + tasks API 触发契约 — r1

> Layer 1 delegated to hook (`.claude/settings.json:lint_format`); 主线程接手 inline 审查（reviewer 子代理 a6eec6998f6a611bd 在 r1 分析期 truncation；详见 EVENT-LOG 2026-05-22T... `truncation recovery` 条目）。

## 元信息

| 字段 | 值 |
|------|----|
| 任务 ID | T-095 |
| 提交范围 | commit `1b1fbf4`（PR #47 已 merge 入 main） |
| task_kind | feature |
| tdd_mode | standard |
| tdd_refactor | required（已执行，同 PR 末尾 `_install_agent_runner` + `_build_deps_bundle` 抽提） |
| security_sensitive | false |
| AC 总数 | 12（AC-1 ~ AC-12） |
| 测试套件 | 43 新测试（27 unit + 4+2 integration + 4 unit-api router 契约） |

## Layer 1 — Lint / Format / Typecheck

| 工具 | 命令 | 结果 |
|------|------|------|
| ruff | `uv run ruff check src/ tests/` | All checks passed |
| ruff format | `uv run ruff format --check src/ tests/` | 247 files already formatted |
| mypy --strict | `uv run mypy --strict src/` | Success: no issues found in 114 source files |

Layer 1 = 0（PASS）。

## Layer 2 — AI 语义审查

### AC 覆盖矩阵

| AC | 测试位置 | PASS | 备注 |
|----|---------|------|------|
| AC-1 composition.py 7 builder | tests/unit/test_composition.py::TestCompositionModuleImportable | ✓ 8 tests | 全部 builder 导出齐全 |
| AC-2 PipelineLoader.load() | TestPipelineLoader | ✓ 5 tests | 委托 `load_pipeline_config` 已断言 |
| AC-3 WorkerComposition dataclass | TestWorkerComposition | ✓ 7 tests | 5 字段全检 |
| AC-4 build_agent_runner kw-only + 非 None | TestBuildAgentRunnerKeywordOnly | ✓ 5 tests | None 入参均 raises |
| AC-5 get_agent_runner 未装配 raises | TestGetAgentRunnerRaisesWhenNotInitialised | ✓ 2 tests | 错误消息含 build_* 提示 |
| AC-6 worker_init 传非 None loader | TestWorkerInitHandlerPipelineLoader | ✓ 1 test | 用 spy 捕获实参 |
| AC-7 run_pipeline 不 AttributeError | TestRunPipelineNoAttributeError | ✓ 3 tests | 见 R-005 关于断言强度 |
| AC-8 send_task kwargs 契约 | tests/unit/api/test_tasks_router_send_task_contract.py | ✓ 4 tests | 4 维断言 |
| AC-9 main.py 删 init_celery | TestMainNoInitCelery + test_celery_singleton_unified | ✓ 4 tests | 双向断言 |
| AC-10 worker_init + run_pipeline no crash | tests/integration/test_worker_pipeline_no_crash.py | ✓ 2 tests | tool_deps 装配 + 不抛 |
| AC-11 app.state.celery_app is module 单例 | tests/integration/test_celery_singleton_unified.py | ✓ 4 tests | `is` 同一对象 |
| AC-12 send_task kwargs.pipeline_name + params.task_id/source_id | test_tasks_router_send_task_contract.py | ✓ 复用 AC-8 用例 | 共享同套断言 |

**12 / 12 AC 全部有失败测试覆盖且 GREEN 后通过。**

### EXP-005 复发审视

sprint-8r 立项核心是 ToolDeps 装配半成品（app.state.llm_gateway / Celery guards / ToolDeps 字段 silent None）。本任务对应处理：

| sprint-8r 立项点 | T-095 处置 | 结论 |
|------------------|-----------|------|
| AgentRunner.ToolDeps 5 字段 silent None | factory.py `build_agent_runner` keyword-only + 5 个 `if X is None: raise ValueError` 显式拦截 | **闭环** — 装配失败 fail-fast |
| API vs Worker Celery 双单例 | main.py 删 `init_celery`；`build_api_composition` + `worker_init_handler` 都绑定 `scheduler.celery_app.celery_app` 模块单例；`is` 断言验证 | **闭环** — CR-012 修复 |
| `run_pipeline` 启动即崩（pipeline_config=None） | boot.py 走 `build_worker_composition().pipeline_loader` 传给 `build_celery_tasks`；CeleryTasks 类型注解显式 `PipelineLoader \| None`，未装配抛 `RuntimeError("worker_init_handler must wire it...")` | **闭环** — CR-002 修复，且失败模式清晰 |
| `_PassThroughProcessor` no-op fallback | factory.py 注释明确标注「T-096 落地真实 PROCESSOR_REGISTRY 时改 fail-fast」 | 已知 stub，注释精确，**不计为本任务遗漏** |
| DistributorFacade 真实编排 | composition.py:94-133 显式定义为 stub，docstring 标注「T-097 ships real impl」，`distribute()` 返回 `status: pending`（非 `degraded`） | 已知 stub，注释精确，**不计为本任务遗漏** |

### 问题列表

---

### [R-001] MEDIUM: `/tasks/collect` 的 source_type 路由是装配半成品

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `src/intellisource/api/routers/tasks.py:155` 写 `source_type = getattr(task, "source_type", None) or "rss"`。但 `CollectTask` ORM 模型（`storage/models.py:160`）只有 `source_id`（FK）和 `source: Mapped["Source"]` lazy relationship，**没有 source_type 列也没有 selectinload**。`task` 来自上一行 `task_repo.create()` 刚返回的对象，其 `task.source_type` 永远是 None，`getattr` 永远落到 `"rss"` 默认值，再经 `SOURCE_TYPE_TO_PIPELINE["rss"]` 拿到 `"scheduled-collect"`。即任何 source 进来都路由到同一个 pipeline。

  AC-8 的字面要求「`pipeline_name`（由 `SOURCE_TYPE_TO_PIPELINE` 映射）」**形式达成**：mapping 调用确实存在；但是 mapping 的输入是死值。这是经典 EXP-005 形态：「装配点在但流量永远不变」，与 sprint-8r 试图根治的「wires-look-correct but functionally inert」同构。

  当前所有三个 source 类型都映射到 `"scheduled-collect"`，因此**今日生产无观察影响**；但 T-096+ 一旦让 SOURCE_TYPE_TO_PIPELINE 分化（例如 `web` → `web-collect`），路由会静默失效。

- **建议**:
  - 短期修补：在 `trigger_collect` 内先 `source = await source_repo.get_by_id(task.source_id)`，从 Source 行读真实的 `type` 字段，再喂给 SOURCE_TYPE_TO_PIPELINE
  - 或：`task_repo.create` 返回的 task 已带 `source_id`，发送 send_task 前用一次性 selectinload；或单独查询批量预取 `{source_id: type}`
  - 测试补：新增反证测试，让 SOURCE_TYPE_TO_PIPELINE 有非 default 项时（例如 monkeypatch 加 `"web": "web-collect"`），创建 web 类型 source 触发 collect，断言 send_task 收到的 `pipeline_name` 是 `"web-collect"` 而非 `"scheduled-collect"`
  - 若决定 T-096+ 处理，应在 task 卡和本文件加 `# TODO[T-096]: resolve source_type from Source row`，并 close 本 finding 为 deferred

---

### [R-002] MEDIUM: `worker_init_handler` docstring 声称 idempotent，实现不是

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `src/intellisource/scheduler/boot.py:133-153` 的 docstring 写 "Celery worker_process_init signal entry point; **idempotent singleton**"，但函数体（141-153）逐行：
  - 无条件 `global _celery_tasks` 后赋值
  - 无条件 `init_worker_session_factory()` 创建新 engine + sessionmaker
  - 无条件 `_build_redis_client()` 新建一个 redis 客户端
  - 进入 `build_worker_composition` 内的 `_build_deps_bundle` 又把 redis_client 传给 `build_llm_gateway`（CircuitBreaker 会持有它）
  - 末尾 `build_celery_tasks` 内部 **再次** 调 `_build_redis_client()` 新建第二个 redis 客户端（boot.py:115）

  即每次 handler 触发会产生 2 个独立 redis 客户端 + 1 个 engine + 一组 composition 对象。如果信号触发两次（pool restart / Celery test fixture / 自定义 `worker_pool="solo"` 边界）就泄漏 2x → 4 个 redis 客户端，且 `worker_shutdown_handler` 只做 `_celery_tasks = None` + `engine.dispose`，**不关闭 redis 客户端**。

  Celery 的 `worker_process_init` 在 prefork 池下每个 worker 进程触发一次（属典型工程默认），所以**生产观察影响有限**。但 docstring claim 与代码事实不符，是 test-quality 缺口；如未来引入 worker 热重启 / pool restart hooks，会成为连接泄漏源头。

- **建议**:
  - 改 1（推荐）：函数开头加幂等守卫 `if _celery_tasks is not None: return`
  - 改 2：删除 docstring 的 "idempotent singleton" 措辞，改为「Celery worker_process_init signal entry point; assembles composition graph once per worker process」
  - 改 3：补一个集成测试 `test_worker_init_handler_idempotent`，连续触发两次 handler，断言 `_celery_tasks` 与 `id(redis_client)` 不变（如果选改 1）
  - 改 4（顺手）：`worker_shutdown_handler` 增加 `await redis_client.aclose()`（虽然 prefork 下进程退出会被 OS 回收，但显式关闭仍是好习惯）

---

### [R-003] LOW: 装配失败用 ValueError/RuntimeError 而非 IntelliSourceError 子类

- **category**: convention
- **root_cause**: self-caused
- **描述**: `src/intellisource/agent/factory.py:98-107` 的 5 个非 None 校验抛 `ValueError("X is required (got None)")`；`get_agent_runner`（66-80）未装配抛 `RuntimeError(...)`。arch#§5.3 错误处理框架规定「所有模块异常继承 `IntelliSourceError` 基类，包含 `category: ErrorCategory` 枚举」，未划入此框架的失败属于约定漂移。

  这些都是 composition-time / startup-time fail-fast 错误，不流到 user-facing API（worker 进程在 init 阶段就崩，FastAPI lifespan 在启动阶段就 raise）。语义上对应 arch 表的 `UNRECOVERABLE`（配置错误），适合用统一框架的话会是 `IntelliSourceError(category=UNRECOVERABLE, recovery_hint=...)`。

- **建议**:
  - 长期：定义 `CompositionError(IntelliSourceError, category=UNRECOVERABLE)` 取代 ValueError/RuntimeError，统一 error code 形如 `IS-CMP-001`
  - 短期：保留现状（不阻断 T-095 通过），但在 backlog 中登记一条「Phase 6 testing 前补 IntelliSourceError 体系覆盖装配层」

---

### [R-004] LOW: composition 与 module-level singleton 的紧耦合

- **category**: structure / coupling
- **root_cause**: self-caused
- **描述**: `composition.py:241` 写 `agent_factory._agent_runner = runner`；`boot.py:153` 写 `setattr(_module_celery_app, "_celery_tasks_instance", _celery_tasks)`。两处都是「装配根知道并直接修改其他模块的私有 / 半私有 module-level 状态」。

  动机明确（legacy `get_agent_runner()` 调用者继续可用 + Celery `@celery_app.task` body 从 module 反查 _celery_tasks_instance），但耦合方向是反的（composition root 应是「装配产生 → 调用者引用」，现在变成「composition root 主动注入到下游模块」）。

- **建议**:
  - 长期：定义一个 `AgentRunnerRegistry` 或干脆把 `_celery_tasks` 改成 `celery_app.app_context["intellisource"]` 这类 namespace，集中管理；factory.py 的 `_agent_runner` 模块变量可以下线，所有调用方走 `request.app.state.agent_runner`
  - 已在 docstring（composition.py:255-258、235-241）明确说明这是 legacy 兼容路径 → 可接受作为 deferred 技术债，不阻断本任务

---

### [R-005] LOW: AC-7 测试的 AttributeError 断言过宽

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `tests/unit/test_composition.py:497-532` 的 `test_run_pipeline_with_real_pipeline_loader_no_attribute_error`：
  ```python
  except AttributeError as exc:
      pytest.fail(...)
  except Exception:
      pass   # 接受任何其他异常
  ```

  AC-7 的语义是「run_pipeline 在 pipeline_config 接对后不再抛 AttributeError」，但 GREEN 后回归如果引入了 `TypeError` / `RuntimeError`（例如 `_run_sync` 内的 ThreadPoolExecutor 行为变化、`PipelineConfig.mode` 类型偏移），测试会**静默放行**。

- **建议**:
  - 收紧断言：`except (TypeError, AttributeError) as exc: pytest.fail(...)` —— 把 TypeError 一起纳入，使其与 AC-10 的反 TypeError 断言对齐
  - 或：用 `with pytest.raises(SomeAcceptableException, match=...)` 显式列出可接受的异常，其余一律失败

---

### [R-006] LOW: `run_pipeline` 的 params 回退到 kwargs 自身是隐式契约分叉

- **category**: error-handling / ambiguity
- **root_cause**: self-caused
- **描述**: `src/intellisource/scheduler/tasks.py:213` 写 `params: dict[str, Any] = kwargs.get("params", kwargs)`。AC-8 把 send_task 契约约束为 `kwargs = {pipeline_name, params}`，AC-12 测试显式验证扁平 legacy keys 不在 top-level。但 worker 侧消费 (`tasks.py:213`) 仍保留「如果没有 params 就把整个 kwargs 当 params」的 fallback —— 这是一条不一致的、与 AC-8 反向兼容的隐藏路径。

  如果生产中某个直接 `send_task` 调用者（绕开 /tasks/collect router）发了旧格式，worker 不会失败，会带着错误的 params 字典执行，错误难定位。

- **建议**:
  - 改成显式拒绝：`if "params" not in kwargs: raise RuntimeError("send_task kwargs missing 'params'; legacy flat shape rejected (T-095 AC-8)")`
  - 或在 kwarg 内做 schema 校验（Pydantic）后再继续
  - 测试补一条反向用例：直接 invoke worker 侧 `run_pipeline` 入口，传 flat kwargs，断言 raises

---

## 汇总

| Severity | 数量 | finding IDs |
|----------|------|-------------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 2 | R-001, R-002 |
| LOW | 4 | R-003, R-004, R-005, R-006 |

**判定**: `approved_with_notes`

依据 COMMON-RULES §三态判定逻辑：「无 CRITICAL/HIGH，但有 MEDIUM/LOW → approved_with_notes」。

T-095 的核心目标（CR-012 双单例修复 + CR-002 worker 启动崩 + ToolDeps 装配半成品根治）已完整达成；12 AC 全部 GREEN；ruff/mypy/format 全 clean；REFACTOR 提取 `_install_agent_runner` + `_build_deps_bundle` 是真去重而非过度抽象。

2 MEDIUM 都不阻断 sprint-9 批次 2（T-096/097/098/099）启动：
- R-001（source_type 路由是装配半成品）— 今天因 SOURCE_TYPE_TO_PIPELINE 三键同值而无观察影响；T-096/T-097 引入差异化 pipeline 前必须修
- R-002（worker_init_handler 非幂等）— prefork 默认池下不触发；如 T-100 引入 Celery Beat / pool restart 路径前必须修

4 LOW 属于约定漂移 / 测试断言强度 / 技术债登记，可在 sprint-9 末端或 sprint-review 时统一收敛。

## orchestrator 后续路径

- approved_with_notes → 按 Approved-with-Notes Protocol：向用户展示 2 MEDIUM + 4 LOW，由用户选「全部接受继续」/「指定项修复后再推进」/「全修」
- 不论选择哪条路径，T-096/097/098/099/100 的批次 2 调度都不被本 review 阻断（无 HIGH/CRITICAL）

## 验证记录

- 测试套件执行：`uv run pytest tests/unit/test_composition.py tests/unit/api/test_tasks_router_send_task_contract.py tests/integration/test_celery_singleton_unified.py tests/integration/test_worker_pipeline_no_crash.py` → 43 passed in 11.80s
- 全量回归（commit 1b1fbf4 提交时声明）：2342 passed / 14 skipped / 0 failed
- Layer 1 工具链：ruff check + ruff format --check + mypy --strict 全 clean
