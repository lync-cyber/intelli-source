---
id: "skill-improve-framework-anti-truncation"
doc_type: skill-improve
author: reflector
status: draft
date: 2026-05-23
deps: ["retro-intellisource-v1-sprint-9"]
target_id: framework-agent-md
target_kind: agent
source_exp: EXP-006
---

# SKILL-IMPROVE: 框架级 anti-truncation 默认守则

## EXP-006: subagent truncation 跨 3 角色 sprint-9 4/4 全发生

**evidence**:
- EVENT-LOG 2026-05-22T08:25:48: T-095 r1 reviewer (a6eec6998f6a611bd) truncated 94 tools / 8.7min, no artifact, partial trail "worker_init_handler idempotency claim"
- EVENT-LOG 2026-05-23T02:35:29: T-096 r1 reviewer (a678cd2f13fd2a8ea) truncated 79 tools / 5.7min / 88K tokens, partial trail "status field handling in _process_execute"
- EVENT-LOG 2026-05-23T08:48:16 (T-098 RED tdd_phase): test-writer subagent truncated mid-finalize "Line 239 check"
- task-notification 2026-05-23T09:06:34: T-098 GREEN implementer truncated 112 tools / 12.2min, mid-thought "Now run T-098 tests"

跨 3 角色（reviewer / test-writer / implementer）共 4 次截断证明 truncation 非 reviewer-skill 局部问题，而是框架级 subagent 上下文管理缺失。

---

## 改进 1: AGENT.md frontmatter 引入 `anti_truncation` 默认字段

### target_file
所有 `.cataforge/agents/*/AGENT.md` + `.cataforge/skills/*/SKILL.md`（涉及 subagent 调度的）

### target_section
§frontmatter（YAML metadata block）

### current_text
```yaml
---
name: reviewer
description: "评审员 — 跨阶段质量审查..."
tools: file_read, file_write, file_edit, file_glob, file_grep, shell_exec
model_tier: light
maxTurns: 80
---
```

### proposed_text
```yaml
---
name: reviewer
description: "评审员 — 跨阶段质量审查..."
tools: file_read, file_write, file_edit, file_glob, file_grep, shell_exec
model_tier: light
maxTurns: 80

# Framework-level anti-truncation defaults (EXP-006)
# Each agent can override these in its own frontmatter; absence means inherit framework default.
anti_truncation:
  tools_budget_soft_cap: 70          # 达到时进入 finalize 模式
  tools_budget_hard_cap: 100         # 必须停止业务工作开始收尾
  stage_commit_required: true        # 每 stage 完成强制 git commit + push
  finalize_before_return: true       # 最后 5 tools 内完成 artifact 写入与状态返回
  on_truncate_artifact_required: true  # 即使 partial，也要 best-effort dump 中间产出到 docs/reviews/wip/
---
```

各 agent 的 override 例:
- reviewer: 默认值即可（80-tool 范围内完成 Layer 2 大部分场景）
- test-writer / implementer: `tools_budget_soft_cap: 60` 因为他们需要预留更多 tools 给 stage commit
- orchestrator (主线程): 不适用（main thread 无固定 budget）

### rationale
sprint-9 4/4 truncation 跨 3 角色覆盖证明现状各 SKILL.md 个别提及预算（如 reviewer 80 cap）不构成框架级保护。把 anti_truncation 提升到 AGENT.md frontmatter inherit 默认值，每个角色按需 override，统一减少未来新角色（如 sprint-10 可能引入的新 subagent）首次跌入此坑的概率。

---

## 改进 2: agent-dispatch SKILL 在 prompt 末尾强制注入 anti-truncation 段

### target_file
`.cataforge/skills/agent-dispatch/SKILL.md`

### target_section
§prompt 模板末尾（subagent 接收的最终 instruction）

### current_text
```
[task-specific prompt body]
```

### proposed_text
```
[task-specific prompt body]

## Anti-Truncation Protocol (framework default, see AGENT.md anti_truncation field)

- **Tools budget**: soft={anti_truncation.tools_budget_soft_cap}, hard={anti_truncation.tools_budget_hard_cap}
- **Approaching soft cap**: 立即切换到 "finalize mode" — 停止 new investigation / file reads / shell exec，开始写报告与产出。
- **Stage-by-stage commit**: 每个 major stage 完成后立即 `git add <stage-specific files> + git commit -m "[stage marker]"`，**不等所有 stage 完成再一次性 commit**：
  - RED stage: tests written + RED run confirms all fail → commit
  - GREEN stage: all RED tests pass → commit
  - REFACTOR stage: each refactor unit done → commit
  - REVIEW stage: report written → commit
- **On truncation detected** (rarely visible to subagent itself; relevant for orchestrator takeover): orchestrator will resume from last stage-commit; subagent's working tree state is expendable but commits are not.
- **Finalize-before-return**: 最后 5 tools 必须完成 ① artifact 写盘 ② return status code（completed / blocked / needs_input）③ summary 描述已落地 artifact 路径 — 不在最后做新的 investigation。
```

