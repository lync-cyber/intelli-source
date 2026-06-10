---
id: "review-dev-plan-intellisource-v1-s10-r2"
doc_type: review
author: reviewer
status: approved
deps: ["dev-plan-intellisource-v1-s10"]
---
# REVIEW: dev-plan-intellisource-v1-s10 — r2（增量验证）

**被审文档**: `docs/dev-plan/dev-plan-intellisource-v1-s10.md`
**doc_type**: dev-plan（Sprint 增补卷 s10）
**审查类型**: revision 增量验证（对照 r1 问题清单逐条核验，仅审查修订触达章节）
**Layer 1**: 沿用 r1 结论（PASS with 1 WARN，分卷 volume_type 模板未注册，不阻塞）
**Layer 2**: 增量执行（focus: consistency / ambiguity / test-quality / completeness / convention）

---

## 逐条闭环核验

### R-001 [HIGH] → 闭环状态: CLOSED

T-BF-2 AC-2 现在明确写明 mock 注入点："`app.state.celery_app` 已被替换为 mock 对象（`app.state.celery_app = mock_celery`）"；AC-3 补充括号注："`（mock 注入点为 `app.state.celery_app`，而非 patch 模块级常量 `intellisource.scheduler.celery_app.celery_app`。）`"。AC-2 同时要求端点内部使用 `celery_instance = getattr(request.app.state, "celery_app", None)` 模式，与现有 `tasks.py` 第 253/331/396 行三处生产访问模式完全对齐。R-001 完全闭环，无残留歧义。

### R-002 [HIGH] → 闭环状态: CLOSED

T-BF-3 所有 AC（AC-1/AC-2/AC-3）已将 `ctx_embedding` 替换为 `ctx.get("embedding")`，与 `process.py` 实际变量访问方式一致。notes 增加了精确描述："fix 目标是在 `existing_processed is not None` 分支（约 line 112-113）内新增 `embedding_val = ctx.get("embedding")` 读取逻辑；该读取在现有代码中仅存在于 `else` 分支（约 line 115-118，变量名 `embedding_val`/`embedding_arg`），fix 后两分支均需处理 embedding 回填。" 行号与代码实际一致（line 112 = `if existing_processed is not None:`，line 113 = `processed = existing_processed`；else 分支从 line 114 起）。R-002 完全闭环。

### R-003 [MEDIUM] → 闭环状态: CLOSED

AC-5 现在明确写："`backfill_embeddings.name == "backfill_embeddings"` 属性断言不满足此 AC，仅作辅助断言可选添加。" 只剩 `celery_app.tasks["backfill_embeddings"]`（或包含性断言）作为唯一有效验证路径。无效备选已降级。R-003 完全闭环。

### R-004 [MEDIUM] → 闭环状态: PARTIAL（新回归——见 [R-NEW-001]）

T-BF-2 deliverables 第一条现已写为 `contents.py | content_admin.py` 的管道分隔备选语法。r1 建议的 A|B 表达已采用。**但产生新问题**：主卷 `dev-plan-intellisource-v1` frontmatter 中不含 `project_features.deliverables_accept_alternation: true`，sprint-review Layer 1 的 `check_deliverables` 在不启用该特性标志时不会将 `A | B` 视为或关系，而是寻找字面含管道符的文件路径，将在 `deliverables_exist` 检查时报 FAIL。详见 [R-NEW-001]。

### R-005 [MEDIUM] → 闭环状态: CLOSED

新增 AC-7 [OPTIONAL]，内容为：Given embed 返回维度不符时，Then 跳过 update 并记录 warn 日志，不 crash，不 raise。可选标注明确，sprint-review 可追踪实现决策。R-005 完全闭环。

### R-006 [MEDIUM] → 闭环状态: PARTIAL（触发条件已补，但产生新一致性问题——见 [R-NEW-002]）

arch-sync 说明现已包含明确截止条件（"pre-deploy review 为硬性截止"），并写明"此补录项已纳入 BACKLOG 候选"。触发条件不明确的问题已解决。但 BACKLOG 文件中未找到对应条目（grep `API-026` / `backfill` 均无命中），以及 "API-026" 命名本身与 arch 文档中已删除的编号冲突——详见 [R-NEW-002]。

### R-007 [LOW] → 闭环状态: CLOSED

