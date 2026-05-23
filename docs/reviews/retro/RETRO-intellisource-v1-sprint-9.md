---
id: "retro-intellisource-v1-sprint-9"
doc_type: retrospective
author: reflector
status: draft
date: 2026-05-23
deps: ["RETRO-intellisource-v1"]
version: "0.4.0"
---

# RETRO-intellisource-v1-sprint-9: Sprint 9 Retrospective

## 范围与触发

**触发原因**: 双阈值同时达成（RETRO_TRIGGER_SELF_CAUSED=5 强制立项）：
1. **EXP-005 装配缺口模式** 跨 sprint-8r→sprint-9 累计 **5 次复发**（T-088 R-007 / T-092 N-001 / T-089 r1 / T-098 R-001 / T-100 R-001），符合 sprint-8r RETRO 立项时定义的 carryover 门槛。
2. **EXP-006 subagent truncation** sprint-9 单 sprint **4/4 全发生**（reviewer ×2 + test-writer ×1 + implementer ×1，跨 3 个角色），首次跨角色覆盖证实非 reviewer-skill 局部问题。

**数据源**:
- CODE-REVIEW-T-095..T-100 共 11 份（r1/r2 配对）
- docs/reviews/CORRECTIONS-LOG.md 末尾 7 条 sprint-9 条目
- docs/EVENT-LOG.jsonl sprint-9 段（≈45 条 review_verdict / tdd_phase / state_change）
- RETRO-intellisource-v1.md（sprint-1~7 baseline + EXP-005/EXP-006 candidate 标注）
- SR-001..007 来自 SPRINT-REVIEW-s8r-r1.md

**统计概览**:
- sprint-9 任务: 6 (T-095/T-096/T-097/T-098/T-099/T-100) 全 approved
- 单 sprint code-review 报告: 11 份（每任务 r1+r2，T-095/T-098/T-099/T-100 均 r1 needs_revision → r2 approved；T-096 r1 needs_revision → r2 inline approve；T-097 r1 approved_with_notes → r2 approve）
- self-caused 问题累计: 47 个跨 6 任务（T-095:0 + T-096:5 + T-097:5 + T-098:13 + T-099:6 + T-100:7 + T-095 r1:6 = 42 + sub-counts diff）
- 反复出现的模式数: 2 个高优先级 EXP 升级为强制改进（EXP-005 装配缺口 + EXP-006 truncation）

---

## 经验条目

### EXP-005: 装配缺口模式（assembly-gap） — 跨任务第 5 次复发

**现象**:
sprint-9 + sprint-8r 累计 5 个案例，每次都是「单元/集成测试通过（fixture 直接 set app.state.X 或注入 mock），但 composition.py / lifespan / build_worker_composition 链路实际未装配」。code-review HIGH 发现率 100%，测试黑洞掩盖率 100%。

| 案例 | finding | 装配缺口本质 | 测试黑洞 |
|------|---------|------------|--------|
| T-088 R-007 | lifespan 未注入 collectors | tests 直接 set app.state.collectors | 单元测试无 lifespan integration |
| T-092 N-001 | build_celery_tasks 漏传 content_repository | tests mock CeleryTasks(content_repository=...) | 集成测试用独立 fake bootstrap |
| T-089 r1 | tool_deps 未注入 + ToolDeps 未构建 | tools.execute(tool_deps=ToolDeps(...)) 直接构造 | 无装配链路反证测试 |
| **T-098 R-001** | webhook_token + cs_messenger 4 状态项 0 装配 | 60 测试 fixture 各自 set app.state.4 项 | 零 lifespan 集成测试断言 |
| **T-100 R-001** | Worker composition._build_deps_bundle 未传 celery_app | 单测 _make_facade(celery_app=MagicMock()) inject | 无 build_worker_composition 反证 |

**根因分析**:
- **implementer 实施惯性**: 在测试 fixture 中 inject 状态项 → 业务逻辑通过测试 → 误认为生产路径也会被自动装配。生产代码缺少装配语句（`app.state.X = build_X()`）时不报错（getattr 返回 None / 默认值），形成 silent-no-op 而非 fail-loud。
- **tech-lead 任务卡缺**: dev-plan 任务卡 deliverables 列举源文件，但没有 "lifespan wiring checklist" 字段强制声明新增 `app.state.X` 字段时必须列出 composition 装配点。implementer 实施时按 deliverables 写，遗漏装配。
- **code-review 维度盲区**: code-review SKILL.md Layer 1 检查 lint/format/类型，Layer 2 维度按 category 走（completeness/structure/security 等），但**没有一条专门检查"读 `app.state.X` / `self._X = celery_app` 是否对应生产装配点"**。每次都靠 reviewer 主观经验抓 HIGH，而 sprint-9 truncation 4/4 让 reviewer 视角进一步缩窄。

