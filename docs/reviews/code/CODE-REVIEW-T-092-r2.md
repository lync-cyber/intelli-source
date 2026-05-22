---
id: "code-review-T-092-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-092"]
---

# CODE-REVIEW T-092 r2

> 本报告为首次独立 reviewer 视角审查（r1 由 orchestrator 内联产出）。
> 审查提交: 1d8e24f

## 元数据

- task_id: T-092
- task_kind: fix
- tdd_mode: standard
- security_sensitive: false
- 涉及模块: M-006 (scheduler), M-009 (storage 接驳)
- 审查范围（git show --stat 1d8e24f）:
  - `src/intellisource/scheduler/boot.py`（+68/-14）
  - `src/intellisource/scheduler/celery_app.py`（+8/-1）
  - `src/intellisource/scheduler/tasks.py`（+41/-41）
  - `tests/integration/test_celery_worker_wiring.py`（+79/-74）
  - `tests/unit/scheduler/test_celery_routes.py`（+64/-0）
  - `tests/unit/scheduler/test_idempotency_wiring.py`（+190/-100）
  - `tests/unit/scheduler/test_tasks.py`（+27/-54）

## Layer 1 自动检查

| 工具 | 范围 | 结果 |
|------|------|------|
| ruff check | src/scheduler/boot.py + tasks.py + celery_app.py | PASS（0 errors） |
| ruff check | tests/unit/scheduler/*.py + tests/integration/test_celery_worker_wiring.py | PASS（0 errors） |
| mypy --strict | src/intellisource/scheduler/boot.py + tasks.py + celery_app.py | PASS（0 issues） |
| pytest | 67 tests（test_idempotency_wiring / test_celery_routes / test_tasks / test_celery_worker_wiring）| 67/67 PASS |

Layer 1 결론: 全量 lint/type/test PASS。

## Layer 2 语义审查

### r1 问题逐项判定

| 问题 | r1 级别 | r2 判定 | 说明 |
|------|---------|---------|------|
| R-001 boot.py 单例 import + handler 签名 | HIGH | **已修** | `from ...celery_app import celery_app as _module_celery_app` 在 L23 顶部存在；`worker_init_handler(**_: Any)` 签名无必填 kwargs；`setattr(_module_celery_app, "_celery_tasks_instance", _celery_tasks)` L108 赋值 |
| R-002 guards 未装配 | HIGH | **已修（部分，见 N-001）** | `build_celery_tasks` 现构造真实 `IdempotencyGuard(redis=)` + `FingerprintChecker(repository=)`；但 `content_repository=` 未传入 CeleryTasks（见 N-001） |
| R-003 `content_repository.create` 空套 | HIGH | **已修** | `tasks.py:172-173` 在成功路径调用 `_content_repository.create(result)`；正反对照测试均存在（`assert_called_once` / `assert_not_called`） |
| R-004 双注册收敛 | MEDIUM | **已修** | `build_celery_tasks` 中闭包 `@celery_app.task` 已删除；单一注册在 tasks.py:193；`worker_init_handler` 通过 `setattr` 赋值 `_celery_tasks_instance` |
| R-005 trigger_type 路由 | MEDIUM | **未修（留存）** | `task_routes` 仍只覆盖 `"run_pipeline"→normal`，trigger_type 队列声明而未路由——与 r1 状态相同，符合 r1 建议"可推迟" |
| R-006 TaskRepository 死代码 | MEDIUM | **已修** | tasks.py 全文搜索 `TaskRepository` 无引用；dead code + stub 已删；error 测试改写为断言异常直接 re-raise |
| R-007 ruff format 漂移 | LOW | **已修** | 所有测试文件 ruff PASS |
| R-008 queues import 上移 | LOW | **已修** | `celery_app.py:10` queues import 在文件顶部，无 `# noqa: E402` |
| R-009 shutdown 吞 RuntimeError | LOW | **已修** | `boot.py:119-123` 用 `logger.warning` 记录；`_worker_engine = None` 在 finally |
| R-010 TODO 注释残留 | LOW | **已修** | tasks.py 全文无该多行注释 |

### 新发现问题

### [N-001] MEDIUM: `build_celery_tasks` 未向 `CeleryTasks` 传 `content_repository=`，生产侧 AC-5 创建仍不发生
- **category**: completeness
- **root_cause**: self-caused
- **描述**:
  `build_celery_tasks`（boot.py:93-99）构造 `CeleryTasks` 时仅传入 `idempotency_guard` 和 `fingerprint_checker`，但未传 `content_repository`。因此生产侧 `CeleryTasks._content_repository` 恒为 `None`，`tasks.py:172` 的 `if self._content_repository is not None:` 分支在真实 worker 上永远不进入——`content_repository.create(result)` 不被调用。
  R-003 单元测试通过是因为测试直接构造 `CeleryTasks(content_repository=mock_repo, ...)`，绕过 `build_celery_tasks` 装配链路。集成测试 `test_build_celery_tasks_returns_celery_tasks_with_session_factory` 只断言 `_session_factory is not None`，未断言 `_idempotency_guard is not None` 或 `_content_repository is not None`，无法拦截此缺口。
  这是 R-002 的同型遗留：装配链路少传一个组件，单元测试无法感知。
- **建议**:
  1. 在 `build_celery_tasks` 内加一行以构造并传入 `content_repository`（可使用已有 `session_factory` 构建一个 `RawContentRepository` 适配器，类似 `_RawContentFingerprintRepo` 方式），并在 `CeleryTasks(...)` 构造调用中添加 `content_repository=content_repository`；
  2. 在集成测试 `TestBuildCeleryTasks.test_build_celery_tasks_returns_celery_tasks_with_session_factory` 追加断言 `tasks._idempotency_guard is not None` 和 `tasks._fingerprint_checker is not None`（顺带也覆盖 R-002 遗留的可观测性缺口）；
  3. 若 `content_repository` 的创建暂时推迟到 T-094，则在此处显式标注 `[ASSUMPTION]` 并让 `_content_repository` 的 `None` 是有意行为，但需确保 T-094 补全前不将此部分标记为"已实现"。

### [N-002] LOW: `_RawContentFingerprintRepo.record_fingerprint` 是空操作，新内容指纹不被持久化
- **category**: completeness
- **root_cause**: self-caused
- **描述**:
  `boot.py:47-48`：
  ```python
  async def record_fingerprint(self, fingerprint: str, content_id: Any) -> None:
      pass
  ```
  `FingerprintChecker.record(fingerprint, content_id)`（idempotency.py:46-48）在 AC-5 happy path 后理应调用以持久化新内容的指纹，否则下次同内容到达时 `is_duplicate` 仍返回 False，dedup 不生效。
  当前 `tasks.py` 的成功路径中也未调用 `self._fingerprint_checker.record(...)`，因此即使 `record_fingerprint` 有真实实现，也不会被触发。整条链路：check→执行→record 中的 record 环节缺失。
  影响：生产环境中相同内容会被反复处理，违背 AC-5 的"跳过重复 DB 写入"语义（只能跳过第一次之外的，但第一次写入后不记录，导致第二次也跑完整流程）。
- **建议**:
  1. `tasks.py` 成功路径在 `content_repository.create(result)` 调用后追加 `_run_sync(self._fingerprint_checker.record(fingerprint, content_id))`（或对应 content_id）；
  2. `_RawContentFingerprintRepo.record_fingerprint` 填写真实的 INSERT/UPDATE 逻辑（或标注 `[ASSUMPTION]` 声明暂不实现）；
  3. 为此补单测：`is_duplicate_return=False` + `record.assert_called_once_after_execute`；可与 N-001 修复合并。

### [N-003] LOW: 集成测试 `test_worker_init_signal_wires_celery_tasks_singleton` 完全 mock `build_celery_tasks`，无法验证"真实 handler 不抛 AttributeError"
- **category**: test-quality
- **root_cause**: self-caused
- **描述**:
  审查提示要求验证"无 mock 的 worker_init 不抛 AttributeError"。当前 `TestWorkerInitSignalHandler.test_worker_init_signal_wires_celery_tasks_singleton`（test_celery_worker_wiring.py:133-186）通过 `patch("intellisource.scheduler.boot.build_celery_tasks", return_value=mock_tasks)` 完全替换了 `build_celery_tasks`，测试只验证 `get_celery_tasks()` 返回非 None——任何能执行 `setattr` 的实现都能通过。真正的 `build_celery_tasks`（含 `IdempotencyGuard(redis=)` 构造）从未在 handler 路径中运行过。
  若 `build_celery_tasks` 内部后续引入错误（如错误 kwarg 名），此测试依然全绿，不会发出警报。
  这是 r1 R-001 描述的"mock 通过、真实失败"模式的延续——已从 handler 签名层面修复，但测试层面仍存在覆盖盲区。
- **建议**:
  补一个仅 mock 外部 I/O（`_build_redis_client` 返回 MagicMock，`init_worker_session_factory` 返回真实 in-memory sessionmaker，`get_agent_runner` 返回 MagicMock）而不 mock `build_celery_tasks` 本体的冒烟测试，断言：
  - `worker_init_handler()` 不抛异常；
  - `get_celery_tasks()._idempotency_guard is not None`；
  - `get_celery_tasks()._fingerprint_checker is not None`。
  此类测试成本低（全在 in-process，不需真实 Redis/DB 连接），能在 T-094 前提前拦截装配缺口。

## 三态判定

| 维度 | 计数 |
|------|------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 1（N-001） |
| LOW | 2（N-002、N-003） |

按 §三态判定逻辑（无 CRITICAL/HIGH，有 MEDIUM/LOW）：

**verdict: approved_with_notes**

## R-001~R-010 修复摘要

| 编号 | r1 级别 | r2 状态 |
|------|---------|---------|
| R-001 | HIGH | 已修 |
| R-002 | HIGH | 已修（IdempotencyGuard + FingerprintChecker 装配；content_repository 缺口降级为 N-001 MEDIUM） |
| R-003 | HIGH | 已修 |
| R-004 | MEDIUM | 已修 |
| R-005 | MEDIUM | 未修（按 r1 建议可推迟；保留低优先级） |
| R-006 | MEDIUM | 已修 |
| R-007 | LOW | 已修 |
| R-008 | LOW | 已修 |
| R-009 | LOW | 已修 |
| R-010 | LOW | 已修 |

## 特别确认事项

**R-003 端到端确认**：`build_celery_tasks` 在 boot.py:93-99 未传 `content_repository=` 给 `CeleryTasks`，生产侧 `content_repository.create` 不会被触发。单元测试覆盖真实，但生产装配不完整（N-001 MEDIUM）。

**集成测试覆盖**：`test_worker_init_signal_wires_celery_tasks_singleton` mock 了 `build_celery_tasks`，未验证无 mock 的 worker_init 路径不抛 AttributeError（N-003 LOW）。
