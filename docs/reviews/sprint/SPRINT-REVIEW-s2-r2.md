# Sprint 2 复审报告
<!-- id: SPRINT-REVIEW-s2-r2 | reviewer: sprint-review | date: 2026-04-05 -->
<!-- sprint: 2 | layer1: passed(0 FAIL, 40 WARN) | layer2: completed -->

## 审查范围

- **Sprint**: Sprint 2 -- 采集引擎与处理管道
- **任务**: T-010, T-011, T-012, T-013, T-014, T-015, T-016, T-017, T-018 (共9个)
- **模块**: M-002 (collector), M-003 (pipeline)
- **背景**: r1 审查发现 3 MEDIUM + 2 LOW 问题，本轮为修复后独立复审

## Layer 1 结果

脚本 `sprint_check.py` 返回 **0 FAIL, 40 WARN**:

- 任务状态: 全部 9 个任务 done
- 交付物: 34 个文件全部存在
- AC覆盖: 19 个验收标准全部在 tests/ 中有引用
- 计划外文件: 39 个 WARN (均为 Sprint 1 遗留的骨架文件 `__init__.py` 和实现文件，合理)
- CODE-REVIEW: 目录不存在 (WARN，与 Sprint 1 一致)

### 自动化工具结果

| 工具 | 结果 |
|------|------|
| pytest | 798 passed in 5.34s |
| mypy --strict | Success: no issues found in 60 source files |
| ruff check | All checks passed! |

## r1 问题修复验证

| 编号 | 严重等级 | 问题 | 修复状态 | 验证详情 |
|------|---------|------|---------|---------|
| SR-001 | MEDIUM | `__init__.py` 模块导出为空 | RESOLVED | `collector/__init__.py` 导出 BaseCollector/RawContent/CollectorRegistry/compute_fingerprint 并定义 `__all__`；`pipeline/__init__.py` 导出 BaseMiddleware/BaseProcessor/MiddlewareChain/PipelineContext/PipelineEngine 并定义 `__all__`；`sources/__init__.py` 保持空 (自动发现目录，合理) |
| SR-002 | MEDIUM | AdaptiveScheduler 最小间隔与 arch 不一致 (r1 报告代码为 300s) | RESOLVED | `adaptive.py` 第15行 `MIN_INTERVAL: int = 120`，与 arch§2.M-002 "最小间隔保护默认 120s" 一致。测试断言 `>= 120`。注: dev-plan AC-T015-2 仍写"最短5分钟"，但以 arch 为准是正确做法 |
| SR-003 | MEDIUM | API JSONPath 为简化实现 | ACCEPTED | `_resolve_path` 保持简化的点号路径实现，已在 docstring 中明确标注局限性："This is a simplified dot-notation resolver, not a full JSONPath implementation...For v1 this covers the common API field mapping use case"。v1 范围内合理 |
| SR-004 | LOW | CODE-REVIEW 报告缺失 | ACCEPTED | docs/reviews/code/ 目录仍不存在。TDD 流程 + mypy strict + ruff 已提供充分质量保障 |
| SR-005 | LOW | WebCollector fingerprint 算法不一致 | RESOLVED | `web.py` 第80行改为 `compute_fingerprint(url, title, None)`，与 RSS/API 采集器使用同一统一函数 |

**小结**: 5 个 r1 问题中 3 个 RESOLVED、2 个 ACCEPTED。无遗留的 CRITICAL/HIGH 问题。

## Layer 2 代码质量审查

### T-010: 采集器抽象基类与注册中心

- `base.py`: BaseCollector 定义 `collect(source_config) -> list[RawContent]` 统一接口；`conditional_fetch()` 支持 ETag/If-Modified-Since 条件请求，304 时返回 None；`RawContent` 为 dataclass，含全部必填字段 (source_url, fingerprint, title, author, body_html, body_text, published_at, raw_metadata)；`compute_fingerprint()` 使用 SHA-256，输入为 source_url + title + published_at。实现简洁清晰。
- `registry.py`: CollectorRegistry 实现注册/获取/自动发现三项功能；`register()` 含 TypeError 类型校验；`get()` 未注册类型抛出 `CollectorError(IS-COL-001, category=UNRECOVERABLE)` 正确使用 core/errors.py 错误框架；`auto_discover()` 扫描 sources/ 目录，通过 `SOURCE_TYPE` 类属性自动注册。

