---
id: "code-review-T-093-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-093"]
---

# CODE-REVIEW T-093 — quiet_hours 时区修复 + 关键词解析器统一 + ReDoS 防护

Layer 1 delegated to hook (PostToolUse Edit → lint_format.py)

## §1 security (强制)

ReDoS 防护核心路径逐项核查：

1. `import regex as regex_lib` — matcher.py:9 和 scorer.py:9 均使用第三方 `regex` 库，不是标准库 `re`。通过。
2. `regex.search(pattern, text, timeout=1.0)` — matcher.py:105 和 scorer.py:96 均使用 `timeout=1.0` kwarg。通过。
3. 捕获异常类型 — matcher.py:107 捕获 `TimeoutError`（Python 内置），与 AC-5 要求（built-in `TimeoutError`，而非 `regex.TimeoutError`）一致。scorer.py:98 同样捕获 `TimeoutError`。通过。
4. 失败返回 — matcher.py 捕获后日志 + 继续循环（`has_match` 保持不变），timeout 的 keyword 视为无匹配，最终返回 False（无其他 keyword 命中时）。通过。
5. 日志是否泄露完整 user-supplied pattern — matcher.py:108-110 使用 `_logger.warning("regex.search timeout for pattern %r — ...", value)` 直接以 `%r` 记录完整 pattern。

### [R-001] MEDIUM: 日志完整记录 user-supplied regex pattern，可能泄露内部数据

- **category**: security
- **root_cause**: self-caused
- **描述**: matcher.py 第 110 行 `_logger.warning("... for pattern %r — ...", value)` 将用户提交的完整 regex pattern 写入日志。若 pattern 本身包含敏感信息（如私人信息的模糊规则、业务关键词），日志收集系统（如 ELK）将持久化这些数据。AC-5 要求"日志不泄漏完整 user-supplied pattern（hash/截断）"。
- **建议**: 改为截断或哈希处理，例如 `value[:50] + ("..." if len(value) > 50 else "")` 或 `hashlib.sha256(value.encode()).hexdigest()[:8]`。

## §2 error-handling

### [R-002] HIGH: `is_quiet_hours` 调用 `ZoneInfo(tz_name)` 无 fallback，无效时区名会抛 `ZoneInfoNotFoundError` 中断推送流程

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: frequency.py:101 `local_now = now_utc.astimezone(ZoneInfo(tz_name))` 不带任何 try/except。若订阅记录的 `timezone` 字段包含无效值（如拼写错误的 `"Asia/Shanghia"`、用户修改入库的错误值），`ZoneInfoNotFoundError` 会从 `is_quiet_hours` 向上传播，进而中断 `should_send_now` 整条推送判断流程。AC-2 描述为"使用 zoneinfo.ZoneInfo 转换"，但未要求无 fallback，而任务卡 risk 区域也未豁免此边界。
- **建议**: 在 `is_quiet_hours` 中包装 `try: ZoneInfo(tz_name) except (ZoneInfoNotFoundError, KeyError): tz_name = "UTC"`，或在 `getattr(subscription, "timezone", "UTC")` 后增加校验步骤，并记录 WARNING 日志。

Alembic 迁移 SQLite 后端降级：迁移文件使用 `ARRAY(sa.String)` 仅从 `sqlalchemy.dialects.postgresql` 导入，在 SQLite 测试环境中 ORM `mapped_column(ARRAY(String))` 会依赖 SQLAlchemy 的 dialect fallback（非 PG 时降为 JSON）。test_subscription_timezone.py:87 已将断言放宽为 `type_name in ("ARRAY", "JSON")`，覆盖了 SQLite 路径。此处无额外 error-handling 问题。

## §3 consistency

matcher.py 和 scorer.py 均导入并使用 `parse_keyword_token`（matcher.py:11、scorer.py:11），无独立的 lower/split 实现。两者 `regex.search` 调用签名一致（`timeout=1.0`）。

