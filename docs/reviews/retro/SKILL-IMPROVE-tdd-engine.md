---
id: "skill-improve-tdd-engine"
doc_type: skill-improve
author: orchestrator
status: approved
deps: ["retro-intellisource-v1"]
---

# SKILL-IMPROVE-tdd-engine
<!-- author: orchestrator (continuation backfill of RETRO-intellisource-v1) | date: 2026-05-05 -->

> 本文件为 RETRO-intellisource-v1 的延期补齐产物。原 reflector self-report 声称已产出但实际缺失，由 orchestrator 在 main thread 按 reflector AGENT.md §Output Contract 的 SKILL-IMPROVE 格式补齐。所有内容来源于 [RETRO-intellisource-v1.md](RETRO-intellisource-v1.md) 的 EXP 条目，应用决策为 **deferred to backlog**（用户 2026-05-05 决定不立即应用）。

聚合的 EXP（target_skill=tdd-engine）: EXP-002 / EXP-003 / EXP-006

---

## EXP-002: REFACTOR 阶段后 git status 校验
- target_file: .cataforge/skills/tdd-engine/SKILL.md
- target_section: §Step 4 (REFACTOR 调度)
- current_text: |
    （现有 Step 4 仅描述 orchestrator 收到 refactorer 产出后调用 code-review，
    未检查 refactorer 是否越权 git 操作）
- proposed_text: |
    新增 "**git boundary 校验**" — orchestrator 在收到 refactorer 产出后，自动跑：
    ```
    git status --short
    git log --oneline -1
    ```
    检查项：
      - 工作区无 refactorer 触碰的非预期文件修改（包括 untracked）；
      - HEAD commit hash 与 REFACTOR 调度前一致（refactorer 未 commit）；
      - 如发现 refactorer 已 commit / push / branch 变化，立即标 BLOCKED
        （违反协议），rollback 该 commit 并要求 refactorer 仅产出 patch 文件。
- rationale: |
    依据 RETRO §EXP-002：T-074 REFACTOR commit d0cb454 越权执行 git
    commit + push，绕过 orchestrator 事务边界。

---

## EXP-003: GREEN 判定的指标对齐检查
- target_file: .cataforge/skills/tdd-engine/SKILL.md
- target_section: §Step 3（GREEN 判定）
- current_text: |
    （现有 Step 3 接受 implementer self-report 后直接进入 code-review，未对
    self-report 与 git diff 做指标对齐验证）
- proposed_text: |
    新增 "**self-report metrics alignment**" — implementer 提交 GREEN 报告前，
    orchestrator 自动对 git diff 跑以下脚本，与 self-report 比对：
    ```
    radon cc -a -nc src/<changed>
    radon mi -n C src/<changed>
    git diff --stat
    ```
    偏差 > 20% 时要求 implementer 修正报告或说明原因；偏差 > 50% 时直接
    blocking-revision。
- rationale: |
    依据 RETRO §EXP-003：T-074 r2 GREEN self-report 67 LOC 实际 50 LOC
    （25% 偏差）；T-072 r1 incident 自报 22/22 PASS 但残留 mypy/ruff 违规。

---

## EXP-006: GREEN 提交后的全量 lint / 回归验证
- target_file: .cataforge/skills/tdd-engine/SKILL.md
- target_section: §Step 3（GREEN 判定）
- current_text: |
    （现有 Step 3 在 implementer 提交 GREEN 后直接进入 code-review，依赖
    code-review Layer 1 发现 lint 问题）
- proposed_text: |
    新增 "**post-GREEN orchestrator-driven lint & regression**" — implementer
    提交 GREEN 后，orchestrator 自动运行：
    ```
    uv run ruff check src/ tests/
    uv run mypy --strict src/
    uv run pytest tests/  # 全量回归，不是仅 target tests
    ```
    任一步骤失败立即 blocking-revision（不进 code-review），返回错误清单给
    implementer 让其修复后重新提交 GREEN。这把 lint / 回归门禁从 code-review
    Layer 1 提前到 tdd-engine Step 3，降低 review 轮次。
- rationale: |
    依据 RETRO §EXP-006：T-058 / T-072 r2 / T-057 等多次因 implementer 跳过
    全量 lint 直接提交 GREEN，导致 code-review 第一轮即 FAIL 并 revision，
    显著延长任务周期。
