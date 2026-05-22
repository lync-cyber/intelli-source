---
id: "corrections-log"
doc_type: correction-log
author: cataforge
status: approved
deps: []
---
# Corrections Log

> 由 CataForge 自动追加。On-Correction Learning Protocol 触发条件见
> `.cataforge/agents/orchestrator/ORCHESTRATOR-PROTOCOLS.md`。

### 2026-05-04 | orchestrator | unknown

- 触发信号: option-override
- 问题/假设: T-073 code-review r1 = approved_with_notes（0 CRITICAL/HIGH，2 MEDIUM + 3 LOW）。R-002 是生产 bug（无效 cursor → 500 而非 400；limit=0 产生 has_more=True / items=[] 语义错误），其余为质量 / 测试增强。如何处理？
- 基线/推荐: 修 R-002 后接受 (Recommended)
- 实际/选择: 修全部 5 个后接受
- 偏差类型: preference

### 2026-05-04 | orchestrator | unknown

- 触发信号: option-override
- 问题/假设: T-073 code-review r2 = approved_with_notes（1 新 LOW + 1 观察）。R-001-r2：invalid cursor 边界测试用 mock side_effect 位推进，未走真实 uuid.UUID() 路径，防回归价值偏低（不影响产品正确性）。另外 ContentRepository LIKE 只在 commit 3857992 message 记了可限性，未进正式 carryover。如何处理？
- 基线/推荐: 接受 r2 + 补 CORRECTIONS-LOG 条目 (Recommended)
- 实际/选择: 再修 R-001-r2 后接受
- 偏差类型: preference

### 2026-05-04 | implementer | T-073 r2

- 触发信号: scope-reduction
- 问题/假设: T-073 r2 R-005 修复将 ClusterRepository.list_clusters 改用 ContentCluster.tags.contains([tag])（JSONB @> operator），同步对 ContentRepository.list 做了 sister fix
- 基线/推荐: 同步修复 ContentRepository
- 实际/选择: 回退 ContentRepository sister fix（保留 LIKE 模式）
- 偏差类型: technical-constraint
- 原因: tests/unit/storage/test_repositories.py 在 SQLite 下运行，SQLite 不支持 JSONB @> 运算符；ContentRepository 已有 SourceRepository 同模式（with SQLite-compat comment），保持一致避免选择性修复
- carryover: ContentRepository / SourceRepository tag 过滤的 LIKE 通配符副作用为 known limitation，待 storage 单元测试迁移到 Postgres test fixture 后统一改用 .contains() / @> 运算符
- 关联: commit 3857992, CODE-REVIEW-T-073-r2.md 追加观察

### 2026-05-04 | orchestrator | unknown
- 触发信号: option-override
- 问题/假设: T-075 code-review r1 verdict 为 approved_with_notes (1 MEDIUM R-001 signal 未连接 + 3 LOW)。R-001 与 T-074 r2 同模式 carryover，sprint-review 时易被误判为完整闭环。如何处理？
- 基线/推荐: 立即修复 R-001 + R-002 (Recommended)
- 实际/选择: 修复全部 4 个 (R-001~R-004)
- 偏差类型: preference

### 2026-05-04 | orchestrator | unknown
- 触发信号: option-override
- 问题/假设: Sprint-7 完整闭环 + RETRO 完成。如何处理 6 条 EXP 的改进应用与下一阶段推进？
- 基线/推荐: 现在应用 EXP-002 + EXP-005 两条高优先并推进 (Recommended)
- 实际/选择: 暂停，我要先设读 RETRO 报告
- 偏差类型: preference

### 2026-05-21 | orchestrator | T-092 r1
- 触发信号: agent-truncation
- 问题/假设: T-092 reviewer 子代理 Layer 2 阶段被 task-notification 截断（88 tools / 91K tokens / 5min），未返回 `<agent-result>` 且 CODE-REVIEW-T-092-r1.md 未落盘。无可恢复中间产出。按 §Sub-Agent Truncation Recovery Protocol 应走 §Agent Crash Recovery；选项为：① 重派 reviewer ② orchestrator 主线程内联接管 ③ 跳过待 sprint-review 兜底。
- 基线/推荐: 重派 reviewer 用更紧凑 prompt（保留独立性，但耗预算）
- 实际/选择: orchestrator 主线程内联 L1+L2，独立性损失换响应速度
- 偏差类型: preference
- 原因: 用户指定选项，明确接受独立性损失换响应速度
- 影响/缓解: code-review 子代理独立性损失记录在案；为弥补 orchestrator-as-reviewer 的利益冲突，本报告 verdict 走从严：3 HIGH + 3 MEDIUM + 4 LOW = needs_revision；R-001/R-002/R-003 三项的"测试通过、生产失效"是 sprint-8r 立项要消除的核心反模式，必须在批次 3 闭合前由 implementer 修订
- 关联: docs/reviews/code/CODE-REVIEW-T-092-r1.md