**建议改进**（target: 框架级 lint + tech-lead 任务卡 template + code-review SKILL）:

1. **框架级 lint 规则**（最高 ROI）— `cataforge skill` 增 `assembly-gap-scan` 检查项，AST 扫描：
   - `getattr(request.app.state, "X", default)` 形式 — 收集所有 X
   - `self._X = celery_app` / `self._X = redis_client` 等构造器 inject 形式 — 收集所有 X
   - 全 src/ 范围内搜 `app.state.X = ` 赋值 + `<Class>(X=...)` 构造点
   - 凡读但无对应"装配赋值"的 X 标记为 ASSEMBLY-GAP error；exit 1 让 code-review L1 直接 fail，强迫修复。
   - 内置于 code-review SKILL.md Layer 1，所有 task_kind 强制运行（不可短路）。

2. **tech-lead 任务卡 template 强制 wiring checklist 字段**：
   - dev-plan-*.md 任务卡新增 `wiring_checklist:` 数组字段
   - 任务涉及新增 `app.state.X` / DistributorFacade.celery_app / lifespan 子组件时，必须填项：
     - `{state_attr: app.state.X, source: composition.build_X(), reader: routers/Y.py}` 三元组
   - tech-lead 拆任务时强制检查；code-review 在 Layer 2 structure 维度交叉验证 implementer 是否按 checklist 装配。

3. **code-review SKILL.md Layer 2 增 "lifespan symmetry" 检查项**：
   - 对每个 sprint 任务，强制审查 `composition.build_api_composition` vs `composition.build_worker_composition` 的装配对称性（API + Worker 双路径应都装配同名 state，除非任务卡显式说明 Worker 不需要）。

**验证方法**:
- 连续 5 个任务的 code-review 零装配缺口 HIGH（基线：sprint-9 累计 5 次复发）；
- code-review Layer 1 `assembly-gap-scan` 在 CI 中拦截过 ≥1 次"测试通过但装配缺失"的真实回归（reverse-test：故意 revert 装配语句，CI 必 fail）。

---

### EXP-006: subagent truncation — 跨 3 角色复发，框架级 anti-truncation 守则缺失

**现象**:
sprint-9 单 sprint 4/4 全 subagent 都被 task-notification truncated，覆盖 reviewer / test-writer / implementer 三大角色：

| 任务 | 角色 | tools / time | 截断位置 | 后续 |
|------|------|--------------|--------|------|
| T-095 r1 | reviewer (a6eec6998f6a611bd) | 94 / 8.7min | "worker_init_handler idempotency claim" | orchestrator inline takeover |
| T-096 r1 | reviewer (a678cd2f13fd2a8ea) | 79 / 5.7min | "status field handling in _process_execute" | orchestrator inline takeover |
| T-098 RED | test-writer | (mid-finalize) "Line 239 check" | orchestrator inline format + commit |
| T-098 GREEN | implementer | 112 / 12.2min | "Now run T-098 tests" | orchestrator inline cleanup + commit |

**根因分析**:
- **subagent 上下文窗口管理缺**: 各 SKILL.md 个别提到 tools 预算（如 reviewer 80 cap），但缺**框架级**默认指令注入 AGENT.md frontmatter / 默认 system prompt。每次新角色实施时（如 test-writer / implementer）都要重新发现这个边界。
- **finalize-before-return 协议缺**: subagent 在接近 budget 末尾继续做 incremental work（多读一次文件、多跑一次测试），而非"先保存所有产出 → 写报告 → return 状态"。当 truncate 突然发生，所有 in-memory 工作丢失。
- **stage-by-stage commit 协议缺**: implementer / test-writer 不会在中途 commit + push（习惯于"完成所有 stage 后一次 commit"）。truncate 时 working tree 状态丢失。orchestrator inline takeover 时需要重建上下文（git status + 跑测试 + 推断中断点）。

**建议改进**（target: framework-level `AGENT.md` defaults + tdd-engine + agent-dispatch）:

1. **`AGENT.md` 框架级 anti-truncation frontmatter 字段**（最高 ROI）— 所有 subagent 共享：
   ```yaml
   anti_truncation:
     tools_budget_soft_cap: 70    # 达到时进入 finalize 模式
     tools_budget_hard_cap: 100   # 必须停止业务工作开始收尾
     stage_commit_required: true  # 每 stage 完成强制 git commit + push
     finalize_before_return: true # 必须在最后 5 tools 内完成 artifact 写入
   ```
   各角色 SKILL/AGENT 通过 inherit 拿到默认值，特殊角色（如 reviewer 需要 cross-file 大量 read）可在自身 frontmatter override。

