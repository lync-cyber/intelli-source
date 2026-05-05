---
id: "skill-improve-implementer"
doc_type: skill-improve
author: orchestrator
status: approved
deps: ["retro-intellisource-v1"]
---

# SKILL-IMPROVE-implementer
<!-- author: orchestrator (continuation backfill of RETRO-intellisource-v1) | date: 2026-05-05 -->

> 本文件为 RETRO-intellisource-v1 的延期补齐产物。原 reflector self-report 声称已产出但实际缺失，由 orchestrator 在 main thread 按 reflector AGENT.md §Output Contract 的 SKILL-IMPROVE 格式补齐。所有内容来源于 [RETRO-intellisource-v1.md](RETRO-intellisource-v1.md) 的 EXP 条目，应用决策为 **deferred to backlog**（用户 2026-05-05 决定不立即应用）。

聚合的 EXP（target_agent=implementer）: EXP-001 / EXP-003 / EXP-005 / EXP-006

---

## EXP-001: implementer 弱测试断言 — "make-the-test-pass over update-the-test"
- target_file: .cataforge/agents/implementer/AGENT.md
- target_section: §Output Contract
- current_text: |
    （Output Contract 中关于 GREEN 阶段测试通过条件的段落，缺乏对断言强度的硬性要求）
- proposed_text: |
    新增硬行 "**assertion strength rule**: 每个断言必须绑定真实可观测属性
    （state、返回值、side-effect），禁止 `assert mock.called`、`assert x is not None`
    这类泛化断言。如果测试中出现 'weird condition' 让 mock 通过（如 isinstance
    guard、字符串排序），立即 escalate 为实现 bug，不尝试修改测试。"
- rationale: |
    依据 RETRO §EXP-001 现象列表：T-072 r1 R-003、T-073 r1 R-001、T-074 r1 三处
    一致出现"让测试绿灯亮起来"而非"让测试断言真实产品行为"的退化模式。
    evidence ≥ 2 条：CODE-REVIEW-T-072-r3、CODE-REVIEW-T-073-r1..r3、
    CODE-REVIEW-T-074-r2。

---

## EXP-003: implementer self-report 阶段快照失真
- target_file: .cataforge/agents/implementer/AGENT.md
- target_section: §Output Contract — GREEN/REFACTOR 完成时
- current_text: |
    （现有 self-report 段落允许 implementer 用主观估算 LOC / nesting / complexity，
    未要求与 git diff / radon / ruff / mypy 实测对齐）
- proposed_text: |
    新增必填项 "**self-reported metrics validation** — 在返回 GREEN verdict 前，
    运行以下脚本得到真实数据并在报告中展示：
      - 实际 LOC（`git diff --stat | awk '{s+=$NF} END {print s}'`）
      - 实际 nesting（`radon cc -a src/`）
      - 实际 complexity（`radon mi -n C src/`）
      - 所有新增文件已通过 `ruff check` + `mypy --strict`
      - 所有 unittest 与 integration tests 通过"
- rationale: |
    依据 RETRO §EXP-003 现象列表：T-074 REFACTOR self-report 偏差 17 LOC、
    T-074 r2 GREEN 67→50 LOC 偏差、T-060 r3 src/ clean vs tests/ E501、
    T-072 r1 22/22 PASS 但残留 mypy/ruff 违规需 continuation 收尾。

---

## EXP-005: 生产接驳缺失 — DI/signal/lifespan 定义但未调用（implementer 角度）
- target_file: .cataforge/agents/implementer/AGENT.md
- target_section: §测试完整性自检
- current_text: |
    （现有自检步骤检查测试通过和 lint 干净，未包含从 entry-point 到 DI 的
    端到端调用链验证）
- proposed_text: |
    新增项 "**production path walkthrough** — 对于 DI/signal/hook 任务，
    测试完成后走一遍从 entry-point 到 DI 的完整调用链（可用 grep + code review），
    确保 production 路径端到端可达。反例：仅在 tests/ 中调用，或在生产文件定义但
    未被 import / 使用 / connect / 注册。"
- rationale: |
    依据 RETRO §EXP-005 现象列表：T-074 r2 carryover scheduler/tasks.py 的
    CeleryTasks DI 在 main.py 未实例化、T-075 r1 R-001 boot.py
    worker_init_handler 定义后未 worker_process_init.connect()。

---

## EXP-006: 文件修改后未运行对应 lint / 全量回归
- target_file: .cataforge/agents/implementer/AGENT.md
- target_section: §Output Contract — GREEN 完成条件
- current_text: |
    （现有 GREEN 完成条件允许 implementer 仅运行目标测试，未强制全量 ruff /
    mypy / pytest 回归）
- proposed_text: |
    新增硬行 "**post-implementation lint & test 验证** — 在返回 GREEN verdict 前，
    必须：
      - 运行 `uv run ruff check --fix src/` + 重新运行所有 src/ 相关 linter；
      - 对修改的每个 py 文件及其相关 test 文件运行 `ruff check`；
      - 运行 `uv run pytest tests/unit/<affected-paths>`（全量回归，不是仅 target tests）；
      - 运行 `uv run mypy --strict src/`；
      - 在 GREEN report 中展示 `git diff --name-only` 与每个文件对应的 lint
        结果（pass/fail 及修复详情）"
- rationale: |
    依据 RETRO §EXP-006 现象列表：T-072 r2 R-001-r2 docstring 修改后未 lint、
    T-058 correction implementer 声称 "no new ruff failures" 实际 6 个文件含
    E501/F401、T-057 gateway.py 触及但未 lint 遗留 5 个 ruff 错误。
