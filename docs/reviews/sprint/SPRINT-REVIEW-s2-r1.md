---
id: sprint-review-s2-r1
doc_type: sprint-review
author: reviewer
status: approved
---
# Sprint 2 审查报告
<!-- id: SPRINT-REVIEW-s2-r1 | reviewer: sprint-review | date: 2026-04-05 -->
<!-- sprint: 2 | layer1: passed(0 FAIL, 40 WARN) | layer2: completed -->

## 审查范围

- **Sprint**: Sprint 2 -- 采集引擎与处理管道
- **任务**: T-010, T-011, T-012, T-013, T-014, T-015, T-016, T-017, T-018 (共9个)
- **模块**: M-002 (collector), M-003 (pipeline)

## Layer 1 结果

脚本 `sprint_check.py` 返回 **0 FAIL, 40 WARN**:

- 任务状态: 全部 9 个任务 done
- 交付物: 34 个文件全部存在
- AC覆盖: 19 个验收标准全部在 tests/ 中有引用
- 计划外文件: 39 个 WARN (均为 Sprint 1 遗留的骨架文件 `__init__.py` 和实现文件，合理)
- CODE-REVIEW: 目录不存在 (WARN，与 Sprint 1 一致，TDD 流程未集成 code-review 步骤)

## Layer 2 审查结果

### 测试结果

```
798 passed in 5.53s
```

全部 798 个测试通过 (Sprint 1: 569 + Sprint 2 新增: 229)。

### mypy 结果

```
Success: no issues found in 60 source files
```

### ruff 结果

```
All checks passed!
```

### 代码质量审查

#### T-010: 采集器抽象基类与注册中心

- `base.py`: BaseCollector 定义 `collect(source_config) -> list[RawContent]` 统一接口，`conditional_fetch()` 支持 ETag/If-Modified-Since。`RawContent` 数据模型包含全部必填字段 (source_url, fingerprint, title, author, body_html, body_text, published_at, raw_metadata)。`compute_fingerprint()` 使用 SHA-256。实现简洁清晰。
- `registry.py`: CollectorRegistry 实现注册/获取/自动发现三项功能。未注册类型抛出 `CollectorError` (IS-COL-001)。自动发现扫描 `sources/` 子目录，通过 `SOURCE_TYPE` 属性注册。类型校验完备。

#### T-011: RSS采集适配器

- `adapters/rss.py`: RSSCollector 使用 feedparser 解析 RSS 2.0 和 Atom 1.0。日期解析支持 RFC 2822 和 ISO 8601 格式。解析失败返回空列表并记录错误日志。fingerprint 使用 `compute_fingerprint` 统一函数。

#### T-012: Web爬虫采集适配器

- `adapters/web.py`: WebCollector 使用 BeautifulSoup4 + lxml。噪音过滤通过移除 nav/footer/header/aside 标签和 sidebar/advertisement class。支持 CSS 选择器配置。超时和连接错误正确处理 (返回空列表)。

#### T-013: API采集适配器

- `adapters/api.py`: APICollector 支持 GET/POST 方法，可配置 headers/params/body。`_resolve_path` 实现简化版 JSONPath (点号分隔路径，支持 `$.` 前缀)。字段映射配置灵活。错误处理完备。

#### T-014: 速率限制与代理管理

- `rate_limiter.py`: Redis Lua 脚本实现令牌桶 + 并发控制原子操作。`acquire()` 阻塞等待而非拒绝。全局默认值 QPS=10, CONCURRENCY=5。`release()` 正确处理并发槽释放。
- `proxy.py`: ProxyManager 简洁实现，按 source_id 查询代理配置。

#### T-015: 频率自适应调度

- `adaptive.py`: AdaptiveScheduler 在 5 次采集后启用自适应。错误退避采用 `interval * (1 + error_count)` 乘法因子。区间钳位到 [300s, 86400s]。RetryPolicy 支持 3 次指数退避 (1s, 2s, 4s)。

#### T-016: 处理管道引擎

- `engine.py`: PipelineEngine 按序执行处理器，支持 fail_fast 模式。异常记录到 context `errors` 列表。记录执行耗时和日志。
- `middleware.py`: MiddlewareChain 实现洋葱模型，从内到外构建调用链。`BaseMiddleware` 定义 `process(ctx, next_fn)` 接口。
- `context.py`: PipelineContext 简洁的键值存储。
- `base.py`: BaseProcessor 抽象基类定义 `process(context) -> context`。

#### T-017: 管道条件分支与批处理

- `condition.py`: ConditionEvaluator 支持 eq/neq/in/not_in/contains 五种操作符。ConditionalProcessor 实现 if-else 路由。
- `batch.py`: BatchProcessor 包装 BaseProcessor 进行批量处理，隔离单项失败。

#### T-018: 内置处理器

- `processors/parser.py`: HTMLParser 使用正则去标签 + html.unescape 解码实体。
- `processors/dedup.py`: ContentDedup 基于 fingerprint 集合检测重复。
- `processors/tagger.py`: KeywordTagger 大小写不敏感匹配，去重标签。
- `processors/formatter.py`: FormatConverter 规范化行尾、空白、空行。

