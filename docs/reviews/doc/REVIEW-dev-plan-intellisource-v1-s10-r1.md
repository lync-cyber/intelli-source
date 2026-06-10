---
id: "review-dev-plan-intellisource-v1-s10-r1"
doc_type: review
author: reviewer
status: approved
deps: ["dev-plan-intellisource-v1-s10"]
---
# REVIEW: dev-plan-intellisource-v1-s10 — r1

**被审文档**: `docs/dev-plan/dev-plan-intellisource-v1-s10.md`
**doc_type**: dev-plan（Sprint 增补卷 s10）
**Layer 1**: PASS（1 WARN: 模板未注册 sprint volume_type，回退自声明 required_sections，不阻塞）
**Layer 2**: 完整执行（dev-plan 不在 DOC_REVIEW_L2_SKIP_DOC_TYPES 白名单）

---

## 问题列表

### [R-001] HIGH: T-BF-2 AC-2 缺少 send_task 调用方式的显式约束——生产路径使用 `request.app.state.celery_app` 而非裸模块导入

- **category**: consistency
- **root_cause**: self-caused
- **描述**: 项目现有 API 层（`tasks.py`）通过 `celery_instance = getattr(request.app.state, "celery_app", None)` 访问 Celery 实例再调用 `send_task`，而非从模块直接导入 `celery_app.send_task`。T-BF-2 AC-2/AC-3 对 `celery_app.send_task` 的断言写法未说明该如何在 FastAPI endpoint 测试中 mock——若 implementer 选择裸导入 `from intellisource.scheduler.celery_app import celery_app; celery_app.send_task(...)`，与 `app.state.celery_app` 方案的 mock 路径完全不同。AC 要求"`celery_app.send_task` 被调用"但未指明 mock 注入点，导致测试编写者需要猜测 mock 路径，存在测试通过但生产接线断的风险。
- **建议**: 在 T-BF-2 context_load 或 notes 中补充一行约束，明确要求新端点遵循现有模式（`request.app.state.celery_app`），并在 AC-2/AC-3 的 mock 说明中注明 mock 对象为 `app.state.celery_app`（通过 `app.state.celery_app = mock_celery`），而非 patch 模块级常量。这与 `test_tasks_router_send_task_contract.py` 的现有测试风格对齐。

---

### [R-002] HIGH: T-BF-3 AC 变量名歧义——`ctx_embedding` 与 `process.py` 实际变量名不匹配

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: T-BF-3 AC-1/AC-2/AC-3 中使用 `ctx_embedding: list[float]` 命名处理上下文中的 embedding 值，但查看现有 `src/intellisource/agent/tools/executes/process.py` 第 114–118 行可见，该变量在 `else` 分支取名为 `embedding_val = ctx.get("embedding")` / `embedding_arg`，且当前 `existing_processed is not None` 分支（第 112–113 行）并无 embedding 相关逻辑——fix 需要新增取 embedding 的代码。AC 中 `ctx_embedding` 是一个不存在于当前代码的变量名，implementer 必须自行推断其实现细节，违反了 AC 作为行为规约的可读性原则。此外，T-BF-3 notes 提到"约 line 111-136"可以找到 embed 调用，但实际嵌入调用在 `else` 分支（第 115–118 行），`existing_processed is not None` 分支（第 112–113 行）根本没有 embed 调用，notes 与代码现状的对应关系会使 implementer 产生误解。
- **建议**: 在 T-BF-3 AC 中将 `ctx_embedding` 改写为 `ctx.get("embedding")` 的形式，或补充说明"fix 需要在 existing_processed 分支内新增 `embedding_val = ctx.get('embedding')` 取值逻辑"，使 AC 与现有代码结构直接对应；修正 notes 中行号说明，准确指向 else 分支（lines 114–136），并澄清 fix 目标是在 `existing_processed is not None` 分支（lines 112–113）新增条件回填逻辑。

---

### [R-003] MEDIUM: T-BF-1 AC-5 生产路径 AC 强度不足——`celery_app.tasks["backfill_embeddings"]` 在 Celery 延迟注册时可能为假阳性

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: AC-5 提出了两条备选验证方式：一是 integration 测试验证 `celery_app.tasks["backfill_embeddings"]` 可取到，二是"直接断言函数对象带 `name` 属性 = `'backfill_embeddings'`"。第二条实际上是 `self-test`——只要写了 `@celery_app.task(name="backfill_embeddings")`，`backfill_embeddings.name == "backfill_embeddings"` 必然为真，无法验证任务真正被注册到 Celery app 的 task registry。若 implementer 选择第二条路，AC-5 等同无效，不能防止"定义了函数但 Celery worker 不认识该任务"的场景。注：现有 `test_celery_routes.py` 已有类似 registry 验证的先例可参考。
- **建议**: 将 AC-5 中第二备选明确降级为"不可满足 AC"：明确要求 integration 测试中通过 `celery_app.tasks["backfill_embeddings"]` 或等价的 `celery_app.tasks.keys()` 包含性断言验证注册，删除"直接断言函数对象带 name 属性"作为等价替代的表述，保留其仅作为辅助断言（可选）。

