---
id: "code-review-T-090-r1"
doc_type: code-review
author: reviewer
status: approved
deps: [T-090]
---

# CODE-REVIEW T-090 r1

Layer 1 delegated to hook (lint hook configured; ruff + mypy --strict clean per implementer pre-submission).

## §1 安全审查（security_sensitive=true — 必审）

以下五个安全维度逐项判定：

| 维度 | 结论 | 说明 |
|------|------|------|
| PII 脱敏 — error_message 持久化前调用 mask helper | **FAIL** | `pii.py` 存在但 `mask_email` / `mask_phone` 在 `base.py` `record_push()` 中 **未被调用**；error_message 原文直写入 DB |
| recipient 哈希 — extra_recipient SHA-256 后再存储 | PASS | `record_push()` 正确计算 `hashlib.sha256(extra_recipient.encode()).hexdigest()` 并以 `recipient_hash` 传入 `repo.create()` |
| 日志无原始 PII | PASS | `base.py` 与三渠道均无 logger；频道层仅透传 error 字符串，未有结构化 PII 日志 |
| UniqueViolation 不泄漏 PII | PASS（有条件） | `PushRepository._create_entity()` 通过 `session.flush()` 触发，UniqueViolation 由 SQLAlchemy 捕获并向上抛，不含 PII；但 `base.py` 的 `_record_push_if_repo` **未捕获该异常**（见 R-002） |
| PII helper 幂等性 | PASS | `mask_email(mask_email(x)) == mask_email(x)` 与 `mask_phone` 均验证通过（idempotent 分支存在）；`mask_email` 检测 `"*" in local`，`mask_phone` 检测 `"***" in phone` |

---

## 问题清单

### [R-001] HIGH: `record_push()` 写入 `error_message` 前未调用 PII 脱敏 helper

- **category**: security
- **root_cause**: self-caused
- **描述**: AC-8 明确要求"record_push() 写入 error_message 前调用 PII 脱敏 helper"。`src/intellisource/distributor/pii.py` 已实现 `mask_email` / `mask_phone`，但 `base.py` 的 `record_push()` 和 `_send_with_dedup_lifecycle()` 均未 import 或调用这两个函数。`error_message`（来自 exception str 或 API errmsg）原文经 `repo.create(error_message=last_error)` 落库。若 error_message 中包含邮箱地址（如 EmailDistributor 的 `SMTPException` traceback）或手机号，将以明文存入 `push_records.error_message` TEXT 字段，违反 AC-8 安全合规要求。
- **建议**: 在 `base.py` 中 import `mask_email, mask_phone`，在 `record_push()` 对 `error_message` 做统一脱敏（可对 error_message 串执行正则扫描后替换，或在 `_send_with_dedup_lifecycle` 的失败路径中调用 mask helper 处理 `last_error`）。同时补充一个测试：传入包含邮箱/手机号的 error_message，断言落库值不含原始 PII。

---

### [R-002] MEDIUM: `_record_push_if_repo` 未捕获 `UniqueViolation`，幂等性仅靠 `check_dedup` 前置守卫

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: 任务卡 mitigation 明确说明"record_push() 捕获 UniqueViolationError 并静默忽略"。当前实现中 `_check_dedup_if_repo()` + `_record_push_if_repo()` 之间没有 DB-level 幂等保证：高并发下两个请求同时通过 `check_dedup`（均读到 exists=False），随后均调用 `repo.create()`，第二个将触发 `sqlalchemy.exc.IntegrityError`（对应 `UniqueConstraint uq_push_records_dedup`）并向上传播，调用方（渠道 `distribute()` 方法）未捕获，导致 500 / 任务失败而非幂等静默。
- **建议**: 在 `_record_push_if_repo()` 中捕获 `sqlalchemy.exc.IntegrityError`（或 psycopg `UniqueViolation`），静默处理（仅 debug 日志）。

---

### [R-003] MEDIUM: `PushRecord.status` 写入值 `"success"` 与 arch E-010 CHECK 约束 `('pending', 'sent', 'delivered', 'failed')` 不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `arch-intellisource-v1-data.md` E-010 `PushRecord.status` 的 CHECK 枚举为 `('pending', 'sent', 'delivered', 'failed')`，其中无 `'success'`。但 `base.py _send_with_dedup_lifecycle` 在成功路径调用 `_record_push_if_repo(status="success")`，在 PostgreSQL 生产环境中若 CHECK 约束被建表时实施，将触发 constraint violation。当前 SQLAlchemy 模型 `PushRecord` 的 `status` 字段仅有 `default="pending"` 而无 `CheckConstraint`，故单元测试未发现此问题，但 arch 约定和 DB schema 文档与实现不一致。
- **建议**: 将 `_send_with_dedup_lifecycle` 成功路径的 `status` 改为 `"sent"`（与 arch E-010 一致）；或在 arch 文档中将 `'success'` 加入枚举并同步 DB migration。同步更新测试中对应的 `assert create_kwargs.get("status") == "success"` 断言。

