---
id: "code-review-T-100-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-100"]
---

# CODE-REVIEW T-100 r1

**任务范围**: T-100 [light] — Celery Beat 同步 + push-optimize 触发 + ChatSession DB
**提交**: 1c1140c (PR #51)
**审查模式**: light + security_sensitive=false; 6 AC > CODE_REVIEW_L2_SKIP_LIGHT_MAX_AC=2 → Layer 2 强制运行
**Reviewer**: orchestrator inline

## Layer 1 结果

`cataforge skill run code-review` exit 0；ruff + ruff format + mypy --strict clean (124 src files)；全量 pytest 2517 PASS / 43 SKIP / 0 FAIL（含 20 个 T-100 新测试）。

## Verdict: needs_revision

1 个 HIGH（worker 路径 push-optimize 永不触发）→ **needs_revision**。

---

## 问题列表

### [R-001] HIGH: Worker composition 未向 DistributorFacade 透传 celery_app — push-optimize 实际永远不触发
- **category**: structure
- **root_cause**: self-caused
- **描述**: `composition.py` 中 `_build_deps_bundle(session_factory, redis_client, celery_app=None)` 默认 celery_app=None。`build_api_composition` 在 API 进程内调用时传入 `_api_celery_app = module_celery_app`，但 `build_worker_composition`（`composition.py:343`）调用：
  ```python
  bundle = _build_deps_bundle(session_factory, redis_client)
  ```
  **不传 celery_app**。这意味着：
  - Worker 进程构造的 DistributorFacade `_celery_app = None`
  - 而 `distribute` 实际**绝大多数时候在 Worker 进程内执行**（Celery `run_pipeline` 任务运行 collection→processing→matching→distribute 链路）
  - `_maybe_trigger_push_optimize` 内 `if self._celery_app is None: return` 即静默跳过
  - 即使 `IS_PUSH_OPTIMIZE_ENABLED=1` 设置，生产环境**push-optimize 任务永远不会被 distribute 链路触发**
  - AC-3 名义上达标（API 直接调 distribute 路径会触发），但实际产品语义不满足

  T-098 R-001 装配缺口模式的变体：单元测试通过（_make_facade 显式 inject celery_app=MagicMock），生产链路无人 wire。
- **建议**:
  1. `composition.py:build_worker_composition` 在调用 `_build_deps_bundle` 时传入 `celery_app=_module_celery_app`：
     ```python
     from intellisource.scheduler.celery_app import celery_app as _module_celery_app
     bundle = _build_deps_bundle(
         session_factory, redis_client, celery_app=_module_celery_app
     )
     ```
  2. 补 `tests/integration/test_composition_wires_celery_app_to_facade.py`（或扩展 test_composition_wires_webhook_state.py）反证：build_worker_composition + build_api_composition 两入口都断言 `bundle.distributor._celery_app is module_celery_app`。

### [R-002] MEDIUM: chat_search 每请求 open DB session 两次（lookup + persist）
- **category**: performance
- **root_cause**: self-caused
- **描述**: `api/routers/search.py:chat_search` 先 `async with db_manager.get_session() as db_session: await _load_chat_session(...)`，再 `async with db_manager.get_session() as db_session: await _persist_chat_turn(...)`。两次 connection round-trip。SQLAlchemy session pool 复用连接降低代价，但仍有上下文管理 + transaction 开销 + 数据一致性风险（lookup 与 persist 之间 history 可能被并发请求改写）。
- **建议**: 合并为单次 session：
  ```python
  async with db_manager.get_session() as db_session:
      stored_session, session_uuid = await _load_chat_session(db_session, body.session_id)
      # ... run_flexible 在 session 内会持有过长 — 实际改进是仅在 persist 时单次 open
      # 简化路径: lookup 后立即 commit 释放, persist 再开新 session（避免 LLM 调用时持锁）
  # ... run_flexible ...
  async with db_manager.get_session() as db_session:
      await _persist_chat_turn(...)
  ```
  当前两次 open 实际是合理的（避免 LLM 调用期间持锁），但应在 docstring 说明 WHY。或封装为 `with_session` helper 集中处理。

### [R-003] MEDIUM: `_bootstrap_beat_schedule` 用 `asyncio.run` 嵌套 loop 时 silent fallback
- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `scheduler/boot.py:_bootstrap_beat_schedule` 用 `asyncio.run(populate_scheduler_from_sources(scheduler_manager, factory))`。`asyncio.run` 拒绝嵌套事件循环（"asyncio.run() cannot be called from a running event loop"）。代码捕获 RuntimeError 后 `logger.warning(...)` 并 return，结果 Beat schedule 整个 sync 被跳过，但 worker 仍 boot。
  - 单元测试 `test_is_beat_disabled_env_skips_sync` 通过仅因 env flag 走 early return
  - 集成测试 `test_sources_populate_beat_schedule` 用 `_bootstrap_beat_schedule` 在测试主线程的 sync 上下文跑通
  - 但若 Celery worker 用 gevent/eventlet pool（已有 event loop）则 silent skip — 这是隐藏的生产路径缺陷

- **建议**: 用 `init_worker_session_factory` 同款 sync-friendly 模式：
  - factory() 返回 sync session（已经是）→ 在 `_bootstrap_beat_schedule` 内创建 loop:
    ```python
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(populate_scheduler_from_sources(...))
    finally:
        loop.close()
    ```
  - 或彻底改为 sync 实现：用 sync SQLAlchemy session（独立于 worker async session）查 Source 表 + 填 SchedulerManager。
  - 至少：把 fallback 从 `logger.warning` 升级为 `logger.error` 标记装配失败。

### [R-004] MEDIUM: push-optimize 触发粒度 = 每匹配订阅，不是每内容
- **category**: performance
- **root_cause**: self-caused
- **描述**: `facade.distribute` 在 `for sub in matched:` 循环内每次成功 send 后调用 `_maybe_trigger_push_optimize`。若一篇 content 匹配到 100 个订阅，则会触发 **100 个** push-optimize 任务（同 content_id，不同 channel 名）。即使 channel 重复（5 wechat + 5 wework + 90 email），仍会触发 100 次（按 sub 计数）。Celery 队列被无意义放大 N 倍。
- **建议**:
  - 选项 A：把触发提到 `distribute` 末尾，按 (content_id, channel_set) 去重一次性触发。
  - 选项 B：保留 per-channel 触发，但 dedup `(content_id, channel)` set 后再投递。
  - 选项 C：放到 Worker process 的 push-optimize.yaml 内部按 content_id 聚合后置策略。
  - 建议选项 B：在 distribute 循环内累计 `triggered_channels: set[str]`，循环结束后逐 channel 触发一次。

### [R-005] LOW: chat_search 中 session_uuid fallback 是 dead code
- **category**: dead-code
- **root_cause**: self-caused
- **描述**: `search.py:chat_search`:
  ```python
  session_id_str = body.session_id or (
      str(session_uuid) if session_uuid is not None else str(uuid.uuid4())
  )
  ```
  逻辑分析：`session_uuid` 仅在 `body.session_id` 非空且 UUID 解析成功时被设置（见 `_load_chat_session`）。如果 `body.session_id` 为空，`session_uuid` 永远是 None，走 `str(uuid.uuid4())`。如果 `body.session_id` 非空，前半 `body.session_id or ...` 短路就返回 body.session_id，永不进入后半。
  → `str(session_uuid) if session_uuid is not None else ...` 这段永远不会执行。
- **建议**: 简化为：
  ```python
  session_id_str = body.session_id or str(uuid.uuid4())
  ```
  删除 dead branch。

### [R-006] LOW: `_maybe_trigger_push_optimize` 是 sync 但 dispatched from async context
- **category**: convention
- **root_cause**: self-caused
- **描述**: `_maybe_trigger_push_optimize` 是 sync def 但在 `async def distribute` 内调用。Celery `send_task` 本身是 sync（producer 阻塞 broker 调用），所以 sync 实现是正确的，但缺少注释说明 "WHY not async"。未来如果有人误将其改为 async 又 await 会引入 bug。
- **建议**: 加单行注释：
  ```python
  def _maybe_trigger_push_optimize(self, ...) -> None:
      # Sync by design: celery_app.send_task is a blocking producer call;
      # wrapping in `await asyncio.to_thread` would add overhead without benefit
      # since send_task returns quickly (it does not wait for task execution).
  ```

### [R-007] LOW: `populate_scheduler_from_sources` 静默跳过 schedule_interval 为零或 None
- **category**: completeness
- **root_cause**: self-caused
- **描述**: `beat_sync.py:populate_scheduler_from_sources`:
  ```python
  interval = getattr(source, "schedule_interval", None)
  if not interval:
      continue
  ```
  `Source.schedule_interval` SQLAlchemy 字段定义为 `int = 3600` 默认 — 不应为 None；但若 DB 数据手工塞 0 或迁移导致 NULL，会被静默跳过没有日志可见性。
- **建议**: 加 `logger.warning("Source %s skipped: schedule_interval=%r", source.id, interval)`，至少标记跳过原因。

---

## 严重等级聚合

| 等级 | 计数 | finding IDs |
|------|------|-------------|
| CRITICAL | 0 | — |
| HIGH | 1 | R-001 |
| MEDIUM | 3 | R-002, R-003, R-004 |
| LOW | 3 | R-005, R-006, R-007 |

## REFACTOR 触发判定

不触发独立 REFACTOR；R-001/R-004 修复都属于结构性微调而非大块代码重构。

## 修订路径建议

r2 必修: R-001（HIGH structure — push-optimize Worker 路径装配）
r2 一并修: R-002 / R-004（performance + N-fold 放大），R-005 / R-006 / R-007（LOW 三件 one-shot）
R-003 短期 r2 升级 log level 即可（asyncio.run fallback 已留 warning），长期 backlog 重构为 sync 实现或 new_event_loop 模式
