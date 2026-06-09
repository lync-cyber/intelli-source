---
id: "code-review-T-EMB-2-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-EMB-2"]
---

# Code Review: T-EMB-2 — 查询侧 semantic 接线

Layer 1 delegated to pre-verification (ruff / mypy --strict 由调用方独立复核，全绿）。

---

## 问题列表

### [R-001] HIGH: builder 工厂 `build_search_engine_factory` 未接入 gateway，RAG 路径实质 keyword-only

- **category**: integration-wiring
- **root_cause**: self-caused
- **描述**: `composition/builders.py` 的 `build_search_engine_factory()` 返回的工厂始终构造 `HybridSearchEngine(session)`（gateway=None）。该工厂经 `_DepsBundle.search_engine_factory` → `ToolDeps.search_engine_factory` → `_search_execute` 流入 RAG 路径（instant-search pipeline / chat_search 的 `run_flexible`）。`build_llm_gateway(...)` 与 `build_search_engine_factory()` 均在同一 `_build_deps_bundle` 调用中、且 `llm_gateway` 已是 bundle 成员，gateway 在该 DI 链路完全可得，仅未传入。结果是：`/search` HTTP 端点（T-EMB-2 新接线）可以进行语义检索，而 agent 工具路径（RAG chat）依然 keyword-only——与任务目标"恢复 semantic 检索"在 RAG 路径落空直接矛盾。

  具体代码链路：
  - `deps.py` L54：`search_engine_factory=build_search_engine_factory()`，无 gateway 参数
  - `builders.py` L141-143：`_factory(session)` 仅传 `session`，无 llm_gateway

  修复路径（已确认可行）：`build_search_engine_factory` 接受可选 `llm_gateway` 参数，工厂内部 `HybridSearchEngine(session, llm_gateway=llm_gateway)`；`_build_deps_bundle` 中改为 `build_search_engine_factory(llm_gateway=llm_gateway)`。无需改动 `_search_execute`、`ToolDeps`、MCP 层（MCP 本身不持有 gateway，属于已知 scope 限制）。

- **建议**: 在本任务闭合——此处修改量极小（2 处传参），且不影响 MCP 和 worker 路径（MCP `_default_search_engine_factory` 继续无 gateway，符合 stdio 进程无 app.state 的既定限制）。若推迟到 T-EMB-3/后续，必须在 backlog 中显式跟踪，并在 `build_search_engine_factory` 处添加 `[ASSUMPTION]` 注释说明 RAG 路径 keyword-only 为临时状态。

---

### [R-002] MEDIUM: `except Exception` 捕获范围过宽，可能吞掉 embed 调用之外的异常

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `hybrid.py` L128-134 的 try/except 块：

  ```python
  try:
      query_vector = await self._llm_gateway.embed(query)
  except Exception:
      logger.warning(...)
      query_vector = None
  ```

  try 块仅含单行 `await self._llm_gateway.embed(query)`，因此在当前实现中捕获范围实际上是精确的——embed 调用本身的任何异常都会被捕获。然而 `except Exception` 会同时吞掉 `asyncio.CancelledError`（Python 3.8+ 中 CancelledError 是 BaseException 的子类，不受影响；但 `KeyboardInterrupt` / `SystemExit` 同理不受影响）。真正的风险在于：若未来有人在 try 块内增加其他逻辑（如日志格式化、条件判断），则这些逻辑抛出的非 embed 异常也将被静默吞掉。建议收窄到具体异常类型或添加注释锁定 try 块范围不扩大。

- **建议**: 将 `except Exception` 改为 `except Exception as exc:` 并在 `logger.warning` 中包含异常信息（`exc_info=True` 或 `%s, exc`），便于排查。同时在 try 块上方加注释"此 try 块仅包裹 embed 调用，禁止在 try 内添加其他逻辑"作为防腐保护。

---

### [R-003] MEDIUM: AC-7 测试断言 gateway 被构造时注入，未验证 gateway 在 embed 调用路径上被实际使用

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `test_search_router.py` `TestSearchEndpointGatewayWiring` 中的 AC-7 测试通过拦截 `HybridSearchEngine.__init__` 的 kwargs 来验证 `llm_gateway` 被传入构造函数。但同时 `HybridSearchEngine.search` 被 patch 为 `AsyncMock`，导致测试绕过了真正的 embed 调用路径。测试只能证明"gateway 被传入 `__init__`"，无法证明"semantic 模式下 gateway.embed 被调用"——即 wiring 的功能闭环未覆盖。如果有人把 `self._llm_gateway = llm_gateway` 这行删掉但保留构造参数，AC-7 仍然通过。

  注：AC-1（`test_ac1_semantic_mode_calls_embed_and_passes_vector`）在 `test_hybrid_engine.py` 中已验证了 engine 层面的 embed 调用，但该测试没有走 HTTP 路径，不能覆盖 router 到 engine 的完整链路。

- **建议**: 补充一个测试：通过 HTTP 发起 semantic 模式请求，不 patch `HybridSearchEngine.search`，仅 patch `HybridIndex.search` 返回空列表，同时让 `fake_gateway.embed` 返回真实向量；断言 `fake_gateway.embed` 被调用了一次。这样才能验证 router → engine → embed 的完整 wiring。

---

### [R-004] LOW: `test_hybrid_engine.py` 文件顶部 AC 列表与实际测试内容不对应

- **category**: convention
- **root_cause**: self-caused
- **描述**: 文件头部 docstring 列出的 AC 编号（AC-1 ~ AC-5）来自旧的 T-085 任务，与 T-EMB-2 新增的 AC-1 ~ AC-7（`TestGatewayEmbedInjection` 类）不对应。新 AC 在文件内以 `# ===========================================================================` 分隔节标题存在，但文件级 docstring 未更新，易造成阅读困惑。

- **建议**: 更新文件顶部 docstring，列出 T-EMB-2 的 7 条 AC 描述，或移除 AC 列表改为简短模块说明，避免与实际测试内容脱节。

---

### [R-005] LOW: `warning` 日志缺少结构化异常信息，embed 失败时可观测性不足

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `hybrid.py` L131-133：

  ```python
  logger.warning(
      "embed() failed for query=%r; degrading to keyword", query
  )
  ```

  吞掉了异常本身，生产环境无法从日志中知道 embed 失败的根因（是超时、网络错误、还是向量服务返回错误格式）。

- **建议**: 改为 `logger.warning("embed() failed for query=%r; degrading to keyword: %s", query, exc, exc_info=True)` 以保留异常栈信息（需要在 `except Exception as exc:` 中）。

---

## MCP 路径评估说明

`mcp_server/__init__.py` 的 `_default_search_engine_factory` 保持 `HybridSearchEngine(session)`（无 gateway）是合理的 scope 决定：MCP 以 stdio 进程运行，无 `app.state`，且 `build_mcp_server` 的 `search_engine_factory` 参数支持外部注入——如果 MCP 调用方有 gateway，可在启动时传入。该决策无需在本任务改动，不计为问题。

## 总结

| 严重度 | 数量 |
|--------|------|
| CRITICAL | 0 |
| HIGH | 1 |
| MEDIUM | 2 |
| LOW | 2 |

**verdict**: needs_revision → **修订后 approved**

R-001（HIGH）直接导致任务核心目标"恢复 semantic 检索"在 RAG 路径（agent `_search_execute` → instant-search pipeline → chat_search）上未实际生效：builder 工厂持有可得的 gateway 却未传入引擎，使 semantic/hybrid 模式在该路径等同 keyword-only。该问题在本任务 scope 内有明确修复路径，应在当前任务闭合而非推迟。

---

## 修订闭环（r1）

R-001 ~ R-005 全部修复并经 orchestrator 验证：

- **R-001**：`build_search_engine_factory(llm_gateway=None)` 增参并在工厂内 `HybridSearchEngine(session, llm_gateway=llm_gateway)`；`deps.py:54` 改为 `build_search_engine_factory(llm_gateway=llm_gateway)`。RAG 路径（`_search_execute`→`ToolDeps`）现已持有 gateway，semantic/hybrid 真实激活。MCP 路径维持无 gateway（stdio 无 app.state，已知 scope 限制，可由调用方注入）。
- **R-002+R-005**：`except Exception as exc:` + try 块范围锁定注释 + `logger.warning(..., exc, exc_info=True)`。
- **R-003**：新增 `test_semantic_request_triggers_gateway_embed_exactly_once`（HTTP→engine→embed 端到端，仅 patch `HybridIndex.search`，断言 `gateway.embed` 被调用一次）。
- **R-004**：`test_hybrid_engine.py` 文件头 docstring 更新为 T-EMB-2 的 AC。
- 附：清理 e2e 测试中一处尾随死元组表达式（`assert_called_once_with(...)` 后的无效 `, (msg)`）。

验证：search + api + composition 全绿（含两个新增测试），mypy --strict 4 源文件通过，ruff 清。**最终 verdict：approved**。
