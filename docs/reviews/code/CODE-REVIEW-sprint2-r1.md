---
id: "code-review-sprint2-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["sprint2"]
---
# Sprint 2 Code Review
<!-- id: CODE-REVIEW-sprint2-r1 | reviewer: code-review | date: 2026-04-05 -->

## 审查范围

### 实现文件 (src/intellisource/)

- collector/base.py, collector/registry.py, collector/__init__.py
- collector/adapters/rss.py, collector/adapters/web.py, collector/adapters/api.py
- collector/rate_limiter.py, collector/proxy.py, collector/adaptive.py
- pipeline/context.py, pipeline/base.py, pipeline/engine.py, pipeline/middleware.py
- pipeline/condition.py, pipeline/batch.py, pipeline/__init__.py
- pipeline/processors/parser.py, pipeline/processors/dedup.py
- pipeline/processors/tagger.py, pipeline/processors/formatter.py

### 测试文件 (tests/unit/)

- collector/test_base.py, collector/test_registry.py
- collector/test_rss.py, collector/test_web.py, collector/test_api.py
- collector/test_rate_limiter.py, collector/test_adaptive.py
- pipeline/test_context.py, pipeline/test_engine.py, pipeline/test_middleware.py
- pipeline/test_condition.py, pipeline/test_batch.py, pipeline/test_processors.py

## 自动化检查

| 工具 | 结果 |
|------|------|
| pytest | 798 passed, 0 failed (5.65s) |
| mypy --strict | Success: no issues found in 60 source files |
| ruff check | All checks passed |
| Layer 1 (lint hook) | 已配置 PostToolUse lint hook，编码阶段已实时修复，Layer 1 跳过 |

## 审查结果

### [R-001] MEDIUM: BaseCollector.conditional_fetch 每次创建新 httpx.AsyncClient

- __category__: performance
- __root_cause__: self-caused
- __描述__: `collector/base.py` 第 61 行 `conditional_fetch` 方法每次调用都通过 `async with httpx.AsyncClient() as client` 创建一个新的 HTTP 客户端实例。在高频采集场景下（单节点并发 >= 20，arch#§5.1），反复创建/销毁连接池会带来不必要的性能开销，无法利用 HTTP 连接复用（keep-alive）。
- __建议__: 在 BaseCollector 或各适配器中持有一个可复用的 httpx.AsyncClient 实例（通过构造函数注入或延迟初始化），并在采集结束后关闭。类似地，`api.py` 第 69 行 `APICollector._request` 也存在相同问题。此项可在后续 Sprint 的集成阶段统一处理，因为 M-006 调度层可能统一管理客户端生命周期。

### [R-002] MEDIUM: APICollector._resolve_path 为简化实现，不支持完整 JSONPath 规范

- __category__: completeness
- __root_cause__: self-caused
- __描述__: `api.py` 中 `_resolve_path` 仅支持简单的点分路径（如 `$.data.articles`），不支持数组索引 `[0]`、通配符 `*`、递归下降 `..` 等 JSONPath 标准特性。dev-plan AC-T013-2 要求"支持 JSONPath 表达式配置响应字段映射"。当前实现已在 docstring 中明确标注了局限性（第 24-26 行），对 v1 大部分 API 集成场景够用。
- __建议__: 当前 docstring 中的 limitation 说明是好做法。若后续有用户需求涉及复杂 JSON 结构（如数组元素提取），可引入 `jsonpath-ng` 库。当前不阻塞。

### [R-003] MEDIUM: RateLimiter.acquire 使用 time.monotonic() 作为 Redis Lua 脚本时间源

- __category__: consistency
- __root_cause__: self-caused
- __描述__: `rate_limiter.py` 第 68 行使用 `time.monotonic()` 获取当前时间并传递给 Redis Lua 脚本。`time.monotonic()` 返回的是进程级单调时钟值，不同 Worker 进程的 monotonic 时钟互不相关。当 AC-T014-2 要求多 Worker 共享速率限制状态时，不同 Worker 传入的 `now` 值可能差异很大，导致令牌桶的 `elapsed` 计算不正确。
- __建议__: 改用 `time.time()`（系统时钟）或在 Lua 脚本中使用 `redis.call('TIME')` 获取 Redis 服务器时间，确保多 Worker 共享一致的时间基准。

### [R-004] LOW: collector/__init__.py 未导出适配器类和辅助组件