---

### [R-004] MEDIUM: T-BF-2 deliverables 引用 `contents.py` 但实际应核查是否与 sources 路由冲突

- **category**: consistency
- **root_cause**: self-caused
- **描述**: T-BF-2 deliverables 第一条写 `src/intellisource/api/routers/contents.py`（新增端点），该文件已存在且注册于 `main.py`（`app.include_router(contents.router, prefix="/api/v1")`）。新端点路径为 `POST /api/v1/content/backfill-embeddings`（注意：单数 `content`，而现有路由 GET `/contents` 是复数），文件名 `contents.py` 无歧义。然而 AC-1 生产路径 AC 给出了两个备选文件名：`contents.py` 或新建的 `content_admin.py`——deliverables 中仅列 `contents.py`，若 implementer 选择新建 `content_admin.py`，deliverables 就不匹配，会在 sprint-review Layer 1 的 deliverables_exist 检查时报 FAIL。此外，备注"若路由文件需拆分则新建 `content_admin.py` 再 include_router"是一个条件决策，但 deliverables 没有用 `A | B` 语法表达或任何等价说明。
- **建议**: 将第一条 deliverable 改为 `src/intellisource/api/routers/contents.py`（优先）**或** `src/intellisource/api/routers/content_admin.py`（若文件按审查建议拆分），显式使用备选语法（`A | B`），或在 `notes` 中说明 implementer 做决策后须同步更新 deliverables 列表。

---

### [R-005] MEDIUM: T-BF-1 风险 R-BF-2 建议的向量维度校验未转化为 AC 或可选 deliverable

- **category**: completeness
- **root_cause**: self-caused
- **描述**: 风险 R-BF-2 指出 embed 向量维度不一致会导致 backfill 任务 crash，并建议在 update 前加 `len(embedding) == EMBEDDING_DIM` 校验，但标注"实现可在 GREEN 阶段根据 implementer 判断决定是否纳入（非强制 AC）"。然而项目已有 `EMBEDDING_DIM: int = 1024`（`storage/models.py:28`）和 `embedding_dimension: int = Field(1024, ...)` （`settings.py`），校验实现成本极低。不将此作为可选 AC 或至少可选 deliverable，意味着 sprint-review AC 覆盖检查时无法追踪该保护是否被实现。
- **建议**: 在 T-BF-1 中新增一条可选 AC（标注 `[OPTIONAL]` 或 `[RECOMMENDED]`），描述：Given embed 返回 `list[float]` 但 `len() != EMBEDDING_DIM`，When 处理该记录，Then 跳过 update 并记录 warn 日志，不 crash——如此即使 implementer 选择不实现，sprint-review 也有明确的覆盖决策记录，而非静默跳过。

---

### [R-006] MEDIUM: `arch-sync 说明` 延后补录 API-026 的决策缺乏触发条件——下游 sprint 若引用 API 文档会产生误读

- **category**: consistency
- **root_cause**: self-caused
- **描述**: T-BF-2 arch-sync 说明提出延后补录 API-026 到 arch 文档，理由是"端点语义简单"。然而 arch-intellisource-v1-api 目前声明对外接口范围为"API-001 至 API-025"（M-011 arch 定义），任何依赖 arch-intellisource-v1-api 的下游文档（test-report、deploy-spec 等）或 sprint-review 交叉引用检查都可能无法感知 API-026 的存在。"下一次 arch review 时补录"没有明确触发条件（是下次 sprint 完成后？还是 pre-deploy 前？），容易无限期推迟。
- **建议**: 在 arch-sync 说明中补充明确触发条件："T-BF-2 approved 合并后 1 个 sprint 内补录 API-026，或 pre-deploy review 前为硬性前提条件，以先到者为准。"并建议在 BACKLOG 中创建一条追踪项而非仅依赖 PR 描述。

---

### [R-007] LOW: T-BF-3 deliverables 中测试路径 `tests/unit/agent/tools/test_process_inline_backfill.py` 对应目录当前不存在

