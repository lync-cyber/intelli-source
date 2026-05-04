---
id: "code-review-t-075-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-075"]
---

# CODE-REVIEW-T-075-r1: Celery worker wiring + runner._persist 参数化

> Layer 1 delegated to hook (`.claude/settings.json` PostToolUse `lint_format.py`)
> Layer 2 全维度执行（task_kind=feature, tdd_mode=standard, AC=5；不满足短路条件）

## 审查范围

- `src/intellisource/scheduler/boot.py` (新建, 73 LOC)
- `src/intellisource/agent/runner.py` (修改, +11 LOC: 2 kwargs + 4 处调用点)
- `tests/integration/test_celery_worker_wiring.py` (新建, 5 tests)
- `tests/unit/agent/test_runner_persist.py` (新建, 4 tests)

## 量化指标

- 11/11 target tests PASSED + 1840 全量回归 PASSED + 1 SKIPPED
- mypy --strict src/ — Success: no issues found in 106 source files
- ruff check / ruff format — All checks passed
- 实施轮数：1（GREEN 一次过；REFACTOR 由 implementer self-report `refactor_needed=false` 跳过）

## 问题列表

### [R-001] MEDIUM: `worker_init_handler` 未连接到 celery `worker_process_init` signal — 重蹈 T-074 r2 "DI 已改但生产路径无人调用" 同模式

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `boot.py` 定义了 `worker_init_handler(*, celery_app, agent_runner, pipeline_config, **_)` 但**没有**调用 `from celery.signals import worker_process_init; worker_process_init.connect(worker_init_handler)`。production celery worker 启动时不会触发该 handler，`get_celery_tasks()` 永远返回 None。测试 `test_worker_init_signal_wires_celery_tasks_singleton` 直接手动调用 `boot_mod.worker_init_handler(...)` 而非通过 signal dispatch，因此测试通过但生产路径未验证。
  本任务 §来源 明确写道："消除 T-074 r2 留下的 'DI 已改但生产路径无人调用' 差距"——但当前实现把同样的 gap 推到了上一层（T-074 是 CeleryTasks 实例化无人触发；T-075 是 worker_init_handler 无人连接到 signal）。AC-T075-1 字面要求"Celery worker 启动时（celery_app.signal.worker_init 或等价 hook）创建独立的 async session_factory"——"或等价 hook" 给了灵活性，但当前实现两端都缺：没有 signal connect 也没有显式的 application bootstrap 调用点。
- **建议**: 任选其一闭环：
  1. 在 `boot.py` 模块级追加 `from celery.signals import worker_process_init; worker_process_init.connect(worker_init_handler)`（最简，但需保证 boot 模块在 worker process 内被 import）
  2. 提供一个 `register_worker_signals(celery_app, agent_runner_factory, pipeline_config_factory)` 工厂函数，由 future `intellisource/scheduler/__main__.py` 或 `manage.py worker` 入口显式调用并注册
  3. 如果决策"延迟到 T-076 / T-063 集成测试"，请在 dev-plan T-075 备注栏明确写入 carryover，并把"production wiring incomplete"标进 CORRECTIONS-LOG。当前 GREEN 阶段没有任何地方记录这个 gap，会让 sprint-review 误判 T-075 为"完整闭环"。

### [R-002] LOW: `init_worker_session_factory` 缺失 `IS_DATABASE_URL` 时抛裸 `KeyError`，与 `DatabaseManager` 模式不一致

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `boot.py:24` 直接 `os.environ["IS_DATABASE_URL"]`；缺失环境变量时抛 `KeyError: 'IS_DATABASE_URL'`，无业务上下文。同项目 `storage/database.py:33-38` 已有清晰约定：

  ```python
  url = database_url or os.environ.get("IS_DATABASE_URL")
  if not url:
      raise ValueError(
          "database_url must be provided or IS_DATABASE_URL "
          "environment variable must be set"
      )
  ```

  worker 端应复用该模式，避免 ops 排障时遇到无上下文的 KeyError。
- **建议**: 改为 `os.environ.get("IS_DATABASE_URL")` + 显式 ValueError，或直接调用 `DatabaseManager().engine` 的 readonly 路径（但前者更简）。

