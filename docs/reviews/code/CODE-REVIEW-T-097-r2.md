---
id: "code-review-T-097-r2"
doc_type: code-review
author: reviewer
status: approved
deps: [T-097]
---

# CODE-REVIEW-T-097-r2

本报告由 orchestrator 主线程 inline 接管（参考 T-094 / T-096 r2 inline approve 模式；sprint-9 EXP-006 频次告警下 r2 限定范围内修复审核可避免重复派 subagent 的 truncation 风险）。

## Layer 1 摘要

- `ruff check .` — All checks passed
- `ruff format` — clean
- `mypy --strict src/` — Success: no issues found in 116 source files
- 全量回归 `pytest -q` — **2409 passed / 43 skipped / 0 failed**（r1 基线 2406 → r2 增 3 反证测试）

Layer 1 clean。

## r1 5 个 finding 修复验证

### R-001 (MEDIUM, security) — _mask_recipient 边界文档 — **fixed**
**Diff**: `src/intellisource/distributor/facade.py:201-206`
```python
def _mask_recipient(raw: str) -> str | None:
    """Mask PII in recipient.

    Email/phone are masked; opaque platform IDs (wechat openid, wework user_id)
    pass through as they are not traditional PII.
    """
```
docstring 多行明确"哪些 ID 类型不属于受保护 PII"，消除函数注释与实现的语义落差。意图落地。

### R-002 (MEDIUM, completeness) — recipient_id 持久化 — **fixed**
**4 处协同修复**:
1. `src/intellisource/storage/models.py:486`: PushRecord 新增 `recipient_id: Mapped[Optional[str]] = mapped_column(VARCHAR(255), nullable=True)`
2. `alembic/versions/b2c3d4e5f6a7_add_push_record_recipient_id.py`: 新 migration，`down_revision=a1b2c3d4e5f6`，upgrade/downgrade 对称
3. `src/intellisource/distributor/facade.py:170-177`: `_record_push` 调用 `repo.create(recipient_id=recipient_id)`，通过 `**kwargs` 透传到 PushRecord 模型
4. 反证测试 `test_distribute_pushrecord_recipient_id_is_masked_and_persisted` PASS，验证脱敏值落库

AC-7 "record.recipient_id 已经过 PII 脱敏" 语义现真正实现。

### R-003 (MEDIUM, test-quality / convention) — session.scalars 消费模式 — **fixed**
**Diff**: `src/intellisource/distributor/facade.py:137-138`
```python
result = await session.scalars(stmt)
subscriptions: list[Any] = list(result.all())
```
与 `src/intellisource/storage/repositories/source.py:72` / `chat_session.py:70` / `base.py:117` 等 5 处 codebase convention 对齐。unit 测试 mock 同步更新为 `mock_scalars_result.all = MagicMock(return_value=[...])` 模式，验证消费链一致。

> **calibration note**: r1 reviewer 诊断"生产路径会得到协程对象列表"经 orchestrator 实证为误判（`list(await session.scalars(stmt))` 在 SQLAlchemy 2.0 async 下返回真实实体列表 — ScalarResult 是 sync iterable，list() 工作正常）。但 codebase convention 一致性是真问题，r2 修复同时根治。category 调整为 `convention`，root_cause 部分为 `reviewer-calibration`。

### R-004 (LOW, structure) — facade dedup 防御 — **fixed**
**Diff**: `src/intellisource/distributor/facade.py:177-186`
```python
try:
    await repo.create(...)
    await session.commit()
except Exception as exc:
    from sqlalchemy.exc import IntegrityError
    if isinstance(exc, IntegrityError):
        # Channel layer already recorded; idempotent skip
        pass
    else:
        raise
```
反证测试 `test_distribute_dedup_integrity_error_is_idempotent` PASS。

**Nit (LOW, 不阻断)**: 直接 `except IntegrityError: pass` 比 `except Exception + isinstance` 更简洁；但功能等价、覆盖率相同，r2 修复可接受。如后续触发 refactor 可顺手简化。

### R-005 (LOW, error-handling) — _collect_execute catch CollectorError — **fixed**
**Diff**: `src/intellisource/agent/tools.py:154-165`
```python
try:
    collector = tool_deps.collector_registry.get(source_type)
except CollectorError:
    return {
        "status": "degraded",
        "tool": "collect",
        "reason": f"unknown source_type: {source_type}",
        "collected": [],
        "source_id": source_id,
    }
```
返回结构与 tools.py 现有 degraded 路径一致（`status` / `tool` / `reason` / `collected` / `source_id`）。反证测试 `test_collect_execute_unregistered_source_type_returns_degraded` PASS。

## 反证测试落地（3 个）

| 测试 | 防回归目标 |
|------|-----------|
| `test_distribute_pushrecord_recipient_id_is_masked_and_persisted` | R-002 — 脱敏 recipient_id 落 PushRecord 列 |
| `test_distribute_dedup_integrity_error_is_idempotent` | R-004 — IntegrityError 触发时 facade 幂等不 raise |
| `test_collect_execute_unregistered_source_type_returns_degraded` | R-005 — 未注册 source_type 走 degraded 不 raise |

## EXP-005 ToolDeps 装配缺口回归审计

r2 仅在 distributor 层与 collector 层做范围内修复，不涉及 composition 装配链、ToolDeps 构造、agent factory；无新增 silent-None / silent-Mock 缺口。EXP-005 持续无回归。

## Verdict

- **status**: approved
- **理由**: r1 5 个 finding 全修；3 反证测试 PASS；2409 全量回归 + ruff + mypy --strict clean；alembic migration 结构正确（down_revision 链 a1b2c3d4e5f6 → b2c3d4e5f6a7）；R-004 风格 nit 不构成阻断。
- **AC 覆盖**: AC-1 ✓ AC-2 ✓ AC-3 ✓ AC-4 ✓ AC-5 ✓ AC-6 ✓ AC-7 ✓（语义完整实现）AC-8 ✓
- **后续 refactor 候选**（无阻断）: R-004 风格简化 `except IntegrityError: pass` 替代 `except Exception + isinstance`。
