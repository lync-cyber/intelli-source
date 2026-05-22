---
id: code-review-T-095-r2
doc_type: code-review
author: reviewer
status: approved
deps: ["T-095"]
---

# CODE-REVIEW: T-095 — r2

> Main-thread inline r2（同 r1 因子代理 truncation 走主线程路径）。覆盖 r1 全部 6 finding 的修复审查 + 新增反证测试验证。

## 元信息

| 字段 | 值 |
|------|----|
| 任务 ID | T-095 |
| 上轮报告 | CODE-REVIEW-T-095-r1.md（approved_with_notes，2 MEDIUM + 4 LOW） |
| 用户裁决 | r2 全修 6 finding + R-004 取「引入 Holder 抽象重构」分支 |
| 修复范围 | r1 → r2 diff（未 commit 的工作区，本次评审完成后单次 commit） |
| 全量回归 | 2356 passed / 31 skipped / 0 failed (+14 新测试) |
| Layer 1 | ruff check + format + mypy --strict 全 clean |

## r1 Finding 闭环表

| Finding | r1 严重度 | r2 修复手段 | 新增测试 | r2 结论 |
|---------|----------|------------|---------|---------|
| R-001 `/tasks/collect` source_type 路由是装配半成品 | MEDIUM | `SourceRepository.get_types_by_ids(ids)` 新方法批量查 Source.type；router 在 send_task 前批量预取 `{source_id: type}`，按真实 type 进 SOURCE_TYPE_TO_PIPELINE，缺失行回退 "scheduled-collect" | `test_send_task_pipeline_name_routes_by_source_type`（验证 web → web-collect）+ `test_send_task_pipeline_name_falls_back_when_source_missing`（缺行回退） | **闭环** |
| R-002 worker_init_handler docstring vs 实现不符 | MEDIUM | 函数开头加 `if _celery_tasks is not None: return` 守卫；docstring 改写「Idempotent across repeated signal firings: 若已 set 则直接 return…」；test_celery_routes.py 三个相关 test class 加 autouse fixture 重置 `_celery_tasks` 避免守卫遮蔽 | `TestWorkerInitHandlerIdempotent::test_second_invocation_does_not_rebuild`（3 次 invoke 后 build_worker_composition 仅 1 次） | **闭环** |
| R-003 ValueError/RuntimeError vs IntelliSourceError 体系 | LOW | composition.py 新增 `CompositionError(IntelliSourceError, ValueError)` + `CompositionNotInitialisedError(IntelliSourceError, RuntimeError)`；factory.py 5 个 None 校验改用 CompositionError；get_agent_runner 经 holder 抛 CompositionNotInitialisedError；MRO 多继承保持 `raises(ValueError)` / `raises(RuntimeError)` 向后兼容 | `TestCompositionErrorHierarchy` 5 个 test（isinstance + category=UNRECOVERABLE + 实际 raise 行为） | **闭环** |
| R-004 module-singleton 紧耦合 | LOW | composition.py 新增 `AgentRunnerHolder` 类（install / get / reset / installed 属性）+ `_global_agent_runner_holder` 模块单例 + `get_agent_runner_holder()` getter；composition._install_agent_runner 改 holder.install 替代 `agent_factory._agent_runner = runner`；factory.py 删 `_agent_runner` 模块变量，get_agent_runner() 改 lazy import + 转发；4 个 test 文件全量迁移（test_composition.py + test_factory.py + test_celery_routes.py + test_worker_pipeline_no_crash.py） | `TestAgentRunnerHolder` 4 个 test（singleton + install/get + reset + factory 模块清洁） | **闭环** |
| R-005 AC-7 测试 `except Exception: pass` 过宽 | LOW | 改成 `except (AttributeError, TypeError) as exc: pytest.fail(...)` + 显式列 `except (RuntimeError, ConnectionError): pass`；注释说明「TypeError = wiring crash」 | （改既有 test 断言，无新 test） | **闭环** |
| R-006 `tasks.py` params 回退到 kwargs 自身 | LOW | 抽出 `_run_pipeline_body(**kwargs) -> dict` 辅助函数（脱离 Celery `@task(bind=True)` 装饰器，便于单测）；缺失 `params` key 直接 `raise RuntimeError("send_task kwargs missing 'params'; the legacy flat-kwargs shape is rejected (T-095 AC-8)...")`；run_pipeline task 调用 _run_pipeline_body | `TestRunPipelineRejectsLegacyFlatKwargs` 2 个 test（reject + accept） | **闭环** |

## 新增测试清单（14 个）