### T-011: RSS采集适配器

- `rss.py`: 使用 feedparser 解析 RSS 2.0 和 Atom 1.0；`_parse_published` 支持 RFC 2822 (`parsedate_to_datetime`) 和 ISO 8601 (`fromisoformat`)；`_extract_body_html` 依次检查 Atom content 和 RSS description/summary；解析失败返回空列表并记录 `logger.error`；使用统一 `compute_fingerprint`。

### T-012: Web爬虫采集适配器

- `web.py`: 使用 BeautifulSoup4 + lxml；噪音过滤移除 nav/footer/header/aside 标签和 sidebar/advertisement class；支持通过 source_config metadata 中的 `css_selector` 自定义提取规则；`httpx.TimeoutException` 和 `httpx.ConnectError` 正确捕获并返回空列表；fingerprint 已统一为 `compute_fingerprint(url, title, None)`。

### T-013: API采集适配器

- `api.py`: 支持 GET/POST 方法，可配置 headers/params/body；`_resolve_path` 支持 `$.` 前缀的点号路径，有明确 docstring 标注局限性；`_resolve_str` 和 `_parse_datetime` 为辅助函数，处理类型安全转换；HTTP 错误和 JSON 解析失败均有 logger.error 日志。

### T-014: 速率限制与代理管理

- `rate_limiter.py`: Redis Lua 脚本在单次 EVAL 调用中完成令牌桶补充 + 并发检查 + 扣减的原子操作；`acquire()` 在令牌不足时以 `1/qps` 秒为间隔阻塞等待；`release()` 使用 Lua 脚本原子性递减并防止计数器降至负数；全局默认 QPS=10, CONCURRENCY=5。
- `proxy.py`: ProxyManager 简洁实现，`get_proxy(source_id)` 返回配置的代理 URL 或 None。

### T-015: 频率自适应调度

- `adaptive.py`: `AdaptiveScheduler.calculate_next_interval()` 在 collect_count < 5 时返回 default_interval；5 次后基于 avg_update_interval 自适应；错误退避 `interval * (1 + error_count)`；钳位到 [120s, 86400s]。`RetryPolicy` 支持 3 次重试，指数退避 (1s, 2s, 4s)。

### T-016: 处理管道引擎与处理器基类

- `engine.py`: PipelineEngine 按序执行处理器；fail_fast=False 时异常记录到 errors 列表继续执行；记录执行耗时写入 context。
- `middleware.py`: MiddlewareChain 从内到外构建调用链实现洋葱模型；`_wrap` 静态方法闭包嵌套清晰。
- `context.py`: PipelineContext 为简洁的 `dict[str, Any]` 封装，提供 get/set 接口。
- `base.py`: BaseProcessor 抽象基类定义 `process(context) -> context`。

### T-017: 管道条件分支与批处理

- `condition.py`: ConditionEvaluator 支持 eq/neq/in/not_in/contains 五种操作符；ConditionalProcessor 实现 if-else 路由，else_processor 可选。
- `batch.py`: BatchProcessor 包装 BaseProcessor 进行批量处理，单项失败时保留原始 context 继续处理。

### T-018: 内置处理器

- `processors/parser.py`: HTMLParser 正则去标签 + `html.unescape` 解码实体。
- `processors/dedup.py`: ContentDedup 基于内存中的 fingerprint 集合检测重复。
- `processors/tagger.py`: KeywordTagger 大小写不敏感匹配，去重标签列表。
- `processors/formatter.py`: FormatConverter 规范化行尾 (`\r\n`/`\r` -> `\n`)、合并多余空格、限制连续空行。

### AC 覆盖度验证

全部 19 个验收标准已验证，测试逻辑有效且断言充分:

