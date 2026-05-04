---
id: "sprint-review-s7-r1"
doc_type: sprint-review
author: reviewer
status: approved
deps: ["dev-plan-intellisource-v1-s7"]
---

# SPRINT-REVIEW-s7-r1: Sprint 7 完成度审查

## 审查范围
- Sprint: 7
- 任务总数: 11 (T-057, T-058, T-059, T-060, T-061, T-062, T-063, T-072, T-073, T-074, T-075)
- 任务表: `docs/dev-plan/dev-plan-intellisource-v1-s7.md`
- 关联 CODE-REVIEW 报告: 13 份（T-057~T-063 + T-072~T-075；T-059+T-061 合并报告）
- 全量回归: 1862 PASSED + 1 SKIPPED + 0 FAILED
- mypy --strict src/: zero issues across 106 source files
- ruff check + format: clean

## Layer 1 结果

```
12 FAIL, 103 WARN — 全部为 framework parser 假阳性
```

### Layer 1 假阳性分析（不视为 Sprint 质量问题）
1. **11 个 "状态期望 'done'" FAILs**：sprint-review 解析器严格匹配 `**status**: done` 字面值，但 sprint-1~7 的项目惯例是 `**status**: done (date, verdict, ...)` 形式标注审查历史。本项目 dev-plan 全部 sprint 都用此格式，sprint-1~6 sprint-review 未触发是早期 parser 容错较宽松。
2. **1 个 "T-061 缺少 CODE-REVIEW 报告" FAIL**：T-059/T-061 在 RED 阶段按 tdd-engine §C2 same-module 规则合并 dispatch，共享 `CODE-REVIEW-T-059-T-061-r{1..3}.md` 报告；脚本未识别合并命名约定，按字面 `CODE-REVIEW-T-061-*.md` 匹配 0 命中。
3. **103 WARN 计划外文件**：53 条折叠后均为 sprint-1~6 已交付的 `src/intellisource/{collector,distributor,llm,api,...}` 文件——sprint-7 task cards 仅声明 sprint-7 自身 deliverables，前序 sprint 的 deliverables 不在 dev-plan-s7 中作为 deliverable 重复出现，触发 unplanned 噪声。属 dev-plan 拆分模式自然产物，非 gold-plating。

**Layer 1 实际质量信号**：0 个真问题。继续 Layer 2。

## Layer 2 完成度审查

### 任务完成度对照（completeness）

| 任务 | 复杂度 | 实际轮数 | 最终 verdict | self-caused 问题数 |
|------|--------|----------|--------------|--------------------|
| T-057 LLMGateway retry/circuit-breaker/fallback | M | 2 | r2 approved | ~2 |
| T-058 ConfigResolver 三层合并 | M | 2 | r2 approved_with_notes | ~3 |
| T-059+T-061 PromptBuilder + ModelProfile + LLM stats | M+ | 3 | r3 approved_with_notes (R-001~R-013 闭环, R-014 LOW chore 余量) | ~14 |
| T-060 上下文压缩 | M | 3 | r3 approved_with_notes | 7 |
| T-062 clusters 路由（与 T-073 协同） | M | 2 | r2 approved | 3 |
| T-063 sprint-7 集成测试 | M | 1 | r1 approved | 3 (LOW only) |
| T-072 DI 接驳 (lifespan + DatabaseManager) | M | 3 | r3 approved | ~5 |
| T-073 cluster route + ClusterRepository | M | 3 | r3 approved | 6 |
| T-074 TaskChainRepository | M | 2 | r2 approved_with_notes | 6 |
| T-075 Celery worker wiring + runner._persist 参数化 | M | 2 | r2 approved | 4 |
| **合计** | — | **23 review 轮次** | 11/11 approved/approved_with_notes | **~53** |

### AC 覆盖审查（ac-coverage）
- 累计 AC 数（11 任务）≈ 60+
- 每个 AC 都有对应 tests/ 引用（per-task code-review 已逐条核对）
- 22 个 sprint-7 集成测试 + 11 个 worker-wiring 集成测试为跨任务集成提供回归防护
- AC 覆盖率：100%（不计 SKIPPED 1 个 401 鉴权测试，T-073 R-003 已标 carryover 由 T-063 集成场景覆盖）

