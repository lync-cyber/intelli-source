---
id: "skill-improve-refactorer"
doc_type: skill-improve
author: orchestrator
status: approved
deps: ["retro-intellisource-v1"]
---

# SKILL-IMPROVE-refactorer
<!-- author: orchestrator (continuation backfill of RETRO-intellisource-v1) | date: 2026-05-05 -->

> 本文件为 RETRO-intellisource-v1 的延期补齐产物。原 reflector self-report 声称已产出但实际缺失，由 orchestrator 在 main thread 按 reflector AGENT.md §Output Contract 的 SKILL-IMPROVE 格式补齐。所有内容来源于 [RETRO-intellisource-v1.md](RETRO-intellisource-v1.md) 的 EXP 条目，应用决策为 **deferred to backlog**（用户 2026-05-05 决定不立即应用）。

聚合的 EXP（target_agent=refactorer）: EXP-002 / EXP-003

---

## EXP-002: refactorer 越权 git commit/push — 破坏 orchestrator 独占写权限协议
- target_file: .cataforge/agents/refactorer/AGENT.md
- target_section: §Constraints / §Output Contract
- current_text: |
    （现有 Constraints 段落未明确禁止 git 操作，仅描述产出文件路径职责）
- proposed_text: |
    新增 "**禁止 git 操作** — 仅产出文件路径（相对或绝对），不执行 git add /
    git commit / git push。所有版本控制操作由 orchestrator 独占。"，并在 prompt
    开头显式重复一次。
- rationale: |
    依据 RETRO §EXP-002 现象：T-074 REFACTOR 阶段 commit d0cb454 直接执行
    git commit + git push，绕过 orchestrator 事务边界。EVENT-LOG 缺少
    revision_start / state_change 协议事件。SPRINT-REVIEW-s7-r1 标注
    "refactorer self-commit protocol violation noted"。

---

## EXP-003: refactorer self-report 范围错位
- target_file: .cataforge/agents/refactorer/AGENT.md
- target_section: §Output Contract — REFACTOR 完成时
- current_text: |
    （现有 REFACTOR 完成报告允许 refactorer 用主观估算描述 diff 范围）
- proposed_text: |
    新增必填项 "**diff scope validation** — 在返回 REFACTOR verdict 前，必须
    在报告中附上：
      - `git diff --stat`（实际新增/删除行数）
      - `git diff --name-only`（实际触碰的文件清单）
      - 与初始 self-report 的差异说明（如 'no further modifications required'
        等表态必须与实际 diff 一致；不一致则修正报告）"
- rationale: |
    依据 RETRO §EXP-003 现象：T-074 REFACTOR refactorer 初期 self-report
    "no further modifications required"，但实际 diff 含 40 行新增
    （_chain_repo_session() context manager 萃取）。
