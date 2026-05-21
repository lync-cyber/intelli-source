---
id: "code-review-T-092-r1"
doc_type: code-review
author: orchestrator
status: approved
deps: ["T-092"]
---

# CODE-REVIEW T-092 r1

> 注：本报告由 orchestrator 主线程内联产出。原 reviewer 子代理在 Layer 2 分析阶段被 task-notification 截断，
> CODE-REVIEW-T-092-r1.md 未落盘且未返回 `<agent-result>`。按用户决策（§Sub-Agent Truncation Recovery
> Protocol 派生选项）由 orchestrator 接管 Layer 1 + Layer 2，独立性损失记录在 CORRECTIONS-LOG。

## 元数据

- task_id: T-092
- task_kind: fix
- tdd_mode: standard
- security_sensitive: false
- 涉及模块: M-006 (scheduler), M-009 (storage 接驳)
- 审查范围（git diff d456240..HEAD ∪ 工作树）:
  - `src/intellisource/scheduler/celery_app.py`（+24/-3）
  - `src/intellisource/scheduler/boot.py`（+14/-14）
  - `src/intellisource/scheduler/tasks.py`（+41/-7）
  - `src/intellisource/scheduler/queues.py`（新建）
  - `src/intellisource/agent/factory.py`（+14/-0，新增 `get_agent_runner()` 单例）
  - `tests/unit/scheduler/test_celery_routes.py`（新建，285 行，14 测试）
  - `tests/unit/scheduler/test_idempotency_wiring.py`（新建，591 行，17 测试）

## Layer 1 自动检查

| 工具 | 范围 | 结果 |
|------|------|------|
| `cataforge skill run code-review` (ruff) | 5 src 文件 | PASS（0 errors / 0 warnings） |
| `cataforge skill run code-review` (ruff) | `test_celery_routes.py` | FAIL（I001 import-order；E501 line>88） |
| `cataforge skill run code-review` (ruff) | `test_idempotency_wiring.py` | FAIL（ruff-format diff） |
| `uv run mypy --strict` | `src/intellisource/scheduler/`, `src/intellisource/agent/factory.py` | PASS（8 source files clean） |
| `uv run pytest tests/unit/scheduler/test_celery_routes.py tests/unit/scheduler/test_idempotency_wiring.py` | T-092 套件 | 31/31 PASS（3.40s） |

Layer 1 结论：源码合规；测试文件存在 format/import 漂移（LOW，归到 R-007）。

## Layer 2 语义审查

### AC 覆盖矩阵

| AC | 实现位置 | 测试位置 | 状态 |
|----|---------|---------|------|
| AC-1 task_routes + task_queues 配置 | `celery_app.py:47-53` | `test_celery_routes.py::TestCeleryTaskRoutes` (8 用例) | 部分通过（见 R-005） |
| AC-2 worker_init handler 无必填 kwargs | `boot.py:71-76` + `agent/factory.py:52-60` | `test_celery_routes.py::TestWorkerInitHandlerSignature` (4 用例) | 通过 |
| AC-3 guards 在 pipeline 前各调一次 | `tasks.py:142-152` | `test_idempotency_wiring.py::TestIdempotencyWiringAC3` (4 用例) | 单元层通过，集成失败（R-001 / R-002） |
| AC-4 lock 失败早退 | `tasks.py:146-147` | `test_idempotency_wiring.py::TestIdempotencyWiringAC4` (4 用例) | 单元层通过，集成失败（R-002） |
| AC-5 指纹重复跳过 DB 写入 | `tasks.py:149-152` | `test_idempotency_wiring.py::TestIdempotencyWiringAC5` (4 用例) | 单元层通过但断言空套（R-003）+ 集成失败（R-002） |

### 问题清单