T-BF-3 notes 末尾已新增："`tests/unit/agent/tools/` 目录需新建，并放置空 `__init__.py`，确保 pytest 模块发现正常。" R-007 完全闭环。

### R-008 [LOW] → 闭环状态: CLOSED

AC-6 末尾现已标注 AC 责任边界分工："AC-3 覆盖调用次数（`call_count == 3`），AC-6 覆盖 fallback 逻辑的参数精确匹配。" AC-3 与 AC-6 的重叠歧义消除。R-008 完全闭环。

---

## 新增问题（修订引入）

### [R-NEW-001] HIGH: T-BF-2 deliverables A|B 语法无对应特性标志，sprint-review Layer 1 将误判 FAIL

- **category**: consistency
- **root_cause**: self-caused
- **描述**: T-BF-2 deliverables 第一条采用了 `src/intellisource/api/routers/contents.py | src/intellisource/api/routers/content_admin.py` 的管道符分隔语法，意图表达"任一存在即可"。然而 sprint-review Layer 1 的 `check_deliverables` 对该语法的解析取决于 dev-plan 主卷 frontmatter 中的 `project_features.deliverables_accept_alternation: true` 特性标志（见 sprint-review SKILL.md §project_features schema）。检查 `docs/dev-plan/dev-plan-intellisource-v1`（主卷，非 sprint 分卷）的 frontmatter，该字段缺失。未启用特性标志时，`check_deliverables` 会将整条字面字符串（含管道符）作为文件路径查找，磁盘上不存在此路径，导致 `deliverables_exist` 检查报 FAIL，阻塞 sprint-review 流程。r1 的 R-004 建议使用 A|B 表达，但未指明需要同步启用特性标志——此次修订忠实执行了 r1 建议但遗漏了必要的前置条件。
- **建议**: 选择以下方案之一：（1）在 `docs/dev-plan/dev-plan-intellisource-v1`（主卷）frontmatter 中新增 `project_features:\n  deliverables_accept_alternation: true`，同时确认主卷 `project_features` 块不影响其他 sprint 分卷的现有 deliverables 检查；（2）或将 deliverable 改回单一路径（`contents.py` 作为优先选择），在 notes 中说明 implementer 若选择 `content_admin.py` 须在合并前更新此字段，放弃 A|B 语法以保持 Layer 1 可执行性。两方案各有权衡：方案 1 解锁 A|B 语法全局可用但需要验证其他 sprint 分卷无副作用；方案 2 放弃语法表达力但零配置变更风险。

---

### [R-NEW-002] MEDIUM: arch-sync 说明使用 "API-026" 命名与 arch 文档已删除编号冲突

- **category**: consistency
- **root_cause**: self-caused
- **描述**: T-BF-2 arch-sync 说明多处使用 "API-026" 作为 backfill 端点在 arch 中的待录编号（如"补录 API-026"、"API-026 当前仅在 dev-plan 内联定义"）。然而检查 `docs/arch/arch-intellisource-v1-api.md` NAV 第 18 行明确声明："API-001..API-025（API-010/011/026-029 工作流相关已移除，由管道配置替代）"。即 API-026 至 API-029 是已显式删除的编号，不可再次分配——前次 s7 审查（REVIEW-dev-plan-intellisource-v1-s7-r3.md [R-008]）已因同样原因判定 HIGH 并要求修复。若 tech-lead 按 arch-sync 说明提交 arch-amendment 时使用 API-026，将再次触发 arch 编号冲突。注：BACKLOG 文件中也未找到对应的 API 补录追踪条目（grep 无命中），"已纳入 BACKLOG 候选"的说法当前无法核实。
- **建议**: 将 arch-sync 说明中所有 "API-026" 引用改为 "API-030"（或当前 arch API 序列末尾后的下一可用编号，视 arch-intellisource-v1-api.md 实际末尾编号而定——当前末尾为 API-025，故下一可用号为 API-026 是保留删除编号、API-030 需先确认无跳号冲突，建议标注 "[ASSUMPTION: 补录时由 tech-lead 在 arch amendment 中确认实际可用编号]" 以避免此处硬编码）；同时在 BACKLOG 中实际创建追踪条目，或将"已纳入"措辞改为"建议纳入"以与现状一致。

---

## 正面确认（[previously-approved]）