### AC 覆盖度验证

| AC 编号 | 描述 | 测试验证 | 状态 |
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

无显著范围偏移。实现与 arch#§2.M-002 和 arch#§2.M-003 的组件定义高度吻合。采集器适配器放在 `adapters/` 子目录而非 `sources/` 子目录，属于合理的组织选择 -- `sources/` 用于自动发现注册，`adapters/` 存放具体实现。

### Gold-plating 检测

未发现计划外额外功能。所有实现文件和测试文件均在 dev-plan deliverables 列表中。

### 质量聚合

无 CODE-REVIEW 报告可聚合 (与 Sprint 1 相同，TDD 流程中未集成 code-review 步骤)。

## 问题列表

### [SR-001] MEDIUM: `__init__.py` 模块导出为空

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `collector/__init__.py`、`collector/sources/__init__.py` 和 `pipeline/__init__.py` 均为空文件。dev-plan 中 T-010 和 T-016 的 deliverables 分别列出了这些文件作为"模块导出"和"数据源自发现目录"，但未定义任何公开 API (`__all__` 或显式 import)。虽然各组件可通过完整路径导入正常工作，但缺少模块级导出不符合"模块导出"交付物的预期。
- **建议**: 在 `collector/__init__.py` 中导出 `BaseCollector`, `RawContent`, `CollectorRegistry` 等核心类；在 `pipeline/__init__.py` 中导出 `PipelineEngine`, `BaseProcessor`, `PipelineContext` 等核心类。`sources/__init__.py` 保持空即可 (自动发现目录)。

### [SR-002] MEDIUM: AdaptiveScheduler 最小间隔与架构文档不一致

- **category**: consistency
- **root_cause**: upstream-caused
- **描述**: arch#§2.M-002 定义 AdaptiveScheduler "最小间隔保护（默认 120s）"，但实现中 `MIN_INTERVAL = 300` (5分钟)。dev-plan AC-T015-2 明确要求"最短 5 分钟"，实现与 dev-plan 一致但与 arch 不一致。
- **建议**: 以 dev-plan AC 为准 (300s) 是合理选择，但建议在后续 arch 修订中统一此数值，避免混淆。

### [SR-003] MEDIUM: API JSONPath 为简化实现，仅支持点号路径

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `api.py` 中的 `_resolve_path` 仅支持简单的点号分隔路径 (如 `$.data.articles`)，不支持标准 JSONPath 的数组索引 (`$.data[0]`)、通配符 (`$.data[*]`) 或过滤表达式。AC-T013-2 要求"支持 JSONPath 表达式"，当前实现覆盖了最常见的使用场景，但对复杂 JSON 结构的 API 响应可能不够。
- **建议**: 当前简化实现对 Sprint 2 范围足够。如后续需要完整 JSONPath 支持，可引入 `jsonpath-ng` 库替换 `_resolve_path`。

### [SR-004] LOW: CODE-REVIEW 报告缺失

- **category**: completeness
- **root_cause**: self-caused
- **描述**: Sprint 2 的 9 个任务均无对应的 CODE-REVIEW 报告 (docs/reviews/code/ 目录不存在)。与 Sprint 1 (SR-003) 相同的流程性问题。
- **建议**: 建议在后续 Sprint 中将 code-review 纳入 TDD 后的标准流程。本问题降级为 LOW，因为 TDD 流程 (RED-GREEN-REFACTOR) 已提供基本质量保障，且 mypy strict + ruff + 798 测试全通过。

### [SR-005] LOW: WebCollector fingerprint 算法与其他采集器不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: RSSCollector 和 APICollector 使用 `compute_fingerprint(source_url, title, published_at)` 生成 fingerprint，而 WebCollector 使用 `sha256(url + html)` 直接对完整 HTML 内容哈希。算法不一致意味着同一内容通过不同采集器采集时 fingerprint 不同，可能影响跨源去重。
- **建议**: 评估是否需要统一 fingerprint 算法。WebCollector 的做法有其合理性 (网页无明确 title/published_at)，但建议在后续 Sprint 的语义去重 (M-004) 实现时统一考虑。

---

## 审查结论

**结论: approved_with_notes**

Sprint 2 共 9 个任务全部完成。798 测试通过，mypy strict 零错误，ruff 零问题。19 个验收标准全部有对应测试覆盖，测试逻辑有效且断言充分。代码质量良好，架构合规。

发现 3 个 MEDIUM 问题和 2 个 LOW 问题，均不阻塞后续开发:

- MEDIUM: `__init__.py` 模块导出为空、AdaptiveScheduler 最小间隔与 arch 不一致、JSONPath 简化实现
- LOW: CODE-REVIEW 报告缺失、WebCollector fingerprint 算法不一致

无 CRITICAL 或 HIGH 问题，Sprint 2 可进入下一阶段。
