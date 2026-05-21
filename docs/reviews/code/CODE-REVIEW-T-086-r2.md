---
id: "code-review-T-086-r2"
doc_type: code-review
author: reviewer
status: approved
deps: [T-086]
---
# 代码审查报告: T-086 r2 — LLMGateway chat + JSON Mode + Function Calling (post-revision)

Layer 1 delegated to hook (lint hook 已配置 Edit|Write 触发)；revision commit `9fd0204` 的
ruff + mypy --strict 均 clean（commit message 已确认），通过门禁。

---

## §0 r1 复检

| ID | 等级 | 描述摘要 | 验证结果 | 说明 |
|----|------|----------|---------|------|
| R-001 | HIGH | runner.py 以 dict 消费 LLMResult | **RESOLVED** | `run_flexible()` 已全面改用 `response.metadata.get("usage", {})` / `response.metadata.get("tool_calls")` / `response.metadata.get("finish_reason", "")` 等属性访问；`test_runner.py` / `test_orchestration.py` / `test_runner_persist.py` 共 15 处 chat() mock 均返回 `LLMResult` 对象；新增 `test_runner_run_flexible.py` 5 个端到端回归测试全部 PASS |
| R-002 | MEDIUM | LLMOutputError 未加入 `llm/__init__.py` `__all__` | **RESOLVED** | `src/intellisource/llm/__init__.py` 已将 `LLMOutputError` 加入 import 和 `__all__`；`uv run python -c "from intellisource.llm import LLMOutputError"` 返回 OK |
| R-003 | MEDIUM | Function Calling 时 content 可为 None | **RESOLVED** | `gateway.py` L469：`content: str = response.choices[0].message.content or ""`；`TestT086ContentNoneGuard` 含 2 个测试：content=None+tool_calls 返回空字符串、CostTracker `output_length==0` 无 TypeError |
| R-004 | MEDIUM | chat() 不经 retry/fallback 包装 | **RESOLVED** | 新增 `_chat_call_with_retry()` 方法（L386-420），使用 `AsyncRetrying(stop=stop_after_attempt(4), reraise=True)` 包装 litellm 调用；捕获 `UnsupportedParamsError` 并降级为不带 tools/response_format 的重试；`TestT086ChatRetry` 覆盖 transient retry + downgrade 两路径 |
| R-005 | LOW | `**kwargs` 声明未转发 | **RESOLVED** | `chat()` 签名已无 `**kwargs` 参数（grep 确认）；docstring 与实现一致 |
| R-006 | LOW | content=None 路径无测试 | **RESOLVED** | 随 R-003 修复同步关闭；`TestT086ContentNoneGuard` 覆盖该路径 |

---

## §1 安全维度专项审查 (security_sensitive=true)

| 安全维度 | 结论 | 说明 |
|---------|------|------|
| SS-1: `_validate_tools()` 在 litellm 前阻断 | **PASS** | 修订后保持不变；`_validate_tools()` 仍在 `_chat_call_with_retry` 调用前执行（L451-452）；测试 `assert_not_awaited()` 验证通过 |
| SS-2: messages 内容透传无修改 | **PASS** | `call_kwargs["messages"] = messages` 直接赋值未变；docstring 保留 "(SS-2)" 标注；`_chat_call_with_retry` 只传入已组装的 `call_kwargs` 不修改 messages |
| SS-3: SchemaEnforcer 非递归，最多一次 | **PASS** | schema 验证路径（L480-490）结构未变；`call_count == 1` 计数器测试仍存在且 PASS |
| SS-4: 日志路径无原始 messages/content 泄漏 | **PASS** | 所有 `logger.warning()` 调用（共 8 处）仅记录 model 名称、配置路径、token 计数、exception 对象（`%s exc`）；retry 降级日志（L408-411）记录 `exc` 对象，不含原始 messages；`_log_retry()` 记录 `input_length=0` 等元数据，不含消息内容 |

---

## §2 net-new 扫描（delta `9fd0204`）

### error-handling — retry 耗尽行为分析

`_chat_call_with_retry` 使用 `reraise=True`，tenacity 在重试次数耗尽后直接重新抛出最后一个异常（原始异常类型与堆栈不变）。`LLMOutputError` 从 schema 验证路径抛出，不经过 retry 包装，两条路径正交、互不干扰。

UnsupportedParamsError 的降级逻辑：第一次调用触发 `UnsupportedParamsError` 时，代码在 `_chat_call_with_retry` 内部 `except` 块中立即执行降级重试并 `return`，不触发 tenacity retry 计数，也不重新 raise——降级调用的失败则会透传原始异常向上。此行为合理，但存在一个边界情形（见下方 N-001）。

### [N-001] LOW: UnsupportedParamsError 降级调用若再次失败，异常直接冒泡无日志标注

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `_chat_call_with_retry` 中降级路径（L418）`return await litellm.acompletion(**degraded_kwargs)` 若本次调用失败，异常会不经任何日志记录地透传给调用方，调试时难以判断是原始调用失败还是降级调用失败。影响面小（降级后参数已简化，再次失败多为不可恢复错误），但与 `_call_with_retry` 对 retry 的结构化记录相比稍不一致。
- **建议**: 对降级调用失败加一行 `logger.warning("Degraded chat call also failed: %s", exc)` 后 re-raise，使日志可区分两种失败来源。此建议不阻塞交付，可纳入后续改进。

---

## §3 test-quality — 新增测试断言有效性核查

`test_runner_run_flexible.py` 5 个新测试逐一核查：

| 测试名 | 断言对象 | 有效性 |
|--------|---------|--------|
| `test_done_on_stop_finish_reason` | `status=="success"`, `steps_executed==1`, `chat` 调用一次 | 有效：确认 finish_reason=stop 触发终止 |
| `test_done_when_tool_calls_empty` | `status=="success"`, chat 调用一次 | 有效：空 tool_calls 等价于 done |
| `test_tool_calls_in_metadata_dispatched_correctly` | `call_count==2`, `len(results)==1`, `results[0]["tool"]=="web_search"` | 有效：端到端验证 tool dispatch 流程 |
| `test_token_budget_tracked_via_metadata_usage` | `budget_exhausted is True`, `status=="success"` | 有效：通过 total_tokens=6000 累计，budget=10000，第二次调用后 12000≥10000 触发 |
| `test_no_attribute_error_on_metadata_access` | `status=="success"`（即不抛出 AttributeError） | 有效：隐式断言 `.metadata` 属性访问不会抛 AttributeError；作为 R-001 回归测试结构清晰 |

所有断言均针对实际行为，非重复 mock 返回值的空校验。

---

## §4 完整测试执行结果

```
uv run pytest tests/unit/llm/ tests/unit/agent/ -q --tb=short
492 passed in 4.16s
```

---

## 问题汇总

| ID | 严重等级 | category | 一句话描述 |
|----|---------|----------|-----------|
| N-001 | LOW | error-handling | UnsupportedParamsError 降级调用失败时无日志区分，调试可见性不足 |

r1 6 个问题全部已验证 RESOLVED。1 个 net-new LOW 问题，无 CRITICAL/HIGH/MEDIUM。

---

## 最终判定

**verdict: approved_with_notes**

无 CRITICAL/HIGH/MEDIUM 问题；1 个 LOW（N-001，降级失败日志缺失）不阻塞交付，可纳入后续改进。
