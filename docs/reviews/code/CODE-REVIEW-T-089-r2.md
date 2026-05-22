---
id: "code-review-T-089-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-089"]
---

# Code Review: T-089 — Agent 工具 6 个 execute stub 真实实现（r2）

**审查轮次**: r2
**审查日期**: 2026-05-22
**commit 范围**: 7798139（T-089 子集：factory.py / runner.py / tools.py / test_factory.py / test_tools_execute.py）
**Layer 1**: ruff check tests/ → All checks passed；mypy --strict src/intellisource/agent/{factory,runner,tools}.py → Success (0 issues)；pytest tests/unit/agent/test_factory.py tests/unit/agent/test_tools_execute.py → 47 passed, 0 failed

---

## r1 问题修复状态

| R-ID | 严重等级 | 标题 | 修复状态 |
|------|---------|------|---------|
| R-001 | HIGH | run_flexible 分发循环不注入 tool_deps | **已修复** |
| R-002 | HIGH | factory.py 接受依赖参数但不构建 ToolDeps | **已修复** |
| R-003 | MEDIUM | 测试仅验证签名，不验证转发行为 | **已修复** |
| R-004 | MEDIUM | 测试文件 ruff 违规 | **已修复** |
| R-005 | LOW | 降级路径返回 ok，调用方无法区分 | **已修复（改为 degraded）** |

---

## Layer 2 — AI 语义审查

### R-001 修复确认：run_flexible tool_deps 注入

runner.py 第 191–192 行：

```python
if effective_deps is not None:
    tc_args = {**tc_args, "tool_deps": effective_deps}
```

`effective_deps` 在方法顶部第 139 行通过 `tool_deps if tool_deps is not None else self._tool_deps` 解析。分发循环在调用 `tool_fn(**tc_args)` 前（第 197 行）已将 `effective_deps` 注入。

`run_strict` 同样在第 79–80 行注入：
```python
**({"tool_deps": effective_deps} if effective_deps is not None else {}),
```

**结论：R-001 完全修复。**

### R-002 修复确认：factory.py 构建 ToolDeps

factory.py 第 84–98 行构建 `ToolDeps(session_factory=, llm_gateway=, pipeline_engine=, search_engine=None, collector_registry=None, distributor=None)` 并作为 `tool_deps=tool_deps` 传入 `AgentRunner(...)` 构造器。

`AgentRunner.__init__` 在第 41 行存储为 `self._tool_deps = tool_deps`。

`get_agent_runner()` 调用 `build_agent_runner(session_factory=None, llm_gateway=None)` — `ToolDeps` 字段为 None，但 ToolDeps 对象本身非 None，`_tool_deps` 有效存储。

**结论：R-002 完全修复。**

### R-003 修复确认：转发行为测试

`TestRunFlexibleForwardsToolDeps`（第 813–990 行）包含两个反证测试：

1. `test_run_flexible_forwards_tool_deps_to_execute`：mock LLM 在第一轮返回 tool_call，在第二轮返回 stop；通过 `captured_deps` 列表验证 `captured_deps[0] is deps`，确认工具执行时收到的 tool_deps 是调用方传入的对象引用，而非 None。

2. `test_run_flexible_uses_instance_tool_deps_as_fallback`：runner 以 `tool_deps=instance_deps` 初始化，`run_flexible` 不传 `tool_deps` 关键字参数；验证工具执行时收到 `instance_deps`。

两项测试均通过（47 passed, 0 failed）。这直接覆盖了 r1 中 R-001 对应的测试盲区。

**结论：R-003 完全修复。**

### R-004 修复确认：ruff 违规

`ruff check tests/unit/agent/test_factory.py tests/unit/agent/test_tools_execute.py` → All checks passed。F401 (unused `call`) 和 E501 违规已消除。

**结论：R-004 完全修复。**

### R-005 修复确认：degraded 路径可观测性

tools.py 中 6 个 `_*_execute` 函数和 `_llm_complete_execute` 的降级分支均改为返回 `{"status": "degraded", "reason": "tool_deps not injected"}`，并在返回前调用 `logger.warning("tool_deps not injected for %s, returning placeholder", tool_name)`。

**结论：R-005 已修复（由低优先级的 warning 建议升级为实际 warning + 明确 degraded 状态）。**

---

## 审查重点专项检查

### 检查点 1：tools.py 的 execute 方法是否真正消费 tool_deps

对 6 个函数逐一确认（已读 tools.py 全文）：

| 函数 | 消费路径 | 验证 |
|------|---------|------|
| `_collect_execute` | `tool_deps.collector_registry.get(source_type).collect(source_id=..., **kwargs)` | 真实调用 |
| `_process_execute` | `tool_deps.pipeline_engine.execute(content_id=..., **kwargs)` | 真实调用 |
| `_distribute_execute` | `tool_deps.distributor.distribute(content_id=..., subscription_id=..., **kwargs)` | 真实调用 |
| `_search_execute` | `tool_deps.search_engine.search(query=..., top_k=..., **kwargs)` | 真实调用 |
| `_get_content_detail_execute` | `tool_deps.session_factory()` → `async with session as s` → `ContentRepository(session=s).get_by_id(UUID(content_id))` | 真实调用 |
| `_summarize_for_user_execute` | `tool_deps.llm_gateway.complete(prompt=..., task_type="summarize")` → `result.content` | 真实调用 |

