---
id: "code-review-T-MCP-GW-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-MCP-GW"]
---

# Code Review: T-MCP-GW — MCP Default Gateway Injection

Layer 1 delegated to hook（`PostToolUse Edit → lint_format`，编码阶段已实时执行 ruff check+format，门禁报告 ruff ✅ / mypy --strict 263 files ✅ / lint-imports 12/12 KEPT ✅）。

---

## 审查范围

- `src/intellisource/mcp_server/__init__.py`（+16 行：`_llm_gateway_singleton` 模块变量 + `_default_llm_gateway()` + `_default_search_engine_factory` 单行改动）
- `tests/unit/test_mcp_server.py`（末尾 +93 行：AC-1 ~ AC-4 四条测试）

---

## 问题列表

### [R-001] MEDIUM: `test_default_search_engine_has_llm_gateway` 注入了 `session_factory` fixture 但函数体未使用

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: 函数签名声明了 `session_factory: Any` 参数（pytest fixture 注入），但函数体完全绕过它，改用 `MagicMock()` 作为 fake session。这是一个 dead variable：pytest 每次都会构建并拆卸真实的 SQLite in-memory 会话工厂，产生无用的 fixture 开销；更重要的是，它给读者留下"测试需要真实会话工厂"的误导印象，与实际意图（仅验证 `_llm_gateway` 类型）不符。
- **建议**: 删除 `session_factory` 参数，保持函数签名与函数体一致。该测试只需 `mcp_mod._default_search_engine_factory(MagicMock())` 即可完成 AC-1 的验证，无需任何 fixture。

---

### [R-002] LOW: 模块级单例 `_llm_gateway_singleton` 在 xdist 进程内跨测试共享，测试依赖手工 `= None` 重置

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: 四条测试均以 `mcp_mod._llm_gateway_singleton = None` 重置单例。这在 xdist 默认的 **进程隔离（`--dist loadfile` / `--dist no`）** 下是安全的，因为每个 worker 进程有独立的模块状态。门禁已用 `-n 4` 跑过并全绿，确认无跨进程泄漏。
  
  然而，若同一 worker 进程内两条 T-MCP-GW 测试以意外顺序运行（例如 `test_default_gateway_is_singleton` 在 `test_default_search_engine_has_llm_gateway` 之前），前者构造的真实 `LLMGateway` 实例会被后者的 `= None` 重置，反之亦然——当前四条测试顺序相关，若 xdist 打乱顺序（`--dist load` 的负载均衡调度），在同一 worker 内连续执行时可能留下已构造的单例影响下一条。目前 `addopts` 无 `-n`，默认串行执行，无实际风险；但若将来开启 `-n auto`，此隐患会出现。
  
  正确的隔离方式是使用 `pytest.fixture(autouse=False)` + `monkeypatch.setattr` 来重置单例，令每条测试的重置行为由 pytest 框架保证，而非依赖函数内裸赋值的执行顺序。
- **建议**: 可选改进（非阻塞）：抽取 `reset_singleton` fixture，使用 `monkeypatch.setattr(mcp_mod, '_llm_gateway_singleton', None)` 替代内联赋值。既消除顺序耦合，也让重置意图在 fixture 层面声明，而非散落在每个测试函数体内。在当前默认串行配置下不修改也可接受。

---

### [R-003] LOW: `test_explicit_search_factory_overrides_default` 使用 `asyncio.get_event_loop().run_until_complete()`

- **category**: convention
- **root_cause**: self-caused
- **描述**: 该测试是同步函数（无 `@pytest.mark.asyncio`），内部用 `asyncio.get_event_loop().run_until_complete(...)` 驱动异步调用。在当前环境（Python 3.14 + asyncio_mode=auto）下，如果测试运行时没有已绑定的事件循环，`get_event_loop()` 会抛出 `RuntimeError: There is no current event loop in thread 'MainThread'`（环境验证已复现此行为）。测试当前通过，原因是 pytest-asyncio `asyncio_mode=auto` 在整个会话期间保持事件循环存在，但这依赖于框架内部行为，并非显式契约。
  
  更规范的做法是将测试声明为 `@pytest.mark.asyncio` 异步函数（与同文件其他测试一致），或使用 `asyncio.run()`（Python 3.7+ 标准入口）替代 `get_event_loop().run_until_complete()`。
