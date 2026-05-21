---
id: "code-review-T-093-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-093"]
---

# CODE-REVIEW T-093 r2 — quiet_hours 时区修复 + 关键词解析器统一 + ReDoS 防护

Layer 1 delegated to hook (PostToolUse Edit → lint_format.py)

修订提交: `b567e46` — fix(distributor): T-093 R-001/R-002/R-003 — tz fallback + log mask + test tightening

---

## §0 r1 复检

### R-002 (HIGH error-handling) — RESOLVED

`frequency.py` 第 104-110 行：`ZoneInfo(tz_name)` 已被包裹在 `try/except (ZoneInfoNotFoundError, KeyError)` 块中，fallback 为 `ZoneInfo("UTC")`，同时通过 `_logger.warning("Invalid timezone %r on subscription, falling back to UTC", tz_name)` 发出 WARNING 日志。`ZoneInfoNotFoundError` 已从 `zoneinfo` 标准库正确导入，`ZoneInfo("UTC")` fallback 本身安全（Python 3.9+ 标准库保证）。WARNING 仅在 except 分支触发，正常路径无额外日志输出，不存在每次推送都打 WARNING 的 spam 风险。**状态: 已解决。**

### R-001 (MEDIUM security) — RESOLVED

`matcher.py` 第 109-117 行：超时日志已改为：
```
"regex.search timeout for pattern (sha256=%s, len=%d) — treating as no-match",
pattern_hash,  # sha256[:12]
len(value),
```
原始 pattern 不再出现在日志中，仅记录 sha256 前 12 字符 + 长度，满足 AC-5 "hash/截断"要求。`hashlib` 的 `import hashlib` 用法与项目既有代码（`collector/base.py`、`distributor/webhooks.py` 等）保持一致。**状态: 已解决。**

### R-003 (LOW test-quality) — RESOLVED

`test_redos_protection.py` 第 93 行：断言已由 `assert (result is False or result is None)` 收紧为 `assert result is False`，与 AC-5 "该关键词返回 False（不匹配）"语义一致，`None` 路径歧义消除。**状态: 已解决。**

---

## §1 新增测试覆盖审查

### test_invalid_timezone_falls_back_to_utc_without_raising（test_quiet_hours_tz.py）

- 使用 `timezone="Asia/Shanghia"`（故意拼写错误的无效时区名）作为 `StubSubscription` 参数，确实触发 `ZoneInfoNotFoundError` fallback 路径；非平凡断言。
- `utc_0300` (03:00 UTC) 在 UTC 时区下仍处于 `09:00-17:00` quiet hours 范围之外，所以 `result is False` 是实际运算结果而非 trivially true；若 fallback 未执行（抛出异常）测试会因 exception 而 FAIL，若 fallback 错误地返回 True，断言 `assert result is False` 会捕获。
- `caplog.at_level(logging.WARNING)` 在 pytest 中默认捕获 root logger 及所有子 logger，`intellisource.distributor.frequency` 日志会被采集到 `caplog.records`；断言 `any("Invalid timezone" in r.message for r in caplog.records)` 有效。
- 覆盖验证通过。

### test_timeout_log_does_not_leak_pattern（test_redos_protection.py）

- 使用 `patch.object(regex_lib, "search", side_effect=TimeoutError("mock timeout"))` 强制触发 `except TimeoutError` 分支；mock 注入方式正确，不依赖真实 ReDoS 触发。
- 断言 `pattern not in caplog.text`：直接检查原始 pattern 字符串 `(secret_business_keyword_xyz+)+$` 是否出现在日志文本，有效。
- 断言 `"sha256=" in caplog.text`：验证 hash marker 存在于日志，确保实现未静默吞掉超时。
- `with patch.object` 作用域包裹了 `SubscriptionMatcher()` 的实例化和 `_evaluate_keywords` 调用；注意 `from intellisource.distributor.matcher import SubscriptionMatcher` 在 with 块内执行，`patch.object` patch 的是 `regex_lib` 模块对象本身（已在顶层 `import regex as regex_lib` 完成），与 matcher.py 内 `import regex as regex_lib` 的同一对象引用绑定，patch 生效。
- 覆盖验证通过。

---

## §2 净新回归扫描（delta-only）

ruff check + mypy --strict 对 `frequency.py`、`matcher.py` 两个变更文件均无 finding，208 个 distributor 单测全部通过。

### convention — PASS

`import hashlib`（标准库顶层导入）、`import logging` + `_logger = logging.getLogger(__name__)`（frequency.py 新增）均符合项目约定；顶层 import 位置（`from __future__ import annotations` 之后）符合 PEP 8 分区。

### error-handling — PASS

fallback 链 `ZoneInfo(tz_name) → ZoneInfo("UTC")` 完整；`ZoneInfo("UTC")` 本身不会抛出，fallback 是安全终点。

### security — PASS

WARNING 日志仅含 hash + 长度，不含原始 pattern，满足 AC-5 要求，无新增泄漏路径。

### test-quality — PASS

两个新测试（见 §1）均为非平凡断言，覆盖了实现中新增的两条分支路径。

### completeness / consistency / structure / complexity — PASS

变更范围严格限于 r1 所列问题的修复，未引入新逻辑分支或模块依赖变化，r1 中已确认通过的所有维度无回归。

---

## 审查结论

**verdict: approved**

| 等级 | 数量 | 编号 |
|------|------|------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 0 | — |
| LOW | 0 | — |

r1 所有 3 个问题（1 HIGH + 1 MEDIUM + 1 LOW）均已正确修复，新增测试覆盖非平凡，无净新 CRITICAL/HIGH/MEDIUM 引入。T-093 代码审查通过。