| AC 编号 | 描述 | 测试文件 | 状态 |
|---------|------|---------|------|
| AC-005 | BaseCollector 统一接口 | test_base.py | PASS |
| AC-006 | 三种采集器正确解析 | test_rss.py, test_web.py, test_api.py | PASS |
| AC-007 | 输出 RawContent 标准字段 | test_rss.py, test_web.py, test_api.py | PASS |
| AC-008 | RSSHub/第三方 API 集成 | test_rss.py, test_api.py | PASS |
| AC-009 | 动态采集频率计算 | test_adaptive.py | PASS |
| AC-010 | ProxyManager 代理路由 | test_rate_limiter.py | PASS |
| AC-011 | Redis 令牌桶限速 | test_rate_limiter.py | PASS |
| AC-012 | 3次指数退避重试 | test_adaptive.py | PASS |
| AC-013 | 管道按序执行 | test_engine.py | PASS |
| AC-014 | 条件分支跳过 | test_condition.py | PASS |
| AC-015 | BaseProcessor 统一接口 | test_engine.py, test_processors.py | PASS |
| AC-016 | PipelineContext 数据传递 | test_context.py | PASS |
| AC-017 | 批处理模式 | test_batch.py | PASS |
| AC-T010-1..7 | 注册/获取/异常/自动发现/HTTP条件请求 | test_base.py, test_registry.py | PASS |
| AC-T011-1..2 | RSS解析失败/fingerprint | test_rss.py | PASS |
| AC-T012-1..4 | BS4+lxml/噪音过滤/CSS选择器/超时 | test_web.py | PASS |
| AC-T013-1..2 | GET/POST/JSONPath | test_api.py | PASS |
| AC-T014-1..3 | 等待模式/共享状态/默认值 | test_rate_limiter.py | PASS |
| AC-T015-1..3 | 默认间隔/钳位/错误退避 | test_adaptive.py | PASS |
| AC-T016-1..4 | 异常处理/日志/中间件链 | test_engine.py, test_middleware.py | PASS |
| AC-T017-1..3 | 条件表达式/批处理状态/if-else路由 | test_condition.py, test_batch.py | PASS |
| AC-T018-1..4 | HTML解析/去重/打标/格式化 | test_processors.py | PASS |

### 范围偏移检测

无范围偏移。实现与 arch§2.M-002 和 arch§2.M-003 的组件定义一致。采集器适配器放在 `adapters/` 子目录，`sources/` 用于自动发现注册，组织结构合理。

### Gold-plating 检测

未发现计划外额外功能。39 个 WARN 文件均为 Sprint 1 骨架或跨模块共享的 `__init__.py`，不构成 gold-plating。

### 质量聚合

无 CODE-REVIEW 报告可聚合 (与 Sprint 1 相同，TDD 流程中未集成 code-review 步骤)。

## 问题列表

### [SR-001] MEDIUM: dev-plan AC-T015-2 与 arch/实现不一致

- **category**: consistency
- **root_cause**: upstream-caused
- **描述**: dev-plan AC-T015-2 明确写"最短 5 分钟"(300s)，但 arch§2.M-002 定义"最小间隔保护默认 120s"，实现 `MIN_INTERVAL = 120` 与 arch 一致。实现正确以 arch 为准，但 dev-plan AC 文本未同步更新，可能导致后续开发者按 dev-plan AC 验收时产生困惑。
- **建议**: 在后续 dev-plan 修订中将 AC-T015-2 更新为"最短 2 分钟 (120s)"以与 arch 和实现保持一致。不阻塞当前 Sprint。

### [SR-002] LOW: CODE-REVIEW 报告缺失

- **category**: completeness
- **root_cause**: self-caused
- **描述**: Sprint 2 的 9 个任务均无对应的 CODE-REVIEW 报告 (docs/reviews/code/ 目录不存在)。与 Sprint 1 相同的流程性问题。
- **建议**: 建议在后续 Sprint 中将 code-review 纳入 TDD 后的标准流程。TDD 流程 (RED-GREEN-REFACTOR) + mypy strict + ruff + 798 测试全通过已提供充分质量保障，降级为 LOW。

---

## 审查结论

**结论: approved_with_notes**

r1 报告的 5 个问题中 3 个 RESOLVED、2 个 ACCEPTED。本轮独立复审发现 1 个新 MEDIUM 问题 (dev-plan AC 文本与 arch/实现不一致，upstream-caused) 和 1 个延续的 LOW 问题 (CODE-REVIEW 报告缺失)。

关键指标:

- 798 测试全部通过
- mypy strict 零错误 (60 源文件)
- ruff 零问题
- 19 个验收标准全部覆盖，测试逻辑有效
- 34 个交付物全部存在
- 无范围偏移，无 gold-plating

无 CRITICAL 或 HIGH 问题，Sprint 2 可进入下一阶段。