`discipline_tags` 权重差异化：scorer.py 定义 `_DISCIPLINE_TAG_WEIGHT = 2.0`、`_GENERIC_TAG_WEIGHT = 1.0`，`_tag_match_score` 分别用于 `discipline_tags` 和 `tags` 计算。matcher.py 中 `_matches` 把 `discipline_tags` 作为独立字段，与 `tags` 分开匹配。两者一致。

一致性无 CRITICAL/HIGH 问题。

## §4 convention

文件命名 snake_case，函数命名 `parse_keyword_token`、`_in_quiet_range`、`_evaluate_keywords` 均符合 PEP 8。常量 `_DISCIPLINE_TAG_WEIGHT`、`_GENERIC_TAG_WEIGHT` 加下划线前缀表私有，符合约定。`import regex as regex_lib` 别名表意清晰（区分标准库 `re`）。

convention 无问题。

## §5 structure

distributor 模块内部依赖链：`matcher.py` → `keyword_parser.py`、`scorer.py`；`scorer.py` → `keyword_parser.py`；`frequency.py` 无跨模块依赖（仅标准库 `zoneinfo`）。

distributor → storage 单向依赖验证：对 `src/intellisource/distributor/` 全目录 grep `from intellisource.storage`，结果为空。distributor 模块未引入 storage 层依赖，依赖方向正确。

structure 无问题。

## §6 completeness

逐 AC 核查：

- AC-1 (`Subscription.timezone` 默认 "Asia/Shanghai"): models.py:426-428 `timezone: Mapped[str] = mapped_column(VARCHAR(100), nullable=False, default="Asia/Shanghai")`；Alembic:24-29 `server_default="Asia/Shanghai"`。通过。
- AC-2 (`_in_quiet_range` 使用 zoneinfo 转换): frequency.py:100-101 `tz_name = getattr(subscription, "timezone", "UTC")` + `ZoneInfo(tz_name)` 转换；跨午夜逻辑 `_in_quiet_range` 保留（line 86-88）。通过（error-handling 问题已在 §2 列出）。
- AC-3 (`parse_keyword_token` 三类 token): keyword_parser.py 返回 `+`、`!`、`regex`、`plain` 四类（`plain` 是 regex 之外的默认）。`matcher.py:11`、`scorer.py:11` 共用。通过。
- AC-4 (scorer 权重差异化): scorer.py `_keyword_match_score` 中 `+` → 2.0，`!` → 0，`regex/plain` → 1.0。通过。
- AC-5 (ReDoS 防护): 见 §1 分析，主干通过，`%r` 日志问题已列 MEDIUM。
- AC-6 (`discipline_tags` 字段 + 迁移): models.py Source:108-110 与 Subscription:429-431 均有 `ARRAY(String)` 字段；Alembic 迁移文件包含三个 `add_column` 操作（timezone + Subscription.discipline_tags + Source.discipline_tags）。通过。

completeness 无 CRITICAL/HIGH 缺失。

## §7 test-quality

**test_subscription_timezone.py ARRAY 断言放宽评估**

`test_discipline_tags_is_array_type` 改为 `assert type_name in ("ARRAY", "JSON")` 后，测试在 SQLite 环境中不会因 dialect 差异失败，同时仍验证了字段存在且类型为集合型（排除 VARCHAR、Integer 等错误类型）。断言并未过宽——它仍然阻止了字段类型被错误定义为标量的情况。可接受。

**test_redos_protection.py 覆盖验证**

① mock TimeoutError 路径：`test_regex_timeout_error_captured_returns_false`（line 114-135）使用 `patch.object` 注入 `side_effect=TimeoutError("timeout")` 并断言 `result is False`。覆盖。

② 断言 `regex.search` 调用 + `timeout=` kwarg：`test_regex_library_is_used_not_re`（line 137-157）用 spy 断言 `regex.search` 被调用；`test_regex_search_called_with_timeout_kwarg`（line 158-181）独立断言 `kwargs["timeout"] == approx(1.0)`。覆盖。

