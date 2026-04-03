# Development Plan 分卷 -- Sprint 1: IntelliSource
<!-- required_sections: ["## 3. 任务卡详细"] -->
<!-- volume_type: sprint -->
<!-- id: dev-plan-intellisource-v1-s1 | author: tech-lead | status: draft -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: sprint | split-from: dev-plan-intellisource-v1 -->

[NAV]

- §3 任务卡详细 → T-001..T-009, T-047 (Sprint 1: 基础设施与数据层)
[/NAV]

## 3. 任务卡详细

### T-001: 项目骨架与基础配置

- **目标**: 搭建项目目录结构、pyproject.toml、基础依赖安装、Ruff/mypy/pytest 配置
- **模块**: 全局
- **接口**: 无
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-T001-1: pyproject.toml 包含所有核心依赖（FastAPI, SQLAlchemy, Celery, Redis, httpx, feedparser, litellm, structlog, pydantic-settings, typer, alembic, pgvector, beautifulsoup4, lxml, opentelemetry-api）且可正常安装
  - [ ] AC-T001-2: `ruff check src/` 和 `ruff format --check src/` 零错误通过
  - [ ] AC-T001-3: `mypy src/` strict 模式零错误通过
  - [ ] AC-T001-4: `pytest tests/` 可执行且基础 conftest.py 加载成功
  - [ ] AC-T001-5: 目录结构与 arch#§6 一致（src/intellisource/ 下所有子包存在 **init**.py）
- **deliverables** (交付物):
  - [ ] `pyproject.toml` -- 项目配置与依赖声明
  - [ ] `src/intellisource/__init__.py` -- 包入口
  - [ ] `src/intellisource/main.py` -- FastAPI 应用入口（空骨架）
  - [ ] `tests/conftest.py` -- pytest 基础配置
  - [ ] `alembic/alembic.ini` -- Alembic 配置
  - [ ] 全部子包 `__init__.py` 文件
- **context_load**:
  - arch#§6
  - arch#§7
  - arch#§1.4

### T-002: 数据库连接管理与ORM基础

- **目标**: 实现 PostgreSQL 异步连接池管理（SQLAlchemy AsyncSession），提供数据库会话工厂和生命周期管理
- **模块**: M-009
- **接口**: 无（内部基础设施）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-T002-1: DatabaseManager 通过 AsyncSession 成功连接 PostgreSQL 测试库
  - [ ] AC-T002-2: 连接池参数可通过环境变量配置（IS_DATABASE_URL）
  - [ ] AC-T002-3: 会话上下文管理器正确处理 commit/rollback（异常时自动回滚）
  - [ ] AC-T002-4: 应用关闭时连接池正确释放
- **deliverables** (交付物):
  - [ ] `src/intellisource/storage/database.py` -- 数据库连接管理
  - [ ] `src/intellisource/storage/__init__.py` -- 模块导出
  - [ ] `tests/unit/storage/test_database.py` -- 单元测试
- **context_load**:
  - arch#§2.M-009
  - arch#§1.4
- **实现提示**: 使用 SQLAlchemy 2.0 的 create_async_engine + async_sessionmaker；数据库 URL 通过 pydantic-settings 从环境变量读取

### T-003: ORM模型定义(全部实体)

- **目标**: 定义全部 12 个数据实体的 SQLAlchemy ORM 模型，包含字段、约束、索引和关系映射
- **模块**: M-009
- **接口**: 无
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-T003-1: 12 个 ORM 模型（E-001~E-012）字段类型与 arch-intellisource-v1-data 定义一致
  - [ ] AC-T003-2: 所有 FK 关系正确建立（Source->CollectTask, RawContent->ProcessedContent 等）
  - [ ] AC-T003-3: JSONB 字段使用 SQLAlchemy 的 JSON 类型且默认值正确
  - [ ] AC-T003-4: pgvector VECTOR(1536) 类型字段正确定义（E-004 embedding, E-005 centroid）
  - [ ] AC-T003-5: 所有索引（含 GIN、HNSW、全文检索）在模型中声明
  - [ ] AC-T003-6: Alembic 可基于模型自动生成迁移脚本且 upgrade/downgrade 成功
- **deliverables** (交付物):
  - [ ] `src/intellisource/storage/models.py` -- 全部 ORM 模型定义
  - [ ] `alembic/versions/{initial_migration}.py` -- 初始迁移脚本（草稿版，由 T-047 完善和验证）
  - [ ] `tests/unit/storage/test_models.py` -- 模型定义测试
- **context_load**:
  - arch-intellisource-v1-data#§4（全部实体 E-001~E-012）
  - arch#§2.M-009

### T-004: 数据访问层(Repository)

