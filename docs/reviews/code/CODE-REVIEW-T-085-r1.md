---
id: "code-review-T-085-r1"
doc_type: code-review
author: reviewer
status: approved
deps: [T-085]
---

# CODE-REVIEW-T-085-r1: HybridSearchEngine 真实查询接驳 + chat 方法补全

Layer 1 delegated to hook (PostToolUse Edit matcher with `lint_format` — ruff format+check run at edit time; commit smoke 2019 passed / 0 failed / 29 skipped).

## 审查摘要

| 维度 | 结论 | 问题数 |
|------|------|--------|
| completeness | PASS | 0 |
| consistency | FAIL | 2（R-001 HIGH, R-002 MEDIUM） |
| convention | PASS | 0 |
| structure | PASS | 0 |
| error-handling | NOTE | 1（R-003 MEDIUM） |
| security | PASS | 0 |
| test-quality | NOTE | 1（R-004 LOW） |
| complexity / duplication / coupling | PASS | 0 |

**AC 覆盖**：AC-1 ✓ AC-2 ✓ AC-3 ✓ AC-4 ✓ AC-5 ✓（均有对应测试且测试逻辑有效）

---

## 问题列表

### [R-001] HIGH: router 传入 `search_mode` 但引擎参数名为 `mode`，模式选择被静默丢弃

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `api/routers/search.py` 第 54 行调用 `engine.search(search_mode=body.search_mode, ...)` ，而 `HybridSearchEngine.search()` 的参数名为 `mode`（见 hybrid.py 第 95 行）。由于 `engine` 类型标注为 `Any`，Python 不报 TypeError——`search_mode` 落入 `**kwargs` 被静默忽略，`mode` 始终取默认值 `"hybrid"`，客户端无法通过 `search_mode` 字段切换检索模式。这违反 arch API-012 的 `search_mode` 字段定义。
- **建议**: 将 router 调用改为 `mode=body.search_mode`；或将 `HybridSearchEngine.search()` 参数名从 `mode` 改为 `search_mode` 以与 API 模型保持一致。二者选其一，对齐后补充测试断言 router 传入的模式能到达底层。

---

### [R-002] HIGH: `chat()` 返回字段与 arch API-013 ChatResponse schema 不符

- **category**: consistency
- **root_cause**: self-caused
- **描述**: arch API-013 定义 `POST /api/v1/search/chat` 响应体为 `{session_id, answer, sources, query_time_ms}`。当前 `chat()` 返回 `{"reply": last_content}`：字段名 `reply` 与契约的 `answer` 不同，且缺失 `session_id`、`sources`、`query_time_ms`。任务卡的 AC-5 仅要求 `reply` key，但 arch 契约是下游集成（T-094、前端/客户端）的参考基准。即使当前为 stub，返回结构与契约不一致会在 T-094 集成测试阶段引入额外返回值重构成本，且现有测试不会对此发出警告。
  `[ASSUMPTION]` 注释已在 docstring 中说明延迟到 T-094，但未说明当前返回结构偏离 API-013 的影响范围。
- **建议**: 将 stub 返回结构对齐 API-013 ChatResponse schema，即 `{"session_id": session_id or str(uuid.uuid4()), "answer": last_content, "sources": [], "query_time_ms": 0}`；同步更新 AC-5 测试断言检查 `answer` key 而非 `reply`；在 `[ASSUMPTION]` 注释中明确注明字段当前为 placeholder。

---

### [R-003] MEDIUM: `chat()` 在 `messages` 为空列表时静默返回 `"..."` 占位符

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `chat(messages=[])` 时 for-loop 未找到任何 user 角色消息，`last_content` 保持默认值 `"..."`，返回 `{"reply": "..."}`。调用方无法区分空输入与正常回复。对于直接由 API 路由调用的场景，`body.message` 是必填字符串（Pydantic 验证保证非空），所以 router 路径不会触发此情况；但直接调用 `chat()` 的集成测试或后续 T-094 代码可能传入空列表。
- **建议**: 在 `chat()` 方法入口添加 `if not messages: raise ValueError("messages must not be empty")`，与 `search()` 对空 query 的处理风格一致；或至少补充一个测试用例验证空列表时的行为（即便是预期返回 `"..."`，也应显式断言）。

---

### [R-004] LOW: `test_instance_weights_used_when_not_overridden` 使用 OR 断言，任一权重缺失不被检测

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `tests/unit/search/test_hybrid_engine.py` 第 294 行断言 `"keyword_weight" in kwargs or "vector_weight" in kwargs`。若实现只转发了一个权重而漏掉另一个，该测试仍会通过。AC-3 的意图是两个权重都应被转发。
- **建议**: 将断言改为 AND 条件：`assert "keyword_weight" in kwargs and "vector_weight" in kwargs`，与 `test_both_weights_forwarded_together` 的测试逻辑保持一致。

---

## 附注：`HybridIndex.search()` 接受但不使用 `keyword_weight`/`vector_weight`

`storage/vector.py` 的 `HybridIndex.search()` 接受 `**kwargs`，但 `_HYBRID_SQL` 中权重硬编码为 0.5/0.5，kwargs 中的 `keyword_weight`/`vector_weight` 被静默忽略。这是 storage 层（T-085 范围外）的已知限制，不计入本次审查问题，但建议在 T-094 或后续任务中通过 arch M-009 完善。

---

## 最终判定

**verdict: needs_revision**

存在 2 个 HIGH 问题（R-001 router 参数名不对齐导致模式切换失效；R-002 chat 返回结构偏离 arch API-013 schema），须修复后 r2 复审。