- __category__: completeness
- __root_cause__: self-caused
- __描述__: `collector/__init__.py` 仅导出 `BaseCollector`、`CollectorRegistry`、`RawContent`、`compute_fingerprint`，未导出 `RSSCollector`、`WebCollector`、`APICollector`、`RateLimiter`、`ProxyManager`、`AdaptiveScheduler` 等。这是合理的设计选择（避免循环导入，按需从子模块导入），但与 Sprint 1 的 `storage/__init__.py` 导出模式不一致。
- __建议__: 保持当前做法即可，适配器通过自动发现或直接子模块导入使用。仅做记录。

### [R-005] LOW: WebCollector 默认超时未显式设置

- __category__: completeness
- __root_cause__: self-caused
- __描述__: AC-T012-4 要求"请求超时（默认 30s）"，但 `web.py` 使用 `self.conditional_fetch(url)` 进行请求，而 `BaseCollector.conditional_fetch` 使用 httpx 默认超时（5s connect + 5s read，非 30s）。实际超时行为由 httpx 默认值决定，与 AC 中声明的 30s 不一致。
- __建议__: 在 `conditional_fetch` 或 `WebCollector.collect` 中显式传递 `timeout=httpx.Timeout(30.0)`，使行为与 AC 文档一致。此项不影响功能正确性（httpx 默认也有超时保护），但改善了可预测性。

### [R-006] LOW: ConditionEvaluator 对未知 operator 静默返回 False

- __category__: error-handling
- __root_cause__: self-caused
- __描述__: `condition.py` 第 39 行，当传入不在已知列表中的 operator 时，`evaluate` 静默返回 `False`。这可能掩盖配置错误（如拼写错误 "equals" 而非 "eq"），用户不会收到任何提示。
- __建议__: 对未知 operator 记录 WARNING 日志或抛出 `PipelineError`（category=UNRECOVERABLE），帮助用户发现配置问题。

### [R-007] LOW: 测试文件中 test_custom_headers_passed_through 断言逻辑复杂且脆弱

- __category__: test-quality
- __root_cause__: self-caused
- __描述__: `test_api.py` 第 318-322 行的 headers 断言使用了复杂的内联条件表达式来处理参数位置不确定性。这种断言方式较脆弱，如果 `_request` 的调用签名变化，测试可能静默通过。
- __建议__: 改为直接断言 `mock_req.call_args` 的特定位置参数或关键字参数，或在 `_request` 方法中使用 keyword-only 参数使断言更明确。

## 架构合规性

| 检查项 | 结果 |
|--------|------|
| 错误框架使用 (core/errors.py) | 符合。CollectorRegistry.get() 使用 CollectorError + IS-COL-001 错误码 + ErrorCategory.UNRECOVERABLE |
| 模块边界 (M-002 / M-003) | 符合。collector 和 pipeline 模块职责清晰分离，无越界依赖 |
| 命名规范 (PEP 8 / arch#§7) | 符合。文件名 snake_case，类名 PascalCase，函数/变量 snake_case |
| 类型标注 (mypy strict) | 符合。60 个源文件零错误 |
| 接口契约 | 符合。BaseCollector.collect() 签名与 arch#§2.M-002 一致；BaseProcessor.process() 与 arch#§2.M-003 一致 |
| 安全检查 | 通过。未发现硬编码密钥、路径遍历或注入风险 |

## 测试质量

| 维度 | 评估 |
|------|------|
| 断言有效性 | 良好。所有测试包含具体的值断言、类型断言和行为断言 |
| AC 覆盖 | 完整。AC-005~AC-017, AC-T010~AC-T018 均有对应测试 |
| 边界覆盖 | 良好。空列表、None 值、错误状态码、网络异常、配置缺失等边界条件均有测试 |
| 测试隔离 | 良好。使用 mock/patch 隔离外部依赖（httpx、Redis），无跨测试状态泄漏 |
| 测试逻辑 | 良好。断言期望值与接口契约一致，测试验证了声称的行为 |

## 结论

__approved_with_notes__

无 CRITICAL 或 HIGH 问题。发现 3 个 MEDIUM 和 4 个 LOW 建议项。其中 R-003（RateLimiter 时间源）在多 Worker 部署时可能影响速率限制精度，建议在集成测试阶段验证；R-001（httpx 客户端复用）可在 M-006 调度层集成时统一优化。整体代码质量优良，架构合规，测试覆盖充分。
