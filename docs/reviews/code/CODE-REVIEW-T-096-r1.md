---
id: code-review-T-096-r1
doc_type: code-review
author: reviewer
status: approved
deps: [T-096]
---

# CODE-REVIEW: T-096 r1

> Layer 1 delegated to hook（`.claude/settings.json` 已注册 `python -m cataforge.hook.scripts.lint_format` 在 Edit|Write matcher；当前 ruff check + ruff format + mypy --strict 全 clean）。
> Layer 2 由 orchestrator 主线程接管 — 原 reviewer subagent (a678cd2f13fd2a8ea) 在 79 tools / 5.7min / 88K tokens 后被 task-notification truncation 打断，无报告 artifact 落地，仅尾部片段 "now let me also check status field handling in _process_execute session exception swallowing" 暗示审查方向。EXP-006 candidate frequency tick（sprint-9 累计 2 次 reviewer truncation：T-095 r1 + T-096 r1）。

## 审查范围
- task: T-096 [standard, fix, security_sensitive=false] PROCESSOR_REGISTRY + `_process_execute` 契约 + `_RawContentResultRepo` 持久化
- commit: c492cba（9 文件 / +151 / -37）
- AC 数: 9（AC-1~9 全 RED 落地于 0c72658，GREEN 后 8 unit 测试 + 30 既有 tools_execute PASS；3 integration 测试本地 SKIP / CI 验证）
- 验证维度: convention / structure / consistency / security / error-handling / dead-code / test-quality（tests 改动仅 ruff fix，test-quality 维度收敛于既有 RED 测试设计）

## verdict: needs_revision

存在 1 HIGH（持久化 contract violation：session.flush 无 commit）→ 路由进 Revision Protocol。其余 1 MEDIUM + 3 LOW 一并修复。

## 问题列表

### [R-001] HIGH: _RawContentResultRepo.create 缺 session.commit，AC-6 持久化未生效
- **category**: error-handling
- **root_cause**: self-caused
- **位置**: `src/intellisource/scheduler/boot.py:87-99`
- **描述**: `_RawContentResultRepo.create()` 用 `async with self._session_factory() as session:` 直接调用 `session_factory()` 获取 AsyncSession，**绕过了** `DatabaseManager.get_session()` 的 `@asynccontextmanager` 包装（database.py:60-72 的 get_session 会在退出时 `await session.commit()`，本路径不会）。当前实现 `row.status = "processed"` + `row.processed_at = utcnow()` 之后只调用 `await session.flush()`，session context 退出后**未 commit**（SQLAlchemy AsyncSession 默认 autocommit=False） → 写入的 SQL 在 session 关闭时被回滚 → DB 行实际不持久化。
- **AC 影响**: AC-6 字面要求"更新对应 RawContent 行的 status='processed'、processed_at=utcnow()"——当前实现不满足。AC-8 集成测试 `test_raw_content_persist_on_pipeline_done.py` 验证此契约，本地 SKIP（无 Docker） + CI 跑 testcontainers PG 时会失败。
- **建议**:
  ```python
  async with self._session_factory() as session:
      row = (
          await session.execute(
              select(RawContent).where(RawContent.id == raw_id).limit(1)
          )
      ).scalar_one_or_none()
      if row is not None:
          row.status = "processed"
          row.processed_at = datetime.now(tz=timezone.utc)
          await session.commit()  # ← 显式 commit，不依赖 context manager
  ```
  或更稳健的模式：复用 `DatabaseManager.get_session()` async context manager 让 commit/rollback 由框架统一处理（需要在 composition.build_worker_composition 把 `db_manager.get_session` 传给 `_RawContentResultRepo`，而非裸 `async_sessionmaker`）。前者改动小，推荐 r2 先采用；后者作为 sprint-9 收尾后的可选重构。

### [R-002] MEDIUM: test_tools_execute.py 用 AsyncMock mock 同步方法 pipeline_engine.execute，无法验证 AC-4 字面契约
- **category**: test-quality
- **root_cause**: self-caused（test-writer @ commit 0c72658；implementer 受其约束）
- **位置**: `tests/unit/agent/test_tools_execute.py:154,178,197`（3 处 `mock_engine.execute = AsyncMock(...)`）
- **描述**: 生产 `PipelineEngine.execute(self, context: PipelineContext) -> PipelineContext`（pipeline/engine.py:50）是**同步**方法，但测试用 `AsyncMock` mock 它使返回值为 coroutine。这迫使 implementer 在 `_process_execute` 增加 `if inspect.isawaitable(ctx_or_coro): ctx_or_coro = await ctx_or_coro`（tools.py:164-165）—— 这是测试-生产 mismatch 的兼容写法，AC-4 字面"**同步调用** pipeline_engine.execute(ctx)（无 await）"在测试下无法被验证。3 个测试运行时触发 `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited`，正是该 mismatch 的副作用。
- **AC 影响**: AC-4 字面契约（同步调用、无 await）当前依赖 implementer 主观自觉，无测试反证；未来回归（重新加 await）可能被静默接受。
- **建议**: r2 中：
  1. test_tools_execute.py 三处 mock 改为 `MagicMock()` + `mock_engine.execute = MagicMock(return_value=PipelineContext())` 准确反映同步签名
  2. 配合 R-003 简化 _process_execute 删除 awaitable fallback

