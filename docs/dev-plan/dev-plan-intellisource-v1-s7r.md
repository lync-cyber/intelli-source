---
id: dev-plan-intellisource-v1-s7r
doc_type: dev-plan
author: tech-lead
status: approved
deps: [arch-intellisource-v1, test-report-intellisource-v1]
consumers: [developer, qa-engineer, devops]
volume: s7r
split_from: dev-plan-intellisource-v1
---
# Development Plan: IntelliSource — Sprint 7r (Pre-Deploy Remediation)

> **Sprint 主题**: pre_deploy remediation — 落地 test-report 残留风险与 deferred 工程债务
> **前置依赖**: Sprint 7 已全部完成；Phase 6 testing approved (test-report-intellisource-v1 status=approved)
> **后置**: 处理完成后回到 pre_deploy Manual Review Checkpoint
> **注意**: 本批任务（T-080~T-082）独立于 sprint-8（T-064~T-079 OpenCode P2 改进），两批互不干扰，可并行规划

[NAV]
- §3 任务卡详细
  - T-080 runner.py DB_URL 环境变量化（12-factor §III Config）
  - T-081 testcontainers-postgres fixture（BD-001 / SR-002 闭环）
  - T-082 tests/ ruff 债务清理（BD-003 / ~166 处 pre-existing 违规）
[/NAV]

## 3. 任务卡详细

### T-080: runner.py DB_URL 环境变量化（12-factor §III Config）

- **目标**: 将 `src/intellisource/agent/runner.py` 中任何硬编码 DB_URL 字面量改为读取 `DATABASE_URL` 环境变量；确保生产部署通过环境变量注入，无需修改源码（12-factor §III Config）
- **溯源**: `CODE-REVIEW-T-074-r2` 新引入观察段落（runner.py 硬编码 DB_URL）+ 12-factor §III Config 原则。注：test-report DEF-006 实指 `trigger_type`/`execution_mode` 硬编码，已由 T-075 闭环；本任务针对 CODE-REVIEW-T-074-r2 独立观察的 DB_URL 硬编码问题，与 DEF-006 无关。
- **task_kind**: fix
- **tdd_mode**: light
- **tdd_refactor**: skip（单文件单点改动）
- **security_sensitive**: false
- **模块**: M-009（storage/database）、M-011（API 入口 / 配置）
- **接口**: internal — `DATABASE_URL` 环境变量约定
- **复杂度**: S（预估 LOC < 50：读取环境变量逻辑 ~10 行 + 单元测试 ~30 行）
- **status**: done
- **依赖**: 无（独立任务，优先执行）

- **tdd_acceptance**:
  - [ ] AC-1: `runner.py`（或其数据库初始化调用路径）读取 `DATABASE_URL` 环境变量作为首选数据库连接串；缺省时回退到与原硬编码值等价的本地开发默认值（`sqlite+aiosqlite:///./intellisource_dev.db` 或同等）
  - [ ] AC-2: 启动时若 `DATABASE_URL` 未设置且当前环境为非开发模式（`ENV=production` 或 `ENV=staging`），抛出明确的 `ValueError` / `RuntimeError` 并拒绝启动；异常消息须包含 `DATABASE_URL` 字样供运维排查
  - [ ] AC-3a: 单元测试 — 环境变量 `DATABASE_URL` 已设置时，初始化逻辑使用该值
  - [ ] AC-3b: 单元测试 — 环境变量未设置且 `ENV` 未设置（开发模式）时，使用开发回退值
  - [ ] AC-3c: 单元测试 — 环境变量未设置且 `ENV=production` 时，抛出预期异常拒绝启动
  - [ ] AC-4: `deploy-spec` 后续可直接通过 `DATABASE_URL=postgresql+psycopg2://...` 注入，无需任何源码改动（行为断言：仅修改环境变量即可切换数据库后端，源码零修改）

- **deliverables**:
  - [ ] `src/intellisource/agent/runner.py` — 移除硬编码 DB_URL，改为读取 `DATABASE_URL` 环境变量（含开发回退逻辑与生产拒绝启动逻辑）
  - [ ] `tests/unit/agent/test_runner_db_url.py` — 新增单元测试，覆盖 AC-3a / AC-3b / AC-3c（至少 3 个测试用例；使用 `monkeypatch.setenv` / `monkeypatch.delenv`）

