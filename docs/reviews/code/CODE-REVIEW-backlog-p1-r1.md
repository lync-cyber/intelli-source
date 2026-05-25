---
id: "code-review-backlog-p1-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["B-003", "B-004", "B-005", "B-006"]
---

# CODE-REVIEW: backlog-p1 (B-003 + B-004 + B-005 + B-006)

> Layer 1 delegated to pre-review CI checks (ruff check + ruff format --check + mypy --strict 全 clean)
> Layer 2 全维度审查（task_kind 含 feature/refactor 非纯 chore，AC 数 > 2，不命中短路条件）

## 审查范围

- B-006: `tests/unit/storage/conftest.py` (+14 行 ARRAY→JSON mutation)
- B-003: `src/intellisource/observability/{metrics.py,health.py}` + `composition.py` + `api/routers/system.py` + `docker/prometheus/alerts.yml` + 2 新测试
- B-004: 新建 `src/intellisource/scheduler/dispatch.py` + 迁移 `api/routers/{tasks,pipelines}.py` + 2 新测试
- B-005: 扩展 `observability/metrics.py` labeled counter + `distributor/facade.py` + `llm/gateway/__init__.py` 调用点迁移 + `alerts.yml` 同步 + 3 新/扩展测试

## 验证基线

- 全量回归: 2805 PASS / 0 FAIL / 0 skip / 0 xfail / 51 deselected
- mypy --strict: 148 files clean
- ruff check + format: clean
- 新增测试数: B-003 (17) + B-004 (7) + B-005 (14) = 38 个

## 问题列表

### [R-001] MEDIUM: labelnames 字段已注册但 increment 时未强制使用
- **category**: consistency
- **root_cause**: self-caused
- **位置**: `src/intellisource/observability/metrics.py:176-206`
- **描述**: `register_labeled_counter` 强制存 `_labeled_counter_labelnames`（不同 labelnames 二次注册抛 ValueError），但 `increment_labeled_counter(name, labels=...)` 内部仅 `_labels_to_key(labels)` 拼 key，**不校验 `labels.keys()` 是否等于注册时的 labelnames**。后果：
  - typo 不报错：`increment_labeled_counter("pushes_total", {"chanel":"email","status":"sent"})` (chanel 拼错) 会生成新 series 并累计，造成无意义的高基数 metric 污染
  - schema 漂移：B-003 labeled gauge 子系统**完全不存** labelnames（弱约束），B-005 counter 子系统**部分存**但未强制使用 — 两个子系统不对称
- **建议**:
  - 短期：`increment_labeled_counter` / `get_labeled_counter_value` 入口处校验 `tuple(sorted(labels.keys())) == self._labeled_counter_labelnames[name]`，不一致抛 KeyError 提示期望 labelnames
  - 中期：对齐 labeled gauge 子系统 — 也接受 labelnames 参数 + 增量校验，统一弱/强约束策略
  - 长期：若引入 prometheus_client 原生 Counter/Gauge，此层抽象可整体替换

### [R-002] LOW: send_task guardrail 仅扫描 src/，BACKLOG 验证目标"全库"措辞偏严
- **category**: consistency
- **root_cause**: self-caused (spec 措辞 vs 实现选择)
- **位置**: `tests/unit/scheduler/test_send_task_guardrail.py:15` (`_SRC_ROOT = .../src`)
- **描述**: BACKLOG B-004 验证目标写"全库 send_task( 匹配数 == 包装函数实现处"，但实现仅扫 `src/`。`tests/integration/test_s8r_coldstart.py:87` 仍用裸 `celery_app.send_task(...)` — 这是合理的（cold start 测试需直接验证底层 celery 契约），但与 spec 字面表述不符
- **建议**: 调整 [BACKLOG-intellisource-v1.md](../../BACKLOG-intellisource-v1.md) §B-004 验证目标为"`src/` 下 `.send_task(` 命中数 == 1（即 `dispatch.py:37` 的 facade 实现处），`tests/` 内允许测试底层 celery 契约的合理使用"；或在 `_ALLOWED_FILE` 旁加注释明确范围限定的设计理由

