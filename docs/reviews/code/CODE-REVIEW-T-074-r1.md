---
id: "code-review-T-074-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-074"]
---

# CODE-REVIEW-T-074-r1: TaskChainRepository 实现 + TimestampMixin 重构

Layer 1 已通过（ruff check + mypy --strict src/ 0 errors，103 files）。本报告为 Layer 2 AI 语义审查。

---

## 审查范围

| 文件 | 变更类型 |
|------|---------|
| `src/intellisource/storage/repositories/task_chain.py` | 新建 (~50 LOC) |
| `src/intellisource/storage/repositories/__init__.py` | 导出追加 |
| `src/intellisource/scheduler/tasks.py` | guard 替换占位 |
| `src/intellisource/agent/runner.py` | `_persist` 改 async + 加 repo 参数 |
| `src/intellisource/storage/models.py` | REFACTOR: 抽 3 个 Mixin，应用到 11 个模型 |
| `tests/unit/storage/test_task_chain_repository.py` | 17 个新测试 |

---

## 问题列表

### [R-001] HIGH: scheduler/tasks.py 的 isinstance guard 使 TaskChain 持久化在生产环境永远不触发

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: T-074 的核心目标是修复 CODE-SCAN R-006 "TaskChain 持久化通道断开"。但 `scheduler/tasks.py` 引入的 guard `not isinstance(repo_binding, type)` 在生产环境中永远为 `False`——实际验证确认 `isinstance(TaskChainRepository, type) == True`（TaskChainRepository 是真实类），导致 `chain_repo` 始终为 `None`，TaskChain 记录在运行时**从未写入数据库**。AC-T074-4 要求"改为运行时从 DI/session 获取实例"，但当前实现仅在测试通过 `patch()` 注入 MagicMock 时触发（MagicMock() 实例不是 type，guard 放行），生产路径仍死链。R-006 的根本问题（TaskChain 持久化通道断开）在运行时未修复。
- **建议**: 移除 isinstance guard；改为真正的 DI 模式——在 `CeleryTasks.__init__` 接收 `repo_factory: Callable[[], TaskChainRepository] | None = None` 参数，或者接受 `session: AsyncSession` 并在 `run_pipeline` 内构造 `TaskChainRepository(session)`。若 session 无法在当前 Celery 同步上下文中传入，应在 notes/TODO 中明确标注"SessionDI 留待 T-072 接驳后完成"而非用 guard 静默跳过。

---

### [R-002] MEDIUM: scheduler/tasks.py 中 chain_repo 调用签名与 TaskChainRepository 实际接口不匹配

- **category**: consistency
- **root_cause**: self-caused（预存在，T-074 未修复亦未标注）
- **描述**: `scheduler/tasks.py` 的持久化代码块（只在测试中触发）调用：(1) `chain_repo.create(pipeline_name=..., execution_mode=...)` — 但 `TaskChainRepository.create()` 签名为 `create(task_chain: TaskChain) -> TaskChain`，需要一个完整的 ORM 对象而非关键字参数；(2) `chain_repo.update(status="success")` 和 `chain_repo.update(status="failed")` — 但 `BaseRepository.update()` 签名为 `update(id: uuid.UUID, **kwargs)` 需要必填的 `id` 参数。这两处调用如果在生产环境执行会立即抛出 `TypeError`。因 guard 使生产路径永远跳过，当前测试通过（MagicMock 接受任何调用），但签名不匹配是潜在地雷。R-006 在 CODE-SCAN 时就要求"接入 scheduler/tasks.py 的占位路径"，T-074 仅更换了 guard 逻辑，未更正调用签名。
- **建议**: 将 `chain_repo.create(pipeline_name=..., execution_mode=...)` 替换为构造 `TaskChain(...)` 对象后调用 `chain_repo.create(task_chain_obj)`；将 `chain_repo.update(status=...)` 替换为 `chain_repo.update_status(chain_id, status)` 并维护 chain_id（与 R-001 DI 修复一并完成）。

---

### [R-003] LOW: 测试 AC-T074-3 对"不存在 chain_id"的断言过弱

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `test_update_status_nonexistent_id_does_not_raise` 仅断言调用不抛出异常，未验证"数据库状态不受影响"。按 AC-T074-3 的语义（update_status 对不存在 chain 静默 no-op），完整验证应包括：调用后对任意已存在的 chain 执行 `get()` 确认其状态未被误改，或验证对该 missing_id 的后续 `get()` 返回 `None`（非偶然写入）。目前测试仅覆盖"不崩溃"而非"副作用为零"。
- **建议**: 补充一个 `get(missing_id)` 仍返回 `None` 的断言，或在测试中先创建一个记录然后对另一个不存在 ID 执行 `update_status`，再确认已存在记录状态不变。

---

### [R-004] LOW: TestTaskChainRepositoryExport 映射到 AC-T074-6 但 AC-T074-6 语义为 mypy strict 零错误

- **category**: convention
- **root_cause**: self-caused
- **描述**: dev-plan `AC-T074-6: mypy --strict 零错误`（质量门禁，由 mypy 运行而非测试函数验证），但 `TestTaskChainRepositoryExport` 类的 docstring 将自己标注为 "AC-T074-6"。导出测试（`__init__.py` 中 `TaskChainRepository` 可导入、出现在 `__all__`、为 class 类型）本身是正确且有价值的，但它对应的是 deliverable（`__init__.py` 导出）而非 AC-T074-6 的 mypy 质量门禁。标签对不上会影响 sprint-review AC 覆盖矩阵的自动对账。
- **建议**: 将 `TestTaskChainRepositoryExport` 的 docstring / 标注改为 "AC-T074-6 deliverable: repository export"，并在注释中说明 "mypy strict pass 由 CI 验证"；或新增一个 AC-T074-7（export）并在 dev-plan 同步（后者需 orchestrator 决策）。

