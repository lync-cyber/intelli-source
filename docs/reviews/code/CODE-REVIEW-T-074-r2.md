---
id: "code-review-T-074-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-074"]
---

# CODE-REVIEW-T-074-r2: TaskChainRepository 持久化 DI 接驳 + 重构清理复审

Layer 1 已通过（任务描述确认；ruff check src/ clean + mypy --strict src/ 0 errors，103 files）。本报告为 Layer 2 复审，核查 r1 verdict (needs_revision) 触发的修订是否闭环。

---

## 审查范围（git diff 36eba9a..a14fe8a）

| 文件 | 变更类型 |
|------|---------|
| `src/intellisource/scheduler/tasks.py` | DI rework: 增加 session_factory 参数 + 抽取 _chain_repo_session / _create_chain / _update_chain_status |
| `src/intellisource/agent/runner.py` | 无实质变更（diff 为空） |
| `tests/unit/scheduler/test_tasks.py` | TestTaskChainPersistence 5 个测试重写为 DI 模式 |
| `tests/unit/storage/test_task_chain_repository.py` | R-003 加强：update_status nonexistent 测试补齐两条断言 |

---

## r1 问题逐项复核

### R-001 (HIGH) 复核：isinstance guard 删除 + DI 真实 production path

**验证结果: 闭环。**

实跑 `grep -n "isinstance" src/intellisource/scheduler/tasks.py` 零结果，确认 guard 已完全删除。

`run_pipeline` 实现（第 139-149 行）：
- `chain_id: uuid.UUID | None = None`
- `if self._session_factory is not None:` → 构造 `TaskChain(pipeline_name, status, trigger_type, execution_mode, total_steps, completed_steps)` → 调用 `self._create_chain(task_chain)` → 内部走 `async with self._chain_repo_session() as repo: await repo.create(task_chain)` → 返回 `task_chain.id`

链路完整：session_factory 开 session → TaskChainRepository(session) → repo.create(task_chain)。

**production wiring 检查**：`grep -rn "CeleryTasks(" src/ tests/` 结果显示，src/ 内无任何 CeleryTasks 实例化点（`main.py` 的 `init_celery()` 仅构造裸 Celery 应用，未构造 CeleryTasks）。tests/ 内两处（第 39 行 / 第 48 行）分别对应无 session_factory 和有 session_factory 的辅助函数。

这意味着 CeleryTasks 的生产接驳（将 DatabaseManager.get_session 绑定为 session_factory）尚不存在于 src/ 内，但该接驳属于 T-072 DB session DI 任务的职责范围，且 r1 报告的建议措辞（"T-072 接驳后完成"）已与此对齐。当前 `session_factory=None` 时 `run_pipeline` 走无持久化路径并不抛异常——是设计意图（降级而非崩溃）。R-001 的核心修复（移除死链 guard、建立真实 DI 构造路径）已完成；生产接驳缺失属于 T-072 范围，不构成本轮 R-001 的遗留风险。

### R-002 (MEDIUM) 复核：调用签名对齐

**验证结果: 闭环。**

- `repo.create(task_chain)` — 传入完整 `TaskChain` 实例，签名 `create(task_chain: TaskChain) -> TaskChain` 匹配。
- `repo.update_status(str(chain_id), status)` — 传入 `(str, str)` 两个位置参数，签名 `update_status(chain_id: str, status: str)` 匹配。
- 旧的 `chain_repo.create(pipeline_name=..., execution_mode=...)` 和 `chain_repo.update(status=...)` 错误调用已完全消除。

### R-003 (LOW) 复核：update_status nonexistent 测试断言加强

**验证结果: 闭环。**

`test_update_status_nonexistent_id_does_not_raise`（第 221-240 行）现包含：
1. 先创建 existing_chain（status="pending"）
2. 对 missing_id 调用 update_status(missing_id, "failed")
3. `assert await repo.get(missing_id) is None` — 无 phantom 记录创建
4. `assert refetched.status == "pending"` — sibling chain 状态不变

两条要求的断言均已到位。

### R-004 (LOW) 复核：TestTaskChainRepositoryExport docstring 标注

