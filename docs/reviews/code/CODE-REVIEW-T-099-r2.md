---
id: "code-review-T-099-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-099"]
---

# CODE-REVIEW T-099 r2

**任务范围**: T-099 [light] — Pipelines API + System 可观测性 + ConfigVersion
**提交**: bd5e87c (PR #51) — fixes on top of r1 baseline df2c939
**审查模式**: light + security_sensitive=false; Layer 2 强制运行
**Reviewer**: orchestrator inline (与 r1 / T-098 r2 同源协议)
**前置**: CODE-REVIEW-T-099-r1.md verdict=needs_revision (1 HIGH + 3 MEDIUM + 2 LOW)

## Layer 1 结果

`cataforge skill run code-review` exit 0；ruff + ruff format + mypy --strict clean (123 src files)；全量 pytest 2497 PASS / 43 SKIP / 0 FAIL（vs r1 baseline 2489，+8 反证测试）。

## Verdict: approved

6 个 r1 findings 全部修复 + 8 反证测试新增。无新引入 CRITICAL/HIGH 问题。

## R1 → R2 逐项验收

### HIGH (1/1 修复)

#### R-001 — Path traversal 防御
- **修复路径**: `pipelines.py` 新建 `_resolve_pipeline_path(name)` 集中防御：
  1. `_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")` 白名单（拒绝 `/` / `.` / 空格 / 中文 / URL-encoded 前缀字符）
  2. `candidate = (_PIPELINES_DIR / f"{name}.yaml").resolve()`
  3. `if not candidate.is_file() or not str(candidate).startswith(str(pipelines_root) + "/")` 双重校验
  4. 404 与 file-not-found 同响应文案，不泄漏目录探测信号
- **反证测试**: `tests/unit/api/test_pipelines_router.py:TestPathTraversalGuard` 7 个：
  - 6 个 parametrized 攻击名（`../sources/something` / URL-encoded / `.hidden` / 空格 / 斜杠 / 中文）→ 404
  - `test_run_pipeline_rejects_path_traversal_name` 额外断言 `celery_app.send_task.call_args is None`（确认未被攻击者控制名触发 Celery 投递）

### MEDIUM (3/3 修复)

#### R-002 — `_PIPELINES_DIR` 双源
- **修复**: `pipelines.py` 改 `from intellisource.agent.tools import _PIPELINES_DIR as _SHARED_PIPELINES_DIR`，赋值给本模块 `_PIPELINES_DIR: Path = _SHARED_PIPELINES_DIR` 别名兼容。单一定义点在 `agent/tools.py:_PIPELINES_DIR = Path(__file__).resolve().parents[3] / "config" / "pipelines"`。

#### R-003 — Celery ping 阻塞事件循环
- **修复**: `composition._check_celery`：
  ```python
  replies = await _asyncio.to_thread(celery_app.control.ping, timeout=0.5)
  ```
  Celery sync 调用迁到 worker thread，event loop 不再阻塞最长 500ms。

#### R-004 — /health 未 catch checker 异常
- **修复**: `api/routers/system.health` 加：
  ```python
  try:
      result = await checker.check_health()
  except Exception:
      logger.exception("health_checker raised")
      return {"status": "unhealthy", "checks": {"meta": "checker_failed"}}
  ```
  观测端点永不 raise；运维侧通过 status=unhealthy + meta=checker_failed 标识。
- **反证测试**: `test_system_health_real.py::test_health_endpoint_swallows_checker_exception` — checker 抛 RuntimeError 时端点仍 200 返回降级 payload。

### LOW (2/2 修复)

#### R-005 — MetricsCollector 封装边界泄漏
- **修复**:
  1. `observability/metrics.py` 增 `iter_counters() / iter_gauges() / iter_histograms()` 公共方法，返回 `[(name, description, value)...]` 三元组列表。
  2. `system._format_prometheus` 调公共 API，不再读 `_counters / _counter_descriptions / ...` 等下划线前缀字段。
- **未引入回归**: 现有 4 个 MetricsCollector 相关测试 + 3 个 _format_prometheus 路径测试全部通过。

#### R-006 — yaml.YAMLError silent swallow
- **修复**: `list_pipelines` 增 `logger.warning("Skipping malformed pipeline YAML: %s", path)` + 非-mapping root 也 warn。可观测性提升。

## 新增反证测试统计

| 类别 | 数量 | 文件 |
|------|------|------|
| Path traversal | 7 | tests/unit/api/test_pipelines_router.py |
| health checker 异常降级 | 1 | tests/integration/test_system_health_real.py |
| **合计** | **8** | — |

## REFACTOR 触发判定

TDD_REFACTOR_TRIGGER `[complexity, duplication, coupling]`：
- complexity: `_resolve_pipeline_path` 圈复杂度 3，所有函数 ≤15 行
- duplication: R-002 在 r2 已合并修复（_PIPELINES_DIR 单一来源）
- coupling: 无新增循环；MetricsCollector 公共 API 暴露反而 *降低* 封装耦合

不需独立 REFACTOR 阶段。

## 跨任务观察

- **EXP-005 装配缺口**：T-099 引入 `config_version_manager` + `health_checker` + `metrics_collector` 3 新 app.state 状态项，全部在 `_install_observability_state` 统一装配；附带 `TestCompositionInstallsObservabilityState` 反证测试 + main lifespan `_config_version_manager` 全局变量注入。复用 T-098 r2 的装配缺口防御模式，零新 silent-gap。
- **EXP-006 truncation**：T-099 light mode + orchestrator inline 实施，零 truncation。sprint-9 累计仍是 4/4，未恶化。
- **arch API-013 余项**：T-098 r2 已完成 amendment，T-099 grep 验证 schema + router + arch 三处一致，无后续工作。

## 结论

T-099 r2 全部 6 findings 闭环 + 8 反证测试。verdict=approved，无 r3 需要。

**下一步**: T-099 status=approved；继续 sprint-9 批次 3 → T-100 [light] (Celery Beat 同步 + push-optimize 触发 + ChatSession DB)。批次 2 全部 5 任务 (T-095/T-096/T-097/T-098/T-099) 已闭环。