### 2026-05-21 | orchestrator | sprint-8r batch 3 revision concurrent dispatch
- 触发信号: git-race + agent-self-report-divergence
- 问题/假设: 并发派出 4 个 implementer revision 子代理（T-087/T-088/T-089/T-092），由于 implementer prompt 未明确禁止它们使用 `git add <files>` 与等待 orchestrator 协调 commit 时序，发生两起 git race + commit-message ↔ diff 错配事故：① commit 2019cbc 由 T-087 agent 创建，但 commit message 写成 T-088 r2 内容（agent 看见工作树有 T-088 staged 文件时假定 dual-purpose batch commit）；实际 diff 只含 T-087 5 个文件；T-088 实际改动留在工作树未 commit。② orchestrator 主线程随后 `git add` T-088 4 个文件 + `git commit`，但此时 T-089 agent 已并行 `git add` 自己的 5 个文件，导致 commit 7798139 message 写 T-088 但 diff 包含 T-088（4）+ T-089（5）共 9 文件；T-089 agent 后续 self-report 时确认改动已入 7798139，未额外创建 commit。
- 基线/推荐: implementer prompt 明确"不要 git add / commit / push，由 orchestrator 串行处理"；orchestrator 派工后保持只读直到所有 agent self-report 后再串行 commit
- 实际/选择: 并发派工 + 各 implementer 自行 commit（race window 暴露）
- 偏差类型: protocol-gap
- 原因: revision protocol 未规定并发派工时的 git 协调；implementer agent 习惯性 `git commit` 而 prompt 给了"commit 可以做"的隐性允许
- 影响/缓解:
  - 已发生事故：commit 历史中 2019cbc / 7798139 message 与 diff 内容不严格对应
  - 短期补救：本 CORRECTIONS-LOG 条目 + EVENT-LOG correction events（2026-05-21T23:55）固化真相，后续 reviewer 看 history 时能溯源
  - 不重写历史（无用户授权 amend/force push）
  - 长期改进 carryover：①修订 implementer AGENT.md / SKILL.md，revision task_type 显式要求 "do not run git add/commit/push; orchestrator handles git" ②修订 orchestrator §revision protocol，并发派工时强制 "agents leave working tree dirty; orchestrator collects & commits sequentially in dispatch order"
- 关联: commit 2019cbc, commit 7798139, T-088 / T-087 / T-089 r2 revision dispatch

### 2026-05-22 | orchestrator | sprint-8r batch 3 r3 inline approve
- 触发信号: option-override
- 问题/假设: 批次 3 r3 三任务全部完成 commit + push（b16f971 / bedd6f4 / db2be0d），2288 PASS / mypy strict / ruff clean。是否对全部 3 任务派 reviewer 还是部分 inline approve？
- 基线/推荐: 派 3 reviewer 完整闭环
- 实际/选择: 只派 T-088 r3 reviewer（重点验证 EXP-005 装配缺口闭环）；T-087 r3（R-005 caplog 单行断言）+ T-092 r3（_RawContentResultRepo adapter + integration test）由 orchestrator inline approve
- 偏差类型: preference
- 原因: 用户判断 T-087/T-092 r3 风险低（implementer self-report 含完整反证测试说明"删修复后必 fail"；改动局部、可读）；T-088 r3 是 sprint-8r 核心反模式闭环点，必须独立 reviewer 视角
- 影响/缓解: T-087/T-092 损失独立审查视角；implementer self-report 中的反证测试声明 + orchestrator 主线程 git 历史检查 + 全量回归通过共同构成代偿。如 T-094 集成测试发现装配缺口再回溯
- 关联: commits b16f971 (T-087 r3) / bedd6f4 (T-088 r3, 仍待 reviewer) / db2be0d (T-092 r3); CODE-REVIEW-T-088-r3.md (in-progress)
