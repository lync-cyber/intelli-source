---
id: "code-review-T-083-r3"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-083"]
---

# CODE-REVIEW T-083 r3: /tasks/collect datetime 序列化修复

Layer 1 delegated to hook (PostToolUse Edit → lint_format.py)

**verdict**: approved
**问题统计**: CRITICAL 0 / HIGH 0 / MEDIUM 0 / LOW 0

---

## §0 r2 复检

### R-007 MEDIUM (error-handling) — RESOLVED

commit `74a7252` 将 `trigger_collect` 成功路径的返回由：

```python
return JSONResponse(
    status_code=202,
    content={
        "task_chain_id": task_chain_id,
        "tasks": [_task_brief(t) for t in tasks],
        "message": f"已创建 {len(tasks)} 个采集任务",
    },
)
```

改为：

```python
return {
    "task_chain_id": task_chain_id,
    "tasks": [_task_brief(t) for t in tasks],
    "message": f"已创建 {len(tasks)} 个采集任务",
}
```

路由装饰器已声明 `status_code=202`，FastAPI 默认响应路径经 `jsonable_encoder` 处理，`_task_brief` 中的 `created_at` datetime 字段将被正确序列化为 ISO 字符串。`JSONResponse` 绕过 `jsonable_encoder` 的问题已消除。

**R-007 RESOLVED.**

---

## §1 回归测试质量验证

### 测试非平凡性 — PASS

新增测试 `TestCollectDatetimeSerialization.test_collect_serializes_datetime_in_response_body` 满足非平凡性要求：

- `real_dt = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)` — 使用真实 `datetime` 对象，非字符串
- `task_obj.created_at = real_dt` — 覆写 `_make_task_obj` 默认的字符串值 `"2025-01-01T00:00:00+00:00"`，强制走 datetime → JSON 序列化路径
- 若代码仍包含 `JSONResponse(content={...})` 包装，该测试将因 `TypeError: Object of type datetime is not JSON serializable` 而 FAIL，具备有效拦截回归的能力
- 断言链：`resp.status_code == 202` → `len(body["tasks"]) == 1` → `isinstance(created_at_value, str)` → `"2026-05-21" in created_at_value`，验证了序列化的完整性（类型 + 值内容）

mock 注入路径：`patch("intellisource.api.routers.tasks.TaskRepository", return_value=mock_task_repo)` 在构造器级别拦截，`source_ids` 列表中含有效 UUID 直接走 resolved 路径，`source_repo.list_active_source_ids()` 不被调用，测试场景聚焦且清晰。

### `uv run pytest tests/unit/api/ -x` 结果 — PASS

168 passed / 1 skipped / 0 failed，含新增测试类全部通过。

---

## §2 非回归扫描（delta 范围）

### `JSONResponse` import 保留 — PASS

`from fastapi.responses import JSONResponse` 导入保留，用于：
- 400 分支（无效 UUID 错误，payload 仅含 `detail: str`，无 datetime 字段）
- 202 空 source_uuids 分支（`tasks: []`，无 datetime 字段）
- 404 分支（`GET /tasks/{id}` 路由，payload 仅含 `detail: str`）

上述三处 `JSONResponse` 使用均不含 datetime 类型字段，无需变更。PASS.

### `_task_brief` 与 `_serialize_task` 未变更 — PASS

`_task_brief` 仍返回 `"created_at": task.created_at`（原始值，由 FastAPI 处理序列化），与修复意图一致。`_serialize_task` 同样返回原始值，行为不变。PASS.

### 返回类型标注 — PASS

`trigger_collect` 签名为 `-> Any`，与其他端点风格一致（本项目 router 层统一使用 `Any` 而非具体 Pydantic 响应模型）。返回 `dict` 替代 `JSONResponse` 实例，`Any` 标注对两者均有效，mypy 无需额外变更。

---

## §3 deferred items 状态确认

以下问题由 orchestrator 决定延后，r3 不重新开启：

| 编号 | 来源 | 内容 | 状态 |
|------|------|------|------|
| R-002 | r1 | `init_celery` 与 `celery_app.py` 双实例分叉 | deferred |
| R-003 | r1 | `factory.py` 死参数 `session_factory / pipeline_config` | deferred |
| R-004 | r1 | `lifespan` shutdown `finally` 块缺少异常屏蔽防护 | deferred |
| R-005 | r1 | broker URL 含密码时 Celery 日志明文风险 | deferred |

---

## 总结

| 维度 | r3 结论 |
|------|---------|
| R-007 error-handling | **RESOLVED** — 成功路径改为 `return dict`，datetime 经 FastAPI jsonable_encoder 正确序列化 |
| 回归测试质量 | **PASS** — 新测试使用真实 datetime，具备有效拦截能力 |
| JSONResponse 其余分支 | **PASS** — 三处保留使用均不含 datetime 字段 |
| 全量 API 单测 | **PASS** — 168 passed / 0 failed |
| deferred (R-002~005) | 按 orchestrator 决定延后，不计入本次 verdict |

**verdict: approved**（0 CRITICAL / 0 HIGH / 0 MEDIUM / 0 LOW）