### [R-003] LOW: `_ALLOWED_FILE` 子串匹配而非精确路径匹配
- **category**: convention
- **root_cause**: self-caused
- **位置**: `tests/unit/scheduler/test_send_task_guardrail.py:9,24`
- **描述**: `if _ALLOWED_FILE in rel_posix: continue` 用子串匹配。任意路径包含 `"scheduler/dispatch.py"` 的文件（如假想的 `tests/unit/scheduler/dispatch.py` 或 `vendored/scheduler/dispatch.py`）都会被豁免。当前不存在 collision，但是潜在的 false-negative 隐患
- **建议**: 改用精确匹配：`if rel == Path("intellisource/scheduler/dispatch.py"): continue`

### [R-004] LOW: distributor `_record_push_outcome` 在 hot path 重复 register
- **category**: structure
- **root_cause**: self-caused
- **位置**: `src/intellisource/distributor/facade.py:31-39`
- **描述**: 每次推送都进入 `register_labeled_counter` (虽然幂等)，与 B-003 health gauge 在 `HealthChecker.__init__` 时集中注册的风格不一致。性能影响极小（dict lookup + lock），但属于 polish issue
- **建议**: composition 阶段（`composition.py` 装配 DistributorFacade 时）集中注册 `pushes_total`，调用点只做 `increment_labeled_counter`。等价改动可一并迁移 `llm/gateway/__init__.py` 的 `_record_llm_call` 注册逻辑

### [R-005] LOW: alerts.yml LLM 表达式未利用 model label 拆分阈值
- **category**: consistency
- **root_cause**: self-caused (功能完整性)
- **位置**: `docker/prometheus/alerts.yml:55-58`
- **描述**: `rate(llm_call_failures_total[5m]) / clamp_min(rate(llm_calls_total[5m]), 0.0001)` 对 labeled counter 仍是有效 PromQL（自动聚合 model 维度），但表达式语义弱化 — 单一 model 故障率高时被其他健康 model 稀释；alert 一旦 fire 也无 model 信息辅助定位
- **建议**: 增强 alert 表达式为 `sum by (model) (rate(llm_call_failures_total[5m])) / clamp_min(sum by (model) (rate(llm_calls_total[5m])), 0.0001) > 0.3 for 5m`，annotations 中模板化 `{{ $labels.model }}`。建议追加 backlog 项 B-029（与 B-005 同源演进）

## 维度审查总结

| 维度 | 结论 | 备注 |
|-----|------|------|
| convention | LOW × 2 | R-003 子串匹配 + R-005 alert 表达式风格 |
| consistency | MEDIUM × 1 + LOW × 1 | R-001 labelnames 不对称（重点）+ R-002 spec 偏离 |
| structure | LOW × 1 | R-004 hot-path register |
| security | clean | B-004 trace_id 注入正确（dict 浅拷贝 + setdefault 不覆盖用户）；headers 合并安全；fallback uuid4 避免常量污染 |
| integration-wiring | clean | B-003 HealthChecker → composition.py 已传 metrics_collector；B-005 distributor / LLM gateway 6 个调用点全部传入正确 model label；删除的 pushes_*_total 在 src/ 已彻底清除 |
| error-handling | clean | distributor `_record_push_outcome` BLE001 静默捕获是合理设计（metric 失败不阻塞 delivery）；dispatch.py headers `dict(headers or {})` + `setdefault` 双重防御 |
| test-quality | clean | guardrail 配套 sanity check 防 dispatch.py 被误改；labeled counter 测试覆盖 register/increment/get/iter + 边界（不同 labelnames 二次注册抛错） |

## 判定

**verdict: approved_with_notes**

