---
id: "review-dev-plan-intellisource-v1-s7-r3"
doc_type: review
author: reviewer
status: approved
deps: ["dev-plan-intellisource-v1-s7"]
---
# 文档审查报告 — dev-plan-intellisource-v1-s7

> **审查目标**: `docs/dev-plan/dev-plan-intellisource-v1-s7.md`
> **文档状态**: draft（审查通过后待 finalize）
> **审查轮次**: r3
> **审查日期**: 2026-05-03
> **Layer 1 结果**: PASS（exit 0，仅 1 个跨分卷 ID WARN，同 r2，不计入）
> **r2 HIGH 闭环验证**: R-003（T-060 三处不一致）— 部分闭环，见下文详情
> **r2 MEDIUM 闭环验证**: R-004（T-059 实现顺序）✓ 已闭环；R-005（T-063 路径）✓ 已闭环；R-006（T-058 阈值）✓ 已闭环
> **Layer 2**: 执行增量审查（standard 模式，聚焦修订点 + [ASSUMPTION] 合理性）

---

## r2 问题闭环确认

| 原问题 | 严重等级 | 修订状态 | 验证依据 |
|--------|---------|---------|---------|
| R-003: T-060 三处不一致（接口/模块/deliverable） | HIGH | **部分闭环，存在新残留问题** | 见 R-008 详述 |
| R-004: T-059 AC-T059-6 + 实现顺序 | MEDIUM | **已闭环** | 第 101/104 行：AC-T059-6 改为"与 T-061 共享 LLMModelsConfig，schema 形状由 T-061 定义"；新增"实现顺序"小节（三步顺序清晰） |
| R-005: T-063 路径 `tests/unit/integration/` | MEDIUM | **已闭环** | 第 207 行：已改为 `tests/integration/test_sprint7_integration.py` |
| R-006: T-058 AC-T058-4 阈值语义层次 | MEDIUM | **已闭环** | 第 73 行：改为 `min(context_window * 0.8, context_token_budget)`，括注说明两层语义及取 min 理由 |
| R-007: T-063 缺 T-061 专项集成 AC | LOW | **未修复（接受）** | 保持 LOW 余量，不阻塞 |

---

## 问题列表

### [R-008] HIGH: R-003 修订引入 API-026 与 arch 冲突 — 应为 API-017

- **category**: consistency
- **root_cause**: self-caused
- **描述**: tech-lead 将 T-060 接口字段改为 `API-026（新增；[ASSUMPTION] arch 待新增 API-026...）`，但该修订与 arch 存在两处直接矛盾：

  1. **API-026 已被 arch 标记为移除编号**: `arch-intellisource-v1-api.md` NAV 第 18 行明确写"API-001..API-025（API-010/011/026-029 工作流相关已移除，由管道配置替代）"——API-026 是已删除的工作流相关接口编号，不可重新分配给统计 API。

  2. **arch 已有 API-017 对应同一端点**: `arch-intellisource-v1-api.md` 第 434–496 行定义了 `API-017: LLM 用量统计`，路径恰为 `GET /api/v1/llm/stats`，模块声明 `M-005`，响应体含 `by_model`/`by_date`/`total_tokens`/`avg_latency_ms` 等字段——与 T-060 的 AC-T060-1~AC-T060-5 描述的统计功能高度一致。`arch-intellisource-v1-modules.md` 第 97 行也确认"M-005 对外接口: API-017（LLM 用量统计）"。

  因此，T-060 应引用 `API-017`（已存在），而非声明"新增 API-026"。[ASSUMPTION] 中"arch 待新增 API-026"的前提不成立；若沿用该 ASSUMPTION，开发者将陷入"是否要在 arch 中新建一个与 API-017 重复的接口"的歧义，且因占用了已删除编号而违背 arch 编号规范。

- **建议**: 将 T-060 接口字段改为 `API-017（arch-intellisource-v1-api.md §3 已定义，GET /api/v1/llm/stats，module: M-005）`，删除 [ASSUMPTION] 及"arch 待新增"说明。若 T-060 的 AC 覆盖范围（AC-T060-2 中的 `task_type` 维度聚合、AC-T060-4 `cached_calls`、AC-T060-5 `p95_latency_ms`）超出 API-017 当前响应体定义，应在 T-060 context_load 中注明"需在 arch API-017 响应体补充相应字段"，而非新增接口编号。

---

## 三态判定

| 严重等级 | 问题数 | 问题编号 |
|---------|--------|---------|
| CRITICAL | 0 | — |
| HIGH | 1 | R-008 |
| MEDIUM | 0 | — |
| LOW | 1 | R-007（r2 保留） |

存在 1 个 HIGH 级别问题（R-008），**verdict: needs_revision**

**修订建议**: tech-lead 对 T-060 接口字段做单点修正：
- 将 `接口: API-026（新增；[ASSUMPTION]...）` 改为 `接口: API-017（arch-intellisource-v1-api.md §3，GET /api/v1/llm/stats，module: M-005）`
- 删除关于"arch 待新增 API-026"的 [ASSUMPTION] 说明
- 若 T-060 AC 要求的响应字段（如 `task_type` 聚合、`cached_calls`、`p95_latency_ms`）不在 API-017 现有响应体中，在 T-060 context_load 或目标描述中注明"实现时需扩充 API-017 响应体，无需新增接口"

R-004/R-005/R-006 已完整闭环，R-007 为 LOW 保留，本轮仅需处理 R-008。
