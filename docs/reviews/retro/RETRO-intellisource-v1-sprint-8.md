---
id: "retro-intellisource-v1-sprint-8"
doc_type: retrospective
author: reflector
status: draft
date: 2026-05-24
deps: ["RETRO-intellisource-v1", "RETRO-intellisource-v1-sprint-9"]
version: "0.4.0"
---

# RETRO-intellisource-v1-sprint-8: Sprint 8 P2 Retrospective

## 范围与触发

**触发原因**: 用户主动触发（非阈值驱动）— sprint-8 P2 8 任务（T-064/065/066/067/069/070/077/079）+ T-071 集成测试 + sprint-review s8 全部 approved_with_notes，零阻塞。和 sprint-9 不同的是：**没有跨任务复发模式**，无强制 RETRO 阈值命中（self-caused 问题 ≈ 0 个 hard/review 级）。本 retro 主要承担**正向经验立项**：将 sprint-8 验证过的 Mid-Progress Drop Contract 抗截断模式形式化为 EXP-007。

**数据源**:
- SPRINT-REVIEW-s8-r1.md（5 issues: 1 MEDIUM + 4 LOW, 全 non-blocking）
- 8 commits 跨 sprint-8 P2: bf7da26 / 82481d3 / 7c63bd4 / ef57935 / dabd4f4 / 961edc8 / a9e4a88 / 2767470
- docs/EVENT-LOG.jsonl sprint-8 段（≈18 条 state_change / tdd_phase）
- 子代理调用日志: T-064 implementer 67K/19t (truncated) / T-065 implementer 76K/67t (in-budget) / T-070 implementer 71K/31t (Mid-Progress Contract) / T-071 implementer 85K/71t (Mid-Progress Contract) / sprint-review reviewer opus 176K/75t (truncated)

**统计概览**:
- sprint-8 任务: 9 (8 真增量 + 1 集成) 全 approved_with_notes（5 issues backlog 已处理）
- 单 sprint code-review 报告: **0** 份（全 merged-review 模式，sprint-review s8 r1 承担 per-task L2 等价交付）
- self-caused 问题累计: ~6 个（5 SR issues + 1 implementer wiring 误报，**全 non-blocking**）
- 反复出现的模式数: 1 个正向 EXP 立项（EXP-007 Mid-Progress Drop Contract 通用化）+ 1 个候选（EXP-008 merged-review 节约模式）

---

## 经验条目

### EXP-007: Mid-Progress Drop Contract 通用化 — 正向 EXP 强制立项

**现象**:
sprint-8 P2 三次 light-dispatch 子代理调用对比：

| 任务 | tools / tokens | Mid-Progress Drop Contract 注入 | 截断结果 |
|------|----------------|----------------------------------|----------|
| T-064 implementer | 19 / 67K | ❌ 未注入 | **截断** — mid-narration "Let me read the current state first:" |
| T-065 implementer | 67 / 76K | ❌ 未注入（"in budget" 偶然不截断） | 未截断（运气） |
| T-070 implementer | 31 / 71K | ✅ 注入 4 步契约 | **零截断** |
| T-071 implementer | 71 / 85K | ✅ 注入 4 步契约 | **零截断** |
| sprint-review reviewer (opus) | 75 / 176K | ❌ **reviewer 类型未注入** | **截断** — mid-narration "SSE 路由真挂载。检查 ruff 与 vulture：" |

**核心数据**: 2/2 (100%) 显式注入 Mid-Progress Drop Contract 的 implementer 调用零截断；2/2 (100%) 未注入的子代理调用截断（含 sprint-review reviewer opus 1 次跨角色复发）。**该数据强化 sprint-9 EXP-006 立项的统计基础** — 不再是 reviewer-skill 局部问题，是 subagent 通用问题。

**Mid-Progress Drop Contract 4 步契约**（sprint-8 P2 验证过的具体落地形式）:

```
### Step 1 - 设计声明 (≤200 tokens)
快速读取 context_load 文件，输出 ≤200 tokens 的设计声明（签名/策略/mock 概览）。
**禁止**展开代码 / 写长说明 / 用 markdown 分隔符。

### Step 2 - 单次或顺序 Write/Edit
逐文件用 Write/Edit 产出，每个文件写完输出 ≤80 tokens 的进度行
(如 "✓ X.py: stream_complete added (~75 LOC)")。
**禁止**多次 Edit 反复修同一文件、长 narration、`---` 章节标题。

### Step 3 - 增量验证（每个命令独立 Bash 调用）
- uv run pytest tests/...
- uv run mypy --strict ...
- uv run ruff check ...
看到失败立即修复 (用 Edit)，最多 2 轮修复；不写长解释。

### Step 4 - 最终汇报 (≤300 tokens, 强制结构化)
输出 ## Done / ### Files / ### Tests / ### AC Coverage / ### Notes / ### Next
五段结构。不允许再有 tool call。
```

