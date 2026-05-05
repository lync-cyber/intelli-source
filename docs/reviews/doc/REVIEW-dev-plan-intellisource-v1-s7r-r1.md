---
id: "review-dev-plan-intellisource-v1-s7r-r1"
doc_type: review
author: reviewer
status: approved
deps: ["dev-plan-intellisource-v1-s7r"]
---
# REVIEW-dev-plan-intellisource-v1-s7r-r1: Sprint 7r Pre-Deploy Remediation Dev-Plan 审查

> Layer 1: 降级（cataforge 命令不可用，exit 127）→ 直接执行 Layer 2 AI 语义审查
> 被审文档: `docs/dev-plan/dev-plan-intellisource-v1-s7r.md`（163 行）
> 审查范围: T-080 / T-081 / T-082 三张 remediation 任务卡

---

## 上游文档加载摘要

| 文档 | 关键章节 | 核心事实 |
|------|---------|---------|
| test-report-intellisource-v1 §6.1 | 缺陷清单 | DEF-006: runner.py `_persist` 中 `trigger_type`/`execution_mode` 硬编码 → T-075 已闭环（`closed`） |
| test-report-intellisource-v1 §6.2 | 测试基础设施债务 | BD-001: SQLite-vs-PG 集成缺口（MEDIUM）；BD-003: tests/ ~166 ruff 警告（LOW） |
| SPRINT-REVIEW-s7-r1 §问题列表 | SR-002 | SQLite-vs-Postgres 集成测试基础设施债务，建议 sprint-8 引入 testcontainers-postgres |
| dev-plan-intellisource-v1-s8 §3 | 任务编号 | T-064~T-079（含 T-071 集成测试），s7r T-080~T-082 无冲突 |

---

## Layer 2 AI 语义审查

### 前置结构检查（Layer 1 代偿）

| 检查项 | 结果 | 说明 |
|--------|------|------|
| Front matter 完整性 (id/doc_type/author/status/deps/consumers/volume/split_from) | 通过 | 全部字段齐全 |
| NAV 块存在且与章节一致 | 通过 | NAV 列出三张卡，对应 §3 内容 |
| 任务 ID 范围 (T-080~T-082) | 通过 | 与 s8 范围 T-064~T-079 无冲突 |
| 依赖链无环 | 通过 | T-080→T-081→T-082 线性链，无循环 |
| task_kind / tdd_mode / AC ≥3 / deliverables / context_load / risk 字段 | 通过 | 三张卡均具备全部必要字段 |
| TDD_LIGHT_LOC_THRESHOLD=150 合规 | 通过 | T-080 <50 LOC→light；T-081 ~260 LOC→standard；T-082 chore→light |
| 行数 ≤ DOC_SPLIT_THRESHOLD_LINES=300 | 通过 | 163 行，在阈值内 |
| 未处理 TODO/TBD/FIXME | 通过 | 无未标注占位符 |

---

## 问题列表

### [R-001] HIGH: T-080 溯源标签与 test-report 缺陷定义不符

- **category**: consistency
- **root_cause**: self-caused
- **描述**: T-080 任务标题标注为"DEF-006 闭环"，context_load 也指向 `test-report-intellisource-v1#§6` 背景说明 DEF-006。但 test-report §6.1 中 DEF-006 的定义是"runner.py `_persist` 中 `trigger_type`/`execution_mode` 硬编码"，且其 status 已标记为 `closed（T-075 已修）`。T-080 实际解决的是 **DB_URL 硬编码**（12-factor §III Config）——这与 DEF-006 是两个不同的问题，test-report 中没有为 DB_URL 硬编码分配独立 defect ID（BD-001 是测试基础设施债务，不是此问题）。当前标注使本批任务的追溯路径断裂：实现者执行 T-080 时查阅 DEF-006 只能看到"已关闭的 trigger_type 问题"，无法理解真正的修复目标。
- **建议**: 将任务标题与 context_load 中的 DEF-006 引用替换为准确的 backlog 来源标注，例如引用 CLAUDE.md §Backlog 中"deploy-spec 后续可直接注入 DATABASE_URL"的需求背景，或新注一个 `[ASSUMPTION: DB_URL 硬编码在 test-report 中无独立 defect ID，本任务源于 12-factor 合规要求]` 标注；确保追溯链条可验证。

---

### [R-002] HIGH: T-081 AC-2b 规格存在技术不可行性（function-scope Alembic 迁移 + 事务回滚）

- **category**: feasibility
- **root_cause**: self-caused
- **描述**: AC-2b 要求 `pg_session` fixture 为 **function-scoped**，且"每个测试前执行 Alembic 迁移（`alembic upgrade head`）；每个测试后回滚事务保证隔离"。这在 PostgreSQL 中是技术不可行的组合：Alembic 执行 DDL（`CREATE TABLE`、`CREATE INDEX`、`CREATE EXTENSION` 等），PostgreSQL DDL 语句自动提交（implicit commit）无法纳入显式事务后回滚。若每个测试函数都执行 `alembic upgrade head`，即使随后 ROLLBACK 也无法撤销已生效的 schema，且重复执行 DDL 会因对象已存在而报错（除非每次也执行 `alembic downgrade base`，这在实践中等价于 DROP/CREATE，性能极差）。mitigation 章节仅提到"事务回滚（而非 DROP/CREATE）以减少开销"，但未解决 DDL 本质上无法回滚的矛盾。正确的工程实践是：Alembic 迁移在 **session-scoped `pg_container` fixture** 阶段执行一次，function-scoped fixture 使用嵌套事务（savepoint）或 truncate 进行 DML 隔离。当前 AC 规格若按字面实现，实现者将面临不可收敛的 schema 冲突错误。
- **建议**: 修改 AC-2b 为："`pg_container` fixture（session-scoped）启动后执行一次 `alembic upgrade head`；`pg_session` fixture（function-scoped）通过 savepoint（`SAVEPOINT sp; ... ROLLBACK TO SAVEPOINT sp`）或 truncate 关键表的方式隔离每个测试的 DML 变更，不再重复运行 Alembic。"同时更新 mitigation 章节使之与修订后的 AC 一致。

