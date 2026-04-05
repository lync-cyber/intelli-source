# Sprint 2 复审报告
<!-- id: SPRINT-REVIEW-s2-r2 | reviewer: sprint-review | date: 2026-04-05 -->
<!-- sprint: 2 | layer1: passed(0 FAIL, 40 WARN) | layer2: completed -->

## 审查范围

- **Sprint**: Sprint 2 -- 采集引擎与处理管道
- **任务**: T-010, T-011, T-012, T-013, T-014, T-015, T-016, T-017, T-018 (共9个)
- **模块**: M-002 (collector), M-003 (pipeline)
- **背景**: r1 审查发现 3 MEDIUM + 2 LOW 问题，本轮为修复后复审

## Layer 1 结果

脚本 `sprint_check.py` 返回 **0 FAIL, 40 WARN**:

- 任务状态: 全部 9 个任务 done
- 交付物: 34 个文件全部存在
- AC覆盖: 19 个验收标准全部在 tests/ 中有引用
- 计划外文件: 39 个 WARN (均为 Sprint 1 遗留的骨架文件 `__init__.py` 和实现文件，合理)
- CODE-REVIEW: 目录不存在 (WARN，与 Sprint 1 一致)

## r1 问题修复验证

| 编号 | 问题 | 修复状态 | 验证结果 |
|------|------|---------|---------|
| SR-001 | `__init__.py` 模块导出为空 | `collector/__init__.py` 导出 BaseCollector/RawContent/CollectorRegistry/compute_fingerprint；`pipeline/__init__.py` 导出 BaseMiddleware/BaseProcessor/MiddlewareChain/PipelineContext/PipelineEngine | RESOLVED |
| SR-002 | AdaptiveScheduler 最小间隔与 arch 不一致 | `MIN_INTERVAL = 120` 现与 arch§2.M-002 一致 (120s)。注意 dev-plan AC-T015-2 写"最短5分钟"，但代码文档注释已更新为"clamped to [120s, 86400s]"，以 arch 为准 | RESOLVED |
| SR-003 | API JSONPath 为简化实现 | 保持简化实现，`_resolve_path` 中添加了明确的 docstring 说明局限性，标注"For v1 this covers the common API field mapping use case" | ACCEPTED -- MEDIUM 建议，v1 范围内合理 |
| SR-004 | CODE-REVIEW 报告缺失 | 仍无 CODE-REVIEW 报告目录 | ACCEPTED -- LOW 问题，TDD 流程已提供基本质量保障 |
| SR-005 | WebCollector fingerprint 算法不一致 | `web.py` 第80行改为 `compute_fingerprint(url, title, None)`，与 RSS/API 采集器使用相同的统一函数 | RESOLVED |

## Layer 2 审查结果

### 测试结果

