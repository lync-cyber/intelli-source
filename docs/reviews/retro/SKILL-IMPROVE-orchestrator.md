---
id: "skill-improve-orchestrator"
doc_type: skill-improve
author: orchestrator
status: approved
deps: ["retro-intellisource-v1"]
---

# SKILL-IMPROVE-orchestrator
<!-- author: orchestrator (continuation backfill of RETRO-intellisource-v1) | date: 2026-05-05 -->

> 本文件为 RETRO-intellisource-v1 的延期补齐产物。原 reflector self-report 声称已产出但实际缺失，由 orchestrator 在 main thread 按 reflector AGENT.md §Output Contract 的 SKILL-IMPROVE 格式补齐。所有内容来源于 [RETRO-intellisource-v1.md](RETRO-intellisource-v1.md) 的 EXP 条目，应用决策为 **deferred to backlog**（用户 2026-05-05 决定不立即应用）。

聚合的 EXP（target_protocol=orchestrator/lint-gate）: EXP-002 / EXP-006

---

## EXP-002: ORCHESTRATOR-PROTOCOLS 写权限章节明确化
- target_file: .cataforge/agents/orchestrator/ORCHESTRATOR-PROTOCOLS.md
- target_section: §写权限协议（如不存在则新增）
- current_text: |
    （现有协议描述 PROJECT-STATE.md 由 orchestrator 独占写入，但未涵盖 git
    操作的独占权限，refactorer/implementer 的 git 边界不清晰）
- proposed_text: |
    新增章节 "§写权限协议（git 边界）"：
    ```
    ## §写权限协议（git 边界）

    | 写入对象 | 独占角色 | 子代理可见性 |
    |----------|---------|------------|
    | git working tree (file edit) | implementer / refactorer | 受 allowed_paths 限制 |
    | git index (add) | orchestrator | 子代理无权 |
    | git commit / push / branch | orchestrator | 子代理无权 |
    | PROJECT-STATE.md | orchestrator | 子代理无权 |
    | docs/EVENT-LOG.jsonl | orchestrator + cataforge event log CLI | 子代理通过 CLI 间接写入 |

    refactorer 与 implementer 同级，均不得执行 git 操作；TDD 三阶段的所有 git
    write 由 orchestrator 异步事务管理。违反协议（refactorer 自行 commit / push）
    立即标 BLOCKED 并 rollback。
    ```
- rationale: |
    依据 RETRO §EXP-002：T-074 REFACTOR commit d0cb454 越权 commit + push，
    EVENT-LOG 缺协议事件，sprint-review r1 标注 "refactorer self-commit
    protocol violation noted"。

---

## EXP-006: orchestrator post-edit lint 门禁
- target_file: .cataforge/agents/orchestrator/ORCHESTRATOR-PROTOCOLS.md
- target_section: §Phase Transition Protocol / TDD Loop
- current_text: |
    （现有 Phase Transition Protocol 在子代理返回 completed 后直接进入 review；
    没有 lint-gate 横切层）
- proposed_text: |
    新增 "**lint-gate**" 横切检查 — 在 implementer / refactorer 子代理返回
    completed 但 reviewer 启动前，orchestrator 自动运行：
    ```
    uv run ruff check {affected_paths}
    uv run mypy --strict src/
    ```
    失败即 blocking-revision，将 lint 错误清单作为 revision 输入返回子代理；
    成功才进入 reviewer。该层与 tdd-engine §Step 3 的 post-GREEN 验证互补，
    覆盖非 TDD 路径（如 amendment / debug）的 lint 漂移。
- rationale: |
    依据 RETRO §EXP-006：T-058 / T-072 r2 / T-057 多次因 implementer 跳过 lint
    直接提交，导致 code-review 第一轮即 FAIL，造成不必要的 revision 轮次。
    把 lint-gate 提前到 orchestrator 层可统一处理 TDD / amendment / debug
    多路径的 lint 漂移问题。