- 无 CRITICAL / HIGH
- 1 MEDIUM (R-001 labelnames 强制使用) + 4 LOW
- R-001 建议立项 backlog（独立任务卡 B-029 或合入下次 metrics 演进批次），其余 LOW 可在 inline 闭环时顺手或归档参考

## 闭环建议

按 §Approved-with-Notes Protocol：
1. **接受并继续**：MEDIUM/LOW 保留在此报告供后续参考（R-001 建议立项 B-029）
2. **要求修复 R-001**：进入 Revision Protocol（增量修复 metrics.py `increment_labeled_counter` 增量校验 + labeled gauge 子系统对齐）

---

## R-001 修订闭环（reviewer 增量审查 — inline，无 r2）

**用户决策**：选项 2（Revision Protocol）

**修订范围**：
- `src/intellisource/observability/metrics.py` — counter + gauge 两子系统对称化：
  - `register_labeled_gauge(name, labelnames: list[str], description="")` 签名加必填 labelnames（与 counter 对称）
  - 新增 `_labeled_gauge_labelnames: dict[str, tuple[str, ...]]` + `_check_labeled_gauge_keys` 辅助
  - `set_labeled_gauge` / `get_labeled_gauge_value` 入口强制 keys 校验
  - 同样 `increment_labeled_counter` / `get_labeled_counter_value` 入口加 `_check_labeled_counter_keys`
  - 校验失败统一抛 KeyError，错误消息含期望/实际 labelnames
- `src/intellisource/observability/health.py:63` — HealthChecker.__init__ 调用迁移传 `labelnames=["component"]`
- `tests/unit/observability/test_labeled_counter.py` — 新增 `TestLabeledCounterLabelValidation` 类 6 测试（typo / missing / extra / get typo / 错误消息内容 / 正确用法）
- `tests/unit/observability/test_labeled_gauge.py` — 新建 9 测试（idempotent / ValueError 不同 labelnames / set 错 key / get 错 key / 错误消息 / HealthChecker 集成）

**增量审查结论**（仅审 R-001 相关 diff + consistency / structure / test-quality 维度，其他维度 `[previously-approved from r1]`）：

| 维度 | 结论 | 备注 |
|-----|------|------|
| consistency | ✅ PASS | counter 和 gauge 子系统 API 完全对称（register/{set,increment}/get/iter + labelnames 必填 + `_check_*_keys` helper），R-001 不对称问题解除 |
| structure | ✅ PASS | `_check_labeled_*_keys` 抽取为私有方法，set/get/increment 入口统一调用，无重复逻辑 |
| test-quality | ✅ PASS | 校验测试覆盖 typo / missing / extra / get / 错误消息断言 + HealthChecker 集成，断言强度足 |
| convention | [previously-approved from r1] | — |
| security | [previously-approved from r1] | — |
| integration-wiring | ✅ PASS | grep `register_labeled_gauge(` 确认无遗漏生产调用点（仅 metrics.py 定义 + health.py 调用 + 测试文件） |
| error-handling | ✅ PASS | KeyError 选型与现有"未注册"分支同 exception type，调用方一次 catch 覆盖两类错误 |

**全量验证**：
- pytest: 2820 PASS / 0 FAIL / 0 skip / 0 xfail / 51 deselected（+15 vs 修订前 2805）
- mypy --strict: 148 files clean
- ruff check + format: clean

**ASSUMPTION**（implementer 报告原文，reviewer 已确认合理）：
- 校验失败统一抛 `KeyError`（与"未注册"分支同 type），调用方 catch KeyError 即覆盖注册缺失和 schema 漂移两类错误
- `labelnames=[]` 空 list 接受，语义为"无标签维度的 labeled 指标"，counter/gauge 两子系统一致

**最终 verdict**：**approved**（R-001 MEDIUM 已修，其余 LOW 按 §Approved-with-Notes 选项 1 处理：R-002/R-005 立项 backlog，R-003/R-004 归档参考）