- **目标**: 实现各数据实体的 Repository 类，提供 CRUD + 游标分页 + 条件查询的统一数据访问接口
- **模块**: M-009
- **接口**: 无（内部接口，被上层模块调用）
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-054 映射: 结构化数据的 CRUD 操作正确执行（创建/读取/更新/删除/列表查询）
  - [ ] AC-T004-1: SourceRepository 支持按 type/tag/status 过滤和游标分页
  - [ ] AC-T004-2: ContentRepository 支持按 source_id/tag/cluster_id/时间范围过滤和游标分页
  - [ ] AC-T004-3: TaskRepository 支持按 status/type/source_id 过滤
  - [ ] AC-T004-4: PushRepository 支持去重查询（subscription_id + content_id + channel）
  - [ ] AC-T004-5: 游标分页返回 items + next_cursor + has_more 格式
- **deliverables** (交付物):
  - [ ] `src/intellisource/storage/repositories/source.py` -- 信源数据访问
  - [ ] `src/intellisource/storage/repositories/content.py` -- 内容数据访问
  - [ ] `src/intellisource/storage/repositories/task.py` -- 任务数据访问
  - [ ] `src/intellisource/storage/repositories/subscription.py` -- 订阅数据访问
  - [ ] `src/intellisource/storage/repositories/push.py` -- 推送记录数据访问
  - [ ] `tests/unit/storage/test_repositories.py` -- Repository 单元测试
- **context_load**:
  - arch#§2.M-009
  - arch-intellisource-v1-data#§4.E-001
  - arch-intellisource-v1-data#§4.E-004
  - arch#§5.1（分页方案）

### T-005: pgvector向量存储与检索

- **目标**: 实现基于 pgvector 的向量存储、相似度检索和混合索引（关键词+向量联合查询）
- **模块**: M-009
- **接口**: 无（内部接口，被 M-008、M-004 调用）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-055 映射: 向量数据正确存储且支持 cosine similarity 检索
  - [ ] AC-056 映射: 混合检索（关键词 + 向量）返回按相关性排序的结果
  - [ ] AC-T005-1: VectorStore.upsert() 正确存储 1536 维向量
  - [ ] AC-T005-2: VectorStore.search() 支持 Top-K 相似度检索，返回结果含 score
  - [ ] AC-T005-3: HybridIndex.search() 支持 keyword/semantic/hybrid 三种模式
  - [ ] AC-T005-4: PostgreSQL 全文检索（zhparser 中文分词）与向量检索结果正确融合
- **deliverables** (交付物):
  - [ ] `src/intellisource/storage/vector.py` -- pgvector 向量操作
  - [ ] `tests/unit/storage/test_vector.py` -- 向量存储测试
- **context_load**:
  - arch#§2.M-009
  - arch-intellisource-v1-data#§4.E-004（embedding 字段）
  - arch-intellisource-v1-data#§4.E-005（centroid 字段）
- **实现提示**: 使用 pgvector 的 SQLAlchemy 集成；混合检索需融合 PostgreSQL ts_rank 和 cosine distance 两个得分；中文全文检索依赖 zhparser，测试时需确保 PostgreSQL 已安装该扩展

### T-006: 结构化日志与可观测性基础

- **目标**: 配置 structlog 结构化日志输出，集成 OpenTelemetry 链路追踪基础设施，实现指标收集器骨架
- **模块**: M-010
- **接口**: 无（内部基础设施）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-057 映射: 日志输出包含 task_id、processing_stage、duration_ms 等结构化字段
  - [ ] AC-058 映射: MetricsCollector 可注册和记录自定义指标（counter/gauge/histogram）
  - [ ] AC-059 映射: TracingMiddleware 为每个请求生成唯一 trace_id 并注入日志上下文
  - [ ] AC-T006-1: 日志格式为 JSON Lines，包含 timestamp、level、message、extra fields
  - [ ] AC-T006-2: 日志级别可通过环境变量配置（IS_LOG_LEVEL）
- **deliverables** (交付物):
  - [ ] `src/intellisource/observability/logging.py` -- structlog 配置
  - [ ] `src/intellisource/observability/metrics.py` -- 指标收集器
  - [ ] `src/intellisource/observability/tracing.py` -- OpenTelemetry 链路追踪
  - [ ] `src/intellisource/observability/__init__.py` -- 模块导出
  - [ ] `tests/unit/observability/test_logging.py` -- 日志测试
  - [ ] `tests/unit/observability/test_metrics.py` -- 指标测试
- **context_load**:
  - arch#§2.M-010
  - arch#§1.4

### T-007: 健康检查与指标端点

- **目标**: 实现系统健康检查端点（检测数据库/Redis/Celery 可用性）和 Prometheus 格式指标端点
- **模块**: M-010
- **接口**: API-018, API-019
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-060 映射: /api/v1/health 返回各组件健康状态（database/redis/celery）
  - [ ] AC-T007-1: 健康检查无需认证即可访问
  - [ ] AC-T007-2: 任一关键组件不可用时返回 503 + status=degraded/unhealthy
  - [ ] AC-T007-3: /api/v1/metrics 返回 Prometheus 文本格式指标
  - [ ] AC-T007-4: 指标端点需 API Key 认证