### rationale
SKILL.md 元数据声明只在文档层面解决问题；agent-dispatch 必须把 anti-truncation 协议**写入 subagent 接收的实际 prompt 末尾**才能影响 LLM 行为。当前 prompt 模板末尾只有 task-specific body，没有任何框架级守则注入。

---

## 改进 3: tdd-engine SKILL 新增 "stage gate" 概念 + EVENT-LOG 自动 record

### target_file
`.cataforge/skills/tdd-engine/SKILL.md` + `cataforge.skill.builtins.tdd_engine`

### target_section
§TDD 编排流程

### current_text
```
RED → GREEN → REFACTOR 三阶段子代理调度，REFACTOR 按 TDD_REFACTOR_TRIGGER 条件触发。
```

### proposed_text
```
RED → GREEN → REFACTOR 三阶段子代理调度，每阶段完成后强制 **stage gate**：

1. RED 完成 → subagent self-report "all tests written + all RED" → orchestrator 验证测试存在 + 全 FAIL → `git commit -m "test({task}): RED — {N} failing tests"` → push → EVENT-LOG `tdd_phase RED done`
2. GREEN 完成 → subagent self-report "all RED → PASS" → orchestrator 验证全量回归 + lint + mypy → `git commit -m "feat({task}): GREEN — {N} tests passing"` → push → EVENT-LOG `tdd_phase GREEN done`
3. REFACTOR 完成（若触发） → 每个 refactor unit 独立 commit + push → EVENT-LOG `tdd_phase REFACTOR done`

**Truncation 恢复路径**: 当 subagent 在某 stage 内 truncate，orchestrator 通过 git log / EVENT-LOG 找到最后一个 stage gate，从该点恢复（重新派 subagent 或 inline takeover）。stage gate 后的 commit 是恢复锚点。

REFACTOR 仍按 TDD_REFACTOR_TRIGGER 条件触发。
```

### rationale
sprint-9 T-098 GREEN implementer truncate 时，working tree 含 implementer 已写好的源代码但没有 commit。orchestrator inline takeover 需要重建上下文（git status + 跑测试 + 推断中断点 + 完成剩余清理 + commit），共耗 5-15 tools。如果 implementer 在写完 src 文件后立即 commit（stage gate "GREEN partial"），orchestrator 只需继续后续 cleanup + 跑测试 + final commit，省 70% 工作。

---

## 改进 4: orchestrator inline-takeover 协议固化

### target_file
`.cataforge/agents/orchestrator/ORCHESTRATOR-PROTOCOLS.md`

### target_section
§Adaptive Review / §Interrupt-Resume Protocol（新增子节）

### current_text
（当前 ORCHESTRATOR-PROTOCOLS 没有 inline-takeover 正式协议；sprint-9 11 份 code-review 中 10 份 inline 是事实演化而非协议规定）

### proposed_text
```
### inline-takeover 协议（EXP-006 衍生）

**触发条件**（任一）:
1. subagent task-notification 返回 `<status>completed</status>` 但 result 末尾是 mid-thought（典型："Now let me check / Let me verify / Next I'll..."）
2. tools 用量达 `anti_truncation.tools_budget_hard_cap` 且无 final artifact
3. 用户主动指令 "orchestrator inline 跑"

**takeover 流程**:
1. orchestrator 读 git status / 最近 EVENT-LOG / working tree 推断中断点
2. 检查 stage gate（最后 commit message）确认进度
3. 在主线程接管剩余工作，沿用 subagent prompt 中的 task-specific instructions
4. **独立性补偿**: 当 takeover 涉及 reviewer 角色时，强制要求：
   - verdict 走从严（所有 finding 报全，不短路 LOW）
   - 反证测试落地（关键 finding 修复后必须新增"if-revert-fix-this-test-fails"测试）
   - CORRECTIONS-LOG 留痕 inline-takeover 决策与独立性损失评估
5. EVENT-LOG record `state_change` 标记 truncation + takeover

**统计预警**: 若连续 5 个任务超过 50% 走 inline-takeover，orchestrator 主动 propose 用户重新评估 EXP-006 改进应用进度（可能是 anti-truncation 协议未生效）。
```

### rationale
sprint-9 inline-takeover 大规模实践但没有协议固化，每次都是 ad-hoc 决策。把 sprint-9 的成熟做法（verdict 从严 + 反证测试 + CORRECTIONS-LOG）写入协议，避免未来项目又一次"摸索式"演化。同时设置 50% 监控预警，让 inline-takeover 从临时补救退化为特殊场景路径，而非默认。

---

## 改进生效验证方法

1. **直接验证**: 应用以上 4 个改进后，连续 5 个任务执行 0 truncation incident（sprint-9 基线 4/4）
2. **间接验证**: stage gate commit 数量增加（sprint-9 大部分任务只有 RED+GREEN 各 1 commit；改进后应见 GREEN partial commits）
3. **独立性验证**: code-review subagent 占比从 sprint-9 的 9%（11 份 review 中 1 份）回升到 70%+，inline-takeover 退化为特殊场景