### [R-003] LOW: tools.py:_process_execute 的 awaitable fallback 在生产为 dead code
- **category**: dead-code
- **root_cause**: self-caused（受 R-002 测试 mock 约束）
- **位置**: `src/intellisource/agent/tools.py:161-167`
- **描述**: `import inspect` + `if inspect.isawaitable(ctx_or_coro): ctx_or_coro = await ctx_or_coro` 分支在生产路径（`PipelineEngine.execute` 同步签名）永不触发。仅为测试 AsyncMock 兼容存在。是 R-002 的下游产物。
- **建议**: R-002 修复测试 mock 后，本处简化为：
  ```python
  ctx = tool_deps.pipeline_engine.execute(ctx)
  ```
  + 删除 `import inspect`（PLC0415 lazy import 也一并清理）。`hasattr(ctx_or_coro, "get")` 防御也可去除（execute 返回 PipelineContext 是契约保证）。

### [R-004] LOW: _process_execute 的 session-exception swallow 缺日志
- **category**: error-handling
- **root_cause**: self-caused
- **位置**: `src/intellisource/agent/tools.py:148-159`
- **描述**: `async with tool_deps.session_factory() as session: ... except Exception: pass` 静默吞掉 session/repo 异常后用空 PipelineContext 继续。生产环境 DB 不可达 / RawContent 缺失等场景被 silently 降级，难以从日志定位。
- **建议**:
  ```python
  except Exception as exc:
      logger.warning(
          "_process_execute: failed to load RawContent for %s: %s",
          content_id, exc, exc_info=True,
      )
  ```
  保持流程不抛（与 placeholder degraded 路径行为一致），但留下追踪线索。

### [R-005] LOW: scheduler/boot.py:_RawContentResultRepo.create 的 silent except 缺日志
- **category**: error-handling
- **root_cause**: self-caused
- **位置**: `src/intellisource/scheduler/boot.py:99`
- **描述**: AC-6 字面授权"不抛异常，仍返回 result"，故 `except Exception: pass` 不抛是合理的。但当前完全无日志，DB 写入失败时 worker 表面成功、实际 RawContent 永远 status=pending，调试时只能 git blame。
- **建议**: 加 logger.warning（同 R-004 模式）。本 LOW 与 R-001 修复一并处理。

## 通过项（不计 finding）
- AC-1: registry.py PROCESSOR_REGISTRY 注册 HTMLParser/ContentDedup/KeywordTagger 三项，覆盖 config/pipelines/*.yaml 所有引用（grep `processor:` 仅这 3 个名字）；get_processor 未知键 raise ValueError 符合"启动期硬失败"语义 ✓
- AC-2: `_build_processors_from_config` 通过 `get_processor(step_name)` + `step.get("params") or {}` 实例化真实 processor ✓
- AC-3: `_PassThroughProcessor` 类已删，两处 `[ASSUMPTION] yaml step → processor class mapping deferred to T-094` 注释已清 ✓
- AC-5: `ContentRepository.get_raw_by_id` 实现 select + scalar_one_or_none，签名 UUID → RawContent|None ✓
- AC-7/8/9: 12 unit + 3 TestProcessExecuteReal + （集成 SKIP 本地）测试 PASS
- Alembic migration a1b2c3d4e5f6 `down_revision = "62f6b6bf5177"` 链路正确（62f6b6bf5177 → a1b2c3d4e5f6）；`server_default="pending"` 处理既有行；downgrade 与 upgrade 反序（先 processed_at 再 status）✓
- tagger.py KeywordTagger keywords 改 optional：dev-plan T-096 deliverables 未列，但为支持 PROCESSOR_REGISTRY 零参数实例化的必要扩展（content-process.yaml steps 不传 params）→ 范围扩展合理
- storage/models.py + alembic migration 超出 dev-plan T-096 deliverables 但为 AC-6 隐含依赖（status/processed_at 字段必须存在），属合理扩展
- EXP-005 ToolDeps 装配回归：`_process_execute` 在 `tool_deps is None` 时仍返回 `status: degraded`（tools.py:131-138）—— T-096 阶段保留属设计正确（T-097 的 _collect/distribute 也保留同样 fallback；EXP-005 闭环在 T-095 已完成主路径，T-096 阶段不必额外清理）
- ruff check + ruff format --check + mypy --strict 全 clean（主线程已 inline 修复 RED 阶段 ruff I001 漏判）
- 全量回归 2380 PASS / 23 expected fail (T-097 RED) / 43 skip

## 修复路径建议（r2 工作量评估）
- R-001: scheduler/boot.py 加 `await session.commit()`（单文件 1 行新增） — **必修**
- R-002: test_tools_execute.py 3 处 mock 改 MagicMock + return_value=PipelineContext（单文件 ~6 行修改）
- R-003: tools.py 删 awaitable fallback + import inspect（单文件 ~6 行删除）
- R-004 + R-005: tools.py + boot.py 加 logger.warning（2 文件 ~4 行新增）
- 反证测试可选: 加 1 个 unit test 验证 `_RawContentResultRepo.create` 在 mock session 上调用 `session.commit()`（防 R-001 回归）—— 建议 r2 补，与 R-001 修复同提交
- 改动局部，无跨模块设计变更；implementer self-report `refactor_needed=false` 仍成立，r2 修复后不需要 REFACTOR

## 范围外（不影响 verdict）
- T-097 的 RED 测试在 commit 0c72658 同提交落地（27 测试 expected fail），属下一任务范围，本审查不评估其内容
- alembic upgrade head 是否需要在 r2 后同时跑 — 由 orchestrator 在 commit 后决定（CI 上 testcontainers 会自动 upgrade）
