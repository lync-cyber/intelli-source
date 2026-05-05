---
id: "review-dev-plan-intellisource-v1-s7r-r2"
doc_type: review
author: reviewer
status: approved
deps: ["dev-plan-intellisource-v1-s7r"]
---
# REVIEW-dev-plan-intellisource-v1-s7r-r2: Sprint 7r Pre-Deploy Remediation Dev-Plan 审查（r2 闭环验证）

> Layer 1: 降级（cataforge exit 127，命令不可用）→ 直接执行 Layer 2 AI 语义审查（含 Layer 1 代偿结构检查）
> 被审文档: `docs/dev-plan/dev-plan-intellisource-v1-s7r.md`（168 行，tech-lead revision 后）
> 审查范围: T-080 / T-081 / T-082 三张 remediation 任务卡；重点验证 r1 六个问题闭环情况

---

## Layer 1 代偿结构检查

| 检查项 | 结果 | 说明 |
|--------|------|------|
| Front matter 完整性 (id/doc_type/author/status/deps/consumers/volume/split_from) | 通过 | 全部字段齐全；`status: draft` 正确 |
| NAV 块存在且与章节一致 | 通过 | NAV 列出 T-080 / T-081 / T-082，与 §3 完全对应 |
| 任务 ID 连续性（T-080~T-082） | 通过 | 连续无跳号；与 s8 范围 T-064~T-079 无冲突 |
| 依赖链无环 | 通过 | T-080（无依赖）→ T-081 → T-082，线性链 |
| 必填字段（task_kind / tdd_mode / tdd_acceptance / deliverables / context_load / risk） | 通过 | 三张卡均具备全部必要字段 |
| TDD_LIGHT_LOC_THRESHOLD=150 合规 | 通过 | T-080 LOC<50→light；T-081 LOC~260→standard；T-082 chore→light |
| 行数 ≤ DOC_SPLIT_THRESHOLD_LINES=300 | 通过 | 168 行，阈值内 |
| 未处理 TODO/TBD/FIXME | 通过 | 无未标注占位符；T-080 risk 中含 `[ASSUMPTION]` 提示，符合规范 |

---

## r1 六项问题闭环验证

### R-001 (HIGH) — T-080 溯源标签与 test-report 缺陷定义不符

**闭环状态: CLOSED**

验证点：
- 任务标题已改为 `T-080: runner.py DB_URL 环境变量化（12-factor §III Config）`，无 DEF-006 字样 ✓
- `溯源` 字段改为 `CODE-REVIEW-T-074-r2 新引入观察段落（runner.py 硬编码 DB_URL）+ 12-factor §III Config 原则` ✓
- 脚注明确说明：`DEF-006 实指 trigger_type/execution_mode 硬编码，已由 T-075 闭环；本任务针对 CODE-REVIEW-T-074-r2 独立观察的 DB_URL 硬编码问题，与 DEF-006 无关` ✓
- `context_load` 改为 `arch-intellisource-v1#§2.M-009` + `CODE-REVIEW-T-074-r2`，已不含 test-report DEF-006 引用 ✓
- 追溯链完整，实现者可通过 CODE-REVIEW-T-074-r2 直接定位真实来源 ✓

---

### R-002 (HIGH) — T-081 AC-2b 规格存在技术不可行性（function-scope Alembic 迁移 + 事务回滚）

**闭环状态: CLOSED**

验证点：
- AC-2a（session-scoped `pg_container`）：`执行一次 alembic upgrade head`，明确注明 `DDL 隐式提交，仅需运行一次，不可在 function-scope 内重复执行` ✓
- AC-2b（function-scoped `pg_session`）：通过 `SAVEPOINT` + `ROLLBACK TO SAVEPOINT` 实现 DML 隔离，明确 `不重复执行 Alembic 迁移` ✓
- AC-2c（可选 function-scoped `pg_truncate`）：为 DDL 场景或 savepoint 不适用场景提供 TRUNCATE 备用路径 ✓
- `mitigation` 新增 `fixture lifecycle 选型理由`：详细解释 PostgreSQL DDL 隐式提交机制、为何 Alembic 只运行一次，以及 function-scoped 隔离方案选型依据 ✓
- `deliverables` 同步更新：列出三个 fixture（pg_container / pg_session / pg_truncate）✓

---

### R-003 (MEDIUM) — T-081 context_load 误引 DEF-001

**闭环状态: CLOSED**

验证点：
- `context_load` 改为 `test-report-intellisource-v1#§6`（BD-001 / BD-002 背景；DEF-001 与本任务无关，无需参阅）✓
- DEF-001 不再作为需要参阅的背景依赖，已通过括号注释说明排除原因 ✓
- 引用正确聚焦于 BD-001 / BD-002，符合 T-081 技术目标 ✓

---

### R-004 (MEDIUM) — T-080 AC-4 的 deliverable 语义混入规范性说明

**闭环状态: CLOSED**

验证点：
- AC-4 修改为纯行为断言：`deploy-spec 后续可直接通过 DATABASE_URL=postgresql+psycopg2://... 注入，无需任何源码改动（行为断言：仅修改环境变量即可切换数据库后端，源码零修改）` ✓
- 注释要求已移入 `mitigation`：`编码规范提示（非 AC）：读取环境变量的代码行旁加单行注释 # 12-factor §III Config，便于后续维护者理解合规意图；此为代码可读性建议，不纳入测试验收` ✓
- AC-4 不再包含"AC 以注释形式记录在代码中"歧义语义；括号内的澄清说明（行为断言）使验收意图更清晰 ✓

---

### R-005 (LOW) — T-082 标题未显式标注 BD-003 溯源 ID

**闭环状态: CLOSED**