**根因分析**:
- **子代理类型尚未全覆盖**: sprint-9 EXP-006 SKILL-IMPROVE 提案只覆盖 implementer，本 sprint 实证 reviewer 同模式截断 — 必须扩展到 **reviewer / refactorer / test-writer / debugger** 全子代理类型。
- **orchestrator 注入需要每次重写**: 当前 4 步契约是 orchestrator dispatch prompt 里**手动写**的段落，不是 framework-level 默认 prompt 片段，每次 dispatch 都要复制 ~400 字 contract — 高出错率（漏注入），高维护成本（contract 更新需要每次同步）。
- **anti-pattern 自检规则缺集中归集**: "禁止 Let me start...", "禁止 Looking at...", "禁止 markdown 分隔符" 这些 anti-truncation 自检规则散落在各 dispatch prompt 里，无单一事实来源；reviewer dispatch 时只列了一般审查规则没列截断防护，是 sprint-review opus 截断的直接成因。

**建议改进**（target: `.cataforge/agents/*/AGENT.md` frontmatter + `agent-dispatch` SKILL.md + Mid-Progress Drop Contract 文档化）:

1. **`AGENT.md` 框架级 `anti_truncation:` frontmatter 字段**（接续 sprint-9 EXP-006 建议）— 所有子代理类型继承：
   ```yaml
   anti_truncation:
     mid_progress_drop_contract: true   # 启用 4 步契约
     tools_budget_soft_cap: 70          # 达到时进入 finalize 模式
     tools_budget_hard_cap: 100         # 必须停止业务工作开始收尾
     forbid_phrases:                    # 自检黑名单
       - "Let me start"
       - "Looking at"
       - "First, let me check"
       - "I'll now implement"
     forbid_markdown_separators: true   # 禁 --- 章节标题
   ```

2. **`.cataforge/skills/agent-dispatch/templates/anti-truncation-contract.md`** 集中归集 4 步契约文本，所有 dispatch prompt 用 `{{INCLUDE anti-truncation-contract.md}}` 占位符引入，避免每次重写。

3. **`agent-dispatch` SKILL.md 强制注入**: 所有 light-dispatch / standard-dispatch 默认在 prompt 末尾追加 anti-truncation-contract.md 全文（除非 dispatch_options.skip_anti_truncation=true 显式关闭）。

4. **per-role override 机制**: 特殊角色（如 reviewer 跨文件大量 read）可在自身 frontmatter 覆盖 tools_budget_soft_cap（如调到 90），但不可关闭 mid_progress_drop_contract — 后者是结构契约，不分角色。

**验证方法**:
- 连续 10 个子代理调用零 truncation incident（基线：sprint-8 P2 2/5 truncation 含跨角色）；
- reviewer / refactorer / test-writer / debugger 各至少调用 1 次零 truncation；
- 任何子代理 dispatch prompt 都通过 `cataforge doctor` 验证已注入 anti-truncation-contract 段（缺失则 WARN 提示）。

---

### EXP-008: merged-review 模式在 light-task 密集 sprint 节约 token 同时不损质量 — **候选** 强度未达正式立项

**现象**:
sprint-8 P2 8 任务全部标注 "code-review 延 sprint-review"（per-task 不产 CODE-REVIEW，sprint-review s8 r1 一份报告承担 per-task Layer 2 八维度矩阵职责）。对比 sprint-7（11 任务产 13 份 CODE-REVIEW 报告）/ sprint-9（6 任务产 11 份 CODE-REVIEW r1+r2 配对），sprint-8 P2 节约了约 8-16 份独立 CODE-REVIEW 的 token + orchestration overhead。

**SPRINT-REVIEW-s8-r1.md** 通过 per-task L2 八维度矩阵（9 任务 × 8 列）+ 集中 issues 列表（SR-001~005）成功承担了 per-task 等价审查职责：
- 7 个 ⚠️ (MEDIUM/LOW) 被识别（在传统模式下会分散到 8 份 CODE-REVIEW 各自的 issues 列表）
- 跨任务模式（如 EXP-006 reviewer 截断 vs sprint-9 implementer 截断）天然进入横截面视角，比 8 份独立 CODE-REVIEW 更易识别
- verdict 一次性给出，避免 8 个独立 verdict 聚合判断

**根因分析（候选阶段，未到立项强度）**:
- sprint-8 P2 任务**同质性高**（全是 sprint-1~7 基础设施的 P2 增强）— 这是 merged-review 适用的关键前提（COMMON-RULES `merged_review` 字段要求）
- 任务 complexity 多为 S 或 M（非 L/XL）— 单任务 self-caused 问题数低（~0.6 个/任务），sprint-review 报告可以容纳全部 issues 而不撑爆篇幅
- self-caused 问题在 sprint-8 P2 整体极低（5 个 SR + 1 wiring 误报 = ~0.7 个/任务），与 sprint-9（~7 个/任务）差距明显 — 可能是 light-inline 模式（orchestrator 直接执行 5/9 任务）减少了子代理-接管 cycle 的失真