```
798 passed in 5.32s
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

逐文件审查 Sprint 2 全部实现文件，验证关键质量属性:

**T-010 采集器抽象基类与注册中心**

- `base.py`: BaseCollector 定义 `collect(source_config) -> list[RawContent]` 统一接口；`conditional_fetch()` 支持 ETag/If-Modified-Since；`RawContent` dataclass 含全部必填字段；`compute_fingerprint()` 使用 SHA-256。实现简洁。
- `registry.py`: CollectorRegistry 实现注册/获取/自动发现三项功能；未注册类型抛出 `CollectorError` (IS-COL-001) 使用 core/errors.py 错误框架；类型校验完备。

**T-011 RSS采集适配器**

- `rss.py`: 使用 feedparser 解析 RSS 2.0 和 Atom 1.0；日期解析支持 RFC 2822 和 ISO 8601；解析失败返回空列表并记录错误日志；使用统一 `compute_fingerprint`。

**T-012 Web爬虫采集适配器**

- `web.py`: 使用 BeautifulSoup4 + lxml；噪音过滤移除 nav/footer/header/aside 标签和 sidebar/advertisement class；支持 CSS 选择器配置；超时和连接错误正确处理；fingerprint 已统一为 `compute_fingerprint(url, title, None)`。

**T-013 API采集适配器**

- `api.py`: 支持 GET/POST 方法；可配置 headers/params/body；`_resolve_path` 简化版 JSONPath 有清晰的 docstring 标注局限性；字段映射灵活；错误处理完备。

**T-014 速率限制与代理管理**

- `rate_limiter.py`: Redis Lua 脚本实现令牌桶 + 并发控制原子操作；`acquire()` 阻塞等待；全局默认值 QPS=10, CONCURRENCY=5；`release()` 使用 Lua 脚本保证原子性并防止计数器降至负数。
- `proxy.py`: ProxyManager 简洁实现，按 source_id 查询代理配置。

**T-015 频率自适应调度**

- `adaptive.py`: 采集 5 次后启用自适应；错误退避采用 `interval * (1 + error_count)` 乘法因子；区间钳位到 [120s, 86400s]；RetryPolicy 支持 3 次指数退避 (1s, 2s, 4s)。

**T-016 处理管道引擎**

- `engine.py`: PipelineEngine 按序执行处理器，支持 fail_fast 模式；异常记录到 context `errors` 列表；记录执行耗时和日志。
- `middleware.py`: MiddlewareChain 实现洋葱模型，从内到外构建调用链；`BaseMiddleware` 定义 `process(ctx, next_fn)` 接口。
- `context.py`: PipelineContext 简洁的键值存储。
- `base.py`: BaseProcessor 抽象基类定义 `process(context) -> context`。

**T-017 管道条件分支与批处理**

- `condition.py`: ConditionEvaluator 支持 eq/neq/in/not_in/contains 五种操作符；ConditionalProcessor 实现 if-else 路由。
- `batch.py`: BatchProcessor 包装 BaseProcessor 进行批量处理，隔离单项失败。

**T-018 内置处理器**

- `processors/parser.py`: HTMLParser 使用正则去标签 + html.unescape 解码实体。
- `processors/dedup.py`: ContentDedup 基于 fingerprint 集合检测重复。
- `processors/tagger.py`: KeywordTagger 大小写不敏感匹配，去重标签。
- `processors/formatter.py`: FormatConverter 规范化行尾、空白、空行。

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
| AC-T010..T018 | 任务级验收标准 | 对应测试文件 | PASS |

### 范围偏移检测

无范围偏移。实现与 arch§2.M-002 和 arch§2.M-003 的组件定义一致。

### Gold-plating 检测

未发现计划外额外功能。39 个 WARN 文件均为 Sprint 1 骨架或跨模块共享的 `__init__.py`。

### 质量聚合

无 CODE-REVIEW 报告可聚合 (与 Sprint 1 相同)。

## 问题列表

### [SR-001] MEDIUM: dev-plan AC-T015-2 与 arch/实现不一致

- **category**: consistency
- **root_cause**: upstream-caused
- **描述**: dev-plan AC-T015-2 明确写"最短 5 分钟"(300s)，但 arch§2.M-002 定义"最小间隔保护默认 120s"，实现 `MIN_INTERVAL = 120` 与 arch 一致。r1 报告 (SR-002) 描述代码为 300 现已改为 120，与 arch 对齐，但 dev-plan AC 文本未同步更新。
- **建议**: 在后续 dev-plan 修订中将 AC-T015-2 更新为"最短 2 分钟"以与 arch 和实现保持一致。不阻塞当前 Sprint。

### [SR-002] LOW: CODE-REVIEW 报告缺失

- **category**: completeness
- **root_cause**: self-caused
- **描述**: Sprint 2 的 9 个任务均无对应的 CODE-REVIEW 报告 (docs/reviews/code/ 目录不存在)。与 Sprint 1 (SR-003) 相同的流程性问题。
- **建议**: 建议在后续 Sprint 中将 code-review 纳入 TDD 后的标准流程。TDD 流程 (RED-GREEN-REFACTOR) + mypy strict + ruff + 798 测试全通过已提供充分质量保障。

---

## 审查结论

**结论: approved_with_notes**

r1 报告的 5 个问题中，3 个已修复 (RESOLVED)，2 个接受 (ACCEPTED)。本轮复审发现 1 个新 MEDIUM 问题 (dev-plan AC 文本与 arch/实现不一致) 和 1 个延续的 LOW 问题 (CODE-REVIEW 报告缺失)。

关键指标:

- 798 测试全部通过
- mypy strict 零错误 (60 源文件)
- ruff 零问题
- 19 个验收标准全部覆盖
- 34 个交付物全部存在

无 CRITICAL 或 HIGH 问题，Sprint 2 可进入下一阶段。
