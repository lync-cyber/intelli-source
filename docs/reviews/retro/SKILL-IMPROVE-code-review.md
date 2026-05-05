---
id: "skill-improve-code-review"
doc_type: skill-improve
author: orchestrator
status: approved
deps: ["retro-intellisource-v1"]
---

# SKILL-IMPROVE-code-review
<!-- author: orchestrator (continuation backfill of RETRO-intellisource-v1) | date: 2026-05-05 -->

> 本文件为 RETRO-intellisource-v1 的延期补齐产物。原 reflector self-report 声称已产出但实际缺失，由 orchestrator 在 main thread 按 reflector AGENT.md §Output Contract 的 SKILL-IMPROVE 格式补齐。所有内容来源于 [RETRO-intellisource-v1.md](RETRO-intellisource-v1.md) 的 EXP 条目，应用决策为 **deferred to backlog**（用户 2026-05-05 决定不立即应用）。

聚合的 EXP（target_skill=code-review）: EXP-001 / EXP-003 / EXP-004 / EXP-005 / EXP-006

---

## EXP-001: 弱断言检测 — Layer 2 test-quality 维度强化
- target_file: .cataforge/skills/code-review/SKILL.md
- target_section: §Layer 2 test-quality 维度
- current_text: |
    （现有 test-quality 维度检查断言数量与覆盖率，未强制断言强度评分）
- proposed_text: |
    新增 check 项 "**assertion strength** — for each test_XXX 函数，断言数 /
    执行路径数 ≥ 0.8，且每条断言涉及真实可观测对象（不计 mock.called /
    isinstance check）；生产类型 != 测试 mock 类型时需显式 type mismatch 注释
    说明为何测试不走真路径"。
- rationale: |
    依据 RETRO §EXP-001 三处证据 + adaptive-review 注入证明该红线对 T-075/T-063
    后期任务有效抑制弱断言模式。

---

## EXP-001 / EXP-003: Layer 1 lint 规则增强
- target_file: .cataforge/skills/code-review/SKILL.md
- target_section: §Layer 1 检查项清单 + builtin lint scripts
- current_text: |
    （现有 Layer 1 lint 不扫 mock 构造的诡异条件、不对比 GREEN 自报指标与
    实际 commit diff）
- proposed_text: |
    新增两条 Layer 1 检查项：
      1. "**mock 诡异条件检测**" — 使用 AST 扫描
         `if isinstance(...) and mock_condition`、`if x and mock.side_effect`
         等模式，命中标 LOW test-quality issue。
      2. "**GreenReport-Metrics-Alignment**" — 对比 GREEN 自报的 LOC / nesting /
         complexity 指标与实际 commit diff，偏差 > 5% 标 LOW precision-issue。
- rationale: |
    EXP-001 现象：T-074 r1 isinstance guard 让 mock 通过；
    EXP-003 现象：T-074 r2 67→50 LOC 偏差、T-074 REFACTOR self-report 与 diff 不符。

---

## EXP-004: completeness 维度增加"task-card vs implementation 字段对齐"检查
- target_file: .cataforge/skills/code-review/SKILL.md
- target_section: §Layer 2 completeness 维度
- current_text: |
    （现有 completeness 维度检查接口字段是否实现，未对比 task card AC 字面与
    arch 文档接口定义的字段名一致性）
- proposed_text: |
    新增 check 项 "**task-card vs implementation 字段对齐**" — 若 task card AC
    的字段名与 CODE-REVIEW 发现的实现字段不一致（如 task card 写 'label' 而
    实现 'topic'），标 HIGH consistency issue，并在报告中追溯 arch authoritative
    字段名。
- rationale: |
    依据 RETRO §EXP-004：T-073 task card AC-T073-1 字面 'label / item_count /
    digest' 与 arch API-016 'topic / content_count / digest' 漂移，
    orchestrator 在 RED 派发前人工识别。

---

## EXP-005: completeness 维度增加 production-path-exists 检查
- target_file: .cataforge/skills/code-review/SKILL.md
- target_section: §Layer 2 completeness 维度
- current_text: |
    （现有 completeness 维度检查代码可编译可通过测试，未验证 production
    entry-point 存在且被调用）
- proposed_text: |
    新增 check 项 "**production-path-exists**":
      - DI 定义（如 `CeleryTasks.__init__`）必须被 src/ 内某处调用；
      - signal handler 必须被 `signal.connect()` 调用；
      - hook 必须被 lifespan 注册。
    反例检测：grep src/ 查找 class/function 是否有调用点，无调用点且非
    base class/mixin 时标 MEDIUM completeness issue。

    Layer 1 配套新增 lint "**unused-class-in-production**" — 标记 src/ 中定义
    但 src/ 内无调用、仅在 tests/ 中使用的 class，输出 LOW convention issue。
- rationale: |
    依据 RETRO §EXP-005：T-074 r2 carryover scheduler/tasks.py CeleryTasks DI
    生产接驳缺失；T-075 r1 R-001 worker_init_handler 未 connect。两次同模式
    碰撞触发 SPRINT-REVIEW-s7-r1 §SR-003 升级为最高优先级。

---

## EXP-006: Layer 1 增加 "all modified files lint clean" 检查
- target_file: .cataforge/skills/code-review/SKILL.md
- target_section: §Layer 1 检查项清单
- current_text: |
    （现有 Layer 1 检查项独立运行 ruff / mypy / pytest，未强制对修改的每个
    文件单独验证）
- proposed_text: |
    新增 check 项 "**all modified files lint clean**":
      - 调用 `cataforge skill run code-review -- --check-modified-files src/`，
        对 git diff 涉及的每个 .py 文件运行 ruff + mypy；
      - 任一文件 FAIL 即整体 Layer 1 FAIL（不进 Layer 2）。
- rationale: |
    依据 RETRO §EXP-006：T-058 implementer 声称 "no new ruff failures" 但 6 个
    文件含 E501/F401；T-057 gateway.py a9802d6 遗留 5 个 ruff 错误。