**验证结果: 部分闭环，保留 LOW 注解。**

查看当前 `TestTaskChainRepositoryExport`（第 358-384 行），类 docstring 已修改为：
`"""AC-T074-6: TaskChainRepository must be exported from storage.repositories.__init__."""`

措辞已指向 "exported from ….__init__"（deliverable 语义），不再声称验证 mypy strict 门禁。r1 建议的"说明 mypy strict pass 由 CI 验证"注释未追加，但 docstring 误导性已消除，属于完全闭环可接受范围。无新问题。

### R-005 (LOW) 复核：trigger_type / execution_mode 动态读取

**验证结果: 闭环。**

- `trigger_type = params.get("trigger_type", "scheduled")` — 从 params 动态读取，默认 "scheduled"（第 134 行）
- `execution_mode = config.get("execution_mode", "strict")` — 从 pipeline config 动态读取，默认 "strict"（第 135 行）
- 两值均传入 `TaskChain(...)` 构造（第 144-145 行）

硬编码已消除。

---

## 本轮 refactor 新增代码审查

### 1. `_chain_repo_session` 设计

`_chain_repo_session` 是 `@asynccontextmanager`，内部先检查 `self._session_factory is None` 即 `raise RuntimeError`；而 `_create_chain` 的入口也有 `if self._session_factory is None: return None` 提前返回。两层检查冗余但安全——内层 RuntimeError 永远不会被外层路径触发（`_create_chain` 先行短路）。这是防御性冗余，不构成问题。

session 生命周期：`try/finally await session.close()` 覆盖正常与异常路径，无连接泄漏风险。

### 2. `_do()` 嵌套函数重复模式

`_create_chain` 和 `_update_chain_status` 各自内部定义 `async def _do()`，模式为 "async with _chain_repo_session() as repo: await repo.XXX()"。两个 `_do` 函数结构相似（均为一次 repo 调用），但类型签名不同（`uuid.UUID` vs `None`）。

这属于合理的局部性设计：每个 helper 的 `_do` 仅三行，合并会引入泛型或 callback 参数，增加额外复杂度。当前形态与现有 `_run_sync` 模式一致，不构成 duplication 问题。

### 3. run_pipeline 复杂度

refactor 后 `run_pipeline` 约 50 LOC，嵌套深度 3（for → try → if）。较 r1 前结构清晰，符合 refactorer self-report。

### 4. TestTaskChainPersistence 测试改写质量

**字段验证**：`test_task_chain_contains_pipeline_name` 断言 `chain_arg.pipeline_name == "news_collect"`（精确比较，非 in str）；`test_task_chain_contains_execution_mode` 断言 `chain_arg.execution_mode == "strict"`；两个测试均断言 `isinstance(chain_arg, TaskChain)` — 字面值比对，强于旧版 `str(call_args)` 包含检查。

**状态流转验证**：`test_task_chain_status_updated_on_completion` / `test_task_chain_status_updated_on_failure` 均通过 `fake_create` side_effect 将 `task_chain.id = persisted_id`，确保 `_create_chain` 返回非 None 的 `chain_id`，从而使 `_update_chain_status` 被调用。两个测试断言 `update_status.call_args_list` 中含 "success" / "failed"。

**一个观察点（不升级为问题）**：`patch("intellisource.scheduler.tasks.TaskChainRepository", return_value=mock_repo)` 方式替换了 TaskChainRepository 类本身，使 `_chain_repo_session` 内的 `TaskChainRepository(session)` 调用变为 `mock_repo`（而非 `mock_repo(session)` 的实例）。这与 `return_value=mock_repo` 的语义匹配：patch 使类构造返回 `mock_repo`，context manager 中 `yield TaskChainRepository(session)` 等价于 `yield mock_repo`，mock_repo 的 `create` / `update_status` 都是 AsyncMock，能被正常 awaitable 调用。测试逻辑正确。

**DI fixture 稳定性**：各测试独立构造 `fake_session_factory`，不依赖 fixture 共享状态。未来 `CeleryTasks.__init__` 增加新参数时，仅需修改 `_make_celery_tasks_with_session_factory` 辅助函数，测试结构稳定。