```
tests/unit/test_composition.py:
  TestCompositionErrorHierarchy (5 tests, R-003)
  TestAgentRunnerHolder (4 tests, R-004)
  TestWorkerInitHandlerIdempotent (1 test, R-002)
  TestRunPipelineRejectsLegacyFlatKwargs (2 tests, R-006)
tests/unit/api/test_tasks_router_send_task_contract.py:
  test_send_task_pipeline_name_routes_by_source_type (1 test, R-001)
  test_send_task_pipeline_name_falls_back_when_source_missing (1 test, R-001)
```

## r2 自审：新代码是否引入新问题

| 问题 | 严重度 | 处置 |
|------|-------|------|
| `composition.py` 引入 multiple-inheritance（`CompositionError(IntelliSourceError, ValueError)`）— Python 多继承钻石问题风险 | LOW（已审） | IntelliSourceError 与 ValueError 在 Python 标准库层面无共同祖先冲突；`super().__init__(...)` 走 IntelliSourceError 单链，未触发钻石；测试已断言 `issubclass(CompositionError, (IntelliSourceError, ValueError))` 双重符合 |
| `tasks.py` 抽出 `_run_pipeline_body` 让 Celery task 变成单行委托 — 调用栈多一层 | 可忽略 | 单层函数调用，Python 解释器优化；可读性 + 可测性收益 > 微调用成本 |
| `boot.py` 幂等守卫使第二次 init 信号沉默 — 测试如不显式 reset 会被遮蔽 | 已防 | 3 个 test class 加 autouse fixture 重置 `_celery_tasks`；新增 idempotent test 显式验证守卫行为 |
| `api/routers/tasks.py` 多一次 DB 查询（`get_types_by_ids`）— 性能 | 可忽略 | 批量查询单次走 `SELECT id, type FROM sources WHERE id IN (...)`，规模与 tasks 列表线性，不引入 N+1 |
| `tests/unit/api/test_tasks_router.py` 16 处加 `get_types_by_ids.return_value = {}` mock | 自洽 | 不改变测试断言，仅消除 mock auto-stub 的 coroutine 警告；3 个 pre-existing 警告仍残留（list_active_source_ids 路径，与本任务无关） |
| factory.py `get_agent_runner()` 改 lazy import composition — 循环依赖延后到运行时 | 可接受 | composition.py 顶层 import factory.build_agent_runner 需要 factory 已加载；factory.get_agent_runner 在调用时 import composition；运行时 import 仅一次，Python module cache 后续命中 |

新增代码未引入任何 HIGH / CRITICAL。

## 全量回归

```
$ uv run pytest -q
2356 passed, 31 skipped, 3 warnings in 37.49s

$ uv run mypy --strict src/
Success: no issues found in 114 source files

$ uv run ruff check src/ tests/
All checks passed!

$ uv run ruff format --check src/ tests/
247 files already formatted
```

3 warnings 残留：均出自 `tests/unit/api/test_tasks_router.py::TestCollectAllActiveSources` 路径的 `list_active_source_ids` AsyncMock 链 — pre-existing pattern，非本任务引入；改属 backlog。

## 汇总

| Severity | 数量 | finding IDs |
|----------|------|-------------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 0 | — |
| LOW | 0 | — |

**判定**: `approved`

依据 COMMON-RULES §三态判定：「无问题 → approved」。

T-095 r1 全部 6 finding 已根治：
- 2 MEDIUM 取得真实修复（R-001 真实 DB 查源类型 + R-002 真实幂等守卫）
- 4 LOW 按 architectural-debt 标准抹平（R-003 体系内异常 + R-004 抽象隔离 + R-005 测试断言强度 + R-006 拒绝兼容兜底）
- 14 新增测试均为反证 / 行为断言（不是 mock-only），与原有 43 个 AC 覆盖测试形成互补

## orchestrator 后续路径

`approved` → Phase Transition Protocol 准备激活 sprint-9 批次 2：
- T-096 [standard, depends on T-095] PROCESSOR_REGISTRY + `_process_execute` 契约 + `_RawContentResultRepo` 持久化
- T-097 [standard, security_sensitive, depends on T-095] CollectorRegistry 装配 + DistributorFacade 真实实现 + 三渠道 from_env
- T-098 [standard, security_sensitive, depends on T-095] `/search/chat` 接 AgentRunner.run_flexible + Webhook + 微信/企微客服消息回调
- T-099 [light, depends on T-095] Pipelines API 只读 + run + System 可观测性 + ConfigVersion
- T-100 依赖 T-097/T-098，留待批次 3

Sprint Review 微型短路判定：sprint-9 任务数 = 6（T-095~T-100）> 3，**不短路**；正常 sprint-review 流程。