### [R-001] HIGH: worker_init_handler 永远拿不到 celery_app 单例，worker 冷启动崩溃
- **category**: structure
- **root_cause**: self-caused
- **描述**:
  `boot.worker_init_handler` 签名 `(*, celery_app: Any = None, **_)`（boot.py:71）期望 Celery 在 `worker_process_init` 信号触发时把 `celery_app` 作为 kwarg 注入。但 Celery 的 `worker_process_init` 信号只发 `sender` / `signal`（详见 celery.signals），不会传 `celery_app`，因此该参数实际永远为 `None`。随后 `build_celery_tasks(celery_app, ...)`（boot.py:76）把 `None` 透传给 `@celery_app.task(name=...)`（boot.py:62），触发 `AttributeError: 'NoneType' object has no attribute 'task'`。
  反向证据：`boot.py` 顶部不存在 `from intellisource.scheduler.celery_app import celery_app` 这一行（已 grep 验证），即 worker 进程根本没有任何路径取得真正的单例。
  测试套通过是因为 `test_handler_callable_with_no_kwargs` 用 `patch(... build_celery_tasks ..., return_value=mock_tasks)` 直接绕过了 `@celery_app.task` 调用路径——掩盖了真实启动时的 NPE。
- **影响**：worker 冷启动时 `worker_process_init` handler 抛 `AttributeError`；Celery 默认会记录该异常但不阻塞 worker 继续，最终结果是 `build_celery_tasks` 走不完，`_celery_tasks = None`，`get_celery_tasks()` 始终返回 None，整个幂等/Pipeline 业务逻辑装配失败。
- **建议**：
  1. 在 `boot.py` 顶部添加 `from intellisource.scheduler.celery_app import celery_app as _module_celery_app`；
  2. `worker_init_handler` 改为 `def worker_init_handler(**_: Any) -> None:`，内部使用 `_module_celery_app`；
  3. 同时把 `worker_init_handler` 通过真实 Celery worker 启动（pytest-celery 或脚本子进程）跑一次冷启动断言，避免再次出现 "mock 通过、真实失败" 的装配缺口。

### [R-002] HIGH: IdempotencyGuard / FingerprintChecker / ContentRepository 在 worker 装配链路中从未被构造与注入
- **category**: structure
- **root_cause**: self-caused
- **描述**:
  `CeleryTasks.__init__` 增加了 `idempotency_guard` / `fingerprint_checker` / `content_repository` 三个 keyword-only 参数（tasks.py:85-87，默认 `None`），AC-3/4/5 单测通过显式注入 mock 来验证短路逻辑。但生产装配链路（`boot.build_celery_tasks`，boot.py:44-68）的签名只接受 `(celery_app, agent_runner, pipeline_config, session_factory)`，构造 `CeleryTasks(agent_runner=..., pipeline_config=..., session_factory=...)` 时**完全没有传入三个守卫组件**，因此生产侧 `CeleryTasks._idempotency_guard` / `_fingerprint_checker` 始终是 `None`，`run_pipeline` 的所有 `if self._idempotency_guard is not None` 分支恒不进入，幂等保护实际未生效。
  这正是 sprint-8r 立项要消除的"测试通过、生产失效"装配缺口（PROJECT-STATE.md §Backlog 第 ③ 条已显式标记此风险）。
- **建议**：
  1. 在 `boot.build_celery_tasks`（或 `worker_init_handler`）中显式构造 `IdempotencyGuard(redis_client=...)`、`FingerprintChecker(content_repo=...)`、`ContentRepository(session_factory=...)`，并通过 kwargs 传入 `CeleryTasks` 构造器；
  2. Redis client 的获取应走环境变量 `IS_REDIS_URL`，与 celery_app.py:26 同源；
  3. 补一个最小冷启动集成测试（pytest fixture 启动 in-process worker + memory broker），断言 `CeleryTasks.run_pipeline` 在生产路径下的 `self._idempotency_guard is not None`——这是 T-094 收口的依赖前置。

### [R-003] HIGH: AC-5 测试 `test_content_repository_create_not_called_on_duplicate_fingerprint` 空套
- **category**: test-quality
- **root_cause**: self-caused
- **描述**:
  AC-5 期望"指纹重复时跳过 DB 写入，`ContentRepository.create` 未被调用"。当前测试断言 `content_repo.create.assert_not_called()`（test_idempotency_wiring.py:373）。但 `CeleryTasks.run_pipeline` **从未在任何分支调用 `self._content_repository.create(...)`**（grep 确认 tasks.py 全文只在 L94 赋值 `self._content_repository = content_repository`，之后没有任何读引用）。因此该断言是空套——即使删除 fingerprint 检查逻辑、即使把 `_content_repository` 完全删掉，断言依然 PASS。
  AC-5 的真实语义未被任何测试覆盖；T-094 集成测试若复用此模式将继续放过缺陷。
