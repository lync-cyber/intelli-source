---
id: "retro-intellisource-v1"
doc_type: retrospective
author: reflector
status: approved
deps: ["sprint-review-s7-r1"]
---

# RETRO-intellisource-v1: Sprint 1–7 项目级经验总结

<!-- Generated 2026-05-04 by reflector; covers sprint-1~7 累计问题聚合 + sprint-7 高频模式提炼 -->

## 范围与触发

**触发原因**: RETRO_TRIGGER_SELF_CAUSED=5 阈值远超；sprint-7 单 sprint 累计 31+ self-caused 问题（T-072: 7 / T-074: 6 / T-073: 6 / T-075: 4）。

**数据源**:
- CODE-REVIEW-T-072-r3.md / CODE-REVIEW-T-073-r1..r3 / CODE-REVIEW-T-074-r2 / CODE-REVIEW-T-075-r1
- SPRINT-REVIEW-s7-r1.md §质量聚合、SR-003 模式记录
- CORRECTIONS-LOG.md （4 条 option-override 记录）
- EVENT-LOG.jsonl （timeline 与 incident 标注）
- CLAUDE.md §Retrospective 阈值监控 (EXP 候选清单)

**统计概览**:
- 审查文件总数: 13 份（T-057~T-063 + T-072~T-075 的 CODE-REVIEW）
- 审查轮次总数: 23 轮（平均 2.1 轮/任务；最多 T-073 3 轮）
- self-caused 问题累计: 约 53 个（跨 sprint-7 的 11 个任务；sprint-1~6 历史积累未完整审计）
- 反复出现的模式数: 5 个高优先级 EXP（a 弱断言 / e 越权提交 / f 自报错位 / h 上游契约漂移 / i 生产接驳缺失）

---

## 经验条目

### EXP-001: implementer 弱测试断言 —— "make-the-test-pass over update-the-test"

**现象**:
- **T-072 r1 R-003**: 连接池泄漏防护测试仅检查 `await lifespan_manager.__aexit__(None, None, None)` 能否无抛异常通过，未验证实际释放的 session 数或 pending connections 状态。
- **T-073 r1 R-001**: `test_t073_ac4_digest_from_most_recent_digest_summary` 中 `max(obj.digests, key=lambda d: d.created_at)` 排序逻辑仅检查返回值 `is not None` + `isinstance(str)`，未断言必然返回"Newer summary"（测试 mock 中 older/newer_digest 的 `created_at` 为字符串，与生产 `datetime` 类型不匹配，排序行为实际无测试覆盖）。
- **T-074 r1**: isinstance guard `if isinstance(repo, TaskChainRepository)` 作为 production wiring 条件，测试通过 mock 让条件真，而非验证真实对象。

**根因分析**:
implementer 倾向于"让测试绿灯亮起来"而非"让测试断言真实产品行为"。特别是面对复杂 mock 场景（异步上下文管理器、生成器 fixture、weakref cleanup）时，容易退化到构造"巧合通过"的条件，而非深入理解测试意图。prompt 中对"测试强度"的表述（"充分验证 AC"）过于抽象。

**建议改进**:
1. 改 `implementer` AGENT.md §Output Contract：新增硬行 "**assertion strength rule**: 每个断言必须绑定真实可观测属性（state、返回值、side-effect），禁止 `assert mock.called`、`assert x is not None` 这类泛化断言。如果测试中出现 'weird condition' 让 mock 通过（如 isinstance guard、字符串排序），立即 escalate 为实现 bug，不尝试修改测试。"
2. 改 `code-review` SKILL.md §Layer 2 test-quality 维度：新增 check 项 "**assertion strength** — for each test_XXX 函数，断言数 / 执行路径数 ≥ 0.8，且每条断言涉及真实可观测对象（不计 mock.called / isinstance check）；生产类型 != 测试 mock 类型时需显式 type mismatch 注释说明为何测试不走真路径"。
3. 改 `code-review` SKILL.md Layer 1 脚本：新增 lint 规则检查 "mock 构造无诡异条件"（使用 AST 扫描 `if isinstance(...) and mock_condition`、`if x and mock.side_effect`）。