验证点：
- 标题改为 `T-082: tests/ ruff 债务清理（BD-003 / ~166 处 pre-existing 违规）` ✓
- 与 T-080（12-factor §III Config）和 T-081（BD-001 / SR-002 闭环）命名风格对齐 ✓

---

### R-006 (LOW) — T-081 AC-6 CI 配置的两种路径缺少优先级指引

**闭环状态: CLOSED**

验证点：
- AC-6 已建立明确优先级结构：
  - **首选**：在已有 `.github/workflows/ci.yml` 中确认 Docker daemon 可用（ubuntu-latest 已内置 Docker，通常无需额外配置；仅需确认无 `--no-docker` 或 rootless 限制）✓
  - **降级**：GitHub Actions 原生 `services: postgres: image: pgvector/pgvector:pg16`（无需 testcontainers，仅在 CI 中替换 fixture 后端）✓
  - 两种方式均须在 README 或 CONTRIBUTING 补充测试运行命令，说明本地 vs CI 差异 ✓
- 实现者不再面临无差别并列选项，决策路径清晰 ✓

---

## Layer 2 全维度正常审查

### 新问题扫描

本节对修订后的完整文档执行全维度审查，以下为扫描结果：

**完整性 (completeness):** 三张卡的 deliverables 字段完整，risk + mitigation 均有；T-081 新增 AC-7（全量 pytest 通过要求，含新增 PG 集成测试）覆盖了回归验证场景。无遗漏 ✓

**一致性 (consistency):** affected_files 与 deliverables 各卡自洽。T-081 deliverables 中新增 `tests/integration/test_pg_vector_search.py`，AC-4/AC-5 有对应的专项测试要求，两者对应 ✓。T-082 `依赖: T-081` 与说明文字一致（确保 T-081 新增 PG fixture 代码纳入清理范围）✓

**可行性 (feasibility):** T-081 修订后的 fixture lifecycle 设计（session-scoped Alembic + function-scoped savepoint/truncate）符合 PostgreSQL 真实行为约束，技术上可行 ✓。T-080 的 ENV 环境变量命名在 risk 中已标注 `[ASSUMPTION]` ✓

**安全性 (security):** T-080 `security_sensitive: false` 合理（DATABASE_URL 通过环境变量注入是 12-factor 安全最佳实践，无鉴权逻辑变更）。无安全问题 ✓

**规范性 (convention):** 字段命名、枚举值、任务卡结构符合 dev-plan 规范；使用 LOC 代码量描述而非时间估算，符合 COMMON-RULES §禁止估算任务用时 ✓

**清晰度 (ambiguity):**

发现一处 LOW 级不一致，记录如下：

---

### [R-007] LOW: T-081 deliverables 第 6 条与 AC-6 优先级结构存在轻微语义落差

- **category**: consistency
- **root_cause**: self-caused
- **描述**: AC-6 已建立明确的首选/降级优先级结构（首选：确认 CI Docker daemon；降级：GitHub Actions 原生 postgres service container）。但 `deliverables` 第 6 条仍写作 `.github/workflows/ci.yml`（或已有 workflow）— docker 环境配置确认；**或** `docker-compose.test.yml`（新建），使用"或"连接，暗示两者等价可选。这与 AC-6 的首选/降级语义不完全对齐：AC-6 排除了"docker-compose.test.yml 新建"作为 CI 配置路径（AC-6 的降级方案是 GitHub Actions 原生 postgres service container，而非 docker-compose），但 deliverables 仍保留了该选项。实现者依赖 AC-6 决策时不会受影响，但 deliverables 层面的描述与 AC-6 存在理论上的选项不一致。
- **建议**: 将 deliverables 第 6 条更新为与 AC-6 一致的表述，例如：`.github/workflows/ci.yml`（确认 Docker daemon 可用；或按降级方案配置原生 postgres service container）；移除 `docker-compose.test.yml（新建）` 作为 CI 选项，若需保留 docker-compose 仅供本地开发使用则另行说明。
- **状态**: CLOSED（orchestrator 2026-05-05 inline 修复）— sprint-7r dev-plan T-081 deliverables 第 6 条与 affected_files 行均已更新：deliverables 改为"`.github/workflows/ci.yml`（或已有 workflow）— 按 AC-6 优先级配置：首选确认 ubuntu-latest runner 内置 Docker daemon 可用以驱动 testcontainers；若不可用则降级改用 GitHub Actions 原生 `services: postgres` 容器并在 README 标注"；affected_files 改为"`.github/workflows/ci.yml`（按 AC-6 首选/降级方案任选其一）"。`docker-compose.test.yml` 不再作为 CI 路径选项。用户决策（2026-05-05）：跳过 r3 复审，inline 修复直接生效。

---

## 审查结论

**approved_with_notes**

r1 全部 6 个问题（2 HIGH + 2 MEDIUM + 2 LOW）均已闭环：

| r1 问题 | 级别 | 闭环状态 |
|--------|------|--------|
| R-001: T-080 溯源标签错误 | HIGH | closed |
| R-002: T-081 AC-2b 技术不可行性 | HIGH | closed |
| R-003: T-081 context_load 误引 DEF-001 | MEDIUM | closed |
| R-004: T-080 AC-4 混入规范性说明 | MEDIUM | closed |
| R-005: T-082 标题缺 BD-003 ID | LOW | closed |
| R-006: T-081 AC-6 缺少优先级指引 | LOW | closed |

本次审查新发现 1 个 LOW 级问题（R-007），无 CRITICAL 或 HIGH 问题。

| 本次新增问题 | 级别 | 数量 |
|---------|------|------|
| CRITICAL | — | 0 |
| HIGH | — | 0 |
| MEDIUM | — | 0 |
| LOW | R-007 | 1 |

文档可进入下一阶段；R-007 作为注记建议，由 orchestrator 决定是否要求修复。