- **建议**：
  1. 在 `run_pipeline` 的成功路径中显式调用 `self._content_repository.create(content)`（与 fingerprint 检查的 happy/skip 路径分支配对），让 mock 断言有实际杠杆；
  2. 或重写测试为对真实 SQLAlchemy session 的 spy（验证 INSERT 实际未发出）；
  3. AC-5 的产生方（test-writer）建议补一条 "断言反证"——同套 mock 在 `check_return=False` 时必须 `create.assert_called_once()`（test_content_repository_create_called_on_new_fingerprint 当前没有验证 create 调用），形成正反对照。

### [R-004] MEDIUM: 双 `run_pipeline` task 注册并存，产生不同执行语义
- **category**: structure
- **root_cause**: self-caused
- **描述**:
  在 worker 生命周期里 `run_pipeline` 被注册了两次：
  - `tasks.py:207` `@celery_app.task(name="run_pipeline", bind=True)` 模块导入时注册，通过 `getattr(celery_app, "_celery_tasks_instance", None)` 找业务实例；**整个代码库中没有任何位置给 `celery_app._celery_tasks_instance` 赋值**（grep 确认），所以该 task 在生产恒走 L224 stub 分支 `return {"status": "queued", ...}`，根本不执行 pipeline。
  - `boot.py:62` `@celery_app.task(name="intellisource.scheduler.run_pipeline")` 在 worker_init 时注册闭包，调用真正的 `CeleryTasks.run_pipeline`（受 R-001 影响，目前也跑不到）。
  `celery_app.py:49-52` `task_routes` 同时把两个名字都映射到 `priority.normal`，由生产者决定调度哪个，行为不确定且任一路径都失效。
- **建议**：
  1. 收敛到单一注册路径：建议把 `tasks.py:207-224` 的模块级 stub 删除，仅保留 `boot.py` 中的运行时注册；同时在 `worker_init_handler` 内 `celery_app._celery_tasks_instance = _celery_tasks` 显式赋值（与 stub 兼容方案二选一）。
  2. `task_routes` 同步收敛为单一 name。

### [R-005] MEDIUM: task_routes 只覆盖 `run_pipeline`，TRIGGER_TYPE 队列声明而未路由
- **category**: completeness
- **root_cause**: self-caused
- **描述**:
  AC-1 字面要求"`PRIORITY_QUEUES` 和 `TRIGGER_TYPE_QUEUES` 中定义的任务路由实际生效"。实际实现 `celery_app.py:49-52` 仅给 `run_pipeline` / `intellisource.scheduler.run_pipeline` 两个名字映射到 `PRIORITY_QUEUES["normal"]`，没有任何任务被路由到 `queue.trigger.scheduled` / `queue.trigger.manual`。这两条 `Queue` 只在 `task_queues` 中被声明（celery_app.py:48），worker 可以监听，但生产者侧没有对应的 `task_routes` 规则把任务投递过去。
  测试 `test_task_queues_include_trigger_type_queue_names` 仅校验队列声明存在，未校验路由完整性。
- **建议**：
  二选一：
  - 若设计意图是 trigger_type 仅"可被路由到"而非"必定路由到"，在 ARCH/dev-plan 显式标注，并在 `tasks.py` 提供 `apply_async(queue=get_queue_for_trigger_type(...))` 调用示例 + 测试；
  - 若 AC-1 要求"自动路由"，扩展 `task_routes` 为 callable 或使用 `apply_async` kwargs 在调度点动态选择队列，并增加端到端断言。

### [R-006] MEDIUM: `TaskRepository` 占位是死代码且签名错误
- **category**: dead-code
- **root_cause**: self-caused
- **描述**:
  `tasks.py:37` `TaskRepository: Any = None` 作为模块级占位声明，注释为"Lazy imports -- patched in tests, resolved at runtime"。生产代码路径中没有任何地方把这个名字替换为真实类（仓库下真实类在 `intellisource.storage.repositories.task.TaskRepository`，但 `tasks.py` 从未 import 它），因此 `tasks.py:188-194` 的失败持久化分支恒不进入。
  即便有人补上 import，`task_repo = TaskRepository()` 的零参构造也与真实仓库 `BaseRepository(session)` 签名不符；`task_repo.update(error_message=str(last_error))` 缺少主键标识，与现行仓库 API 不兼容。
  整段死代码会让代码搜索误以为"已实现错误持久化"，掩盖真实缺口。