2. **`tdd-engine` / `agent-dispatch` 在 prompt 末尾强制注入 anti-truncation 段**：
   ```
   ## Anti-Truncation Protocol
   - Tools budget: soft={soft_cap}, hard={hard_cap}
   - When approaching soft cap: switch to "finalize mode" — stop new investigation, save all in-progress artifacts, write report
   - Stage-by-stage commit: after each major stage (RED tests written / GREEN tests passing / REFACTOR done), git commit + push immediately
   - On truncation: orchestrator will resume; leave working tree in a known state via stage commit
   ```

3. **`tdd-engine` SKILL.md 新增 "stage gate" 概念**：
   - RED → commit after all tests written
   - GREEN → commit after all RED tests pass
   - REFACTOR → commit after each refactor unit
   - 每个 gate 后 orchestrator 自动 record event 到 EVENT-LOG，truncate 时可从 gate 恢复

**验证方法**:
- 连续 5 个任务零 truncation incident（基线：sprint-9 4/4）；
- truncation 发生时 orchestrator inline takeover 平均耗时 ≤2 tools（基线：当前需要 5-15 tools 重建上下文，因为 working tree 状态需重建）。

---

## 跨 EXP 横向观察

**inline-takeover 模式涌现**（非 EXP，但需要后续治理）:
sprint-9 因 truncation 4/4 + 用户连续选择 inline approve，**11 份 code-review 中 10 份是 orchestrator inline**（仅 T-095 r2/T-097 r1 是独立 reviewer subagent）。这模糊了原 ORCHESTRATOR-PROTOCOLS 的 reviewer 独立性边界。

- **风险**: orchestrator 既是 r1 reviewer 又是 r2 modifier，利益冲突。当前缓解措施（反证测试落地 + CORRECTIONS-LOG 留痕 + 全量回归 + lint clean）形成事实保护带，但理论独立性损失存在。
- **机会**: 如果 EXP-006 anti-truncation 改进生效后 truncation 频率降至零，inline-takeover 就会自然退化到只在特殊场景使用（用户主动选 / 角色明确单点），不再是默认路径。
- **决议**: 不立 EXP-007（属过程演化非反复出错），但在下一 retro 评估周期持续监控 inline-takeover 占比，若持续 >50% 且 truncation 已根治，考虑写入 ORCHESTRATOR-PROTOCOLS 作为正式协议分支。

---

## 应用决策

按 reflector AGENT.md §Output Contract 与 RETRO-intellisource-v1 应用决策模式：

| EXP | target_file | apply 状态 | 用户决策 |
|-----|-------------|-----------|---------|
| EXP-005 | code-review SKILL.md / .cataforge/skills/code-review/scripts/ + tech-lead AGENT.md / dev-plan template | **deferred to backlog**（等用户触发） | pending |
| EXP-006 | 所有 AGENT.md frontmatter 默认字段 + tdd-engine SKILL.md + agent-dispatch | **deferred to backlog**（等用户触发） | pending |

**Backlog 任务挂载**（CLAUDE.md §Backlog 已挂载第 1 项 "6 EXP 改进应用"）— 本 retro 新增 2 个 EXP 后，触发应用工作量评估为单独 backlog cycle，不阻断 sprint-9 deploy 进程。

---

## 与 sprint-8r RETRO 对比

sprint-8r RETRO 标注的 EXP-006/007/008 candidate 状态更新：

| candidate | sprint-8r 状态 | sprint-9 演化 | 当前状态 |
|-----------|--------------|------------|---------|
| EXP-006 (truncation) | candidate, frequency 1/3 | sprint-9 4/4 全发生 | **升 EXP 强制立项** |
| EXP-007 (inline approve 边界) | candidate | sprint-9 大规模实践，未恶化也未根治 | 持续监控，不立 EXP |
| EXP-008 (implementer git-race) | candidate | sprint-9 全 inline 模式无并发派工，无新案例 | 缓存为 future candidate |

---

## 结论

sprint-9 6 任务全 approved 但暴露 2 个跨任务级 EXP（装配缺口 + truncation）。两者都已超阈值，必须升级为框架级强制改进而非建议级 SKILL-IMPROVE。本 retro 同时产出：

1. `SKILL-IMPROVE-code-review-assembly-gap-scan.md` — Layer 1 强制装配缺口扫描
2. `SKILL-IMPROVE-framework-anti-truncation.md` — AGENT.md 框架级 anti-truncation 默认字段 + tdd-engine stage gate

应用顺序建议：先 EXP-006（影响所有后续 sprint 的执行效率），再 EXP-005（影响生产部署的装配安全性）。