### [R-003] LOW: 缺失 `worker_process_shutdown` engine dispose

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `init_worker_session_factory()` 内 `create_async_engine(url)` 创建的 engine 在 worker 进程退出时未被显式 dispose；连接池中的 connection 也不会被优雅释放（OS 进程回收会兜底，但不符合 SQLAlchemy 最佳实践，长期运行的 worker 在重载/优雅停机场景会留 dangling connections，触发 PostgreSQL 端 `idle in transaction` 告警）。
  对比 `storage/database.py:67-79` 的 `DatabaseManager.close()` + `engine.dispose()` + `_creator` guard 模式。
- **建议**: 把 engine 单例化（如挂到模块级 `_worker_engine: AsyncEngine | None`），追加 `worker_shutdown_handler` 调用 `await _worker_engine.dispose()`，并通过 `worker_process_shutdown.connect(...)` 注册。可与 R-001 一并修复（同样是 signal 连接缺失的子集）。

### [R-004] LOW: `_session_factory is not None` 断言过松，未验证 callable 协议

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `test_build_celery_tasks_returns_celery_tasks_with_session_factory` (line 96-98) 仅断言 `tasks._session_factory is not None`。若 `build_celery_tasks` 把未包装的 `async_sessionmaker(...)` 实例直接传给 `CeleryTasks._session_factory`（而非当前的 `_make_session` async 包装器），断言依然通过——但 `CeleryTasks._chain_repo_session` 内部会 `await self._session_factory()` 失败（`async_sessionmaker.__call__()` 返回 `AsyncSession` 而非 awaitable）。
  end-to-end 测试 `test_run_pipeline_end_to_end_repo_create_called_once` 用 mock_session_factory 覆盖了正确路径，所以总体行为正确；但 `_session_factory is not None` 这一条单测的断言强度不够，未来重构 `build_celery_tasks` 改实现时不会被它捕获。
- **建议**: 追加：`assert asyncio.iscoroutinefunction(tasks._session_factory) or callable(tasks._session_factory) and asyncio.iscoroutine(tasks._session_factory())`，或直接 `result = await tasks._session_factory(); assert isinstance(result, AsyncSession-or-Mock)` 走真路径。

## 良好实践 (Highlights)

- `test_init_worker_session_factory_does_not_import_main` 用 `sys.modules['intellisource.main']=None` sentinel 防御 boot.py 偷偷反向依赖 main 的 silent regression — 这是高质量防御性测试设计
- `_spy_persist` monkeypatch 模式干净地捕获 kwargs，没有走 mock 而走 wrapping，保留了 _persist 的真实行为路径
- runner.py 的修改严格"加而不改"：只新增 2 个 kwargs（带默认值，向后兼容）+ 替换 2 处字面量为变量引用，最低破坏面
- adaptive-review 注入的"严禁 make-the-test-pass"红线被正确遵守——implementer 对测试文件仅做 ruff/mypy convention 修复（PLC0415 / E501 / dict[str, Any] / `__future__` 位置），断言逻辑零变更

## 验收标准对照

| AC | 状态 | 备注 |
|----|------|------|
| AC-T075-1 | ⚠️ 部分完成 | session_factory 创建函数齐全；signal 连接缺失（见 R-001） |
| AC-T075-2 | ✅ | build_celery_tasks 注册 `intellisource.scheduler.run_pipeline`，CeleryTasks 实例 wired |
| AC-T075-3 | ✅ | `_persist` 接受 kwargs，run_strict/run_flexible 传 "strict"/"flexible" |
| AC-T075-4 | ✅ | 5 integration tests（≥3 要求） |
| AC-T075-5 | ✅ | mypy strict clean (106 files) |

## 审查结论

**approved_with_notes**

无 CRITICAL/HIGH 问题；1 MEDIUM (R-001) + 3 LOW (R-002/R-003/R-004)。R-001 是结构性 gap 与 T-074 r2 carryover 同模式，建议**立即在 sprint 内修复**或显式 carryover 进 CORRECTIONS-LOG（不要让 sprint-review 误判为完整闭环）；R-002/R-003/R-004 可作为后续优化任务延迟，但 R-002（KeyError 一致性）成本极低，建议顺手修。

按 ORCHESTRATOR §Approved-with-Notes Protocol，由 orchestrator 向用户展示问题列表并选择处理路径。