**为什么候选不立项**:
- 数据点不足（仅 sprint-8 P2 一次案例），EXP 立项需要 ≥2 次相似 sprint 场景验证
- merged-review 适用条件已在 `.cataforge/skills/sprint-review/SKILL.md` §合并审查模式 文档化，本 sprint 是文档化条件的实证而非新发现
- 节约的 token 在 sprint-8 P2 占比未量化（需对照 sprint-7 / sprint-9 一致 metric）

**记入未来观察清单**:
- 下次类似的 P2 增强 / 同质轻量任务密集 sprint，对照本次数据验证；累计 ≥3 次类似数据后升 EXP

---

## 跨 EXP 横向观察

### inline-takeover 模式持续涌现，但已被 anti-truncation 协议覆盖路径

sprint-8 P2 内 orchestrator inline 情况:
- 5/9 任务 light-inline (T-066 / T-067 / T-069 / T-077 / T-079) — 主动选择避免子代理 dispatch overhead，**非 truncation 触发**
- 2/9 任务子代理截断后 inline takeover (T-064 implementer / sprint-review reviewer opus) — **EXP-006/007 应用域**

inline-inline 主动模式与 truncation-inline 应用域不同。前者是 orchestrator 的合理调度选择，后者是 EXP-007 要消除的失败恢复模式。一旦 EXP-007 应用，仅前者会继续存在，与 sprint-9 RETRO §跨 EXP 横向观察 一致。

### Mid-Progress Drop Contract 见效正向数据持续累积

sprint-8 P2 提供了 EXP-006/007 立项以来**首次**有控对照（两组 implementer，注入 vs 未注入 contract，2/2 vs 0/2 截断对比）。这个对照不是统计意义上的 N>>1 显著性数据，但作为协议设计的早期信号已足够清晰，支持立项继续进入 framework-level 应用。

---

## 应用决策

按 reflector AGENT.md §Output Contract 与 RETRO-intellisource-v1 应用决策模式：

| EXP | target_file | apply 状态 | 用户决策 |
|-----|-------------|-----------|---------|
| EXP-007 | 所有 `.cataforge/agents/*/AGENT.md` frontmatter + `.cataforge/skills/agent-dispatch/SKILL.md` + 新建 `templates/anti-truncation-contract.md` | **deferred to backlog**（等用户触发，与 sprint-9 EXP-006 合并落地） | pending |
| EXP-008 候选 | — (不立项) | n/a | n/a |

**Backlog 任务挂载** — CLAUDE.md §Backlog 第 2 项 "sprint-9 2 EXP 强制改进应用" 升级为 "sprint-8/9 3 EXP 改进应用 (EXP-005 assembly-gap + EXP-006/007 anti-truncation 协议扩展到 reviewer/refactorer/test-writer/debugger)"。

---

## 与 sprint-9 RETRO 对比

sprint-9 RETRO 候选 candidates 状态更新:

| candidate | sprint-9 状态 | sprint-8 P2 演化 | 当前状态 |
|-----------|--------------|----------------|---------|
| EXP-006 (truncation, implementer-only scope) | 立项 | sprint-8 reviewer/opus 截断新案例 — 跨角色复发再次验证 | **升级范围**: EXP-007 扩展到 reviewer/refactorer/test-writer/debugger 全角色 |
| EXP-007 (inline approve 边界) | candidate, 持续监控 | sprint-8 P2 inline-takeover 占比 ~22% (2/9 truncation-recovery + 5/9 主动 light-inline) | 持续监控；当 EXP-007 落地后预期 truncation-recovery 路径归零，仅主动 light-inline 保留 |
| EXP-008 (implementer git-race) | future candidate | sprint-8 P2 无并发派工 | 缓存为 future candidate |

---

## 结论

sprint-8 P2 9 任务全 approved_with_notes 且零阻塞，主要价值不在新缺陷而在**正向经验形式化**：

1. `Mid-Progress Drop Contract` 4 步契约（Step 1 设计声明 / Step 2 顺序产出 + 进度行 / Step 3 增量验证 / Step 4 结构化汇报）经 2/2 implementer 实证生效
2. sprint-review reviewer opus 截断案例证明**子代理 truncation 是通用问题不限 implementer**，sprint-9 EXP-006 改进必须**扩展到全角色**（reviewer / refactorer / test-writer / debugger）

应用顺序建议（与 sprint-9 retro 联合）:
1. **EXP-006/007 合并落地**（影响所有后续 sprint 执行效率, **优先级最高**）— framework-level `anti_truncation:` frontmatter + `agent-dispatch` 强制注入 contract template
2. **EXP-005 assembly-gap-scan**（影响生产部署装配安全性）
3. **sprint-1~7 6 EXP** 老 backlog（重要性低于 EXP-005~007）

**sprint-8 P2 收尾决议**: sprint-review s8 verdict approved_with_notes → 已通过 SR-001~005 5 个 backlog 处理（本 retro 同 commit）→ sprint-8 P2 sprint-level done，可进入 deploy 阶段 / 下一 sprint 规划 / EXP 应用 cycle 任一线程。