- **affected_files**:
  - `src/intellisource/agent/runner.py`
  - `tests/unit/agent/test_runner_db_url.py`（新建）

- **context_load**:
  - `arch-intellisource-v1#§2.M-009`（存储层数据库连接约定）
  - `CODE-REVIEW-T-074-r2`（新引入观察段落：runner.py 硬编码 DB_URL，本任务直接溯源）

- **risk**:
  - 回退默认值与既有 1862 PASSED 测试环境的 SQLite 连接串必须保持一致，否则会破坏现有测试；`monkeypatch` 隔离可防止污染
  - `ENV` 环境变量命名需与 deploy-spec 约定一致；若 deploy-spec 尚未定义，需在任务卡实现时标注 `[ASSUMPTION]`

- **mitigation**:
  - 新增测试文件不修改既有用例；使用 `monkeypatch` 确保隔离
  - 与 T-081 无硬依赖，可先行完成
  - 编码规范提示（非 AC）：读取环境变量的代码行旁加单行注释 `# 12-factor §III Config`，便于后续维护者理解合规意图；此为代码可读性建议，不纳入测试验收

---

### T-081: testcontainers-postgres fixture（BD-001 / SR-002 闭环）

- **目标**: 引入 `testcontainers[postgres]` 将 `tests/integration/` 下的 22 个集成测试从 SQLite mock 迁移至真实 PostgreSQL（含 pgvector 扩展），并新增 pgvector 向量检索与 JSONB 操作符专项集成测试，覆盖 test-report BD-001 缺口
- **task_kind**: feature
- **tdd_mode**: standard（预估 LOC > 150：conftest fixture ~80 行 + 22 测试迁移适配 ~100 行 + 新增 PG 专项测试 ~80 行；跨 M-009 / M-008 两个 arch 模块）
- **tdd_refactor**: auto（GREEN 后 code-review Layer 1 命中 `complexity` / `coupling` 时触发；fixture lifecycle 抽象存在 REFACTOR 空间）
- **security_sensitive**: false
- **模块**: M-009（storage/pgvector/repositories）、M-008（search/hybrid）
- **接口**: internal — pytest fixture 接口
- **复杂度**: L（预估 LOC ~260）
- **status**: done（pg_* 集成测试 PASS 验证需 Docker daemon — 本地无 Docker 时 17 个新增测试 + 11 个迁移测试 graceful skip；CI ubuntu-latest 内置 Docker 完成最终验证）
- **依赖**: T-080（DATABASE_URL 环境变量化后，fixture 可通过 `monkeypatch.setenv("DATABASE_URL", pg_url)` 干净注入，避免硬编码）