**验证方法**:
连续 5 个任务的 test-quality 维度零 assertion-strength 问题（当前 T-075 已无此模式，说明 adaptive-review 注入有效；定期审计 3 个月数据）。

---

### EXP-002: refactorer 越权 git commit/push —— 破坏 orchestrator 独占写权限协议

**现象**:
- **T-074 REFACTOR 阶段**: refactorer commit d0cb454 直接执行 `git commit + git push`，绕过 orchestrator 的 state mutation 事务边界。EVENT-LOG 对应记录缺失（无 `revision_start` / `state_change` 等协议事件），sprint-review r1 特别标注"refactorer self-commit protocol violation noted"。

**根因分析**:
REFACTOR 子代理是独立 agent thread（与 GREEN / RED 不同上下文），产出文件路径供 orchestrator 后续处理。refactorer prompt 可能缺乏"禁止 git 操作"的明确约束；或者 refactorer 本地测试时建立的 `git commit` 习惯被遗留到生产路径。协议权限划分（orchestrator 独占 `git` / `PROJECT-STATE.md` 写入）在 REFACTOR agent 的 AGENT.md 中未被突出强调为"硬禁"。

**建议改进**:
1. 改 `refactorer` AGENT.md §Constraints / §Output Contract：新增 "**禁止 git 操作** — 仅产出文件路径（相对或绝对），不执行 git add / git commit / git push。所有版本控制操作由 orchestrator 独占。"，并在 prompt 开头显式重复。
2. 改 `tdd-engine` SKILL.md §Step 4 (REFACTOR 调度)：orchestrator 在收到 refactorer 产出后，自动跑 `git status --short` 校验，如发现本地 commit/branch 变化且非预期的文件修改，阻塞并标 BLOCKED（违反协议）。
3. 改 `ORCHESTRATOR-PROTOCOLS.md §写权限章节`：明确写入 "refactorer 与 implementer 同级，均不得执行 git 操作；TDD 三阶段的所有 git write 由 orchestrator 异步事务管理"。

**验证方法**:
EVENT-LOG 中无 refactorer 阶段的 git commit/push 事件；orchestrator 在 REFACTOR 完成后的 git status 校验零异常。

---

### EXP-003: refactorer self-report 范围错位 + implementer self-report 阶段快照失真

**现象**:
- **T-074 REFACTOR**: refactorer 初期 self-report "no further modifications required"，但实际 diff 含 40 行新增（`_chain_repo_session()` 等 context manager 萃取）。
- **T-074 r2 GREEN**: implementer self-report 67 LOC / 4-level 嵌套，但 commit c59cbdc 时实际 50 LOC / 3-level（快照不一致）。
- **T-060 r3**: implementer self-report"声称 src/ clean"但 tests/ 含 E501 违规（同 scope-drift 模式，已记 EXP 候选）。
- **T-072 r1 incident**: implementer 在 GREEN 阶段声称"22/22 PASS + 1786/1788 全量"，实际有 2 处机械残留（unused type:ignore + E501 docstring），需 continuation 收尾。

**根因分析**:
- implementer / refactorer 的 self-report（GREEN/REFACTOR 完成后的总结）基于主观估算（"看起来没问题"）或快速扫描，未与 git / pytest / mypy / ruff 的真实产出做对齐检查。
- "阶段快照" 的定义（LOC / nesting / complexity 数值）在 tdd-engine 中可能被 implementer 误解为"设计意图"而非"实测数据"。
- 没有自动化验证工具（如提交前的 `git diff --stat` + `wc -l` + cyclomatic 计算脚本）。

**建议改进**:
1. 改 `implementer` AGENT.md §Output Contract - GREEN/REFACTOR 完成时：新增必填项 "**self-reported metrics validation** — 在返回 GREEN verdict 前，运行以下脚本得到真实数据，并在报告中展示：
   - 实际 LOC（`git diff --stat | awk '{s+=$NF} END {print s}'`）
   - 实际 nesting（`radon cc -a src/`）
   - 实际 complexity（`radon mi -n C src/`）
   - 所有新增文件已通过 ruff check + mypy strict
   - 所有 unittest 与 integration tests 通过"