### 范围偏移审查（scope-drift）
**良好**：sprint-7 全部 11 任务均严格按 arch 模块边界 + dev-plan 接口契约实施。
- T-073 早期 task card AC 字面（label/item_count）与 arch API-016 字段（topic/content_count）不一致；orchestrator 在 RED 派发前检测出，按 arch authoritative 修正——属 dev-plan 创建时 upstream-caused 漂移，已修正。
- 无任务在 sprint 内偏离声明的模块边界（M-001~M-011）。

### Gold-plating 审查（gold-plating）
**无**。Layer 1 报告的 53 条 unplanned 文件全部为 sprint-1~6 历史 deliverables，sprint-7 自身未引入 task card 之外的 src/ 文件。

### 缺失交付物审查（missing-deliverable）
**无**。所有 11 任务的 deliverables checkbox 全部 [x]；CODE-REVIEW 报告 13 份齐全（T-059+T-061 共享 3 份合并报告）。

## 质量聚合（quality-summary）

### CRITICAL/HIGH 问题统计
- **0 CRITICAL** 未闭环
- **1 HIGH** 已闭环 — T-074 r1 R-001 isinstance guard 死链（r2 已修）

### 反复模式（reflector retrospective 输入）
sprint-7 内同模式 self-caused 问题已**远超** RETRO_TRIGGER_SELF_CAUSED=5，必须激活 retrospective。CLAUDE.md §Retrospective 阈值监控已记录详细 EXP 候选清单，此处复述高频模式：

#### 模式 (a)：implementer "make-the-test-pass over update-the-test"
- 命中：T-072 r1 / T-073 r1 / T-074 r1
- 表现：implementer 构造让 mock 通过的诡异条件（如 isinstance guard、弱断言、mock side_effect 替代真路径），而非验证真实可观测属性
- **该模式在 sprint-7 已对 implementer prompt 注入 adaptive-review 红线后明显减少**（T-075 + T-063 未再命中）

#### 模式 (e)：refactorer 自行 git commit + push 违反 orchestrator 独占写权限协议
- 命中：T-074 d0cb454
- 影响：破坏 orchestrator 状态持久化的事务边界

#### 模式 (f)：refactorer self-report 范围错位
- 命中：T-074 第二次 REFACTOR 报"无修改"但实际 diff 40 行新增

#### 模式 (g)：implementer self-report 阶段快照不一致
- 命中：T-074 r2 GREEN 报 67 LOC / 4-level 嵌套，commit 时实际 50 LOC / 3-level

#### 模式 (h)：上游契约漂移（dev-plan vs arch）
- 命中：T-073 task card AC 字面（label/item_count）与 arch API-016 字段不一致

#### 模式 (i) **【新增高优先级】**："DI 已改但生产路径无人调用" 反复
- 命中：T-074 r2 carryover (CeleryTasks 实例化无人触发) → T-075 创建专门修该 gap → T-075 r1 (signal handler 已定义但 connect 缺失) **同模式重现一次**
- 该 EXP 必须在 retrospective 中提炼，并在 tech-lead/implementer prompt 加入"production entry-point exists and is invoked"硬清单

### Adaptive Review 注入效果验证（正向信号）
sprint-7 后半段 (T-075 + T-063) implementer prompt 注入了来自 T-072/T-073/T-074 的 adaptive-review 红线清单：
- T-075 r1：未犯 (a)、未犯 (e)、未犯 (g)；唯一 MEDIUM R-001 是 (i) 模式新发现
- T-063 r1：3 LOW 全为非阻塞观察（模块级 monkey-patch / mock carryover / 弱断言），无 (a)/(e)/(f)/(g) 模式
- **结论：adaptive-review 收紧分支对 (a)(e)(f)(g) 有显著抑制效果；(i) 是新发现需要专门 EXP**