### 5. runner.py _persist 中的硬编码 (R-005 部分遗留)

`runner.py` 的 `_persist` 方法（第 256-265 行）在 `elif repo is not None` 分支内构造 TaskChain 时仍有：
- `trigger_type="manual"` 硬编码
- `execution_mode="strict"` 硬编码

r1 R-005 针对的是 `scheduler/tasks.py`（已修复），但 `runner.py _persist` 的同类硬编码属于预存在问题（不在本次 diff 范围内，r1 亦未单独列项）。`_persist` 的 `repo` 参数路径目前无对应测试覆盖（`test_runner_persist_calls_repo_create_when_provided` 只验证 `create` 被调用，未验证字段值）。这是 runner.py 内的一个低优先级问题，不阻塞当前 sprint，供后续迭代处理。

---

## 验证基线确认

| 指标 | 结果 |
|------|------|
| 目标测试（17 T-074 + 27 T-027）| 44/44 PASS |
| 全量回归 | 1803 PASS（无增减） |
| mypy --strict src/ | 0 errors（103 files） |
| ruff check src/ | clean |
| Layer 1 | 已通过（event-log commit 0affce3 记录） |

---

## 问题列表

### [R-001] LOW: runner.py _persist 中 trigger_type / execution_mode 仍为硬编码

- **category**: consistency
- **root_cause**: self-caused（预存在，T-074 r1 未单独列项，本轮首次识别）
- **描述**: `agent/runner.py` 第 260-261 行 `_persist` 方法的 `elif repo is not None` 分支构造 TaskChain 时硬编码 `trigger_type="manual"` 和 `execution_mode="strict"`，不区分 `run_strict` 与 `run_flexible` 路径。r1 R-005 已修复 `scheduler/tasks.py`，但 `runner.py` 的同类问题未同步清理。该路径目前无外部调用传入 `repo`（生产中 `_persist` 均不带 repo），实际影响有限，但与 R-005 的修复方向不一致。
- **建议**: 为 `_persist` 增加 `trigger_type: str = "manual"` 和 `execution_mode: str = "strict"` 参数，由 `run_strict` / `run_flexible` 传入对应值；或在 `run_strict` / `run_flexible` 调用 `_persist` 时直接传参。可与 T-072 DB session 接驳一并处理。

---

## 备注：Retrospective 证据（Sprint-7 末尾）

本轮 r2 审查新增以下 EXP 候选，补充至 r1 备注段：

1. **refactorer self-report 范围错位（同 T-060/T-072 模式）**: refactorer commit `a14fe8a`（"collapse run_pipeline session lifecycle"）在 implementer 报告 `refactor_needed=true` 后执行，但 refactorer 初期 self-report "no further modifications required" 与实际 diff 含 40 行新增不符。与 T-060 implementer scope drift（"声称 src/ clean 但 tests/ 含 E501"）、T-072 orchestrator 时序（"orchestrator 在 implementer 收尾期间运行验证"）同属 **self-report 范围与实际范围错位**，建议 retrospective 提炼统一 EXP。

2. **T-074 累计 self-caused 数量**: r1 5 个（R-001 HIGH + R-002 MEDIUM + R-003/R-004/R-005 LOW）+ refactorer 协议违规（直接 git commit）。r2 新增 R-001 LOW（runner.py 硬编码）。累计 self-caused 条目持续增长，RETRO 阈值监控应已覆盖。

---

## 三态判定

| 等级 | 数量 |
|------|------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 0 |
| LOW | 1 (R-001: runner.py _persist 硬编码，预存在，不阻塞) |

**verdict: approved_with_notes**

r1 的 HIGH (R-001) 和 MEDIUM (R-002) 已真实闭环：isinstance guard 完全删除、production path 走 session_factory DI、调用签名对齐实际接口。三个 LOW (R-003/R-004/R-005) 均闭环。本轮新发现 runner.py 内 1 个预存在 LOW（与 T-072 接驳一并清理更合适）。验证基线全部满足（44 目标测试 PASS + 1803 全量回归 PASS + mypy/ruff clean）。
