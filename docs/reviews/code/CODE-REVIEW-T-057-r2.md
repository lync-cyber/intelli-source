---
id: "code-review-T-057-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-057", "code-review-T-057-r1", "dev-plan-intellisource-v1-s7", "arch-intellisource-v1"]
---
# CODE-REVIEW: T-057 LLM 调用指数退避重试 (r2 — closure)
<!-- date: 2026-05-03 | reviewer: orchestrator-as-reviewer | task: T-057 | sprint: sprint-7 -->
<!-- 闭环审查：r1 verdict approved_with_notes，用户选择修复全部 4 项；r2 验证修复完成 -->

## 审查范围

- 修订基线：CODE-REVIEW-T-057-r1.md（R-001 MEDIUM + R-002/R-003/R-004 LOW）
- 增量改动文件：
  - `src/intellisource/llm/gateway.py`（_log_retry 增 call_type 参数；_call_with_retry 增 task_type 透传；_try_fallback docstring 补契约）
  - `tests/unit/llm/test_gateway_retry.py`（4 处 pytest.raises 收紧 + 2 个新测试）

## 验证结果

- ✅ `uv run pytest -q tests/unit/llm/`：**229 PASSED**（基线 227 + 新增 2 测试，全部通过）
- ✅ `uv run mypy --strict src/intellisource/llm/gateway.py src/intellisource/llm/cost_tracker.py src/intellisource/storage/models.py`：零错误

## R-001~R-004 闭环核对

| ID | 严重度 | 修复内容 | 证据 | 状态 |
|---|---|---|---|---|
| R-001 | MEDIUM | 4 处 `pytest.raises(Exception)` 收紧为具体异常类 | `test_gateway_retry.py:152` `le.Timeout`, `:192` `le.BadRequestError`, `:205` `le.AuthenticationError`, `:247` `le.Timeout` | ✅ closed |
| R-002 | LOW | `_log_retry` 增 `call_type: str` 参数；`_call_with_retry` 增 `task_type` 并透传 `task_type or "unknown"`；`complete()` 调用点同步 | `gateway.py:330` `_call_with_retry(..., task_type)`, `:352` `call_type=task_type or "unknown"`, `:382` `_log_retry(self, model, retry_attempt, call_type)` | ✅ closed |
| R-003 | LOW | `_try_fallback` docstring 显式声明三种 fallback 异常优先级 + 新增 `test_fallback_function_raises_propagates_fallback_error` | `gateway.py:367` docstring contract; `test_gateway_retry.py:252` 新测试 | ✅ closed |
| R-004 | LOW | 新增 `test_acompletion_timeout_preserved_across_retries`，断言 retry 路径下两次调用 timeout 均为 45 | `test_gateway_retry.py:318` 新测试 | ✅ closed |

## 回归检查

- ✅ 既有 14 测试全部保持 PASSED（未因 mock 改动破坏）
- ✅ 213 LLM 单元测试基线无回归
- ✅ R-002 引入的 `task_type` 透传不影响既有 task_type 路由逻辑（complete() 第 226-234 行的 task_type 模型路由仍正确）
- ✅ `_log_retry` 签名变更为强制位置参数 `call_type`，所有调用点已同步更新（仅 `_call_with_retry` 一处）

## 判定

R-001 (MEDIUM) + R-002/R-003/R-004 (LOW) 全部闭环。无新增问题，无 CRITICAL/HIGH。

**Verdict: approved**

T-057 可以标记为 done，进入 dev-plan-s7 的 T-058。