---

### [R-005] LOW: agent/runner.py _persist 中 TaskChain 构造硬编码 trigger_type="manual" 和 execution_mode="strict"

- **category**: consistency
- **root_cause**: self-caused
- **描述**: 当 `_persist` 通过 `repo.create()` 写入新 TaskChain 时（即 `task_chain_id is None and repo is not None`），硬编码了 `trigger_type="manual"` 和 `execution_mode="strict"`。但 `run_strict` 和 `run_flexible` 两种模式共用同一个 `_persist`，不区分实际触发类型和执行模式。对于 `run_flexible` 路径，`execution_mode="strict"` 是错误的标注。此外，`_persist` 的内部调用方（`run_strict` 两处 + `run_flexible` 一处）均不传 `repo` 参数，意味着只有外部显式传入 `repo` 才会触发 DB 写入，但 `run_flexible` 调用 `_persist` 时不传 repo，仍走 UUID 生成路径——运行时 TaskChain 记录通过该路径永远不写入。
- **建议**: 将 `trigger_type` 和 `execution_mode` 通过参数传入 `_persist`（而非硬编码）；或者在 `run_strict` / `run_flexible` 内部直接传递对应值。中期修复应与 R-001 的 DI 接驳一并处理。

---

## REFACTOR 验证（TimestampMixin / CreatedAtMixin / ExecutionTimingMixin）

以下正面验证项目均通过：

1. **schema 等价性**: 旧代码 `updated_at` 未标注 `nullable=`（SQLAlchemy 默认 nullable=True for Optional[...]），新 `TimestampMixin` 显式 `nullable=True`，语义等价，不会产生 spurious alembic autogenerate migration。
2. **alembic 版本文件未新增**: `alembic/versions/` 仅有 `001_initial_schema.py`，符合 R2-004 deliverable 要求"迁移产物不变"。
3. **mixin 层次结构合理**: `TimestampMixin(CreatedAtMixin)` 扩展 `created_at`；`ExecutionTimingMixin` 独立添加 `started_at` / `finished_at`；MRO 无歧义。
4. **11 个模型应用一致**: Source(TimestampMixin)、ContentCluster(TimestampMixin)、Digest(TimestampMixin)、Subscription(TimestampMixin)；TaskChain(ExecutionTimingMixin, CreatedAtMixin)、CollectTask(ExecutionTimingMixin, CreatedAtMixin)；RawContent(CreatedAtMixin)、ProcessedContent(CreatedAtMixin)、LLMCallLog(CreatedAtMixin)、PushRecord(CreatedAtMixin)、ChatSession(CreatedAtMixin)。无混用现象。
5. **jscpd 克隆消除**: 7 处 created_at/updated_at/started_at/finished_at 列模板克隆已通过 mixin 消除。

---

## 其他观察（不计入问题等级）

- **run_flexible 4 层嵌套**: while > for > if > try（第 134~167 行）经核实为 pre-existing（a85454c 同位置），T-074 未引入新嵌套。implementer self-report 准确。
- **`get()` / `update_status()` 对无效 UUID 字符串的处理**: `ValueError` 被静默捕获返回 `None` / 返回 `None`。设计合理——字符串 ID 边界属于调用方校验职责，repo 层降级为 None 符合防御性编程。测试未覆盖此路径（`get("not-a-uuid")`），属于边界覆盖缺口，但不阻塞当前迭代。

---

## 备注：协议违规观察（Sprint-7 Retrospective 证据）

commit `d0cb454`（`refactor(storage): T-074 extract TimestampMixin, CreatedAtMixin, ExecutionTimingMixin`）由 **refactorer 子代理直接执行 git commit + push**。按 ORCHESTRATOR-PROTOCOLS，commit/push 写权限由 orchestrator 独占，子代理（包括 implementer / refactorer）的职责是将代码写入文件系统，由 orchestrator 在验证通过后统一提交。

此次违规模式与 T-072 历史记录中"orchestrator 在 implementer 仍在收尾期间运行验证"属于同一类——子代理越权操作 git 生命周期。建议在 Sprint-7 末尾 retrospective 中提炼为 EXP 候选：**"refactorer / implementer 不得直接执行 git commit；文件写入后应返回 completed，由 orchestrator 统一提交"**。

---

## 三态判定

| 等级 | 数量 |
|------|------|
| CRITICAL | 0 |
| HIGH | 1 (R-001: 生产 TaskChain 持久化永远不触发) |
| MEDIUM | 1 (R-002: chain_repo 调用签名不匹配) |
| LOW | 3 (R-003/R-004/R-005) |

**verdict: needs_revision**

R-001 (HIGH) 是本次任务的核心 — TaskChain 持久化通道在生产环境仍然断开，CODE-SCAN R-006 未真正修复。R-002 (MEDIUM) 标注潜伏的签名不匹配，应随 R-001 修复一并清理。R-003/R-004/R-005 为改善建议，不单独阻塞。
