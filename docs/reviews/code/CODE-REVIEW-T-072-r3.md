---
id: "code-review-T-072-r3"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-072"]
---

# CODE-REVIEW-T-072-r3

任务: T-072 — 数据库会话 DI 接驳（DatabaseManager lifespan + get_db_session 迁移）
复审范围: git diff ff5c382..c59cbdc — src/intellisource/main.py (+4/-2) · tests/unit/api/conftest.py (+3/-1) · tests/unit/api/test_app_entry.py (+5/-1) · tests/unit/api/test_lifespan.py (+16/-16)

验证基线: 18 lifespan+app_entry 测试 PASS · 126 tests/unit/api/ PASS · 1786 全量回归 PASS · mypy --strict src/ 0 errors · Layer 1 (cataforge skill run code-review -- src/intellisource/main.py ...): PASS · ruff check tests/unit/api/test_app_entry.py --select E501: 零违规

---

## r2 四项 notes 闭环复核

### R-001-r2 (LOW/convention): E501 违规 — 闭环确认

实跑 `uv run ruff check tests/unit/api/test_app_entry.py --select E501`：All checks passed，零 E501 输出。

读文件 test_app_entry.py L181-184：

```python
"""AC-T045-2: Startup triggers Redis and Celery init.

DB lifecycle is managed by DatabaseManager.
"""
```

原 96 字符单行 docstring 已拆分为首行 48 字符 + 续行 38 字符，两行均远低于 88 字符上限。

**R-001-r2: 闭环 ✓**

---

### R-004 (MEDIUM/consistency): IS_CELERY_BROKER_URL 独立变量 — 闭环确认

读 main.py L54-56：

```python
broker_url = os.environ.get("IS_CELERY_BROKER_URL") or os.environ.get(
    "IS_REDIS_URL", "redis://localhost:6379/0"
)
```

优先级链正确：`IS_CELERY_BROKER_URL`（非空非 None）→ `IS_REDIS_URL`（非空非 None）→ `"redis://localhost:6379/0"` 硬编码兜底。

空串行为核查：`IS_CELERY_BROKER_URL=""` 时 `or` 语义跳过空串，回落到 `IS_REDIS_URL`。空串等价于"未设置"，在环境变量惯例下属于合理行为（ops 手动清空变量即可回落）；架构文档未定义空串与缺失的语义差异，视为设计决策，不产生新问题。

**R-004: 闭环 ✓**

---

### R-005 (LOW/test-quality): 冗余 `create=True` — 闭环确认

实跑 `grep -n "create=True" tests/unit/api/test_lifespan.py`：无输出。

diff 确认 7 处 `create=True` 全部删除（TestLifespanDatabaseManagerDI 4 处 + TestInitRedis 2 处 + TestInitCelery 1 处）。1786 全量回归 PASS，证实 `create=True` 为真冗余（被 patch 对象均已在 main.py 的实际 import 中存在）。

**R-005: 闭环 ✓**

---

### R-006 (LOW/convention): `_patch_main_database_manager` 返回类型注解 — 闭环确认

读 conftest.py L19 + L64：

```python
from collections.abc import Iterator          # 新增 import
...
def _patch_main_database_manager() -> Iterator[MagicMock]:
```

- `AsyncIterator[None]` → `Iterator[MagicMock]`：修正为同步生成器 fixture 的正确返回类型（fixture body 以 `yield _p` 结束，`_p` 类型为 `MagicMock`）
- `# type: ignore[misc]` 已删除（`grep -n "type: ignore" conftest.py` 无输出）
- mypy --strict src/ 0 errors（tests/ 不在 mypy strict scope，但 fixture 类型本身合理）

同类模式检查：conftest.py 内另一个 autouse fixture `_inject_mock_db_into_app_fixtures` 返回 `None`（非 generator），无类型注解问题，不适用本次修复范围。test_lifespan.py / test_deps_integration.py 中的同类 patch 均为局部 `with patch(...)` 块，非 fixture 定义，不存在相同问题。

