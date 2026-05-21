---
id: "code-review-T-085-r2"
doc_type: code-review
author: reviewer
status: approved
deps: [T-085]
---

# CODE-REVIEW-T-085-r2: HybridSearchEngine 真实查询接驳 + chat 方法补全（r2 复检）

Layer 1 delegated to hook (PostToolUse Edit matcher with `lint_format` — ruff format+check run at edit time).

## §0 r1 复检

| 编号 | 严重等级 | 标题 | 状态 |
|------|----------|------|------|
| R-001 | HIGH | router 传入 `search_mode` 但引擎参数名为 `mode`，模式选择被静默丢弃 | RESOLVED |
| R-002 | HIGH | `chat()` 返回字段与 arch API-013 ChatResponse schema 不符 | RESOLVED |
| R-003 | MEDIUM | `chat()` 在 `messages` 为空列表时静默返回占位符 | RESOLVED |
| R-004 | LOW | `test_instance_weights_used_when_not_overridden` 使用 OR 断言 | RESOLVED |

---

## §1 R-001 复检: router `mode=` kwarg 对齐

`api/routers/search.py:55` 已改为 `mode=body.search_mode`，`search_mode=` 调用已移除。

`tests/unit/api/test_search_router.py` 新增 `TestSearchModeForwarding`，包含两个测试：

- `test_search_mode_keyword_reaches_engine`：POST `/api/v1/search` 传入 `search_mode="keyword"`，断言 `captured_kwargs.get("mode") == "keyword"` 且 `"search_mode" not in captured_kwargs`。
- `test_search_mode_semantic_reaches_engine`：同上，`search_mode="semantic"`。

两个测试均通过（76 passed），R-001 **RESOLVED**。

---

## §2 R-002 复检: ChatResponse schema 对齐 API-013

`hybrid.py chat()` 现返回 `{session_id, answer, sources, query_time_ms}`。新增测试覆盖每个字段：

| 断言 | 测试方法 | 有效性 |
|------|----------|--------|
| `session_id` 非 None | `test_chat_response_has_session_id` | 有效 |
| 提供的 `session_id` 被回传 | `test_chat_uses_provided_session_id` 断言 `result["session_id"] == "session-abc-123"` | 有效 |
| `answer` 回显最后用户消息 | `test_chat_answer_echoes_last_user_content` 断言 `result.get("answer") == "Explain neural networks"` | 有效 |
| `sources == []` | `test_chat_response_has_empty_sources` | 有效 |
| `query_time_ms` 为 int 且 ≥ 0 | `test_chat_response_has_query_time_ms` | 有效 |

`[ASSUMPTION]` 注释已更新为明确说明字段为 placeholder，全 LLM 接驳延迟到 T-094。

R-002 **RESOLVED**。

---

## §3 R-003 复检: 空 messages 引发 ValueError 并路由 400

`hybrid.py chat()` 入口添加：

```python
if not messages:
    raise ValueError("messages must contain at least one entry")
```

`api/routers/search.py chat_search` 使用 `try/except ValueError` 返回 `JSONResponse(status_code=400, content={"detail": str(exc)})`。

`TestChatEmptyMessages` 包含：

- `test_chat_engine_value_error_returns_400`：mock engine 抛出 `ValueError`，断言响应为 400 且 `body["detail"]` 包含 `"messages"`。
- `test_chat_with_empty_message_string_still_calls_engine`：正常非空 message 路径不触发 400，返回 200。

R-003 **RESOLVED**。

---

## §4 R-004 复检: AND 断言 + pytest.approx 数值检查

`test_instance_weights_used_when_not_overridden` 已改为：

```python
assert "keyword_weight" in kwargs and "vector_weight" in kwargs, (
    "Both instance-level weights must be forwarded to HybridIndex.search()"
)
assert kwargs["keyword_weight"] == pytest.approx(0.3)
assert kwargs["vector_weight"] == pytest.approx(0.7)
```

R-004 **RESOLVED**。

---

## §5 净增量扫描（delta 范围：revision 4 文件）

### session_id 空字符串行为

`chat()` 使用 `session_id or str(uuid.uuid4())`，空字符串（falsy）会降级为随机 UUID。`ChatRequest.session_id` 字段类型为 `str | None`，Pydantic 接受 `""`，因此调用方传入空字符串时不会得到回传的空字符串，而是一个随机 UUID。

此行为属于有意义的防御策略（空字符串无法标识会话），与非预期输入的处理一致。当前为 stub 阶段，T-094 重构时可视需要改为显式 `if session_id is not None` 判断。不构成问题，信息性备注。

### query_time_ms 计时范围

`start = time.monotonic()` 在 `if not messages` 检查之后、for-loop 之前；`elapsed_ms` 在 for-loop 之后计算。目前计时范围仅覆盖列表遍历，属于 stub 的近零开销区间。T-094 接驳 LLMGateway 后计时范围应扩展到实际 LLM 调用。这是已知的 stub 限制，不构成问题。

### `chat_search` 返回类型注解

`chat_search` 返回值改为 `-> Any` 以支持 `JSONResponse` 返回路径，型注解宽泛但因 `engine` 本身标注为 `Any` 且为 stub 阶段，在 T-094 前不引入额外风险。mypy 全量检查 clean（见 commit 前置状态）。

### 净增量无新 CRITICAL/HIGH/MEDIUM 问题

四文件 delta 检查完毕，无净新问题。

---

## 最终判定

**verdict: approved**

所有 r1 问题（2 HIGH + 1 MEDIUM + 1 LOW）已全部解决，测试套件 76 passed / 0 failed，净增量扫描未发现新问题。