---

### [R-003] MEDIUM: T-081 context_load 误引 DEF-001 作为背景

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: T-081 的 context_load 列出 `test-report-intellisource-v1#§6`（BD-001 / BD-002 / **DEF-001** 背景）。DEF-001 定义为"`test_sprint7_integration.py` 模块级 monkey-patch `SQLiteTypeCompiler.visit_JSONB` 全局副作用"，属于测试隔离问题，与 T-081 引入 testcontainers-postgres fixture 无直接关联。T-081 真正需要了解的背景是 BD-001（PostgreSQL 集成缺口）和 BD-002（鉴权测试 skipped，testcontainers 可顺带解决）。包含 DEF-001 会误导实现者关注不相关的 monkey-patch 问题。
- **建议**: 将 context_load 中的引用修改为 `test-report-intellisource-v1#§6`（BD-001 / BD-002 背景），去除 DEF-001 字样；若需保留 §6 完整引用，以注释说明"DEF-001 与本任务无关，参阅 BD-001/BD-002 即可"。

---

### [R-004] MEDIUM: T-080 AC-4 的 deliverable 语义混入规范性说明

- **category**: convention
- **root_cause**: self-caused
- **描述**: AC-4 内容为："deploy-spec 后续可直接通过 `DATABASE_URL=postgresql+psycopg2://...` 注入，无需任何源码改动；**AC 以注释形式记录在代码中**（`# 12-factor §III Config`）"。AC 本应描述可验证的系统行为，而非要求"在代码中写注释"这类代码风格约束。"AC 以注释形式记录在代码中"的意思含糊（是指 AC-4 本身还是全部 AC 都要写注释？），且注释要求不属于 TDD 验收标准（无法通过测试自动验证）。后半句的实际含义可能是：确保 12-factor 遵从性在代码层有可读的上下文注释，但混入 AC 描述会引起歧义。
- **建议**: 将 AC-4 拆分：保留可验证的行为断言（"deploy-spec 可通过环境变量注入无需源码修改"），将注释要求移入 deliverables 描述或 mitigation 说明中作为编码规范提示。

---

### [R-005] LOW: T-082 标题/正文未显式标注 BD-003 溯源 ID

- **category**: completeness
- **root_cause**: self-caused
- **描述**: T-082 任务标题为"tests/ ruff 债务清理（~166 处 pre-existing 违规）"，context_load 中正确引用了 `test-report-intellisource-v1#§6`（BD-003 背景）。但标题本身未标注 BD-003，而 T-080 和 T-081 的标题均标注了相应的 defect/debt ID（DEF-006 / BD-001 / SR-002）。格式不一致使 sprint 溯源视图在标题层无法均匀对齐；从审查角度看也略显不完整。
- **建议**: 将标题修改为"tests/ ruff 债务清理（BD-003 / ~166 处 pre-existing 违规）"，与 T-080、T-081 的命名惯例保持一致。

---

### [R-006] LOW: T-081 AC-6 CI 配置的两种路径缺少优先级指引

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: AC-6 提供了两个并列选项："在已有 workflow 中添加 `services: docker`"或"新增 `docker-compose.test.yml`"，并均标注为"无论哪种方式"皆可。mitigation 章节也提到了第三种路径（GitHub Actions 原生 `postgres` service container）。三条路径并列而无优先推荐，会导致实现者在选择上耗费额外决策成本，且不同选择在 CI 合并时可能产生配置冲突（如同时存在 docker-compose 和 service container）。
- **建议**: 在 AC-6 中明确优先级顺序，例如："首选：在已有 `.github/workflows/ci.yml` 中启用 docker（testcontainers 需要 Docker daemon，GitHub Actions ubuntu-latest runner 已内置 Docker，仅需确认 workflow 无 `--no-docker` 限制）；降级：若 docker-in-docker 不可用，改用 GitHub Actions 原生 `postgres` service container（`services: postgres: image: pgvector/pgvector:pg16`）并在 README 说明两套指令的区别。"

---

## 审查结论

**needs_revision**

存在 2 个 HIGH 问题阻塞当前任务卡正确执行：

| 级别 | 数量 | 编号 |
|------|------|------|
| HIGH | 2 | R-001, R-002 |
| MEDIUM | 2 | R-003, R-004 |
| LOW | 2 | R-005, R-006 |

- **R-001 (HIGH)**: T-080 溯源 DEF-006 指向一个已关闭的不同缺陷，实现者拿到任务卡无法正确理解修复目标；必须修正溯源标注。
- **R-002 (HIGH)**: T-081 AC-2b 的 function-scope Alembic 迁移 + 事务回滚规格在 PostgreSQL DDL 隐式提交机制下技术不可行；按字面实现必然失败；必须修正为 session-scope 迁移 + function-scope savepoint/truncate 隔离模式。
- R-003、R-004 为 MEDIUM，可在修订 HIGH 问题时一并处理。
- R-005、R-006 为 LOW，建议修订但不阻塞。