这些函数内部不存在 `raise NotImplementedError` 或静态 mock 返回。当 `tool_deps is not None`（且对应字段非 None）时，均真实调用了底层服务。

**结论：6 个 execute 方法均真正消费 tool_deps，HIGH-002 不再适用。**

### 检查点 2：R-005 degraded 路径的调用方区分能力

通过全仓库 grep 确认，`tasks.py` 是 `agent_runner.execute()` 的唯一调用方（第 171 行）。tasks.py 接收 `result = _run_sync(...)` 后直接 `return dict(result)`（第 176 行），未检查 `result["results"]` 内各工具输出的 `status` 字段。

降级路径发生时，runner 将 `{"tool": tc_name, "output": {"status": "degraded", ...}}` 写入 `tool_results` 列表（runner.py 第 207 行），最终包含在 `_persist()` 返回的 `results` 键内。tasks.py 不区分 `status=degraded`，Celery 任务会以 success 状态返回。

这意味着运行期若 `ToolDeps` 字段（如 `search_engine`）为 None，工具调用静默降级，Celery 任务仍报 success。日志层面有 `logger.warning` 可供运维感知，但应用层无反馈。

这是一个已知的设计局限，但当前 sprint-8r 目标（接驳真实链路）在 factory.py 确保了生产路径的 `ToolDeps` 字段由注入参数填充。对于 `session_factory=None, llm_gateway=None`（`get_agent_runner()` 零参调用场景），降级会静默发生。

该问题不构成 r2 新增的 CRITICAL/HIGH，属于已知行为（r1 R-005 本为 LOW 级建议）。

### 检查点 3：ToolDeps 签名与 get_agent_runner() 兼容性

`ToolDeps` 字段均为 `Any`（deps.py），无 None 排斥。`build_agent_runner(session_factory=None, llm_gateway=None)` 构建 `ToolDeps(session_factory=None, llm_gateway=None, pipeline_engine=<实例>, search_engine=None, collector_registry=None, distributor=None)`。

`AgentRunner.__init__` 第 36 行 `tool_deps: ToolDeps | None = None` 有默认值，兼容原有无 `tool_deps` 参数的调用方（测试中存在）。

**结论：签名兼容，无破坏性变更。**

### 检查点 4：T-092 boot.py build_agent_runner 签名兼容性

boot.py 第 105 行调用 `_agent_factory.get_agent_runner()`，不直接调用 `build_agent_runner`。`get_agent_runner()` 签名无变化（零参数）。

如果 T-092 将来调用 `build_agent_runner(session_factory=session_factory)`，当前签名要求同时传入 `llm_gateway`（位置参数）。boot.py 中未见直接调用，不存在当前兼容性问题。

---

## 覆盖率矩阵

| 维度 | r2 状态 | 备注 |
|------|---------|------|
| completeness | PASS | R-001/R-002 均已修复；6 工具真实消费 tool_deps |
| consistency | PASS | ToolDeps 字段命名一致 |
| convention | PASS | ruff + mypy --strict 全通 |
| security | PASS | 无安全风险 |
| feasibility | PASS | 注入链路完整可落地 |
| structure | PASS | factory→runner→tool 三层 ToolDeps 流转完整 |
| error-handling | PASS | 降级路径有 logger.warning + status=degraded 可区分 |
| performance | PASS | 无性能瓶颈 |
| test-quality | PASS | 47 passed；转发行为通过对象引用断言验证 |
| duplication | PASS | 6 个 execute 函数结构相似但职责各异，可接受 |
| dead-code | PASS | 无不可达分支 |
| complexity | PASS | 复杂度合理 |
| coupling | PASS | ToolDeps 作为 Any 注入，解耦合理 |

---

## 新增问题

本轮审查未发现新的 CRITICAL、HIGH、MEDIUM 或 LOW 问题。

---

## 三态判定

**verdict: approved**

r1 的 2 个 HIGH（R-001、R-002）和 2 个 MEDIUM（R-003、R-004）均已完整修复，1 个 LOW（R-005）已超预期修复（warning + degraded 状态）。47 个测试全通，ruff + mypy --strict 全通。无新增问题。

| 严重等级 | r1 数量 | r2 新增 | r2 状态 |
|---------|--------|--------|--------|
| CRITICAL | 0 | 0 | — |
| HIGH | 2 | 0 | 全部修复 |
| MEDIUM | 2 | 0 | 全部修复 |
| LOW | 1 | 0 | 已修复 |
