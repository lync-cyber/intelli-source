---
id: "code-review-T-089-r1"
doc_type: code-review
author: reviewer
status: draft
deps: ["T-089"]
---

# Code Review: T-089 — 配置热加载边界 / ToolDeps 注入

**审查轮次**: r1
**审查日期**: 2026-05-21
**Layer 1**: ruff (impl 全通过) + mypy --strict (8 文件无问题) + pytest (62 passed, 0 failed)
**Layer 2**: AI 语义审查

---

## Layer 1 结果

| 检查项 | 结果 |
|--------|------|
| ruff check (impl files, 8 files) | CLEAN |
| mypy --strict (src/) | SUCCESS — no issues in 8 source files |
| pytest (unit/agent/test_tools_execute.py, unit/agent/test_runner_run_flexible.py) | 27 passed, 0 failed |
| pytest (全量 T-089 相关) | 62 passed, 0 failed |

测试文件 ruff 违规（不影响 verdict，但记录以供修复）：
- `tests/unit/agent/test_tools_execute.py`：F401（unused `call`）、E501（行长超 88）
- 其他测试文件（与 T-087 共享）见 T-087 r1 报告

---

## Layer 2 问题列表

### [R-001] HIGH: runner.py run_flexible — LLM 驱动工具调用时 tool_deps 从未注入

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `run_flexible()` 方法签名接受 `tool_deps` 参数（第 113 行），但在 LLM 工具调用分发循环中（第 163–209 行），工具调用的参数 `tc_args` 完全来自 LLM 返回的 JSON 解析，`tool_deps` 从未被插入 `tc_args`。最终执行（第 179 行）为 `await tool_fn(**tc_args)`，每次 LLM 驱动的工具调用均以 `tool_deps=None` 执行，触发 `_*_execute` 函数中的降级分支（返回 `{"status": "ok", ...}` 占位结果），而非真实工具调用。
- **影响**: AC-7 要求 6 个 `_*_execute` 函数通过 `tool_deps` 参数接收依赖注入；run_flexible 是 flexible mode 的执行路径，该路径下 ToolDeps 注入实际为空操作，AC-7 在 run_flexible 路径上未满足。
- **建议**: 在分发工具调用时将 `tool_deps` 注入 `tc_args`：
  ```python
  # 在 tool_fn 确认不为 None 之后、执行之前
  if tool_deps is not None:
      tc_args = {**tc_args, "tool_deps": tool_deps}
  result = await tool_fn(**tc_args)
  ```
  同时 run_strict 路径的 `step_params` 同样不含 `tool_deps`，需同步修复（`step_params = {**step.get("params", {}), **({"tool_deps": tool_deps} if tool_deps else {})}`）。

---

### [R-002] HIGH: factory.py build_agent_runner — session_factory/llm_gateway 被接受但丢弃，ToolDeps 从未构建

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `build_agent_runner(session_factory, llm_gateway, *, pipeline_config=None)` 接受 `session_factory` 和 `llm_gateway` 两个参数，但函数体内两者均未被使用——没有构建 `ToolDeps` 实例，也没有将其传递给 `AgentRunner`。`AgentRunner.__init__` 的签名为 `(self, tool_registry, llm_gateway, *, pipeline_engine)`，亦无 `tool_deps` 参数。在工厂层，ToolDeps 完全缺失组装逻辑。
- **影响**: 即使调用方传入有效的 `session_factory` 和 `llm_gateway`（如生产环境 DI 容器），这两个依赖均被静默丢弃，ToolDeps 无法在工厂层构建并流转到 AgentRunner，整个依赖注入链路在出口处断开。`get_agent_runner()` 单例更以 `session_factory=None, llm_gateway=None` 调用工厂，进一步固化了空依赖问题。
- **建议**: ① 在 `AgentRunner.__init__` 中增加 `tool_deps: ToolDeps | None = None` 参数，存储为 `self._tool_deps`；② 在 `build_agent_runner` 中构建 `ToolDeps` 并传入；③ 在 `run_flexible` 和 `run_strict` 中使用 `self._tool_deps` 作为工具分发时的依赖来源（R-001 建议的修复基础）。

---

### [R-003] MEDIUM: 测试 test_agent_runner_execute_with_tool_deps 仅验证签名，不验证转发行为

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `test_tools_execute.py` 中 AC-7 相关测试验证各 `_*_execute` 函数接受 `tool_deps` 参数，但未验证 `run_flexible` 在实际执行工具调用时是否将 `tool_deps` 转发给工具函数。由于 R-001 的转发缺口存在，这一测试盲区使得 HIGH 级缺陷得以通过所有测试。
- **建议**: 补充集成测试，mock LLM gateway 返回一个工具调用，验证工具函数被调用时收到的 `tool_deps` 不为 None。

---

### [R-004] MEDIUM: 测试文件 ruff 违规

- **category**: convention
- **root_cause**: self-caused
- **描述**: `tests/unit/agent/test_tools_execute.py` 存在 F401（unused `call`）和 E501（行长）违规。与 T-087 共享的测试文件同样有违规，详见 T-087 r1 报告 R-003。
- **建议**: 修复所有测试文件的 ruff 违规，确保 `ruff check tests/` 全通。

---

### [R-005] LOW: _*_execute 降级分支返回 `{"status": "ok"}` 占位结果，调用方无法区分真实执行与降级

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: 6 个 `_*_execute` 函数在 `tool_deps is None`（或对应字段为 None）时均返回形如 `{"status": "ok", "tool": "..."}` 的占位结果。这一设计下，调用方无法区分"工具真实执行成功"与"tool_deps 未注入导致静默降级"，排查困难。
- **建议**: 在降级路径中至少输出一条 `logger.warning("tool_deps not injected for %s, returning placeholder", tool_name)`，保持可观测性。此为改进建议，不阻塞当前功能。

---

## 覆盖率矩阵

| 维度 | 状态 | 备注 |
|------|------|------|
| completeness | FAIL | R-001 (HIGH): run_flexible 未转发 tool_deps；R-002 (HIGH): factory 未构建 ToolDeps |
| consistency | PASS | ToolDeps 字段命名在 deps.py / tools.py / 测试中一致 |
| convention | PASS (impl) / FAIL (tests) | impl ruff/mypy 全通，test 文件违规 |
| security | PASS | 无安全风险 |
| feasibility | PASS | 依赖注入设计可行 |
| structure | WARN | AgentRunner 接受 tool_deps 参数但不存储；工厂-Runner-工具 的 ToolDeps 流转链路不完整 |
| error-handling | WARN | R-005: 降级无可观测性 |
| performance | PASS | 无性能瓶颈 |
| test-quality | FAIL | R-003: 转发行为未被测试，导致 HIGH 缺陷漏测 |
| duplication | PASS | 6 个 execute 函数结构相似但职责各异，可接受 |
| dead-code | PASS | 无不可达分支 |
| complexity | PASS | 复杂度合理 |
| coupling | PASS | ToolDeps 作为 Any 类型注入，解耦合理 |

---

## 三态判定

**verdict: needs_revision**

存在 2 个 HIGH 问题（R-001、R-002）：run_flexible 分发循环不注入 tool_deps；factory.py 接受依赖参数但不构建 ToolDeps。两者共同导致 AC-7 在实际运行路径上无法满足。必须修复后重新提交审查。

| 严重等级 | 数量 |
|---------|------|
| CRITICAL | 0 |
| HIGH | 2 |
| MEDIUM | 2 |
| LOW | 1 |