③ `(a+)+$` 回归守卫：`test_redos_pattern_does_not_block_beyond_2s`（line 76-95）使用 `"/(a+)+$/"` + `_TRIGGER_STRING` 断言 `elapsed < 2.0`；`test_all_redos_patterns_complete_quickly` 用 parametrize 覆盖 4 个经典 pattern。覆盖。

### [R-003] LOW: `test_redos_pattern_does_not_block_beyond_2s` 断言逻辑有轻微歧义

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: line 93-95 断言 `assert (result is False or result is None)`——其中 `result is None` 表示"excluded constraint violated"，而这个 pattern `(a+)+$` 属于 `operator == "regex"`，timeout 后不应触发 `None` 返回路径（None 只由 `+`/`!` 分支返回）。允许 `None` 实际上掩盖了一个潜在回归：若实现错误地把 regex timeout 路由到了 `None`（表示 required/excluded constraint 失败），测试不会捕获。
- **建议**: 断言改为 `assert result is False`，与 `test_regex_timeout_error_captured_returns_false` 保持一致，且符合 AC-5 "该关键词返回 False（不匹配）"的要求。

**test_quiet_hours_tz.py**：覆盖 UTC→北京时间转换、跨午夜边界、DST 边界（America/New_York）、无 quiet_hours 情况、同日区间。测试逻辑与 `is_quiet_hours` 实现对应，断言均有效，无空断言。通过。

**test_keyword_parser.py**：覆盖 AC-3 四类 token，含边界情况（空串、单字符 `+`/`!`、无结尾斜杠、`//`）。AC-4 scorer 权重覆盖 `+`（加倍）、`!`（零贡献）、`/regex/`（等价 plain）、空 keyword 列表。断言有效。通过。

## §8 complexity / duplication / coupling (TDD_REFACTOR_TRIGGER 触发判定)

**complexity**: `_evaluate_keywords`（matcher.py:75-116）约 25 LOC，含 1 层 for + 4 条 if/elif，圈复杂度约 6。`is_quiet_hours`（frequency.py:90-111）约 22 LOC，逻辑清晰。均在可接受范围内。

**duplication**: matcher.py 与 scorer.py 均有 `regex_lib.search(value, text, timeout=1.0)` + `except TimeoutError` 的 try/except 块（matcher:104-111，scorer:95-99），属于 Type-2 近似克隆。两处逻辑几乎相同但处于不同上下文（一处决定 match/no-match，另一处决定 score），逻辑分量小（4-5 行），提取为公共 helper 收益有限。

**coupling**: distributor 内部 matcher → scorer → keyword_parser 三层单向依赖，无循环。模块扇出可控。

三个 TDD_REFACTOR_TRIGGER 分类均未超过阈值：complexity 低，duplication 克隆块轻量，coupling 无循环。

## REFACTOR 触发建议

推荐: skip

分析：TDD_REFACTOR_TRIGGER 三项（complexity / duplication / coupling）均未达触发条件。`try/except TimeoutError` 的轻量克隆不值得为其单独提取公共 helper（会增加跨模块依赖）。建议在下次接触 distributor 模块时可顺手合并，但不构成本次 REFACTOR 必要性。

---

## 审查结论

**verdict: needs_revision**

| 等级 | 数量 | 编号 |
|------|------|------|
| CRITICAL | 0 | — |
| HIGH | 1 | R-002 |
| MEDIUM | 1 | R-001 |
| LOW | 1 | R-003 |

存在 1 个 HIGH 问题（R-002：`is_quiet_hours` 中 `ZoneInfo(tz_name)` 无 fallback，无效时区名会向上抛出 `ZoneInfoNotFoundError` 中断推送流程）。需修复后重新审查。

用户决策（2026-05-21）：走 Revision Protocol 修 R-002 + R-001（R-003 LOW 顺手修）。REFACTOR 推荐 skip 保持。
