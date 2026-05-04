---
id: "code-review-T-072-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-072"]
---

# CODE-REVIEW-T-072-r2

任务: T-072 — 数据库会话 DI 接驳（DatabaseManager lifespan + get_db_session 迁移）
复审范围: git diff 2e21315..2225b65 — src/intellisource/main.py · src/intellisource/api/deps.py · tests/unit/api/test_deps.py · tests/unit/api/test_app_entry.py

验证基线: 37 目标测试 PASS · 1786 全量回归 PASS · mypy --strict src/ 0 errors · Layer 1 (cataforge skill run code-review -- src/): PASS

---

## R-001 复核：get_db_session 签名收紧 — 闭环确认

diff 确认以下全部修复：

- `request: Request = None` → `request: Request`（无默认值，必传）
- 删除 `# type: ignore[assignment]`
- 删除 `if request is None: yield None; return` 分支
- 返回类型 `AsyncIterator[AsyncSession | None]` → `AsyncIterator[AsyncSession]`

实跑 `grep -n "type: ignore\|request.*None\|yield None" deps.py` 返回空，无任何残留路径可触发 yield None。

**R-001: 闭环 ✓**

---

## R-002 复核：lifespan try 块覆盖完整初始化序列 — 闭环确认

修订后的 `_lifespan` 结构：

```python
db = DatabaseManager()    # try 块之前：若 ValueError 则 pool 从未建立，finally 无需运行
app.state.db = db
try:
    await init_redis()    # 在 try 内
    init_celery()         # 在 try 内
    yield {}
finally:
    await db.close()      # 覆盖 init_redis/init_celery 可能的失败
    await close_redis()
    shutdown_celery()
```

`DatabaseManager()` 实例化在 try 之前：若它抛 `ValueError`（IS_DATABASE_URL 缺失），连接池从未建立，finally 块不执行符合预期，无泄漏风险。`init_redis()` 或 `init_celery()` 失败时 `db.close()` 被 finally 保障执行，R-002 描述的连接池泄漏路径已消除。

`init_db_pool` / `close_db_pool` no-op 函数已完整删除（`grep -rn "init_db_pool\|close_db_pool" src/ tests/` 返回空）。

**R-002: 闭环 ✓**

---

## R-003 复核：TestGetDbSession 删除 — 闭环确认

`TestGetDbSession` 类（含 `test_yields_session`、`test_generator_completes`）已完整删除；`get_db_session` import 已从 test_deps.py 移除；`TestRequireApiKey` 的 5 个测试全部 PASS，未受影响。

**R-003: 闭环 ✓**

---

## 问题列表

### [R-001] LOW: `test_app_entry.py` 修订引入新的 ruff E501 违规（convention）

- **category**: convention
- **root_cause**: self-caused
- **描述**: r2 修订中将 `test_startup_initialises_db_redis_celery` 的 docstring 从原有的 `"AC-T045-2: Startup triggers database pool, Redis, and Celery init."` （80 字符，符合 88 字符限制）改写为 `"AC-T045-2: Startup triggers Redis and Celery init (DB managed by DatabaseManager)."` （96 字符，超出 88 字符限制）。这一新 E501 违规是 r2 **新引入** 的，不属于 pre-existing 问题（pre-r2 版本通过 ruff 检查时不存在 E501；pre-r2 该文件共 4 个 ruff 错误均为 F401/F841 pre-existing，r2 在此基础上新增 1 个 E501）。

  `uv run ruff check tests/unit/api/test_app_entry.py` 输出共 5 个错误，其中 F401 × 3 + F841 × 1 为 pre-existing，E501 × 1（行 181）为 r2 新增。

  注：pre-existing 的 4 个 ruff 错误（3 × F401 未使用 import + 1 × F841 未使用变量 `state`）属于本次修订范围之外的历史遗留，不新增到本报告作为独立问题；但实施者在修订该文件时应一并清理或至少不增加新的违规。

- **建议**: 缩短 docstring，例如 `"AC-T045-2: Startup triggers Redis and Celery init."` 即可还原到限制之内；或拆分为多行。此为 LOW，不阻塞合并，但建议在下次接触该文件时顺手修复（含一并清理同文件 pre-existing F401/F841）。

---

## Carryover（未修复，符合 Revision Protocol §3 策略）

以下问题在 r1 中标为 MEDIUM/LOW，未在 r2 中修复。验证结果：r2 diff 未涉及 R-004/R-005/R-006 的相关代码路径，均按预期保持原状。

| 编号 | 等级 | 描述 | 状态 |
|------|------|------|------|
| R-004 | MEDIUM | `IS_CELERY_BROKER_URL` 独立变量缺失，broker 与 cache 共用 `IS_REDIS_URL` | 未修复（carryover） |
| R-005 | LOW | `test_lifespan.py` 中冗余 `create=True` 参数 | 未修复（carryover） |
| R-006 | LOW | `conftest.py` `_patch_main_database_manager` 返回类型注解错误 | 未修复（carryover） |

---

## 备注

**ruff tests/ pre-existing 问题趋势**：r1 报告记录 `uv run ruff check tests/` 发现 166 个错误。r2 修订在 `test_app_entry.py` 中新引入 1 个 E501（上方 R-001），未改善也未显著恶化整体态势，但提示修订流程中 implementer 未对所修改的文件执行 `ruff check tests/`。建议在 retrospective 中评估是否将 `uv run ruff check tests/` 纳入质量门禁（当前质量门禁 scope 限于 `src/`）。

**Retro EXP 候选保留观察**：R-001 (r2 中已闭环) 的历史 lineage 与 r2 新引入的 ruff E501 共同构成 "implementer self-report scope drift / make-the-test-pass over update-the-test / 修改文件未运行对应 lint" 模式的持续证据。Lineage: T-058 N-001 → T-059 r1 R-003/R-004 → T-060 r1 R-001/R-002/R-003/R-004/R-006（ruff scope 声称 src/ clean 但 tests/ 含 E501）→ T-072 r1 R-001（get_db_session None fallback 测试约束实现）→ T-072 r2 新增 E501（修改 test_app_entry.py docstring 未执行 ruff check）。Sprint-7 末尾 retrospective 应提炼该模式为 EXP 学习条目。

---

## 三态判定

| 严重等级 | 问题编号 |
|---------|---------|
| HIGH | 无 |
| MEDIUM | 无（R-004 carryover，不新增） |
| LOW | R-001（新增 E501）；R-004/R-005/R-006（carryover） |

r1 HIGH 级问题 R-001 + R-002 全部闭环，R-003 MEDIUM 亦闭环。未引入新的 HIGH/CRITICAL。新增 1 个 LOW（test_app_entry.py E501），carryover MEDIUM/LOW 不增不减。

**verdict: approved_with_notes**

r1 HIGH 全闭环，无新 CRITICAL/HIGH。存在 1 个新增 LOW（convention/E501）及 3 个 carryover MEDIUM/LOW（R-004/R-005/R-006）。建议用户决策是否在后续迭代中处理这四项 notes，不阻塞当前 Sprint 推进。