---

### [R-004] MEDIUM: `BaseDistributor._push_repo` 仅有类型注解无默认值，未实现 `__init__` 的子类会在 `_check_dedup_if_repo` 时抛出 `AttributeError`

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `BaseDistributor` 声明了 `_push_repo: "PushRepository | None"` 作为类级注解，但未赋初始值（未在 `__init__` 中设为 `None`）。三个现有渠道类均在 `__init__` 中显式赋值，但若未来新渠道子类遗忘赋值，调用 `_check_dedup_if_repo()` 时 `if self._push_repo is None` 会先触发 `AttributeError` 而非返回 `False`。经验证：`_C()._push_repo` 直接抛出 `AttributeError: '_C' object has no attribute '_push_repo'`。
- **建议**: 在 `BaseDistributor` 中添加 `_push_repo: PushRepository | None = None` 类属性赋值（或添加 `__init__` 设置默认值），消除 AttributeError 风险。

---

### [R-005] LOW: `WeWorkDistributor.attempt_fn` 无 try/except，HTTP 异常不经 `record_push("failed")` 直接上抛

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `WeChatDistributor` 和 `EmailDistributor` 的 `attempt_fn` 均有 try/except 包裹 HTTP 调用，捕获 Exception 后返回 `(False, str(exc), {})`，从而确保失败路径走 `record_push("failed")`。但 `WeWorkDistributor.attempt_fn` 无 try/except：`send_text_message / send_markdown_message / send_news_card` 内部调用 `http_client.post()` 若抛出 `aiohttp.ClientError` 等网络异常，会直接传播出 `_send_with_dedup_lifecycle`，导致三渠道行为不对称：WeWork 网络错误无 push record 落库，其他两渠道有。单元测试 `test_retry_on_http_error` 使用 errcode=-1 的响应（非异常），未覆盖此场景。
- **建议**: 在 `WeWorkDistributor.attempt_fn` 中添加 try/except 捕获 HTTP 异常，对称处理返回 `(False, str(exc), {})`；或在 `_send_with_dedup_lifecycle` 中统一 wrapping attempt_fn 调用。

---

### [R-006] LOW: `success` 路径 `retry_count` 恒为 0，无法区分首次成功和重试后成功

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `_send_with_dedup_lifecycle` 在任意 attempt 成功时均返回 `retry_count=0`（`return False, True, 0, None, raw`）。若在第 2 次或第 3 次 attempt 才成功，实际重试了 1-2 次，但 `PushRecord.retry_count` 仍写 0，丢失了重试诊断信息。AC-5 仅要求失败时 retry_count >= 1，故功能正确；但运维可观测性有损失。
- **建议**: 将成功路径改为 `return False, True, attempt, None, raw`（即用当前 attempt 索引作为 retry_count），使 push record 更准确地反映实际重试次数。

---

## §REFACTOR Delta 评估

REFACTOR commit `dca8be9` 从三渠道提取 `_send_with_dedup_lifecycle()` 模板到 `BaseDistributor`，同时引入 `_check_dedup_if_repo` / `_record_push_if_repo` 两个守卫方法。重构目标达成：

- 重复消除：三渠道各自的 dedup check + retry loop + record_push 约 10-15 行近克隆代码替换为一次 `await self._send_with_dedup_lifecycle(...)` 调用。
- 无泄漏抽象：渠道层仅负责 payload 构建和 API 调用，生命周期管理完全下沉到 base。
- mypy --strict 干净，251 个测试全通过。

遗留问题：R-001（PII masking 缺失）在 REFACTOR 中未修复，且 REFACTOR commit message 中提到 "masked error_message" 但代码中并未体现，存在误导性表述。

---

## AC 覆盖摘要

| AC | 覆盖情况 | 备注 |
|----|---------|------|
| AC-1 | 覆盖 | `check_dedup` / `record_push` 方法存在，委托测试通过 |
| AC-2 | 覆盖 | WeChatDistributor dedup + record 测试通过 |
| AC-3 | 覆盖 | WeWorkDistributor + grep 无 `push:dedup:` / `wework:dedup:` 确认 |
| AC-4 | 覆盖 | EmailDistributor + grep 无 `_sent_keys` 确认 |
| AC-5 | 覆盖 | 失败路径 retry_count >= 1、error_message 非空断言通过 |
| AC-6 | 覆盖 | 第二次调用 check_dedup 返回 True 测试通过 |
| AC-7 | 覆盖 | SHA-256 hash 测试通过；raw value 不在 create kwargs 中 |
| AC-8 | **未完整覆盖** | mask_email / mask_phone 函数测试通过，但 `record_push()` 中未调用（R-001），无端到端持久化掩码测试 |

---

## 最终判定

存在 R-001（HIGH: security — PII error_message 未脱敏落库）及 R-002（MEDIUM）、R-003（MEDIUM）。

**verdict: needs_revision**