- **deliverables** (交付物):
  - [ ] `src/intellisource/observability/health.py` -- 健康检查逻辑（HealthChecker）
  - [ ] `tests/unit/observability/test_health.py` -- 健康检查测试
- **context_load**:
  - arch#§2.M-010
  - arch-intellisource-v1-api#API-018
  - arch-intellisource-v1-api#API-019
- **实现提示**: 健康检查通过尝试 ping 各服务判断可用性；Prometheus 指标使用 prometheus_client 库或自行格式化文本输出

### T-008: 配置模型与校验器

- **目标**: 定义信源配置的 Pydantic 模型（SourceConfig），实现 YAML/JSON 配置文件解析和格式校验
- **模块**: M-001
- **接口**: 无（内部接口）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-001 映射: SourceConfig 模型支持 name/type/url/tags/schedule/proxy/rate_limit 等字段定义
  - [ ] AC-003 映射: 无效配置（缺失必填字段、类型错误、URL 格式错误）抛出明确的 ValidationError
  - [ ] AC-T008-1: 支持 YAML 和 JSON 两种格式解析
  - [ ] AC-T008-2: 校验失败返回所有错误列表（非第一个错误即停止）
  - [ ] AC-T008-3: 配置支持 ${ENV_VAR} 占位符语法，运行时从环境变量解析
- **deliverables** (交付物):
  - [ ] `src/intellisource/config/models.py` -- 配置 Pydantic 模型
  - [ ] `src/intellisource/config/validator.py` -- 配置校验逻辑
  - [ ] `src/intellisource/config/__init__.py` -- 模块导出
  - [ ] `config/sources.example.yaml` -- 信源配置示例文件
  - [ ] `tests/unit/config/test_models.py` -- 模型测试
  - [ ] `tests/unit/config/test_validator.py` -- 校验器测试
- **context_load**:
  - arch#§2.M-001
  - arch-intellisource-v1-data#§4.E-001
  - prd#§2.F-001

### T-009: 配置加载与热加载

- **目标**: 实现配置文件的加载（从 YAML/JSON 文件读取并持久化到数据库）、热加载（文件变更自动重载）和版本管理（回退）
- **模块**: M-001
- **接口**: API-005（配置重载的业务逻辑层）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-002 映射: 配置文件修改后 10s 内自动生效（watchfiles 监听）
  - [ ] AC-004 映射: 配置变更时自增版本号，支持回退到上一版本
  - [ ] AC-T009-1: ConfigLoader.load_file() 解析 YAML/JSON 并调用 validator 校验
  - [ ] AC-T009-2: ConfigLoader.sync_to_db() 将配置同步到 Source 表（新增/更新/标记删除）
  - [ ] AC-T009-3: ConfigWatcher 检测文件变更后自动触发 reload
  - [ ] AC-T009-4: 校验失败时拒绝加载，已有配置不受影响
  - [ ] AC-T009-5: ConfigVersionManager.rollback(version) 恢复到指定版本
- **deliverables** (交付物):
  - [ ] `src/intellisource/config/loader.py` -- 配置文件加载与热加载
  - [ ] `tests/unit/config/test_loader.py` -- 加载器测试
- **context_load**:
  - arch#§2.M-001
  - arch-intellisource-v1-api#API-005
  - arch#§5.2（输入校验策略 -- API-005 白名单）

### T-047: Alembic数据库迁移(初始)

- **目标**: 配置 Alembic 迁移框架，基于 ORM 模型生成初始迁移脚本，确保 upgrade/downgrade 正确工作
- **模块**: M-009
- **接口**: 无
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-054 映射: 数据库表结构与 ORM 模型一致
  - [ ] AC-T047-1: `alembic upgrade head` 从空库创建全部表和索引
  - [ ] AC-T047-2: `alembic downgrade base` 回退所有迁移（清除全部表）
  - [ ] AC-T047-3: 迁移脚本包含 pgvector 扩展创建（CREATE EXTENSION IF NOT EXISTS vector）
  - [ ] AC-T047-4: 迁移脚本包含 zhparser 扩展创建（CREATE EXTENSION IF NOT EXISTS zhparser）
  - [ ] AC-T047-5: E-007 LLMCallLog 分区表正确创建
- **deliverables** (交付物):
  - [ ] `alembic/env.py` -- Alembic 环境配置
  - [ ] `alembic/versions/{initial}.py` -- 初始迁移脚本（完整版）
  - [ ] `tests/integration/test_migration.py` -- 迁移测试
- **context_load**:
  - arch-intellisource-v1-data#§4（全部实体）
  - arch#§1.4（pgvector, zhparser）
- **实现提示**: 紧跟 T-003 完成后立即生成初始迁移，确保后续 Sprint 的数据库 schema 变更有版本控制；分区表创建需手写 SQL 而非 autogenerate
