---
id: "review-dev-plan-intellisource-v1-s7-r2"
doc_type: review
author: reviewer
status: approved
deps: ["dev-plan-intellisource-v1-s7"]
---
# 文档审查报告 — dev-plan-intellisource-v1-s7

> **审查目标**: `docs/dev-plan/dev-plan-intellisource-v1-s7.md`
> **文档状态**: draft（审查通过后待 finalize）
> **审查轮次**: r2
> **审查日期**: 2026-05-03
> **Layer 1 结果**: PASS（exit 0，仅 1 个跨分卷 ID WARN，不计入）
> **r1 HIGH 闭环验证**: R-001（[NAV] 块）✓ 已补充；R-002（split_from）✓ 已补充
> **Layer 2**: 执行（standard 模式，dev-plan 不在 DOC_REVIEW_L2_SKIP_DOC_TYPES 白名单）

---

## r1 HIGH 问题闭环确认

| 原问题 | 修订状态 | 验证依据 |
|--------|---------|---------|
| R-001: 缺少 [NAV] 块 | **已闭环** | 文件第 20-31 行包含完整 [NAV] 块，列举 T-057~T-063 |
| R-002: 缺少 split_from 字段 | **已闭环** | front matter 第 9 行：`split_from: dev-plan-intellisource-v1` |

---

## 问题列表

### [R-003] HIGH: T-060 接口声明与 arch 定义三处不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: T-060 任务卡在以下三个维度与 arch 文档存在不一致，开发者无法确定正确实现路径：
  1. **接口引用**：任务卡写 `接口: API-019 增强`，但 arch API-019（`arch-intellisource-v1-api.md` 第 507 行）定义的是 `GET /api/v1/metrics`、Prometheus 文本格式、归属 M-010；T-060 AC 要求的是 JSON 格式聚合统计，与 Prometheus text 完全不同的响应体。
  2. **模块声明**：任务卡写 `模块: M-011, M-010`，但 arch M-005 模块定义（`arch-intellisource-v1-modules.md` 第 106 行）明确写"LLMStatsAggregator 供 API-019 增强端点使用"，聚合逻辑归属 M-005，M-010 是可观测性基础设施，不包含 LLM 统计聚合业务逻辑。
  3. **deliverable 路径**：任务卡声明 `src/intellisource/api/routers/system.py`（URL `/api/v1/system/llm-stats`），但项目中已存在 `src/intellisource/api/routers/llm.py` 的 stub 实现（URL `/api/v1/llm/stats`，通过 `main.py` 挂载），两者路径冲突。
- **建议**: 明确以下三点并统一任务卡：（1）将接口引用改为"新增 API-019b" 或重命名为 `API-026 LLM 统计仪表盘`，与 arch API-019（Prometheus）区隔；（2）模块改为 `M-005, M-011`（聚合逻辑在 M-005，路由注册在 M-011）；（3）deliverable 路径统一改为 `src/intellisource/api/routers/llm.py`，保留已有 stub，URL 使用已确立的 `/api/v1/llm/stats`。

---

### [R-004] MEDIUM: T-059 AC-T059-6 引用 T-061 输出，形成实现顺序自锁

- **category**: consistency
- **root_cause**: self-caused
- **描述**: T-059 AC-T059-6 要求"合并结果通过 Pydantic model 验证（复用 T-061 的 LLMModelsConfig）"，但 T-061 的依赖声明是 `T-059（ConfigResolver 集成）`。在实现顺序上：执行 T-059 时 T-061 的 `LLMModelsConfig` 尚未产出，AC-T059-6 无法通过；执行 T-061 时需要 T-059 的 `ConfigResolver` 已存在。文档层面的自引用导致开发者需猜测实现顺序：先实现 T-059（跳过 AC-T059-6）→ 再实现 T-061 → 回头补 AC-T059-6，但这个三步顺序未在任务卡中说明。
- **建议**: 在 T-059 的"依赖"字段中明确添加 `T-061（LLMModelsConfig 定义，需先完成 T-061 Pydantic 模型定义部分）`，或将 AC-T059-6 的措辞改为"合并结果通过 Pydantic 验证，验证模型与 T-061 的 LLMModelsConfig 共享实现"，并在 T-059 实现提示中说明先完成 T-061 Schema 定义部分。

