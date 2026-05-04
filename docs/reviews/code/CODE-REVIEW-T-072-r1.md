---
id: "code-review-T-072-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-072"]
---

# CODE-REVIEW-T-072-r1

任务: T-072 — 数据库会话 DI 接驳（DatabaseManager lifespan + get_db_session 迁移）
审查范围: src/intellisource/main.py · src/intellisource/api/deps.py · src/intellisource/api/routers/{sources,contents,tasks,subscriptions,search}.py · tests/unit/api/test_lifespan.py · tests/unit/api/test_deps_integration.py · tests/unit/api/conftest.py

Layer 1 (ruff check src/ + mypy --strict src/): 已 PASS（由任务描述确认，Layer 1 delegated 到 GREEN 前已验证）

---

## 问题列表

### [R-001] HIGH: `get_db_session` 保留 `request=None` fallback — 语义契约偏离 AC-T072-2，且以 `# type: ignore[assignment]` 掩盖类型不安全

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `deps.py:get_db_session` 当前签名如下：

  ```python
  async def get_db_session(
      request: Request = None,  # type: ignore[assignment]
  ) -> AsyncIterator[AsyncSession | None]:
      if request is None:
          yield None
          return
      async with request.app.state.db.get_session() as session:
          yield session
  ```

  问题一：AC-T072-2 明确要求函数从 `request.app.state.db.get_session()` yield **真实 AsyncSession**；但当前实现保留了一条 `request is None → yield None` 分支，该分支在 production 路径中不应存在，却被保留以兼容 `tests/unit/api/test_deps.py:60-75` 两个 placeholder 时代测试（`gen = get_db_session()` 不传 request，期望 yield None）。

  问题二：返回类型声明为 `AsyncIterator[AsyncSession | None]`，但 5 个路由全部声明 `session: AsyncSession = Depends(get_db_session)`（无 `| None`）。mypy strict 因 FastAPI `Depends()` 的特殊类型推导不报错，但 **运行时若 None 分支被意外触发，`SourceRepository(None)` 等调用将在调用栈深处引发 AttributeError，而非在 DI 层立即失败**。

  问题三：`# type: ignore[assignment]` 使用不当——该注释压制了"Request 类型的默认值 None 不合法"这一真正的设计信号，而不是真正的误报。

  正确做法（Option A，推荐）：收紧签名为 `request: Request`（无默认值），删除 None 分支，返回类型改为 `AsyncIterator[AsyncSession]`；同时将 `test_deps.py:60-75` 两个 placeholder 测试替换为使用真实 mock Request 的有效断言（参考 `test_deps_integration.py` 已有模式）。

  正确做法（Option B，最小改动）：保留可选 request 但改为 `Optional[Request] = None`；若 None 则应抛 `RuntimeError("no request context")` 而非 yield None，并将 `test_deps.py:60-75` 改为期望 RuntimeError。这比当前行为更安全，但仍不如 Option A 整洁。

  Option A 与 Option B 均消除了"None 被静默传入下游 Repository"的风险；Option A 更符合 AC-T072-2 的语义契约。

- **建议**: 采用 Option A。删除 `# type: ignore[assignment]`，改签名为 `async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:`，删除 None 分支，将 `test_deps.py:60-75` 两个测试改写为使用 mock Request 的正常路径验证（或直接迁移进 `test_deps_integration.py` 已有的 `TestGetDbSessionYieldsRealSession` 类）。

---

### [R-002] HIGH: lifespan 启动失败时 `db.close()` 不被调用 — 连接池泄漏

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `main.py` 的 `_lifespan` 结构如下：

  ```python
  await init_db_pool()     # no-op
  db = DatabaseManager()   # 若 IS_DATABASE_URL 缺失则 ValueError
  app.state.db = db
  await init_redis()       # 若 Redis 不可达则抛出异常
  init_celery()            # 若配置错误则抛出异常
  try:
      yield {}
  finally:
      await db.close()     # 仅在 try 块正常进入后才执行
      ...
  ```

  `try/finally` 仅包裹 `yield {}` 本身，不覆盖 `init_redis()` 和 `init_celery()` 的调用。若 `DatabaseManager()` 成功（pool 已建立）但 `init_redis()` 随后抛出异常，`db.close()` **不会被调用**，SQLAlchemy 连接池不会被 dispose，导致连接资源泄漏。在容器健康检查循环或测试套件多次重启场景下，泄漏会累积。

  arch#§5.3 要求所有基础设施初始化失败须有明确的恢复路径。

- **建议**: 将 `db.close()` 调用覆盖到完整初始化序列之上。推荐重构为：

  ```python
  db = DatabaseManager()
  app.state.db = db
  try:
      await init_redis()
      init_celery()
      yield {}
  finally:
      await db.close()
      await close_redis()
      shutdown_celery()
  ```

  `init_db_pool()` 和 `close_db_pool()` 是 no-op，可直接移除以减少误导性代码。

---

### [R-003] MEDIUM: `test_deps.py:60-75` 两个 placeholder 测试断言过时行为，与 AC-T072-2 语义冲突

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `TestGetDbSession.test_yields_session` 和 `test_generator_completes` 直接调用 `get_db_session()`（无 request 参数），然后断言 `session is None`，注释写明"Placeholder implementation yields None"。这两个测试已经过时：它们验证的是 placeholder 旧行为，而不是 AC-T072-2 要求的新行为。当前实现通过 `request=None` fallback 刚好能让这两个测试继续 PASS，但这恰好是 R-001 指出的问题的根因——测试约束了实现向后收紧。  
  即使不修改 `get_db_session` 签名（选择 Option B），这两个测试也应当更新为验证真实的请求路径行为，而非 placeholder 行为。