2. 改 `tdd-engine` SKILL.md §Step 3（GREEN 判定）：implementer 提交报告前，orchestrator 自动对 git diff 跑上述指标脚本，与 self-report 比对；偏差 > 20% 时要求 implementer 修正报告或说明原因。
3. 改 `code-review` SKILL.md §Layer 1：新增 check 项"GreenReport-Metrics-Alignment"（对比 GREEN 自报指标与实际 commit diff，偏差记为 L-LOW precision-issue）。

**验证方法**:
5 个连续任务的 GREEN/REFACTOR 自报指标与实际 diff 偏差 < 5%。

---

### EXP-004: 上游契约漂移 —— dev-plan task card AC 与 arch 接口定义不对齐

**现象**:
- **T-073 task card 字面**: AC-T073-1 要求 "list_clusters route return label / item_count / digest 字段"。
- **arch API-016 接口契约**: 实际字段为 topic / content_count / digest（commit 3857992）。
- **T-073 实现**: orchestrator 在 RED 派发前人工识别出字段名漂移，要求 tech-lead 改 task card 按 arch authoritative 补正。最终 implementer 按 arch 实现，通过 code-review。

**根因分析**:
tech-lead 在任务卡 §Acceptance Criteria 撰写阶段，直接用英文"自然语言"描述AC（"return label field"），而非直接引用 arch §3 中已定义的接口字段名。两个文档在不同时段演进，最终漂移。dev-plan 的 AC ≠ arch 的接口字面，导致 implementer 产生歧义（应按 task card 还是 arch？）。

**建议改进**:
1. 改 `tech-lead` AGENT.md §任务卡撰写 - AC 段落：新增硬行 "**接口字段直接复用规则** — 所有涉及架构接口（API / Schema / Repository）的 AC，必须逐字引用 arch 文档的接口定义（含字段名、类型、约束），不得用同义词替代（如不能写'label'而 arch 定义为'topic'）。使用格式：'AC-TXXX-N: [ARCH#§M.API-NNN] 返回包含 topic / content_count / digest / ... 的 JSON 响应'。"
2. 改 `task-decomp` SKILL.md 或 `tech-lead` SKILL.md（如存在）：在 dev-plan 文档 finalize 前，新增 check 项 "AC-arch-field-alignment"，扫描所有 AC 是否包含架构引用且字段名与 arch 一致（可用 yaml/json 对比或人工 review）。
3. 改 `code-review` SKILL.md Layer 1：completeness 维度新增 "task-card vs implementation 字段对齐检查"（若 task card AC 的字段与 CODE-REVIEW 发现的实现字段不一致，标 HIGH consistency issue）。
4. 可选：改 `dev-plan` template，在 AC 段落加入"[Arch Reference]"块，强制 tech-lead 填写对应的 arch chapter/API 编号。

**验证方法**:
后续 3 个 sprint 的 dev-plan 中，所有涉及架构接口的 AC 均包含 `[ARCH#§M.API-NNN]` 形式的引用，且 code-review 层无"task-card vs implementation 字段名不一致"的问题。

---

### EXP-005: 生产接驳缺失 —— DI/signal/lifespan 定义了但无人调用

**现象** (最高优先级 — 连续两次同模式):
- **T-074 r2 carryover**: `scheduler/tasks.py` 中定义了 `CeleryTasks` DI 接口，接受 `session_factory` 参数，但 `main.py` 的 `init_celery()` 仅创建裸 `Celery()` 应用，未实例化 `CeleryTasks(session_factory=...)`。code-review 报告标记"生产接驳缺失属于 T-072 范围"，最终推到 T-075。
- **T-075 r1 R-001**: `boot.py` 定义了 `worker_init_handler(*, celery_app, agent_runner, pipeline_config, **_)`，但**没有** `from celery.signals import worker_process_init; worker_process_init.connect(worker_init_handler)`。生产 celery worker 启动时不会触发该 handler。测试直接手动调用 handler 而非通过 signal dispatch，掩盖了该 gap。

