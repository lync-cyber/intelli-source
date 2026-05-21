---
id: "code-review-T-090-r2"
doc_type: code-review
author: reviewer
status: approved
deps: [T-090]
---

# CODE-REVIEW T-090 r2

Layer 1 delegated to hook (lint hook configured; ruff + mypy --strict clean per implementer pre-submission commit message).

## §0 r1 复检

| 编号 | 严重等级 | 标题 | 结论 |
|------|---------|------|------|
| R-001 | HIGH | `record_push()` 写入 `error_message` 前未调用 PII 脱敏 helper | RESOLVED |
| R-002 | MEDIUM | `_record_push_if_repo` 未捕获 `UniqueViolation` | RESOLVED |
| R-003 | MEDIUM | `PushRecord.status` 使用 `"success"` 与 arch E-010 不一致 | RESOLVED |
| R-004 | MEDIUM | `_push_repo` 仅注解无默认值，未实现 `__init__` 的子类会 AttributeError | RESOLVED |
| R-005 | LOW | `WeWorkDistributor.attempt_fn` 无 try/except，三渠道行为不对称 | RESOLVED |
| R-006 | LOW | 成功路径 `retry_count` 恒为 0 | RESOLVED |

---

## §1 安全审查（security_sensitive=true — 必审）

以下五个安全维度逐项判定：

| 维度 | 结论 | 说明 |
|------|------|------|
| SS-1 PII 脱敏 — error_message 持久化前调用 mask helper | PASS | `_mask_error_message` 在 `record_push()` 第 80 行调用；`mask_email` / `mask_phone` 从 `intellisource.distributor.pii` 正确 import；三个非模拟路径的 `TestAC8PiiMasking` 测试验证端到端脱敏 |
| SS-2 recipient 哈希 — extra_recipient SHA-256 后再存储 | PASS | 无变更；`record_push()` 仍正确计算 `hashlib.sha256(extra_recipient.encode()).hexdigest()` |
| SS-3 日志无原始 PII | PASS | `base.py` 与三渠道代码均无 `logger` 调用；r2 delta 未引入任何日志语句 |
| SS-4 UniqueViolation 不泄漏 PII | PASS | `except IntegrityError: pass` 静默吞掉，无任何日志或 re-raise；except 子句仅捕获 `sqlalchemy.exc.IntegrityError`，不覆盖连接失败等其他 DB 错误（见下方 §2） |
| SS-5 PII helper 幂等性 | PASS | 无变更；`mask_email` / `mask_phone` 幂等分支已验证 |

---

## §2 r1 修复验证详情

### R-001 RESOLVED — PII masking 集成

- `base.py` 第 13 行：`from intellisource.distributor.pii import mask_email, mask_phone` — import 存在。
- `base.py` 第 44-50 行：`_mask_error_message()` helper 通过模块级 `_EMAIL_RE` / `_PHONE_RE` 正则定位 PII 子串后调用 `mask_email` / `mask_phone` 逐个替换，而非直接 `sub(lambda: masked_whole_string)`——设计正确，处理混合文本中的嵌入式 PII。
- `base.py` 第 80 行：`error_message=self._mask_error_message(error_message)` — 脱敏在 `repo.create()` 调用之前完成。
- `TestAC8PiiMasking` 三个测试均未 mock `mask_email` / `mask_phone`，调用真实函数并断言落库值不含原始 PII — 非空洞测试。

### R-002 RESOLVED — IntegrityError 静默吞掉

- `_record_push_if_repo` 第 111-124 行：`except IntegrityError: pass` 精确捕获 `sqlalchemy.exc.IntegrityError`，不吞掉 `OperationalError`（连接失败）/ `ProgrammingError` / `DataError` 等其他 DB 异常——符合最小捕获原则。
- `TestIntegrityErrorRace` 两个测试（直接调用 + lifecycle 完整路径）均通过。

### R-003 RESOLVED — status enum 对齐 arch E-010

- `base.py` 第 21 行：`_VALID_STATUSES = frozenset({"pending", "sent", "delivered", "failed"})` — 与 arch E-010 一致。
- `base.py` 第 65-69 行：`if status not in _VALID_STATUSES: raise ValueError(...)` — 无效值在 `record_push()` 入口拦截。
- `base.py` 第 157 行：成功路径 `status="sent"`；第 166 行：失败路径 `status="failed"` — `"success"` 已完全从 DB 持久化路径清除。
- 注：`wework.py` 第 94 行和 `wechat.py` 第 195 行保留 `"success"` 字符串，但这是渠道 `distribute()` 方法的**返回值 dict**（调用方 API 响应），与 `PushRecord.status` 数据库字段无关，不属于 R-003 修复范围。
- `TestStatusEnum` 五个测试（sent 路径 / failed 路径 / invalid 直接拒绝 / 五值参数化无效 / 四值参数化有效）均通过。

### R-004 RESOLVED — `_push_repo` 类属性默认值

- `base.py` 第 27 行：`_push_repo: "PushRepository | None" = None` — 类属性赋初始值，消除未实现 `__init__` 的子类 AttributeError 风险。

### R-005 RESOLVED — WeWork attempt_fn 异常对称

- `wework.py` 第 64-74 行：`exc_ref: list[Exception] = []`；`try/except Exception as exc: exc_ref.append(exc); res = {"errcode": -1, "errmsg": "network_error"}` — 网络异常被捕获并转换为失败响应，随后走正常失败路径写 `record_push("failed")`，与 WeChatDistributor / EmailDistributor 对称。
- `TestWeWorkExceptionSymmetry` 两个测试（OSError / RuntimeError）均通过。

### R-006 RESOLVED — retry_count 反映实际 attempt

- `base.py` 第 157-158 行：成功路径 `retry_count=attempt`，`return False, True, attempt, None, raw`。
- `TestRetryCountTracking` 两个测试（首次成功 retry_count=0 / 第三次成功 retry_count=2）均通过。

---

## §3 净新问题扫描

r2 delta 涉及 `base.py` (+55-28)、`wework.py` (+21-7)、`test_push_dedup.py` (+349)、`test_wework.py` (+76)，无净新问题，扫描结论如下：

- **security**: SS-1..SS-5 全部维持 PASS；无新日志语句；IntegrityError except 子句精确不扩散。
- **error-handling**: `except IntegrityError` 仅捕获重复键冲突，`OperationalError` / `ProgrammingError` 等其他 DB 错误不被吞掉，连接失败会正常向上传播——符合约定。
- **convention**: `_mask_error_message` 私有前缀正确，命名风格与 `_check_dedup_if_repo` / `_record_push_if_repo` 一致；模块级常量 `_EMAIL_RE` / `_PHONE_RE` / `_VALID_STATUSES` 命名符合 PEP 8。
- **test-quality**: 抽检三个测试体——`test_error_message_email_is_masked_before_persist`（直接从 `create_kwargs` 取 `error_message` 断言原始地址不存在，调用真实 mask 函数）、`test_third_attempt_success_retry_count_two`（通过 `call_count` 计数器验证 attempt_fn 被调用三次，断言 `retry_count==2`）、`test_lifecycle_integrity_error_swallowed`（验证 lifecycle 在 IntegrityError 后仍返回 `succeeded=True`）——三个测试均非空洞，断言有效。

全量回归：272 distributor 测试 / 0 失败（`uv run pytest tests/unit/distributor/ -q` 验证）。

---

## 最终判定

所有 r1 问题（R-001 HIGH + R-002/R-003/R-004 MEDIUM + R-005/R-006 LOW）均已解决，无净新 CRITICAL / HIGH / MEDIUM / LOW 问题。

**verdict: approved**
