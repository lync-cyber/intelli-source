---
id: "code-review-T-100-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-100"]
---

# CODE-REVIEW T-100 r2

**任务范围**: T-100 [light] — Celery Beat 同步 + push-optimize 触发 + ChatSession DB
**提交**: e5a783f (PR #51) — fixes on top of r1 baseline 1c1140c
**审查模式**: light + security_sensitive=false; Layer 2 强制运行
**Reviewer**: orchestrator inline (与 T-099 r2 + T-098 r2 同源协议)
**前置**: CODE-REVIEW-T-100-r1.md verdict=needs_revision (1 HIGH + 3 MEDIUM + 3 LOW)

## Layer 1 结果

`cataforge skill run code-review` exit 0；ruff + ruff format + mypy --strict clean (124 src files)；全量 pytest 2519 PASS / 43 SKIP / 0 FAIL (+2 反证 vs r1 baseline 2517)。

## Verdict: approved

7 个 r1 findings 全部修复 + 2 反证测试新增。无新引入 CRITICAL/HIGH 问题。

## R1 → R2 逐项验收

### HIGH (1/1 修复)

#### R-001 — Worker composition 未透传 celery_app
- **修复路径**: `composition.py:build_worker_composition` 从 module-level 拉 `_module_celery_app`，传入 `_build_deps_bundle(...celery_app=_module_celery_app)`。
- **反证测试**: `tests/unit/distributor/test_push_optimize_trigger.py::TestWorkerCompositionWiresCeleryApp::test_worker_composition_facade_has_celery_app` — monkeypatch `_build_deps_bundle` 捕获调用 kwargs，断言 `celery_arg is module_celery_app`。
- **EXP-005 闭环**: 这是装配缺口模式的第 5 次复发（T-088 R-007 + T-092 N-001 + T-089 r1 + T-098 R-001 + T-100 R-001）。retrospective 立项时强烈建议把 "Worker path vs API path 装配对称性" 加入 framework-level lint 规则讨论。

### MEDIUM (3/3 修复)

#### R-002 — chat_search 双 session 性能
- **修复路径**: 保留双 open 设计（lookup 与 persist 分离），但在 docstring 显式标注 WHY："避免 LLM 调用期间持 DB 锁"。设计意图固化。无 code 改动。
- **替代评估**: 单 session 包裹 LLM 调用会让连接池在等 LLM 响应（数秒）期间持锁，对 DB 连接数压力更大。当前双开是正确权衡。

#### R-003 — `asyncio.run` 嵌套 loop fallback
- **修复路径**: `scheduler/boot.py:_bootstrap_beat_schedule` 改 `asyncio.new_event_loop() + run_until_complete + close()`。
  - 解 gevent/eventlet pool 已有 loop 时 silent skip 整个 Beat sync 的隐藏路径缺陷
  - fallback log 升 `logger.warning` → `logger.error` 标记装配失败
  - 集成测试 `test_sources_populate_beat_schedule` 继续通过

#### R-004 — push-optimize 触发 N-fold 放大
- **修复路径**: `facade.distribute` 维护 `triggered_channels: set[str]`，在 for-sub 循环内累加 channel 名，循环结束后按 sorted 序唯一遍历调用 `_maybe_trigger_push_optimize`。
- **反证测试**: `test_push_optimize_dedup_per_channel` — 5 个匹配订阅（3 wechat + 2 wework）触发后 `celery.send_task.call_count == 2`，channels_dispatched == {wechat, wework}。

### LOW (3/3 修复)

#### R-005 — `session_uuid` fallback dead code
- **修复**: 简化 `session_id_str = body.session_id or str(uuid.uuid4())`。删除不可达分支。

#### R-006 — sync-by-design 未注释
- **修复**: `_maybe_trigger_push_optimize` 加注释 "Sync by design: celery_app.send_task is a blocking broker producer call but returns quickly; wrapping in asyncio.to_thread adds overhead without benefit."

#### R-007 — schedule_interval=0/null 静默跳过
- **修复**: `populate_scheduler_from_sources` 在 `not interval` 分支加 `logger.warning("Source %s skipped: schedule_interval=%r ...", source.id, interval)` 提升可观测性。

## 新增反证测试统计

| 类别 | 数量 | 文件 |
|------|------|------|
| Worker composition celery_app wiring | 1 | tests/unit/distributor/test_push_optimize_trigger.py |
| Push-optimize per-channel dedup | 1 | 同上 |
| **合计** | **2** | — |

## REFACTOR 触发判定

`TDD_REFACTOR_TRIGGER [complexity, duplication, coupling]` 不触发：
- complexity: `_bootstrap_beat_schedule` 圈复杂度 4，其余 ≤3
- duplication: 无跨文件重复
- coupling: composition → scheduler.celery_app 是 sprint-9 一致的 lifespan 协议，非引入

不需独立 REFACTOR 阶段。

## EXP-005 装配缺口模式 — sprint-9 累计 5 次复发观察

| Sprint | 任务 | Finding | 装配缺口本质 |
|--------|------|---------|------------|
| sprint-8r | T-088 | R-007 | lifespan 未注入 collectors |
| sprint-8r | T-092 | N-001 | build_celery_tasks 漏传 content_repository |
| sprint-8r | T-089 | r1 | tool_deps 未注入 + ToolDeps 未构建 |
| sprint-9 | T-098 | R-001 | webhook_token + cs_messenger 4 状态项未装配 |
| sprint-9 | T-100 | R-001 | Worker composition 未向 facade 透传 celery_app |

**5 次跨 6 任务复发**，每次发现于 code-review HIGH，每次测试黑洞掩盖。retrospective 立项时框架级建议：
1. 自定义 ruff plugin 扫描 `app.state.X` / `self._X = celery_app` 等模式，标记"读但全 src 无写"或"装配差异 between Worker vs API path"。
2. tech-lead 任务卡 template 强制 "Worker path + API path lifespan symmetric checklist" 字段。
3. code-review SKILL.md 第 0 步 — 装配缺口扫描作为强制 Layer 1 检查。

## EXP-006 truncation 观察

T-100 light + orchestrator inline 实施零 truncation 复发。sprint-9 累计仍 4/4（T-095 r1 reviewer + T-096 r1 reviewer + T-098 RED test-writer + T-098 GREEN implementer），未恶化。

## 结论

T-100 r2 全部 7 findings 闭环 + 2 反证测试。verdict=approved，无 r3 需要。

**下一步**: T-100 status=approved；sprint-9 全 6 任务（T-095/T-096/T-097/T-098/T-099/T-100）批次 2-3 全闭环。可启动 sprint-9 sprint-review 或直接进入 retrospective（5 次 EXP-005 复发 + 4 次 EXP-006 truncation 已超 RETRO_TRIGGER_SELF_CAUSED=5 阈值，强制立项）。