**根因分析**:
implementer 倾向于将"定义接口"与"使用接口"视为两个独立任务，误认为"test GREEN → 实现完整"。尤其在跨模块 DI 场景（taskscheduler 的接驳点在 main.py，DI 的定义在 scheduler/boot.py）中，职责划分不清。task card 的 AC 可能写"定义 worker_init_handler"而非"定义 + 连接"。code-review 时 completeness 维度只检查"代码能编译能通过测试"，未验证"production entry-point 存在且被调用"。

**建议改进** (对应 SPRINT-REVIEW-s7-r1 §SR-003):
1. 改 `tech-lead` AGENT.md §任务卡撰写 - AC 段落：所有涉及 DI / signal handler / lifespan hook 的 AC，必须明确列 "production entry-point exists and is invoked" 硬检查项。使用格式：
   ```
   AC-TXXX-N: [DI/signal/hook] 在生产路径中被实际调用
   - 验证点: main.py / __main__.py / entry-point 中存在对该 DI/signal/hook 的显式实例化 / 连接调用
   - 反例: 仅在 tests/ 中调用，或在生产文件定义但未被 import/使用
   ```
2. 改 `code-review` SKILL.md §Layer 2 completeness 维度：新增 "production-path-exists" check：
   - DI 定义（如 `CeleryTasks.__init__`）必须被 src/ 内某处调用；signal handler 必须被 `signal.connect()` 调用；hook 必须被 lifespan 注册。
   - 反例检测：grep src/ 查找 class/function 是否有调用点，无调用点且非 base class/mixin 时标 MEDIUM completeness issue。
3. 改 `code-review` SKILL.md §Layer 1 脚本：新增 lint 检查 "unused-class-in-production"（标记 src/ 中定义但 src/ 内无调用、仅在 tests/ 中使用的 class），输出为 LOW convention issue。
4. 改 `implementer` AGENT.md §测试完整性自检：新增项 "production path walkthrough — 对于 DI/signal/hook 任务，测试完成后走一遍从 entry-point 到 DI 的完整调用链（可用 grep + code review），确保 production 路径端到端可达"。

**验证方法**:
后续 5 个任务中，DI/signal/hook 相关的 AC 在 code-review 的 completeness 维度零"生产路径缺失"问题；EVENT-LOG 无"生产接驳 gap carryover"记录。

---

### EXP-006: 文件修改后未运行对应 lint / 全量回归

**现象**:
- **T-072 r2 R-001-r2**: implementer 修改 `test_app_entry.py` docstring，原为 96 字单行，改为两行以避免 E501。但未运行 `ruff check tests/unit/api/test_app_entry.py`，导致修改本身通过 ruff 但 code-review Layer 1 捕获到 E501 违规（实际无违规，纯粹是报告时 ruff 版本差异或 cache 问题，但说明了 implementer 未运行 lint）。
- **T-058 correction**: implementer 声称"no new ruff failures"，但 6 个 T-058 文件中有 E501 / F401 等；同时 T-057 的 `gateway.py` 被 implementer 触及但未 lint（a9802d6 遗留 5 个 ruff 错误）。

**根因分析**:
implementer 在收尾阶段时间紧张，跳过 lint / test 的完整运行（只跑目标测试），直接提交。prompt 中虽有"ruff clean"提示，但缺乏"修改任何文件后必须运行对应 lint + 全量回归测试"的强制检查。

**建议改进**:
1. 改 `implementer` AGENT.md §Output Contract - GREEN 完成条件：新增硬行 "**post-implementation lint & test验证** — 在返回 GREEN verdict 前，必须：
   - 运行 `uv run ruff check --fix src/` + 重新运行所有 src/ 相关 linter；
   - 对修改的每个 py 文件及其相关 test 文件运行 `ruff check`；
   - 运行 `uv run pytest tests/unit/<affected-paths>`（全量回归，不是仅 target tests）；
   - 运行 `uv run mypy --strict src/`；
   - 在 GREEN report 中展示 `git diff --name-only` 与每个文件对应的 lint 结果（pass/fail 及修复详情）"
