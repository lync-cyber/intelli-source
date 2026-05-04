---
id: "code-review-t-075-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-075"]
---

# CODE-REVIEW-T-075-r2: revision verification (R-001~R-004 全闭环)

> Layer 1 delegated to hook
> Layer 2 限定 revision 范围（仅核对 R-001~R-004 修复 + 新引入风险扫描）

## 审查范围
- `src/intellisource/scheduler/boot.py` (revision: +37 / -4)
- `tests/integration/test_celery_worker_wiring.py` (revision: +8 / 0)
- `docs/reviews/CORRECTIONS-LOG.md` (auto-appended by detect_correction hook for option-override 决策)

## 量化指标
- 11/11 target tests + 1840 PASSED + 1 SKIPPED 全量回归
- mypy --strict src/ — clean (106 files)
- ruff check / format — clean

## R-001~R-004 修复核对

### R-001 MEDIUM (signal connect missing) — ✅ 闭环
- `boot.py:12` 引入 `from celery.signals import worker_process_init, worker_process_shutdown`
- `boot.py:103-106` 模块加载时连接两个 signal，使用 `_intellisource_connected` attribute hack 保证幂等（避免 reload 重复注册污染 celery 全局 signal registry）
- production worker 启动时 `worker_process_init` 触发 → `worker_init_handler` → `init_worker_session_factory` + `build_celery_tasks`，wiring 闭合

### R-002 LOW (KeyError → ValueError) — ✅ 闭环
- `boot.py:32-34` 改为 `os.environ.get(...) + raise ValueError("IS_DATABASE_URL must be set for the worker process")`，与 `storage/database.py:33-38` `DatabaseManager` 模式一致

### R-003 LOW (engine dispose missing) — ✅ 闭环
- `boot.py:23` 模块级 `_worker_engine: AsyncEngine | None`
- `boot.py:31` `init_worker_session_factory` 把 engine 存为单例
- `boot.py:83-95` 新增 `worker_shutdown_handler`：`asyncio.run(_worker_engine.dispose())` + `RuntimeError` fallback（嵌套 loop 场景 best-effort，注释明确）+ reset `_celery_tasks = None`
- `worker_process_shutdown` signal 连接已在 R-001 修复中带入

### R-004 LOW (loose assertion) — ✅ 闭环
- `test_celery_worker_wiring.py:99-104` 追加：
  ```python
  assert callable(factory_callable)
  assert asyncio.iscoroutinefunction(factory_callable)
  ```
- 该断言精确捕捉"未包装的 `async_sessionmaker` 实例 vs 包装后的 `async def`"回归——`async_sessionmaker.__call__` 不是 coroutine function，断言会失败

## 新引入观察（不计 verdict）

### [R-001-r2] LOW: `worker_shutdown_handler` 静默吞 `RuntimeError`
- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `boot.py:90-93` 的 `try/except RuntimeError` 在嵌套 event loop 场景下静默跳过 `engine.dispose()`，对 worker 进程退出场景影响有限（OS 会回收 fd/socket），但若未来在 application-managed event loop 下复用此 handler（如测试 fixture），dispose 不会发生。注释 `# Already in event loop — best-effort` 说明了意图，可接受。
- **建议**: 后续若引入 application-managed loop 路径，改为 `asyncio.get_running_loop().create_task(_worker_engine.dispose())` 让宿主 loop 完成 dispose。当前不修。

### [R-002-r2] LOW: signal 幂等 guard 用动态 attribute hack
- **category**: structure
- **root_cause**: self-caused
- **描述**: `boot.py:103-106` 通过 `worker_process_init._intellisource_connected = True` 给 celery 的 signal 对象设动态属性。虽然 attribute 名带前缀避免冲突，但属于 monkey-patch celery 全局对象。更干净的做法是 boot 模块内部 `_signals_connected = False` 标志。但当前实现简洁且 mypy strict 通过，可接受。

两个观察均 LOW，与 sprint-7 已存在的 R-001 不同模式（不是 carryover），属于新增代码的细节优化空间。**不影响 verdict**。

## 验收标准最终对照

| AC | 状态 | r1→r2 变化 |
|----|------|------------|
| AC-T075-1 | ✅ | r1 部分完成 → r2 闭环（signal connect 已注册） |
| AC-T075-2 | ✅ | 不变 |
| AC-T075-3 | ✅ | 不变 |
| AC-T075-4 | ✅ | 测试断言强度提升（R-004 fix） |
| AC-T075-5 | ✅ | mypy strict clean 持续保持 |

## 审查结论

**approved**

R-001~R-004 全部闭环。新引入 2 个 LOW 观察（R-001-r2 / R-002-r2）属于 minor structural detail，不阻塞；如未来代码风格审查时偏好可一并优化。本任务可标记 **done**。

## CORRECTIONS-LOG 状态
detect_correction hook 已自动追加 option-override 条目（用户从 Recommended "立即修复 R-001+R-002" 偏向 "修复全部 4 个"）。该条目计入 sprint-7 retrospective 阈值统计（hard 类）。