- **tdd_acceptance**:
  - [ ] AC-1: `pyproject.toml` dev-dependencies 新增 `testcontainers[postgres]`；选定 Docker 镜像 `pgvector/pgvector:pg16`（含 pgvector 扩展）；镜像版本锁定以确保 CI 可重现
  - [ ] AC-2a: `tests/integration/conftest.py` 新增 **session-scoped** `pg_container` fixture — 启动 PostgreSQL 容器并等待就绪（连接健康检查）；容器启动后在 session 生命周期内**执行一次** `alembic upgrade head`（DDL 隐式提交，仅需运行一次，不可在 function-scope 内重复执行）
  - [ ] AC-2b: `tests/integration/conftest.py` 新增 **function-scoped** `pg_session` fixture — 基于 `pg_container` 创建 async session；每个测试在 SQLAlchemy session-level savepoint（`SAVEPOINT`）内运行，测试结束后 `ROLLBACK TO SAVEPOINT` 保证 DML 隔离（适用于纯 DML 测试；不重复执行 Alembic 迁移）
  - [ ] AC-2c: 提供可选的 **function-scoped** `pg_truncate` fixture — 测试结束后执行 `TRUNCATE` 所有业务表 + `RESTART IDENTITY`，供 DDL 相关测试或 savepoint 不适用场景使用；fixture 通过参数或直接引入可选调用，不强制每个测试使用
  - [ ] AC-3: 将 `tests/integration/test_sprint7_integration.py` 和 `tests/integration/test_celery_worker_wiring.py` 内共 22 个集成测试迁移至使用 `pg_session` fixture；迁移过程中**不允许放宽任何断言**（assertion 强度不降）
  - [ ] AC-4: 新增至少 1 个集成测试验证 pgvector 向量检索行为：向 `processed_contents` 表插入带 embedding 的记录，调用 `/api/v1/search` 混合检索路径，断言返回 HTTP 200 且 `items` 数组非空、余弦相似度排序正确（覆盖 BD-001 向量检索缺口）
  - [ ] AC-5: 新增至少 1 个集成测试验证 JSONB 操作符：向 `content_clusters` 表插入含 `tags` 字段的记录，使用 `@>` 操作符查询 cluster by tag，断言过滤结果正确（覆盖 BD-001 JSONB 缺口）
  - [ ] AC-6: CI 配置确保 testcontainers 可用，按以下优先级选择：**首选**——在已有 `.github/workflows/ci.yml` 中确认 Docker daemon 可用（GitHub Actions `ubuntu-latest` runner 已内置 Docker，通常无需额外配置；仅需确认 workflow 无 `--no-docker` 或 rootless 限制）；**降级**——若 docker-in-docker 不可用，改用 GitHub Actions 原生 `services: postgres: image: pgvector/pgvector:pg16`（无需 testcontainers，仅在 CI 中替换 fixture 后端）；两种方式均须在 `README`（或 `CONTRIBUTING`）中补充对应的测试运行命令，并说明本地 vs CI 的差异
  - [ ] AC-7: `uv run pytest` 全量执行通过（含原 1862 个单元测试 + 迁移后的 22 个集成测试 + 新增 PG 专项测试，至少 5 条 PG 集成测试全部 PASS）

- **deliverables**:
  - [ ] `pyproject.toml` — `[tool.uv.sources]` / `[project.optional-dependencies]` 中追加 `testcontainers[postgres]`
  - [ ] `tests/integration/conftest.py` — session-scoped `pg_container`（含 session 级一次性 Alembic migrate）+ function-scoped `pg_session`（savepoint 隔离）+ 可选 function-scoped `pg_truncate` fixture（DDL 场景备用）
  - [ ] `tests/integration/test_sprint7_integration.py` — 迁移到 PG fixture（22 个测试）
  - [ ] `tests/integration/test_celery_worker_wiring.py` — 迁移到 PG fixture（部分测试，按实际 DB 依赖情况）
  - [ ] `tests/integration/test_pg_vector_search.py`（新建）— pgvector 向量检索 + JSONB 操作符专项集成测试（≥2 个测试用例，覆盖 AC-4 / AC-5）
  - [ ] `.github/workflows/ci.yml`（或已有 workflow）— 按 AC-6 优先级配置：首选确认 ubuntu-latest runner 内置 Docker daemon 可用以驱动 testcontainers；若不可用则降级改用 GitHub Actions 原生 `services: postgres` 容器并在 README 标注

- **affected_files**:
  - `pyproject.toml`
  - `tests/integration/conftest.py`（修改或新建）
  - `tests/integration/test_sprint7_integration.py`
  - `tests/integration/test_celery_worker_wiring.py`
  - `tests/integration/test_pg_vector_search.py`（新建）
  - `.github/workflows/ci.yml`（按 AC-6 首选/降级方案任选其一）

- **context_load**:
  - `arch-intellisource-v1#§2.M-009`（存储层、pgvector 配置）
  - `arch-intellisource-v1#§2.M-008`（混合检索引擎接口）
  - `test-report-intellisource-v1#§6`（BD-001 / BD-002 背景；DEF-001 与本任务无关，无需参阅）
  - `test-report-intellisource-v1#§1`（测试策略 / 集成测试分布）

- **risk**:
  - testcontainers 容器启动开销可能使 pytest session 增加；session-scoped `pg_container` 可摊销开销（每 session 只启动一次容器）
  - CI 环境 docker-in-docker 权限问题（GitHub Actions 默认支持 Docker，但需确认当前 workflow 配置）
  - `pgvector/pgvector:pg16` 镜像体积较大（~500MB），首次拉取可能超时；可配置 GitHub Actions cache 或使用 `--pull-policy=if-not-present`
  - savepoint 隔离仅覆盖 DML；若测试自身执行 DDL（CREATE/DROP），savepoint 无法回滚，需改用 `pg_truncate` fixture

