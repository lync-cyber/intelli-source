---
id: "code-review-T-083-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-083"]
---

# CODE-REVIEW T-083 r2: 应用组合根与 Celery 链路真实初始化

Layer 1 delegated to hook (PostToolUse Edit → lint_format.py)

**verdict**: approved_with_notes
**问题统计**: CRITICAL 0 / HIGH 0 / MEDIUM 1 / LOW 0

---

## §0 r1 复检

### R-001 HIGH (consistency) — 已解决

commit `f567ad1` 将 `CollectRequest` 由 `source_id: str + trigger_type: str` 重写为 `source_ids: list[str] | None = None` + `priority: str = "normal"`，完全匹配 arch API-007 请求体契约。

响应体现在返回 `TaskTriggerResponse` 格式（`task_chain_id` / `tasks: [TaskBrief]` / `message`），HTTP 状态码为 202。
- `source_ids` 为 `None` 或空列表时调用 `SourceRepository.list_active_source_ids()` 做全量 fan-out。
- 无活跃信源时返回 202 + `tasks: []` + `task_chain_id` + `message`，不报错。
- `source_ids` 含无效 UUID 时返回 400，`detail` 字段列出无效条目。
- 每个 source 独立调用 `celery_instance.send_task("run_pipeline", kwargs=...)`，含 `source_id / task_id / task_chain_id / priority`。

**R-001 RESOLVED.**

### R-006 LOW (test-quality) — 已解决

新测试类 `TestCollectSendTaskPrecision` 全部使用精确断言：
- `call_args.args[0] == "run_pipeline"`
- `call_args.kwargs["kwargs"]["source_id"] == str(SOURCE_ID)`
- `call_args.kwargs["kwargs"]["task_id"] == str(FAKE_TASK_ID)`
- `call_args.kwargs["kwargs"]["priority"] == "high"`

原有字符串包含检查 (`"source_id" in str(sent_kwargs)`) 已全部移除。

**R-006 RESOLVED.**

---

## §1 deferred from r1（预期未修，不重新开启）

以下问题由 orchestrator 决定延后至后续 sprint，本 r2 不重新计入问题计数，仅记录状态：

| 编号 | 级别 | 内容 | 状态 |
|------|------|------|------|
| R-002 | MEDIUM | `init_celery` 与 `celery_app.py` 双实例分叉 | deferred |
| R-003 | MEDIUM | `factory.py` 死参数 `session_factory / pipeline_config` | deferred |
| R-004 | MEDIUM | `lifespan` shutdown `finally` 块缺少异常屏蔽防护 | deferred |
| R-005 | LOW | broker URL 含密码时 Celery 日志明文风险 | deferred |

---

## §2 net-new regression scan（revision delta 审查）

revision 涉及文件：`tasks.py`、`source.py`、`cli/main.py`、`test_tasks_router.py`、`test_tasks.py`

### 全量回归基线

`uv run pytest` 1949 passed / 0 failed / 29 skipped — 无回归。

### `source.py` 新增 `list_active_source_ids`

- `select(Source.id).where(Source.status == "active")` 查询结构清晰，使用 ORM scalars API 正确。
- 返回值类型 `list[uuid.UUID]` 与调用方 `source_uuids: list[uuid.UUID]` 一致。
- 无异常处理需求（SQLAlchemy 执行错误会自然传播至 FastAPI 异常中间件，与其余 repository 方法一致）。
- PASS.

### `cli/main.py` 变更

`payload = {"source_ids": [source_id]}` — CLI 单 source_id 正确包装为列表，与新 schema 对齐。PASS.

### `tasks.py` — trigger_collect 重构

- UUID 验证循环结构清晰，CC ≤ 3，无复杂度问题。
- `task_chain_id = str(uuid.uuid4())` 在 loop 外生成，所有子任务共享同一 chain ID — 正确。
- `celery_instance` guard 保留，行为与 r1 一致。

### [R-007] MEDIUM: `_task_brief` 将 `created_at`（datetime）直接传入 `JSONResponse.content`

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `_task_brief` 返回 `"created_at": task.created_at`，该字段在生产环境为 `datetime` 对象（见 `storage/models.py` `CreatedAtMixin`）。`JSONResponse` 内部使用标准 `json.dumps`，不通过 FastAPI 的 `jsonable_encoder`，无法序列化 `datetime`，在生产环境中将引发 `TypeError: Object of type datetime is not JSON serializable` 并导致 500 响应。单元测试中 `obj.created_at` 被 mock 为字符串 `"2025-01-01T00:00:00+00:00"`，因此测试通过但未覆盖此场景。注意：`_serialize_task`（用于 `GET /tasks` 等端点）直接 `return dict` 由 FastAPI 经 `jsonable_encoder` 处理，不存在此问题；本次 revision 新增的 `trigger_collect` 改用 `JSONResponse(content={...})` 包装，引入了这一不一致。
- **建议**: 将 `_task_brief` 中的 `created_at` 改为 `task.created_at.isoformat() if task.created_at else None`；或将 `trigger_collect` 的成功响应改为直接 `return {"task_chain_id": ..., "tasks": [...], "message": ...}`（配合路由的 `status_code=202`），令 FastAPI 统一处理序列化，与其他端点风格一致。

### 测试覆盖

- `test_tasks_router.py` 重写为 5 个测试类 15 个测试用例，覆盖：单 source / 多 source / 无 source_ids fan-out / 无活跃信源 / 无效 UUID / send_task 精确断言。
- `test_tasks.py` 同步更新，所有测试通过。
- 未覆盖场景：`celery_app` 未挂载到 `app.state` 时的 fan-out 行为（send_task 被跳过，仅返回 task 列表）— 此为 pre-existing gap，非本次 revision 引入。

---

## 总结

| 维度 | r2 结论 |
|------|---------|
| consistency (R-001) | **RESOLVED** — `source_ids: list[str] \| None` + `TaskTriggerResponse` 与 arch API-007 完全对齐 |
| test-quality (R-006) | **RESOLVED** — `send_task` 精确断言，消除字符串序列化模糊 |
| error-handling (R-007, net-new) | MEDIUM — `_task_brief` datetime 传入 `JSONResponse` 在生产环境会 500 |
| deferred (R-002~005) | 按 orchestrator 决定延后，不计入本次 verdict |
| regression | 无回归（1949 passed） |

**verdict: approved_with_notes**（0 CRITICAL / 0 HIGH；1 MEDIUM R-007，按 COMMON-RULES §三态判定 → approved_with_notes）