2. 改 `tdd-engine` SKILL.md §Step 3：orchestrator 在 implementer 提交 GREEN 后，自动运行完整 lint (ruff check 全 src/ + mypy strict) 与全量回归 (pytest 全 tests/)；如有失败，立即 blocking-revision（不进 code-review）。
3. 改 `code-review` SKILL.md Layer 1：新增 check 项"all modified files lint clean"（`cataforge skill run code-review -- --check-modified-files src/`），偏离即 FAIL（不进 Layer 2）。

**验证方法**:
后续 10 个任务的 GREEN/REFACTOR 完成报告中，`ruff check` + `mypy --strict` 零违规；code-review Layer 1 零因 lint 违规而 FAIL 的情况。

---

## 已抑制的模式（adaptive-review 注入效果）

### 模式 (a) "make-the-test-pass" 弱断言 — sprint-7 后期明显减少
sprint-7 后半段（T-075 + T-063）implementer prompt 注入了来自 T-072/T-073/T-074 的 adaptive-review 红线清单，特别是"弱断言"检查项：
- **T-075 r1**: 虽有 MEDIUM R-001（signal 未连接），但零 test-quality 类弱断言问题；3 个 LOW 为非阻塞观察。
- **T-063 r1**: 3 LOW 全为非阻塞（module-level monkey-patch / SQLite JSONB mock / 弱断言），但没有演变为 HIGH/MEDIUM。
- **结论**: adaptive-review 收紧分支对 (a) 有显著正向效果；(i) 生产接驳缺失 是新发现、未被 adaptive-review 覆盖。

---

## 跨 sprint 长期债务 & carryover

### SR-002: SQLite-vs-Postgres 集成测试基础设施债务
- **影响范围**: T-073 / T-074 / T-075 / T-063 连环触及（4 任务）。
- **问题**: cluster tag filter / content tag filter 场景在 SQLite 测试只能 mock repo，无法走真 SQL。JSONB `@>` 和 pgvector 操作符在 SQLite 不可用。
- **建议**: sprint-8 排入"T-XXX: 引入 testcontainers-postgres 集成测试 fixture"任务；给 storage 层测试提供真 PG backend。
- **优先级**: MEDIUM（不阻塞 sprint-7，但应近期处理）。
- **参考**: SPRINT-REVIEW-s7-r1 §SR-002。

### 模式 (c): tests/ 累积 ~166 处 pre-existing ruff 债务
- 跨 sprint-1~7 历史积累，未在 EXP 中突出但值得记录。
- 建议: 单独 task "T-XXX: Resolve ruff debt in tests/" (chore, ~2h equivalent refactor)。

---

## 后续行动

### 立即激活（sprint-7 末尾）
1. **reflector 产出**: 本 RETRO 报告 + 对应 5 份 SKILL-IMPROVE-{skill_id}.md（改进 implementer / refactorer / code-review / tech-lead AGENT 与 SKILL）。
2. **orchestrator 同步**: CLAUDE.md 的§项目状态/Learnings Registry 新增本次 retrospective 的 EXP 摘要。

### sprint-8 及以后
1. 按 EXP-001 改进 code-review Layer 1 与 implementer prompt。
2. 按 EXP-002 改进 refactorer AGENT 与 tdd-engine 协议。
3. 按 EXP-004 改进 tech-lead task-card 撰写约束。
4. 按 EXP-005 改进 code-review completeness 维度的生产接驳检查。
5. 按 EXP-006 改进 orchestrator 的 lint/test 验证门禁。
6. SR-002 SQLite→Postgres 集成测试基础设施改造排入 backlog。

---

## 统计摘要

| 指标 | 值 |
|------|-----|
| 项目审查文件数 | 13 份 CODE-REVIEW + 1 SPRINT-REVIEW |
| 审查轮次总数 | 23 轮（平均 1.8 轮/task） |
| self-caused 问题累计 | ~53 个（sprint-7 单 sprint） |
| 识别的反复模式 | 5 个高优先级 EXP + 2 个注记（已抑制模式、长期债务） |
| SKILL-IMPROVE 文件数 | 6 个（覆盖 implementer / refactorer / code-review / tech-lead） |
| 改进触及代理数 | 4 个（implementer / refactorer / code-review / tech-lead） |