- **mitigation**:
  - **fixture lifecycle 选型理由**：PostgreSQL DDL 语句（`CREATE TABLE`、`CREATE INDEX` 等）隐式提交，无法纳入显式事务后回滚；因此 Alembic `upgrade head` 必须在 session-scoped `pg_container` 内执行一次，而非在每个 function-scoped 测试内重复执行（重复执行会因对象已存在报错，且 ROLLBACK 无法撤销已提交 DDL）。function-scoped 隔离通过 savepoint（DML 测试）或 TRUNCATE（全表重置）实现，不再依赖 Alembic 幂等性。
  - CI 超时风险：在 workflow 设置合理的 `timeout-minutes`（建议 15 分钟）
  - 若 docker-in-docker 不可用，降级方案：在 CI Job 中显式声明 `postgres` service container（GitHub Actions 原生支持，无需 testcontainers），在本地仍用 testcontainers

---

### T-082: tests/ ruff 债务清理（BD-003 / ~166 处 pre-existing 违规）

- **目标**: 消除 `tests/` 目录约 166 处 pre-existing ruff 风格违规（test-report-intellisource-v1#§4 BD-003），使 `uv run ruff check tests/` 退出码为 0，与 `src/` 一致性对齐
- **task_kind**: chore
- **tdd_mode**: light（chore 类型按规则跳过 RED/GREEN/REFACTOR 子代理调度；implementer 主线程直接执行 `ruff --fix` + 手工处理剩余 + 全量回归验证）
- **tdd_refactor**: skip
- **security_sensitive**: false
- **模块**: 仅 `tests/`（不涉及 `src/` 任何模块）
- **接口**: 不涉及
- **复杂度**: S（机械重构；大部分可 `ruff --fix` 自动处理）
- **status**: done（ruff check 0 violations / ruff format clean / pytest 1854 passed 0 failed；4 处 `# noqa: E501` 用于无法合理折行的固定字符串字面量与测试断言文本）
- **依赖**: T-081（确保 T-081 新增的 PG fixture 代码也被同步纳入清理范围）

- **tdd_acceptance**:
  - [ ] AC-1: `uv run ruff check tests/` 退出码为 0（零残留违规）
  - [ ] AC-2: `uv run ruff format tests/` 执行后无文件 diff（格式完全合规）
  - [ ] AC-3: `uv run pytest`（含 T-081 新增 PG 集成测试）全量 PASS，零回归（PASSED 数 ≥ 前一轮 PASSED 数，0 FAILED）
  - [ ] AC-4: 仅做格式 / import 排序 / 未使用变量等纯风格修改；不修改任何断言逻辑，不改变测试覆盖语义；凡涉及语义判断的改动必须在 PR 描述中逐条标注理由
  - [ ] AC-5: 若 ruff 自动修复触发既有测试失败（如 `F401 unused import` 误删 fixture 注入 import），回退该改动并在 PR 描述中单独列出"人工保留"清单及原因

- **deliverables**:
  - [ ] `tests/` 下全部 `.py` 文件（格式 / import 排序 / 未使用变量清理；不含 `src/`，不改动 conftest 注入语义）

- **affected_files**:
  - `tests/**/*.py`（范围：~166 处违规分布的文件；按 `uv run ruff check tests/ --format=files` 输出确定具体文件清单）

- **context_load**:
  - `test-report-intellisource-v1#§6`（BD-003 背景：~166 处 pre-existing ruff 警告）

- **risk**:
  - `F401 unused import` 自动删除可能误删 pytest fixture 注入的间接 import（如 `from conftest import pg_session`），导致测试失败
  - `E501 line-too-long` 在长断言或 SQL 字符串处自动折行可能产生语法错误

- **mitigation**:
  - 运行 `ruff check tests/ --fix` 后立即跑 `uv run pytest` 验证；若有失败即定位并回退具体 fix
  - 对 `E501` 类超长行，优先手工折行而非依赖 ruff format 自动折行，保证语义不变
  - AC-5 明确要求在 PR 描述中列出"人工保留"清单，作为审查依据
