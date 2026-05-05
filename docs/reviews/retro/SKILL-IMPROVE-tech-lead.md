---
id: "skill-improve-tech-lead"
doc_type: skill-improve
author: orchestrator
status: approved
deps: ["retro-intellisource-v1"]
---

# SKILL-IMPROVE-tech-lead
<!-- author: orchestrator (continuation backfill of RETRO-intellisource-v1) | date: 2026-05-05 -->

> 本文件为 RETRO-intellisource-v1 的延期补齐产物。原 reflector self-report 声称已产出但实际缺失，由 orchestrator 在 main thread 按 reflector AGENT.md §Output Contract 的 SKILL-IMPROVE 格式补齐。所有内容来源于 [RETRO-intellisource-v1.md](RETRO-intellisource-v1.md) 的 EXP 条目，应用决策为 **deferred to backlog**（用户 2026-05-05 决定不立即应用）。

聚合的 EXP（target_agent=tech-lead）: EXP-004 / EXP-005

---

## EXP-004: 接口字段直接复用规则 — AC 段落
- target_file: .cataforge/agents/tech-lead/AGENT.md
- target_section: §任务卡撰写 — AC 段落
- current_text: |
    （现有 AC 撰写指南允许 tech-lead 用自然语言描述返回字段，未强制逐字引用
    arch 文档接口定义）
- proposed_text: |
    新增硬行 "**接口字段直接复用规则** — 所有涉及架构接口（API / Schema /
    Repository）的 AC，必须逐字引用 arch 文档的接口定义（含字段名、类型、
    约束），不得用同义词替代（如不能写 'label' 而 arch 定义为 'topic'）。
    使用格式：'AC-TXXX-N: [ARCH#§M.API-NNN] 返回包含 topic / content_count /
    digest / ... 的 JSON 响应'。"

    可选模板增强：dev-plan task-card 模板的 AC 段落新增 `[Arch Reference]` 块，
    强制 tech-lead 填写对应的 arch chapter / API 编号。
- rationale: |
    依据 RETRO §EXP-004：T-073 task card AC 写 'label' 但 arch API-016 定义
    'topic'，dev-plan 与 arch 在不同时段演进导致漂移；orchestrator 在 RED 派发
    前人工识别并要求 tech-lead 改 task card。

---

## EXP-004: dev-plan finalize 前的 AC-arch-field-alignment 检查
- target_file: .cataforge/skills/task-decomp/SKILL.md（或 tech-lead SKILL 如存在）
- target_section: §dev-plan finalize 前置检查
- current_text: |
    （现有 finalize 检查仅扫 AC 完整性，不对比 arch 字段名）
- proposed_text: |
    新增 check 项 "**AC-arch-field-alignment**" — 扫描所有 AC 是否包含 arch 引用
    且字段名与 arch 一致。可用 yaml/json 字段对比，或要求人工 review 标记
    [Arch Reference] 后再 finalize。
- rationale: |
    依据 RETRO §EXP-004 同上；从源头预防而非依赖 orchestrator 派发前的人工识别。

---

## EXP-005: 任务卡 AC 中 DI/signal/hook 的硬检查项
- target_file: .cataforge/agents/tech-lead/AGENT.md
- target_section: §任务卡撰写 — AC 段落
- current_text: |
    （现有 AC 撰写允许 tech-lead 写 "定义 worker_init_handler" 这类只描述定义不
    强制调用的验收条件）
- proposed_text: |
    新增硬行 "所有涉及 DI / signal handler / lifespan hook 的 AC，必须明确列
    'production entry-point exists and is invoked' 硬检查项。使用格式：
    ```
    AC-TXXX-N: [DI/signal/hook] 在生产路径中被实际调用
      - 验证点: main.py / __main__.py / entry-point 中存在对该 DI/signal/hook
        的显式实例化 / 连接调用
      - 反例: 仅在 tests/ 中调用，或在生产文件定义但未被 import / 使用
    ```"
- rationale: |
    依据 RETRO §EXP-005：T-074 r2 carryover + T-075 r1 R-001 连续两次同模式
    碰撞，根因为 task card AC 只要求 "定义" 不要求 "连接"，触发
    SPRINT-REVIEW-s7-r1 §SR-003 最高优先级。
