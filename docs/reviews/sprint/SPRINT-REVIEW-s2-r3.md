# Sprint 2 终审报告
<!-- id: SPRINT-REVIEW-s2-r3 | reviewer: sprint-review | date: 2026-04-05 -->
<!-- sprint: 2 | layer1: degraded(9 FAIL script-level, see notes) | layer2: completed -->

## 审查范围

- **Sprint**: Sprint 2 -- 采集引擎与处理管道
- **任务**: T-010, T-011, T-012, T-013, T-014, T-015, T-016, T-017, T-018 (共9个)
- **模块**: M-002 (collector), M-003 (pipeline)
- **背景**: r1 发现 3M+2L，r2 复审确认修复后发现 1M+1L (dev-plan文本+CODE-REVIEW缺失)。CODE-REVIEW-sprint2-r1 发现 3M+4L，其中 R-003/R-005/R-006 要求修复。本轮为终审。

## Layer 1 结果

脚本 `sprint_check.py` 返回 **9 FAIL, 39 WARN**:

- 任务状态: 全部 9 个任务 done
- 交付物: 34 个文件全部存在
- AC覆盖: 19 个验收标准全部在 tests/ 中有引用
- 计划外文件: 39 个 WARN (均为 Sprint 1 遗留的骨架文件和跨模块共享的 `__init__.py`，合理)
- CODE-REVIEW: 9 个 FAIL -- 脚本按 `CODE-REVIEW-T-{NNN}-*.md` 模式匹配，而实际 CODE-REVIEW 以 Sprint 整体粒度产出 (`CODE-REVIEW-sprint2-r1.md`)。CODE-REVIEW 报告确实存在，脚本匹配模式与实际命名不一致，**降级进入 Layer 2**。

### 自动化工具结果

| 工具 | 结果 |
|------|------|
| pytest | 798 passed in 5.20s |
| mypy --strict | Success: no issues found in 60 source files |
| ruff check | All checks passed! |

## 历史问题修复验证

### r1 问题 (SPRINT-REVIEW-s2-r1)

| 编号 | 严重等级 | 问题 | 修复状态 | 终审验证 |
|------|---------|------|---------|---------|
| SR-001 | MEDIUM | `__init__.py` 模块导出为空 | RESOLVED (r2确认) | `collector/__init__.py` 导出 BaseCollector/RawContent/CollectorRegistry/compute_fingerprint 并定义 `__all__`；`pipeline/__init__.py` 导出核心类并定义 `__all__` |
| SR-002 | MEDIUM | AdaptiveScheduler MIN_INTERVAL 与 arch 不一致 | RESOLVED (r2确认) | `adaptive.py` 第15行 `MIN_INTERVAL: int = 120`，与 arch§2.M-002 一致 |
| SR-003 | MEDIUM | API JSONPath 简化实现 | ACCEPTED (r2确认) | docstring 明确标注局限性，v1 范围内合理 |
| SR-004 | LOW | CODE-REVIEW 报告缺失 | RESOLVED | `docs/reviews/code/CODE-REVIEW-sprint2-r1.md` 已产出 |
| SR-005 | LOW | WebCollector fingerprint 算法不一致 | RESOLVED (r2确认) | `web.py` 第80行 `compute_fingerprint(url, title, None)`，与 RSS/API 采集器统一 |

### r2 问题 (SPRINT-REVIEW-s2-r2)

| 编号 | 严重等级 | 问题 | 修复状态 | 终审验证 |
|------|---------|------|---------|---------|
| SR-001 | MEDIUM | dev-plan AC-T015-2 文本与 arch/实现不一致 | RESOLVED | dev-plan AC-T015-2 已更新为"最短 2 分钟，最长 24 小时（arch§2.M-002: 默认 120s）"，与 arch 和实现一致 |
| SR-002 | LOW | CODE-REVIEW 报告缺失 | RESOLVED | `docs/reviews/code/CODE-REVIEW-sprint2-r1.md` 已产出，覆盖全部 9 个任务 |

### CODE-REVIEW 问题 (CODE-REVIEW-sprint2-r1)

| 编号 | 严重等级 | 问题 | 修复状态 | 终审验证 |
|------|---------|------|---------|---------|
| R-001 | MEDIUM | BaseCollector.conditional_fetch 每次创建新 httpx.AsyncClient | ACCEPTED | 可在 M-006 调度层集成时统一优化，当前不阻塞 |
| R-002 | MEDIUM | APICollector._resolve_path 简化实现 | ACCEPTED | docstring 已标注局限性，v1 合理 |
| R-003 | MEDIUM | RateLimiter.acquire 使用 time.monotonic() | RESOLVED | `rate_limiter.py` 第68行已改为 `time.time()`，多 Worker 共享时间基准正确 |
| R-004 | LOW | collector/**init**.py 未导出适配器类 | ACCEPTED | 适配器通过自动发现机制注册，设计合理 |
| R-005 | LOW | WebCollector 默认超时未显式设置 | RESOLVED | `base.py` `conditional_fetch` 签名增加 `timeout: float = 30.0` 参数，`httpx.AsyncClient(timeout=timeout)` 显式传递，与 AC-T012-4 一致 |
| R-006 | LOW | ConditionEvaluator 对未知 operator 静默返回 False | RESOLVED | `condition.py` 第42行增加 `logger.warning("Unknown condition operator: %s", operator)`，配置错误可追溯 |
| R-007 | LOW | test_custom_headers_passed_through 断言逻辑复杂 | ACCEPTED | 不影响测试有效性，可在后续重构 |

## Layer 2 终审确认

### 代码质量

对 r1/r2/CODE-REVIEW 涉及的关键修复文件进行了逐项代码抽查:

- `collector/base.py`: `conditional_fetch` 增加 `timeout` 参数 (默认30.0)，传递至 `httpx.AsyncClient(timeout=timeout)`，签名和实现正确
- `collector/rate_limiter.py`: 第68行 `now = time.time()`，多 Worker 时间源一致
- `collector/adapters/web.py`: 第80行 `compute_fingerprint(url, title, None)`，fingerprint 统一
- `collector/adaptive.py`: 第15行 `MIN_INTERVAL: int = 120`，与 arch 一致
- `pipeline/condition.py`: 第42行 `logger.warning("Unknown condition operator: %s", operator)`，错误可追溯
- `collector/__init__.py` / `pipeline/__init__.py`: 均定义 `__all__` 并导出核心类

### 自动化质量门禁

- 798 测试全部通过 (Sprint 1: 569 + Sprint 2: 229)
- mypy strict 零错误 (60 源文件)
- ruff 零问题
- 19 个验收标准全部覆盖
- 34 个交付物全部存在

---

## 问题列表

无新问题。所有历史问题均已 RESOLVED 或 ACCEPTED。

---

## 审查结论

**结论: approved**

Sprint 2 终审通过。r1 的 5 个问题 (3M+2L)、r2 的 2 个问题 (1M+1L)、CODE-REVIEW 的 7 个问题 (3M+4L) 已全部验证:

- RESOLVED: 8 个 (修复并验证)
- ACCEPTED: 6 个 (合理取舍，已记录，不阻塞)

关键指标:

- 798 测试全部通过
- mypy strict 零错误 (60 源文件)
- ruff 零问题
- 19 个验收标准全部覆盖，测试逻辑有效
- 34 个交付物全部存在
- 无范围偏移，无 gold-plating
- 无 CRITICAL、HIGH、MEDIUM 或 LOW 未解决问题

Sprint 2 可进入下一阶段。