- **建议**：
  二选一：
  - 真正接入：在 `__init__` 接收 `task_repository`，重试耗尽时 `await self._task_repository.update(task_id, error_message=...)`，并补单测；
  - 直接删除 L37 + L188-194 占位，让 commit diff 自身承载"未实现"事实，由后续任务卡（T-094 或 P2 backlog）显式补齐。

### [R-007] LOW: 两个新建测试文件 ruff format / import-order 漂移
- **category**: convention
- **root_cause**: self-caused
- **描述**:
  - `tests/unit/scheduler/test_celery_routes.py:12` I001（import block 未排序）+ L76 E501（93 > 88）
  - `tests/unit/scheduler/test_idempotency_wiring.py` 整文件 ruff-format 待重排
- **建议**：`uv run ruff format tests/unit/scheduler/test_celery_routes.py tests/unit/scheduler/test_idempotency_wiring.py && uv run ruff check --fix tests/unit/scheduler/test_celery_routes.py`。

### [R-008] LOW: `celery_app.py:38` 模块级 import 被 `# noqa: E402` 抑制
- **category**: convention
- **root_cause**: self-caused
- **描述**:
  `from intellisource.scheduler.queues import (...)` 放在 `celery_app = Celery(...)` 之后并加 `# noqa: E402`。`queues.py` 是纯常量模块，无副作用、无循环依赖（已确认 `queues.py` 不 import `celery_app`），应可放回顶部。
- **建议**：把 queues 的 import 上移到 `from kombu import Queue` 之后；删除 `# noqa: E402`；如确有循环依赖（请验证 import 顺序），用 lazy import in `conf.update()` 的 lambda 中。

### [R-009] LOW: `boot.worker_shutdown_handler` 吞 RuntimeError 无日志
- **category**: error-handling
- **root_cause**: self-caused
- **描述**:
  `boot.py:85-89` `except RuntimeError: pass` 把"已在事件循环中"作为 best-effort 静默忽略。生产 worker 关闭时如果 `engine.dispose()` 真的因别的原因抛 RuntimeError，资源泄漏后无任何痕迹可追。
- **建议**：`except RuntimeError as exc: logger.warning("engine.dispose skipped during shutdown: %s", exc)`，并把 `_worker_engine = None` 移到 `finally` 块保证清理。

### [R-010] LOW: `tasks.py:182-184` 速记 TODO 不符合项目注释规范
- **category**: convention
- **root_cause**: self-caused
- **描述**:
  ```python
  # When integrated with real Celery, replace with
  # self.retry(countdown=...) for non-blocking retries.
  ```
  这是设计阶段残留 / TODO 性质的对比叙事注释（"现在用 X，将来要改为 Y"），违反 COMMON-RULES §禁止设计阶段与变更说明残留。
- **建议**：删除该多行注释；如果"工程师还没决定是否替换"是真实状态，按 `[ASSUMPTION]` 标准格式表达；否则直接陈述当前事实（worker 进程内同步休眠）即可。

## 三态判定

| 维度 | 计数 |
|------|------|
| CRITICAL | 0 |
| HIGH | 3 |
| MEDIUM | 3 |
| LOW | 4 |

按 §三态判定逻辑（存在 HIGH → needs_revision）：

**verdict: needs_revision**

阻断项：R-001 / R-002 / R-003。三项共同指向同一根因——"单元测试用 mock 注入验证、生产装配链路未串联"——这是 sprint-8r 立项要消除的核心模式，必须在批次 3 闭合前修复，否则 T-094 冷启动 e2e 必然失败。

## 修复优先级建议

| 阶段 | 任务 |
|------|------|
| 立即（同次 GREEN/REFACTOR 修订） | R-001（boot 导入 celery_app 单例） + R-002（装配三守卫 + 真实冷启动测试） + R-003（让 ContentRepository.create 实际被调） |
| 同次修订（连带清理） | R-004（收敛双注册） + R-006（删/补 TaskRepository 死代码） + R-007（ruff format） |
| 可推迟到 T-094 收口或 P2 backlog | R-005（trigger 队列路由策略澄清）、R-008、R-009、R-010 |
