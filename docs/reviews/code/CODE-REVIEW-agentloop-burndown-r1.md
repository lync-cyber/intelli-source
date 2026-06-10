---
id: "code-review-agentloop-burndown-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["agentloop-burndown"]
---

# CODE-REVIEW: BACKLOG 烧债批次 (R-005 / R-011 / R-012 / P11 / P12)

Layer 1 delegated to hook（PostToolUse Edit → `lint_format`）。Layer 2 由 reviewer 子代理对抗式深审三接缝（scheduler 幂等 / agent loop 并发 / LLM gateway 缓存可观测），主审复核子代理暴露的发现并就一处可行改动闭环。

- 审查范围：`fix/agentloop-hardening-review` 分支上烧债批次的增量改动（在 agentloop-hardening r1 之上）
- 全量门禁：unit 3564 passed / 5 deselected + ruff(format+check) + mypy --strict 267 文件，均绿
- verdict：**approved** —— 无 CRITICAL/HIGH；唯一可行 LOW（R-001 双读 registry）已闭环，其余为证伪项

## 审查闭环

| 条目 | 处置 | 验证 |
|------|------|------|
| R-001 LOW | `_execute_one_tool` 双重 `registry.get` → Phase 1 解析一次 callable 经 action 透传，registry 每调用读一次 | full agent suite 绿 + mypy 绿 |
| R-002 REFUTED | P11 `tool_deps` 共享引用：spread `{**tc_args, "tool_deps": tool_deps}` 给每个工具独立 args dict；`tool_deps` 引用在重构前的串行版本同样共享，非新增风险 | 核实 |
| R-003 REFUTED | P11 顺序/隔离：Phase 3 按 `actions` 原序回放，`outcome_iter` 与 run-action 一一对应；`_execute_one_tool` `except Exception` 逐工具兜底，`CancelledError`（BaseException）正确传播不被 `gather` 吞 | barrier 并发测试 + 顺序断言 |
| R-004 REFUTED | R-012 增量 token under-count：压缩改变 `len` 时全量重算；同长度 1→1 摘要边界仅 over-count（提前压缩，安全），永不漏压缩 | precomputed 触发/跳过测试 |

## 严重度分布
| SEVERITY | 数量 | 条目 |
|----------|------|------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 0 | — |
| LOW | 1 | R-001（已闭环） |
| 证伪（非问题）| 3 | R-002 R-003 R-004 |

---

## LOW

### [R-001] LOW: P11 `_execute_one_tool` 双重读取 registry
- **category**: duplication
- **root_cause**: self-caused
- **file**: `src/intellisource/agent/executors/flexible.py`
- **描述**: 重构后 Phase 1 以 `self._tool_registry.get(tc_name) is not None` 判定可执行，Phase 2 的 `_execute_one_tool` 又 `_resolve_callable(self._tool_registry.get(tc_name))` 二次读取同一 registry。read-only dict 下无正确性问题，但属冗余读且留有理论 TOCTOU 窗口。
- **建议**: Phase 1 解析 callable 一次，存入 run-action 的 `fn` 字段，`_execute_one_tool` 直接接收 —— registry 每调用读一次，并使 helper 不再依赖 registry（更易测）。**已按此闭环。**

---

## 证伪（已核实非问题）

### [R-002] REFUTED: P11 `tool_deps` 并发共享不构成新增竞争
- **file**: `src/intellisource/agent/executors/flexible.py`
- **核实**: `tc_args = {**tc_args, "tool_deps": tool_deps}` 为每个工具产生独立 args dict；被注入的 `tool_deps` 对象引用在串行重构前同样跨工具共享。工具对 `tool_deps` 的契约是只读使用，本批未改变该契约，故并发化未引入新的共享态写竞争。

### [R-003] REFUTED: P11 结果顺序与错误隔离正确
- **file**: `src/intellisource/agent/executors/flexible.py`
- **核实**: Phase 3 遍历 `actions`（原 tool_call 序），gated outcome 携带与重构前逐字一致的 message/tool_result；run outcome 经 `outcome_iter` 按 `run_actions` 入队序消费，二者同序 → 严格保持原序。`_execute_one_tool` 以 `except Exception` 逐工具兜底返回 `ok:False`，单个工具失败不拖垮 `asyncio.gather`；`CancelledError` 属 `BaseException` 不被捕获、正确向上传播。`sources_yielded` 在 Phase 3 按序判定，首个 `search` 结果仍只 yield 一次。

### [R-004] REFUTED: R-012 增量 token 计数不会漏压缩
- **file**: `src/intellisource/agent/executors/flexible.py`、`src/intellisource/llm/compaction.py`
- **核实**: `_drive` 维护 `history_tokens`，循环顶部折入上轮 tail，压缩返回 `len` 变化时全量重算（`_estimate_history_tokens`）。唯一同长度边界（1 条旧消息摘要为 1 条 summary）下计数 over-count（旧消息 token ≥ summary token），导致**提前**压缩而非漏压缩 —— 偏保守，安全。`compact_agent_messages(precomputed_total=...)` 与内部 `_total_tokens` 同一估算基（`gateway.estimate_tokens`），无 basis 漂移。

---

## 主审补充核实（安全）
- R-005 幂等：成功标记在副作用之后写、在 `acquire` 之前查；`force` 旁路标记检查并以 plain SET 刷新 TTL；`RESULT_MARKER_TTL=86400 > broker visibility 3600s`；非 UUID lock key 经 `_task_lock_key` 覆盖。有状态 `_StatefulGuard` 验证 redelivery 短路；同步修复 7 处未配 `was_succeeded` 的 guard mock（避免真值 MagicMock 误短路）。
- `_CompactionMixin` 迁移：`estimate_tokens` 保留为 Protocol 声明的跨切原语；`compress_if_needed`/`estimate_history_tokens` 内聚迁出 `__init__.py`；litellm 打桩面迁移已在 8 处测试同步（TestEstimateTokens 4 + 截断集成 4），无假绿残留。
- P12：`_extract_cached_tokens` 对对象/dict/None/缺失/非整数形状健壮（4 例忠实形状）；计量 best-effort（异常吞并记日志），不破坏调用链。