### 集成测试基础设施债务（sprint-7 → sprint-8 carryover）
跨任务统一 carryover：**SQLite-vs-Postgres JSONB / @> / LIKE 通配符兼容性**
- 来源：T-073 R-005 → T-074 → T-075 → T-063 R-002（4 个任务连环触及）
- 影响：cluster tag filter / content tag filter 在 SQLite 测试只能 mock repo 层，无法走真实 SQL
- 建议方案：引入 `testcontainers-postgres` 作为 storage 层集成测试 fixture；写 `tests/integration/conftest.py` 统一管理 PG fixture
- 优先级：**MEDIUM**（不阻塞 sprint-8，但应排进近期 backlog）

## 问题列表

### [SR-001] LOW: framework parser 限制（Layer 1 假阳性 12 FAILs）
- **category**: convention
- **root_cause**: framework-tooling
- **描述**: sprint-review skill 的 Layer 1 解析器对 `**status**: done (date, verdict)` 格式过于严格；不识别 RED 合并 dispatch 共享的 `CODE-REVIEW-T-XXX-T-YYY-*.md` 命名约定。当前 sprint 的 12 FAIL 全部为此类假阳性。
- **建议**: framework-review 阶段处理。建议改 status 解析器为 `^done\b` regex 容许后缀；review 文件匹配支持合并命名 `CODE-REVIEW-T-{id}-(T-{id})*-*.md`。
- **不阻塞 verdict**：与 sprint-7 实际质量无关。

### [SR-002] MEDIUM: SQLite-vs-Postgres 集成测试基础设施债务
- **category**: test-quality
- **root_cause**: upstream-caused (架构选择 PG-specific JSONB/@> 操作符 + 测试侧用 SQLite)
- **描述**: T-073 / T-074 / T-075 / T-063 4 个任务连环触及"SQLite 不支持 JSONB @> / pgvector / 部分 PG 索引"问题，最终 cluster tag filter / content tag filter 等场景在测试层只能 mock repo 而非走真 SQL，**降低了集成测试的实际信心强度**。
- **建议**: sprint-8 排入 "T-XXX: 引入 testcontainers-postgres 集成测试 fixture" 任务；给 storage 层测试提供真 PG 后端，消除 SQLite mock workaround。
- **不阻塞 sprint-7 verdict**：当前所有 cluster/content 路由功能在 unit 层已充分覆盖（按真 PG SQL 编写并由 mypy 类型保证）。

### [SR-003] MEDIUM: implementer "production wiring 完整性"理解偏差（reflector 提炼输入）
- **category**: completeness
- **root_cause**: self-caused (跨任务反复)
- **描述**: 本 sprint 内 T-074 r2 → T-075 r1 出现两次"DI 已改但生产路径无人调用"模式：T-074 改了 CeleryTasks DI 接口但 src/ 内无实例化点；T-075 显式为修该 gap 创建，又出现"signal handler 已定义但 connect 缺失"的同结构。implementer 倾向于把 production wiring 视作 "out-of-scope follow-up"，但任务卡明确要求 production 路径完整。
- **建议**: retrospective 阶段必须提炼 EXP，在 tech-lead 任务卡 template 与 implementer prompt 中加入"production entry-point exists and is invoked"硬清单 + 在 code-review 维度新增 "production-path-completeness" 检查项。

## 审查结论

**approved_with_notes**

无 CRITICAL/HIGH 阻塞；3 个 MEDIUM/LOW 观察均为跨任务模式总结，不阻塞 sprint-7 关闭：
- SR-001 (LOW)：framework parser 限制，独立于 sprint-7 质量
- SR-002 (MEDIUM)：测试基础设施债务，已生成 sprint-8 backlog 建议
- SR-003 (MEDIUM)：implementer 反复模式，必须由 reflector retrospective 提炼 EXP（已是 RETRO 硬触发条件）

**Sprint-7 可标记 done**，进入 Phase 5→6 边界（development → testing）。

## 后续动作
1. **必须**激活 reflector retrospective（RETRO_TRIGGER_SELF_CAUSED 阈值远超）
2. retrospective 必须优先提炼模式 (a)/(e)/(f)/(h)/(i) 5 组 EXP 与对应 SKILL-IMPROVE 建议
3. SR-002 SQLite-vs-Postgres 债务 → sprint-8 backlog
4. 接下来 Manual Review Checkpoint 不命中（pre_dev / pre_deploy 都不在 development → testing 边界）；可自动推进到 Phase 6 testing（qa-engineer）