**R-006: 闭环 ✓**

---

## 副审：r3 diff 新问题检查

### 检查范围
仅审查 git diff ff5c382..c59cbdc 的实际改动行（+/-），按 COMMON-RULES §统一问题分类体系 逐维度扫描。

### main.py (+4/-2)
- **convention**: `os.environ.get("IS_CELERY_BROKER_URL") or os.environ.get(...)` 换行符合 ruff E501（max 88 字符），格式经 ruff format 验证无副作用（Layer 1 PASS）。
- **consistency**: `init_redis()` 中 `IS_REDIS_URL` 保持原有单变量查找，与 `init_celery()` 中 `IS_REDIS_URL` 作为兜底的语义一致；两个函数均使用相同的默认值 `"redis://localhost:6379/0"`，未引入新的不一致。
- **security / error-handling**: 改动仅为新增一条 `or` 链，未引入注入向量或异常处理遗漏。
- 结论：**无新问题**

### conftest.py (+3/-1)
- **convention**: `from collections.abc import Iterator` 新增 import 位置正确（stdlib，排在 contextlib 之前，符合 isort 规范；ruff Layer 1 PASS）。
- **structure**: `_patch_main_database_manager` 的行为无变化，仅类型注解修正。
- 结论：**无新问题**

### test_app_entry.py (+5/-1)
- **test-quality**: docstring 内容精确（首行 AC 编号 + 核心断言描述，续行补充实现说明），不影响测试逻辑。
- **convention**: 所有改动行 ≤88 字符（ruff E501 已验证）。
- 结论：**无新问题**

### test_lifespan.py (+16/-16)
- **test-quality**: 删除 7 处 `create=True`，测试仍以相同断言通过，语义等价，质量不退化。
- **convention**: 无格式违规（Layer 1 PASS）。
- 结论：**无新问题**

---

## 问题列表

本次 r3 diff 无新问题产生，r2 全部 4 项 notes 已闭环。

---

## 备注：retro 候选（供 sprint-7 retrospective 使用）

T-072 经历 r1 → r2 → r3 三轮 review，累计 self-caused 问题：

| 轮次 | 编号 | 等级 | category |
|------|------|------|----------|
| r1 | R-001 | HIGH | error-handling |
| r1 | R-002 | HIGH | error-handling |
| r1 | R-003 | MEDIUM | test-quality |
| r2 | R-001-r2 | LOW | convention（r2 修订中引入） |
| r2 | R-004 | MEDIUM | consistency（carryover 被选择修复） |
| r2 | R-005 | LOW | test-quality（carryover 被选择修复） |
| r2 | R-006 | LOW | convention（carryover 被选择修复） |

共 7 个 self-caused 问题，已超出 `RETRO_TRIGGER_SELF_CAUSED=5` 阈值。

主线模式观察：
1. **implementer self-report scope drift**：r1 实现了功能但引入了两个 HIGH 级错误处理问题（连接池泄漏路径 + None fallback 分支），提示"让测试 PASS"优先于"让行为正确"。
2. **修改文件未运行对应 lint**：r2 修订 test_app_entry.py 时引入新的 E501（修改 docstring 时未执行 `ruff check tests/`），符合 T-060 r1 已记录的同类模式（"声称 src/ ruff clean 但 tests/ 含违规"）。
3. **测试冗余未清理**：`create=True` 冗余（R-005）和类型注解错误（R-006）属于编写测试时的粗糙细节，非功能性 bug 但降低代码可维护性。

以上观察已完整保留在报告中，供 sprint-7 末尾 retrospective 提炼为 EXP 学习条目（reflector 介入）。

---

## 三态判定

| 严重等级 | 问题编号 |
|---------|---------|
| CRITICAL | 无 |
| HIGH | 无 |
| MEDIUM | 无 |
| LOW | 无 |

r2 全部 4 项 notes（R-001-r2 / R-004 / R-005 / R-006）已完整闭环，r3 diff 无新问题引入。

**verdict: approved**