- **AC 行为断言性** [previously-approved from r1]: 全部 AC 保持 Given-When-Then 格式，无主观措辞。
- **依赖图一致性** [previously-approved from r1]: T-BF-1→T-BF-2 串行、T-BF-3 独立并行的三处声明（§2 Mermaid、并行批次描述、任务卡依赖字段）仍一致。
- **E-004 引用** [previously-approved from r1]: ProcessedContent 实体引用（embedding VECTOR(1024) NULL）与 AC 中 NULL 判断和 fallback 逻辑继续对齐。
- **R-EMB 忠实 mock** [previously-approved from r1]: T-BF-1 / T-BF-3 notes 均明确要求 mock 返回 `list[float]`（1024 维），不得返回 `True`/`1`/dict。

---

## 汇总与判定

| 编号 | 级别 | category | 状态 | 简述 |
|------|------|----------|------|------|
| R-001 | HIGH | consistency | CLOSED | T-BF-2 mock 路径约束已与 app.state.celery_app 模式对齐 |
| R-002 | HIGH | ambiguity | CLOSED | T-BF-3 AC 变量名已改为 ctx.get("embedding")，行号对齐 |
| R-003 | MEDIUM | test-quality | CLOSED | AC-5 name 属性断言已明确降级为不满足 AC |
| R-004 | MEDIUM | consistency | PARTIAL | A\|B 语法采用但缺特性标志，见 R-NEW-001 |
| R-005 | MEDIUM | completeness | CLOSED | AC-7 [OPTIONAL] 维度校验已添加 |
| R-006 | MEDIUM | consistency | PARTIAL | 触发条件已补，但 API-026 编号冲突，见 R-NEW-002 |
| R-007 | LOW | convention | CLOSED | 目录新建提醒已写入 notes |
| R-008 | LOW | test-quality | CLOSED | AC-3 / AC-6 职责边界已明确 |
| R-NEW-001 | HIGH | consistency | 新引入 | deliverables A\|B 语法无特性标志支撑，Layer 1 将 FAIL |
| R-NEW-002 | MEDIUM | consistency | 新引入 | API-026 为已删除编号，arch-sync 说明需改用下一可用编号 |

**存在 HIGH 级别问题（R-NEW-001）→ verdict: needs_revision**

修订重点：R-NEW-001（deliverables A|B 语法与特性标志配置不一致）为 HIGH，必须在 TDD 实现阶段前解决，否则 sprint-review Layer 1 将因 deliverables_exist 检查 FAIL 阻塞流程。R-NEW-002 为 MEDIUM，建议同批修复以防止 arch amendment 提交时引入已删除编号冲突。

---

## Inline-Fix 闭环记录（orchestrator）

`needs_revision(2)` 触发人工介入门。原 r1 的 2 个 HIGH（R-001/R-002）已在 r2 确认 CLOSED；剩余 R-NEW-001/R-NEW-002 为修订引入的机械 doc 卫生问题、均不阻塞 TDD 开工。用户裁决（AskUserQuestion）选择「orchestrator 内联修 + 进开发」，由主线程逐条修复后放行，verdict 实质等价 approved_with_notes。

| 编号 | 级别 | 修复方式 | 验证 |
|------|------|---------|------|
| R-NEW-001 | HIGH | 采用 reviewer 建议方案（2）：T-BF-2 deliverables 还原为单一路径 `src/intellisource/api/routers/contents.py`（磁盘已存在），`content_admin.py` 备选移入 prose 说明，放弃 A\|B 管道语法 → 零特性标志配置风险 | `cataforge skill run doc-review -- dev-plan docs/.../s10.md` Layer 1 **PASS**（deliverables_exist 通过，仅模板回退 WARN） |
| R-NEW-002 | MEDIUM | arch-sync 全部 "API-026" 改为「编号取 arch 当时下一可用值，`[ASSUMPTION]` 待 arch amendment 确认；API-026~API-029 已声明删除不可复用」；"已纳入 BACKLOG" 改为登记进 BACKLOG（backfill 条目 arch-sync 跟进项，由 orchestrator 同步落 BACKLOG.md） | 文档措辞与 arch 删除编号声明一致；BACKLOG 落项见 backlog-intellisource-v1 |

**闭环结论**: R-NEW-001/R-NEW-002 by-orchestrator-inline-fix CLOSED；dev-plan-s10 status → approved，进入 development。