---

### [R-005] MEDIUM: T-063 deliverable 路径 `tests/unit/integration/` 与项目目录结构不符

- **category**: convention
- **root_cause**: self-caused
- **描述**: T-063 deliverables 写 `tests/unit/integration/test_sprint7_integration.py`，但项目测试目录结构中 `tests/unit/` 和 `tests/integration/` 是平级的两个顶层子目录（`tests/unit/` 含 collector/config/agent 等单测，`tests/integration/` 用于集成测试），不存在 `tests/unit/integration/` 路径。将集成测试放入 `tests/unit/` 下也与语义不符。
- **建议**: 将路径改为 `tests/integration/test_sprint7_integration.py`，与项目现有目录约定一致。

---

### [R-006] MEDIUM: T-058 触发阈值（AC-T058-4）与 arch §5.1 配置参数语义层次不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: arch §5.1 在 `settings.example.toml [chat]` 段定义了 `context_token_budget=2000`（上下文注入 LLM 的最大 token 预算），T-058 AC-T058-4 却使用 `estimated tokens > context_window * 0.8` 作为触发阈值（`context_window` 是模型级全局窗口，如 128000）。两者属于不同层次：`context_token_budget` 是系统对话配置层的上限（小值，控制注入 LLM 的 token 数），`context_window * 0.8` 是模型容量层的阈值（大值）。任务卡未说明 T-058 是否废弃 `context_token_budget` 参数，或两者如何配合生效。
- **建议**: 在 T-058 描述或 context_load 中补充说明新触发策略与 arch §5.1 `[chat].context_token_budget` 的关系：（1）若 `context_window * 0.8` 取代 `context_token_budget`，需在 T-059 配置层或本任务说明废弃迁移路径；（2）若两者并存，需说明优先级（如：先检查 `context_token_budget`，再检查 `context_window * 0.8`）。

---

### [R-007] LOW: T-063 缺少 T-061（Pydantic Schema 验证）的专项集成回归 AC

- **category**: completeness
- **root_cause**: self-caused
- **描述**: T-063 的 6 条 AC 分别覆盖了 T-057（AC-T063-1）、T-059（AC-T063-2）、T-062+T-053（AC-T063-3）、T-058（AC-T063-4）、全量测试（AC-T063-5/6），但没有专项 AC 覆盖 T-061 的 `LLMModelsConfig` Pydantic 验证在实际配置加载流程中是否正确触发（如使用无效配置文件时是否抛出带字段定位的 `ValidationError`）。T-060（LLM 统计 API 端到端）同样无专项 AC。全量 pytest（AC-T063-5）可部分兜底，但集成测试文件的有针对性覆盖更有利于回归定位。
- **建议**: 在 T-063 中补充：`AC-T063-7: 无效 llm_models.yaml 配置加载时抛出含字段定位信息的 ValidationError（T-061 集成验证）`。T-060 的端到端可通过 AC-T063-5 全量 pytest 兜底，不强制补 AC。

---

## 三态判定

| 严重等级 | 问题数 | 问题编号 |
|---------|--------|---------|
| CRITICAL | 0 | — |
| HIGH | 1 | R-003 |
| MEDIUM | 3 | R-004, R-005, R-006 |
| LOW | 1 | R-007 |

存在 1 个 HIGH 级别问题（R-003），**verdict: needs_revision**

**修订建议**: tech-lead 对 T-060 任务卡进行以下修订（均为单点改动）：
1. 将 `接口: API-019 增强` 改为明确的新接口编号（如 `API-026`）或添加注释说明与 Prometheus API-019 的区别
2. 将 `模块: M-011, M-010` 改为 `M-005, M-011`
3. 将 deliverable `src/intellisource/api/routers/system.py` 改为 `src/intellisource/api/routers/llm.py`，URL 改为 `/api/v1/llm/stats`

R-004/R-005/R-006 为 MEDIUM 级别改善建议，tech-lead 可在修订 R-003 时一并处理，也可在本 Sprint 执行中按需澄清，不强制阻塞。