- **建议**: 删除或重写 `test_deps.py:TestGetDbSession` 类中的两个 placeholder 测试，改为与 `test_deps_integration.py` 一致的 mock Request 方式验证真实 session 注入路径。若采纳 R-001 Option A，这两个测试会自然失败并需要重写，可在同一 PR 中一并处理。

---

### [R-004] MEDIUM: `init_redis()` 和 `init_celery()` 共用同一个 `IS_REDIS_URL` 环境变量作为 Celery broker URL — 可配置性不足

- **category**: consistency
- **root_cause**: self-caused
- **描述**:

  ```python
  # init_redis()
  redis_url = os.environ.get("IS_REDIS_URL", "redis://localhost:6379/0")
  # init_celery()
  broker_url = os.environ.get("IS_REDIS_URL", "redis://localhost:6379/0")
  ```

  Celery broker 和 aioredis 客户端指向同一个 URL 和同一个 Redis database index（/0）。在需要将 broker 和 cache 分离到不同 Redis database（如 broker=db:1, cache=db:0）的生产部署中，此设计无法满足需求，且两者共用同一个环境变量名使分离成本更高。arch#§7.1 规定环境变量使用 `IS_` 前缀，但 Celery broker 应有独立变量（如 `IS_CELERY_BROKER_URL`）。

- **建议**: 为 Celery broker 引入独立环境变量 `IS_CELERY_BROKER_URL`，默认值 fallback 到 `IS_REDIS_URL`（向后兼容）：

  ```python
  broker_url = os.environ.get("IS_CELERY_BROKER_URL") or os.environ.get("IS_REDIS_URL", "redis://localhost:6379/0")
  ```

---

### [R-005] LOW: `test_lifespan.py` 中大量 patch 使用 `create=True` — RED 阶段与 GREEN 阶段修改合理但可简化

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: GREEN 阶段 implementer 对 `test_lifespan.py` 中多处 `patch()` 调用加上了 `create=True` 参数。`create=True` 的语义是"如果目标属性不存在，自动创建它"。由于 GREEN 阶段实现后 `intellisource.main` 已经真实导入了 `DatabaseManager`、`aioredis`、`Celery`，这些属性已经存在，`create=True` 是多余的。它的存在会掩盖将来 import 路径变更时本应失败的 patch，降低测试的脆性保护能力。

  修改本身不算错误——测试仍然正确地验证了预期行为。但作为 RED 产出的修改，需确认这是 patch 路径调整（合理），而非改变测试的断言逻辑（不合理）。经核查，GREEN 阶段的修改仅限于：(1) 添加 `mock_db.close = AsyncMock()` 防止 AttributeError；(2) 添加 `create=True`；(3) 轻微格式调整。断言逻辑未变。这些修改属于合理的技术适配。

- **建议**: 后续可以考虑移除冗余的 `create=True` 参数（当 import 路径已经确立时），保持 patch 的严格性。不阻塞本次审查。

---

### [R-006] LOW: `conftest.py` `_patch_main_database_manager` 返回类型注解错误（`AsyncIterator[None]` 应为 `Iterator[MagicMock]`）

- **category**: convention
- **root_cause**: self-caused
- **描述**: `conftest.py:63`:

  ```python
  def _patch_main_database_manager() -> AsyncIterator[None]:  # type: ignore[misc]
  ```

  该 fixture 是一个**同步生成器**（使用 `with patch... as _p: yield _p`），正确类型应为 `Generator[MagicMock, None, None]` 或简写 `Iterator[MagicMock]`。`AsyncIterator[None]` 既错误（不是 async），又掩盖了真实返回值类型（yield 的是 mock patcher，不是 None）。`# type: ignore[misc]` 被用来压制由此产生的类型错误，而非抑制合理误报。  
  该注解不影响运行时行为（pytest 正确处理同步生成器 fixture），但违反 arch#§7.2 mypy strict 的精神。

- **建议**: 修改为：
  ```python
  from typing import Generator
  from unittest.mock import MagicMock

  def _patch_main_database_manager() -> Generator[MagicMock, None, None]:
  ```
  并移除 `# type: ignore[misc]`。

---

## 备注

**仓库 tests/ 目录下的 pre-existing ruff 错误**：本次审查执行 `uv run ruff check tests/` 发现 **166 个错误**（主要为 E501 行过长 + 少量 F401 未使用 import），分布于 `tests/unit/agent/test_orchestration.py` 等多处。这些错误为 pre-existing，与 T-072 无关，T-072 的 ruff scope 限于 `src/` 故未阻断。但这与 Sprint-7 RETRO 候选证据一致（`T-060 r2 ruff scope 声称 src/ clean 但 tests/ 含 16 处 E501`，当前数据显示问题已扩大至 166 处），建议在 retrospective 时纳入讨论，并评估是否将 `uv run ruff check tests/` 纳入质量门禁范围。

---

## 三态判定

| 严重等级 | 问题编号 |
|---------|---------|
| HIGH | R-001, R-002 |
| MEDIUM | R-003, R-004 |
| LOW | R-005, R-006 |

**verdict: needs_revision**

存在 HIGH 级问题：

- **R-001** (`get_db_session` optional-request + None fallback)：直接违背 AC-T072-2 语义契约，且引入类型不安全的 `AsyncSession | None` 泄漏至路由层。
- **R-002** (lifespan startup 失败时 `db.close()` 未保护)：基础设施资源泄漏，违反 arch#§5.3 错误处理策略。

必须修复后提交 r2。