- **建议**: 将 `test_explicit_search_factory_overrides_default` 改为 `async def` + `@pytest.mark.asyncio`（或依赖 asyncio_mode=auto 的隐式标注），并将 `asyncio.get_event_loop().run_until_complete(...)` 改为直接 `await mcp.call_tool(...)`。与文件其余测试风格保持一致。

---

## 正向审查记录

**正确性**：
- `_default_llm_gateway()` 的懒构造逻辑正确。`_llm_gateway_singleton` 在模块级初始化为 `None`，首次调用时构造并缓存，后续调用复用同一实例。MCP 以 stdio 单进程运行，无多线程并发写竞争，当前 GIL + 单线程事件循环下线程安全成立。
- `redis_client=None` 路径经 CircuitBreaker 代码验证：`__init__` 仅将 `redis` 存为 `self._redis`，不在构造期触碰 Redis；`embed()` 调用路径（`litellm.aembedding`）完全不经过 CircuitBreaker 的 `record_failure / record_success / allow_request`，无任何 `await self._redis.hgetall()` 触发点。`redis=None` 在 embed 路径上不会崩溃。
- 覆盖优先级逻辑完好：`build_mcp_server` 中 `search_factory = search_engine_factory or _default_search_engine_factory`，显式注入永远优先于默认 factory，与变更目的一致。

**架构/耦合**：
- `_default_llm_gateway()` 函数体内懒导入 `intellisource.composition.builders.build_llm_gateway`，避免了 MCP 模块加载时触发 builders 的重型顶层导入链（builders.py 顶层导入了 collector adapters、distributor channels 等多个包）。仅在第一次真正构造 gateway 时才引入此开销，符合 MCP stdio 启动轻量化目标。
- lint-imports Contract 11（"MCP server must not import other transport adapters directly"）已验证 KEPT，无边界违规。

**规约 §禁止设计阶段与变更说明残留**：
- `_default_llm_gateway()` 的 docstring 描述当前职责（"Return the process-wide LLMGateway singleton, constructing it on first call."），无溯源叙事，符合规约。
- 四条测试 docstring 均一句话描述 AC 语义（"AC-1: HybridSearchEngine produced by the default factory carries a LLMGateway."），无变更历史。

**测试断言强度**：
- AC-1/AC-2：`isinstance(engine._llm_gateway, LLMGateway)` + `engine_a._llm_gateway is engine_b._llm_gateway` — 既验证类型又验证对象同一性，断言强度足够。
- AC-3：`assert payload["total"] == 0` + `custom_engine.search.assert_awaited_once()` — 覆盖返回值和调用路径两个维度。
- AC-4：`engine._llm_gateway.embed.assert_awaited_once_with("semantic test")` — 精确断言 embed 被以正确参数调用，语义分支验证有效。

---

## 判定

**verdict: approved**（初判 approved_with_notes；用户选择修复全部 notes，三项已闭环并复跑门禁全绿）

无 CRITICAL / HIGH 问题。三条 notes 修复状态：

- R-001（MEDIUM）✅ 已修复：删除 `test_default_search_engine_has_llm_gateway` 的未使用 `session_factory` 参数（同型 dead variable 在 AC-4 一并清理）。
- R-002（LOW）✅ 已修复：抽取 `reset_gateway_singleton` fixture，以 `monkeypatch.setattr` 重置单例（自动恢复），消除四条测试的裸赋值顺序耦合。
- R-003（LOW）✅ 已修复：`test_explicit_search_factory_overrides_default` 改为 `@pytest.mark.asyncio async def` + 直接 `await mcp.call_tool(...)`，去除 `asyncio.get_event_loop().run_until_complete()`。

修复后门禁：ruff check . ✅ / ruff format ✅ / 全量 unit EXIT=0 全 PASS ✅（test-only 改动，impl 未动，mypy --strict src/ 与 integration 不受影响保持绿）。
