---
id: "code-review-T-099-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-099"]
---

# CODE-REVIEW T-099 r1

**任务范围**: T-099 [light] — Pipelines API + System 可观测性 + ConfigVersion
**提交**: df2c939 (PR #51)
**审查模式**: light + security_sensitive=false; 8 AC > CODE_REVIEW_L2_SKIP_LIGHT_MAX_AC=2 → Layer 2 强制运行 (无短路)
**Reviewer**: orchestrator inline (sprint-9 truncation 4/4 后续延续 inline 模式)

## Layer 1 结果

`cataforge skill run code-review` exit 0；ruff + ruff format + mypy --strict clean (123 src files)；全量 pytest 2489 PASS / 43 SKIP / 0 FAIL（含 14 个 T-099 新测试）。

## Layer 2 结果

按 COMMON-RULES §统一问题分类体系审查 4 个 src 文件 + 3 个新测试文件。

## Verdict: needs_revision

存在 1 个 HIGH 安全问题（路径遍历）→ 三态判定为 **needs_revision**。

---

## 问题列表

### [R-001] HIGH: pipelines router `name` 路径参数未做路径遍历防御
- **category**: security
- **root_cause**: self-caused
- **描述**: `src/intellisource/api/routers/pipelines.py:74-79` 与 `:86-90` 的 `get_pipeline` / `run_pipeline` 直接拼路径：
  ```python
  path = _PIPELINES_DIR / f"{name}.yaml"
  if not path.is_file():
      raise HTTPException(status_code=404, ...)
  ```
  攻击者发 `GET /api/v1/pipelines/..%2fsources%2fexample` → `name="../sources/example"` → `path = _PIPELINES_DIR / "../sources/example.yaml"` → 解析为 `config/sources/example.yaml`，`path.is_file()` 为真 → 暴露 sources 目录或其他配置文件的 YAML 内容（含潜在 secret/URL）。同时 run_pipeline 端点会以攻击者控制的字符串作为 `pipeline_name` 投递给 Celery `run_pipeline` 任务，构成进一步入口。
- **建议**: 校验 resolved path 仍在 `_PIPELINES_DIR` 内：
  ```python
  resolved = path.resolve()
  if not resolved.is_relative_to(_PIPELINES_DIR.resolve()) or not resolved.is_file():
      raise HTTPException(status_code=404, detail=...)
  ```
  并对 `name` 增白名单（如 `^[a-z0-9_-]+$`）拒绝 `/` / `.` / 中文等字符。两端点 (get + run) 共用同一防御。

### [R-002] MEDIUM: `_PIPELINES_DIR` 5-level `.parent` 链脆弱
- **category**: structure
- **root_cause**: self-caused
- **描述**: `pipelines.py:18-20` `Path(__file__).parent.parent.parent.parent.parent / "config" / "pipelines"` — 5 层 parent 调用对包结构高度敏感，重新打包/部署/移到 src layout 不同位置时计算结果错。`agent/tools.py:_PIPELINES_DIR` 已经定义同一目录但未复用。
- **建议**: 从 `intellisource.agent.tools` 重新导出 `_PIPELINES_DIR`（或新建 `intellisource.config.paths` 模块作为单一事实来源），pipelines router 与其他模块共用。

### [R-003] MEDIUM: `celery_app.control.ping(timeout=0.5)` 在 async 健康检查中是同步阻塞
- **category**: performance
- **root_cause**: self-caused
- **描述**: `composition._install_observability_state._check_celery`：
  ```python
  replies = celery_app.control.ping(timeout=0.5)
  ```
  Celery `control.ping` 是同步阻塞调用（使用 kombu broker，不是 asyncio-aware）。在 async health check 中调用会阻塞事件循环最长 500ms，影响并发 health 端点的延迟。
- **建议**: 用 `asyncio.to_thread`：
  ```python
  replies = await asyncio.to_thread(celery_app.control.ping, timeout=0.5)
  ```
  保持 event loop 不被阻塞。

### [R-004] MEDIUM: /health endpoint 未 catch `checker.check_health()` 异常
- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `api/routers/system.py:health` 函数体内 `result = await checker.check_health()` 无 try/except。HealthChecker.check_health 内部确实捕获了每个 check_fn 的异常并返回 healthy/unhealthy，但若 checker 自身（或 dataclass 解析 + isoformat）出错，端点会返回 500 — 反而是 /health 自己变得不健康。
- **建议**: 加包裹：
  ```python
  try:
      result = await checker.check_health()
  except Exception:
      logger.exception("health_checker raised")
      return {"status": "unhealthy", "checks": {"meta": "checker_failed"}}
  ```
  健康端点必须永不抛 — 这是观测性核心契约。

### [R-005] LOW: `system._format_prometheus` 读 MetricsCollector 私有 attr
- **category**: convention
- **root_cause**: self-caused
- **描述**: `_format_prometheus` 通过 `getattr(metrics_collector, "_counters", {})` 等访问以下划线前缀的字段：`_counters / _counter_descriptions / _gauges / _gauge_descriptions / _histograms / _histogram_descriptions`。这是封装边界泄漏；MetricsCollector 内部数据结构变更会静默破坏 prom 渲染。
- **建议**: 在 `observability/metrics.py:MetricsCollector` 增 `def to_prometheus_text(self) -> str:` 公共方法，或暴露 `iter_counters() / iter_gauges() / iter_histograms()` 视图。`_format_prometheus` 改调公共 API。

### [R-006] LOW: `list_pipelines` yaml.YAMLError 静默 swallow
- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `pipelines.py:51-53`:
  ```python
  try:
      raw = yaml.safe_load(path.read_text()) or {}
  except yaml.YAMLError:
      continue
  ```
  损坏的 pipeline YAML 会被静默跳过，运维端无可见信号。
- **建议**: `logger.warning("Skipping malformed pipeline YAML: %s", path)` 或 raise → 让 list 端点对部分破坏快速可见。

---

## 严重等级聚合

| 等级 | 计数 | finding IDs |
|------|------|-------------|
| CRITICAL | 0 | — |
| HIGH | 1 | R-001 |
| MEDIUM | 3 | R-002, R-003, R-004 |
| LOW | 2 | R-005, R-006 |

## REFACTOR 触发判定

TDD_REFACTOR_TRIGGER `[complexity, duplication, coupling]`：
- complexity: 各函数 ≤15 行，无超阈值
- duplication: R-002 命中（_PIPELINES_DIR 重复定义），但属于 structure 而非典型代码重复
- coupling: 无新增模块循环

不触发独立 REFACTOR；R-002 在 r2 顺手合并即可。

## 修订路径建议

r2 必修: R-001 (HIGH path traversal)
r2 一并修: R-002 + R-003 + R-004 + R-005 + R-006（均为单点修改，合并入 r2 经济性高）