- **category**: convention
- **root_cause**: self-caused
- **描述**: 当前项目 `tests/unit/agent/` 目录存在，但其下没有 `tools/` 子目录（已验证）。deliverable 路径 `tests/unit/agent/tools/test_process_inline_backfill.py` 需要 implementer 新建 `tools/` 目录，并保证 `__init__.py` 存在以使 pytest 正确发现。这不是错误，但未在 notes 中提醒，可能导致 implementer 忘记建目录或未加 `__init__.py` 而使测试静默丢失。
- **建议**: 在 T-BF-3 notes 中添加一句："`tests/unit/agent/tools/` 目录需新建，并放置空 `__init__.py`，确保 pytest 模块发现正常。"

---

### [R-008] LOW: T-BF-1 AC-3 断言 embed mock 被调用 3 次但未约束调用顺序或调用参数精确匹配方式

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: AC-3 要求"embed mock 被调用 3 次，调用参数为各条记录的 `body_text`（非空时）或 `title`（body_text 空时）"，但没有说明断言方式是 `assert_called_once_with` / `call_args_list` 逐一匹配还是仅断言 call_count == 3。若 implementer 只断言调用次数，则 body_text/title fallback 逻辑的正确性不被验证（AC-6 部分覆盖了 fallback，但 AC-3 + AC-6 之间有重叠而无精确说明哪条 AC 负责哪种断言形式）。
- **建议**: 在 AC-3 中补充断言形式指引，例如"通过 `mock.call_args_list` 逐一断言每次调用的 `text` 参数值"；或者在 notes 中说明 AC-3 覆盖 call_count，AC-6 覆盖 fallback 逻辑精确断言，以消除双重覆盖的歧义。

---

## 汇总与判定

| 编号 | 级别 | category | 简述 |
|------|------|----------|------|
| R-001 | HIGH | consistency | T-BF-2 AC-2/AC-3 mock 路径未与现有 `app.state.celery_app` 模式对齐 |
| R-002 | HIGH | ambiguity | T-BF-3 AC 中 `ctx_embedding` 变量名与 process.py 实际代码不对应 |
| R-003 | MEDIUM | test-quality | T-BF-1 AC-5 第二备选（name 属性断言）等同无效，不能防止任务未注册到 registry |
| R-004 | MEDIUM | consistency | T-BF-2 deliverables 未用 A\|B 表达两备选文件名，sprint-review L1 存在假 FAIL 风险 |
| R-005 | MEDIUM | completeness | R-BF-2 建议的维度校验未转化为可选 AC，sprint-review 无法追踪实现决策 |
| R-006 | MEDIUM | consistency | API-026 补录无明确触发条件，易无限期推迟，下游文档无法感知新 API |
| R-007 | LOW | convention | T-BF-3 deliverable 路径中 `tests/unit/agent/tools/` 目录不存在，notes 未提醒 |
| R-008 | LOW | test-quality | T-BF-1 AC-3 未说明 embed 调用参数的断言精确度，与 AC-6 存在覆盖歧义 |

**存在 HIGH 级别问题（R-001、R-002）→ verdict: needs_revision**

## 正面肯定

- 全部 3 张任务卡的 AC 均为行为断言（Given-When-Then 形式），无"应正确渲染"等主观措辞，符合 ac-observability 要求。
- T-BF-1 AC-3 明确要求 mock embed 返回真实 `list[float]` 长度 1024，并在 notes 中强调"不得返回 `True`/`1`/dict"，R-EMB 教训已内化。
- T-BF-3 模块引用（M-006/M-009）、AC-1/AC-2/AC-4 幂等保护均可验证，逻辑完整。
- 依赖图（T-BF-1→T-BF-2 串行，T-BF-3 独立并行）与 §2 Mermaid 图、任务卡依赖字段三处一致。
- E-004 ProcessedContent 实体引用（embedding VECTOR(1024) NULL、body_text NOT NULL）与 AC 中 NULL 判断和 fallback 逻辑对齐正确。
- API-007 参考端点（202 + task_chain_id 结构）被合理用于同类 202-accepted 模式参考，T-BF-2 响应结构（`status + task_id`）轻量化设计合理。
- arch-sync 延后决策的理由（语义简单、不致误读）已内联说明，符合项目决策记录要求。

---

**Verdict**: `needs_revision`

修订重点：R-001（T-BF-2 mock 路径约束）和 R-002（T-BF-3 AC 变量名与 process.py 对应）为 HIGH，必须修复后方可进入 TDD 实现阶段。R-003/R-004/R-005/R-006 为 MEDIUM，建议同批修复以提升任务卡可执行性。
