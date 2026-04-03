# Development Plan 分卷 -- Sprint 5: IntelliSource
<!-- required_sections: ["## 3. 任务卡详细"] -->
<!-- volume_type: sprint -->
<!-- id: dev-plan-intellisource-v1-s5 | author: tech-lead | status: draft -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: sprint | split-from: dev-plan-intellisource-v1 -->

[NAV]

- §3 任务卡详细 → T-037..T-047 (Sprint 5: 检索/API/CLI与集成)
[/NAV]

## 3. 任务卡详细

### T-037: 混合检索引擎

- **目标**: 实现关键词 + 向量语义混合检索引擎，支持多种检索模式和结果融合排序
- **模块**: M-008
- **接口**: API-012 的业务逻辑层
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-051 映射: 基于检索意图执行混合检索（关键词 + 向量语义），返回相关结果
  - [ ] AC-056 映射: 混合检索结果按相关性排序
  - [ ] AC-T037-1: HybridSearchEngine 支持 keyword/semantic/hybrid 三种检索模式
  - [ ] AC-T037-2: hybrid 模式下融合 ts_rank 和 cosine similarity 两个得分（可配置权重）
  - [ ] AC-T037-3: 支持按 tags/date_from/date_to 过滤
  - [ ] AC-T037-4: 返回结果包含 content_id/title/snippet/score/source_name/published_at
  - [ ] AC-T037-5: 查询耗时记录到 query_time_ms
- **deliverables** (交付物):
  - [ ] `src/intellisource/search/hybrid.py` -- 混合检索引擎
  - [ ] `src/intellisource/search/__init__.py` -- 模块导出
  - [ ] `tests/unit/search/test_hybrid.py` -- 混合检索测试
- **context_load**:
  - arch#§2.M-008
  - arch-intellisource-v1-api#API-012
  - arch-intellisource-v1-data#§4.E-004（embedding, 全文检索索引）

### T-038: 意图理解与即时问答

- **目标**: 实现 LLM 驱动的自然语言意图理解和基于检索的即时问答功能
- **模块**: M-008
- **接口**: API-013 的业务逻辑层
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-050 映射: IntentParser 调用 LLM 理解用户自然语言检索意图
  - [ ] AC-052 映射: 检索结果经 LLM 摘要后返回，不阻塞消息通道
  - [ ] AC-T038-1: IntentParser 输出结构化检索参数（keywords, tags, date_range, search_mode）
  - [ ] AC-T038-2: SearchSummarizer 对检索结果生成简洁的回答摘要
  - [ ] AC-T038-3: 回答中包含引用来源列表（content_id/title/url）
  - [ ] AC-T038-4: 意图理解降级为关键词直接搜索
  - [ ] AC-T038-5: SearchSummarizer 输出 schema 包含 intent_summary 字段（1-2 句意图摘要），搭便车于已有 LLM 调用
- **deliverables** (交付物):
  - [ ] `src/intellisource/search/intent.py` -- 意图理解器
  - [ ] `src/intellisource/search/chat.py` -- 即时问答（SearchSummarizer，含 intent_summary 输出）
  - [ ] `tests/unit/search/test_intent.py` -- 意图理解测试
  - [ ] `tests/unit/search/test_chat.py` -- 问答测试
- **context_load**:
  - arch#§2.M-008
  - arch-intellisource-v1-api#API-013

### T-039: 多轮对话管理与上下文压缩

- **目标**: 实现多轮对话会话管理器，基于 token 预算的上下文压缩，支持意图分离和异步摘要
- **模块**: M-008
- **接口**: API-013（session_id 支持）
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-053 映射: 支持多轮对话上下文保持，基于可配置 token 预算（`chat.context_token_budget`）而非硬编码轮数
  - [ ] AC-T039-1: ChatSessionManager.get_or_create(channel, channel_user_id) 获取或创建会话
  - [ ] AC-T039-2: 对话上下文使用结构化 JSONB 格式存储（summary + recent_turns），assistant 消息分离 content（意图摘要）与 full_content（完整回答）
  - [ ] AC-T039-3: get_context_for_llm() 按 token 预算从最近轮次向前填充，仅使用 assistant 的 content（意图摘要），超预算时截断最旧轮次
  - [ ] AC-T039-4: 超过 `chat.session_timeout_hours` 无活跃的会话自动清理
  - [ ] AC-T039-5: 新会话或 session_id 为空时创建新 ChatSession
  - [ ] AC-T039-6: ContextCompressor.should_compress() 在轮次超过 `chat.compress_after_turns` 且旧轮次即将被淘汰时返回 true
  - [ ] AC-T039-7: ContextCompressor.compress_older_turns() 使用 `chat.compress_model` 将旧轮次压缩为结构化摘要
  - [ ] AC-T039-8: 压缩操作在响应用户后异步执行，不影响响应延迟
  - [ ] AC-T039-9: 压缩调用记录到 LLMCallLog（call_type="context_compress"，priority=low）
  - [ ] AC-T039-10: 读取到旧格式（[] 数组）的 context 时自动迁移为新格式
- **deliverables** (交付物):
  - [ ] `src/intellisource/search/session.py` -- 对话会话管理器（ChatSessionManager）
  - [ ] `src/intellisource/search/context_compressor.py` -- 上下文压缩器（ContextCompressor）
  - [ ] `src/intellisource/llm/prompts/context_compress.txt` -- 压缩 prompt 模板
  - [ ] `tests/unit/search/test_session.py` -- 会话管理测试
  - [ ] `tests/unit/search/test_context_compressor.py` -- 压缩器测试
- **context_load**:
  - arch#§2.M-008
  - arch-intellisource-v1-data#§4.E-011（含 Context Schema）
  - arch#§5.1（上下文压缩缓存策略、对话配置表）
- **实现提示**: 意图分离搭便车于 T-038 SearchSummarizer 的 intent_summary 输出；压缩使用 LLMGateway.estimate_tokens()（T-019 AC-T019-5）进行 token 计数；异步压缩通过 asyncio.create_task 或 Celery 实现

### T-040: Webhook回调处理(微信/企业微信)

- **目标**: 实现微信和企业微信的消息回调处理，包括签名验证、消息解析和指令路由
- **模块**: M-007
- **接口**: API-020, API-021
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-T040-1: WebhookHandler 验证微信签名（sha1(sort(token, timestamp, nonce))）
  - [ ] AC-T040-2: WebhookHandler 验证企业微信消息签名
  - [ ] AC-T040-3: 解析 XML 消息体提取用户消息内容
  - [ ] AC-T040-4: 文本消息路由到即时检索模块（M-008）处理
  - [ ] AC-T040-5: 签名验证失败返回 403
  - [ ] AC-T040-6: 消息处理异步执行，5s 内先返回空响应（微信要求）
- **deliverables** (交付物):
  - [ ] `src/intellisource/distributor/webhooks.py` -- Webhook 回调处理
  - [ ] `tests/unit/distributor/test_webhooks.py` -- 回调处理测试
- **context_load**:
  - arch#§2.M-007
  - arch-intellisource-v1-api#API-020
  - arch-intellisource-v1-api#API-021
  - arch#§5.2（Webhook 签名验证）

### T-041: API路由层 -- 信源管理

- **目标**: 实现信源管理的 FastAPI 路由（CRUD + 配置重载），连接 M-001 业务逻辑
- **模块**: M-011
- **接口**: API-001, API-002, API-003, API-004, API-005
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-061 映射: API 支持信源的创建/查询/更新/删除操作
  - [ ] AC-065 映射: FastAPI 自动生成 OpenAPI 文档
  - [ ] AC-T041-1: GET /api/v1/sources 支持分页和过滤（type/tag/status）
  - [ ] AC-T041-2: POST /api/v1/sources 创建信源，409 冲突正确处理
  - [ ] AC-T041-3: PATCH /api/v1/sources/{id} 部分更新
  - [ ] AC-T041-4: DELETE /api/v1/sources/{id} 删除信源
  - [ ] AC-T041-5: POST /api/v1/sources/reload 配置重载（白名单校验）
- **deliverables** (交付物):
  - [ ] `src/intellisource/api/routers/sources.py` -- 信源路由
  - [ ] `tests/unit/api/test_sources.py` -- 信源 API 测试
- **context_load**:
  - arch#§2.M-011
  - arch-intellisource-v1-api#API-001
  - arch-intellisource-v1-api#API-002
  - arch-intellisource-v1-api#API-003
  - arch-intellisource-v1-api#API-004

### T-042: API路由层 -- 任务与工作流

- **目标**: 实现任务管理和工作流管理的 FastAPI 路由
- **模块**: M-011
- **接口**: API-006, API-007, API-008, API-009, API-010, API-011, API-026, API-027, API-028, API-029
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-062 映射: API 支持手动触发采集任务和查询任务状态
  - [ ] AC-063 映射: API 支持定义和执行自定义工作流
  - [ ] AC-065 映射: 自动生成 OpenAPI 文档
  - [ ] AC-T042-1: GET /api/v1/tasks 任务列表（分页+过滤）
  - [ ] AC-T042-2: POST /api/v1/tasks/collect 触发采集（返回 202）
  - [ ] AC-T042-3: 工作流 CRUD（GET/POST/PATCH/DELETE /api/v1/workflows）
  - [ ] AC-T042-4: POST /api/v1/workflows/{id}/run 执行工作流（返回 202）
- **deliverables** (交付物):
  - [ ] `src/intellisource/api/routers/tasks.py` -- 任务路由
  - [ ] `src/intellisource/api/routers/workflows.py` -- 工作流路由
  - [ ] `tests/unit/api/test_tasks.py` -- 任务 API 测试
  - [ ] `tests/unit/api/test_workflows.py` -- 工作流 API 测试
- **context_load**:
  - arch#§2.M-011
  - arch-intellisource-v1-api#API-006
  - arch-intellisource-v1-api#API-007
  - arch-intellisource-v1-api#API-010
  - arch-intellisource-v1-api#API-011

### T-043: API路由层 -- 内容/检索/订阅/LLM/系统

- **目标**: 实现内容查询、检索、订阅管理、LLM 统计和系统端点的 FastAPI 路由
- **模块**: M-011
- **接口**: API-012, API-013, API-014, API-015, API-016, API-017, API-018, API-019, API-022, API-023, API-024, API-025
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-061 映射: 内容列表/详情/聚类 API 正确路由
  - [ ] AC-065 映射: 自动生成 OpenAPI 文档
  - [ ] AC-T043-1: GET /api/v1/contents 内容列表（分页+过滤）
  - [ ] AC-T043-2: POST /api/v1/search 混合检索
  - [ ] AC-T043-3: POST /api/v1/search/chat 即时问答
  - [ ] AC-T043-4: 订阅规则 CRUD（/api/v1/subscriptions）
  - [ ] AC-T043-5: GET /api/v1/llm/stats LLM 用量统计
  - [ ] AC-T043-6: GET /api/v1/health 和 GET /api/v1/metrics 系统端点
- **deliverables** (交付物):
  - [ ] `src/intellisource/api/routers/contents.py` -- 内容路由
  - [ ] `src/intellisource/api/routers/search.py` -- 检索路由
  - [ ] `src/intellisource/api/routers/subscriptions.py` -- 订阅路由
  - [ ] `src/intellisource/api/routers/llm.py` -- LLM 统计路由
  - [ ] `src/intellisource/api/routers/system.py` -- 系统路由
  - [ ] `tests/unit/api/test_contents.py` -- 内容 API 测试
  - [ ] `tests/unit/api/test_search.py` -- 检索 API 测试
  - [ ] `tests/unit/api/test_subscriptions.py` -- 订阅 API 测试
- **context_load**:
  - arch#§2.M-011
  - arch-intellisource-v1-api#API-012
  - arch-intellisource-v1-api#API-014
  - arch-intellisource-v1-api#API-022

### T-044: 认证中间件与请求追踪

- **目标**: 实现 API Key 认证中间件、请求日志中间件和请求链路追踪中间件
- **模块**: M-011
- **接口**: 全部需认证的 API
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-T044-1: AuthMiddleware 校验 X-API-Key 请求头，无效时返回 401
  - [ ] AC-T044-2: API Key 通过环境变量配置（IS_API_KEY）
  - [ ] AC-T044-3: 健康检查和 Webhook 端点豁免认证
  - [ ] AC-T044-4: RequestLogger 记录每个请求的 method/path/status_code/duration_ms
  - [ ] AC-T044-5: TracingMiddleware 为每个请求注入 trace_id 到日志上下文和响应头
- **deliverables** (交付物):
  - [ ] `src/intellisource/api/deps.py` -- FastAPI 依赖注入（认证）
  - [ ] `src/intellisource/api/middleware.py` -- 中间件（日志/追踪）
  - [ ] `tests/unit/api/test_middleware.py` -- 中间件测试
- **context_load**:
  - arch#§2.M-011
  - arch#§5.2（认证机制）
  - arch#§5.3（统一错误响应格式）

### T-045: CLI工具

- **目标**: 实现基于 typer 的 CLI 工具，封装常用 API 操作（信源管理/任务触发/状态查询）
- **模块**: M-011
- **接口**: 无（CLI 通过 HTTP 调用 API）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-064 映射: CLI 工具封装常用 API 操作
  - [ ] AC-T045-1: `intellisource source list/add/update/delete` 信源管理命令
  - [ ] AC-T045-2: `intellisource task trigger/status` 任务操作命令
  - [ ] AC-T045-3: `intellisource workflow list/create/run` 工作流命令
  - [ ] AC-T045-4: `intellisource search <query>` 检索命令
  - [ ] AC-T045-5: CLI 输出格式化为表格（默认）或 JSON（--json 参数）
  - [ ] AC-T045-6: API 地址和 Key 通过环境变量或 --api-url/--api-key 参数配置
- **deliverables** (交付物):
  - [ ] `src/intellisource/cli/main.py` -- typer CLI 入口
  - [ ] `tests/unit/cli/test_main.py` -- CLI 测试
- **context_load**:
  - arch#§2.M-011
  - arch#§6（cli/ 目录结构）

### T-046: FastAPI应用入口与Docker部署

- **目标**: 组装 FastAPI 应用入口（注册路由/中间件/生命周期），编写 Dockerfile 和 docker-compose.yml
- **模块**: M-011
- **接口**: 全部 API
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-065 映射: /docs 自动提供 OpenAPI/Swagger 文档
  - [ ] AC-T046-1: main.py 注册所有路由组和中间件
  - [ ] AC-T046-2: 应用启动时初始化数据库连接池、Redis 连接、Celery app
  - [ ] AC-T046-3: 应用关闭时正确释放所有资源
  - [ ] AC-T046-4: Dockerfile 构建成功且镜像大小合理（多阶段构建）
  - [ ] AC-T046-5: docker-compose.yml 包含 app/celery-worker/celery-beat/postgres(zhparser)/redis 服务
  - [ ] AC-T046-6: `docker compose up` 一键启动全部服务
- **deliverables** (交付物):
  - [ ] `src/intellisource/main.py` -- FastAPI 应用入口（完整版）
  - [ ] `docker/Dockerfile` -- Docker 镜像构建
  - [ ] `docker/docker-compose.yml` -- Docker Compose 编排
  - [ ] `config/settings.example.toml` -- 系统配置示例
  - [ ] `tests/integration/test_app_startup.py` -- 应用启动集成测试
- **context_load**:
  - arch#§6
  - arch#§1.4（技术栈）
  - prd#§3.3（兼容性 -- Docker 部署）
- **实现提示**: PostgreSQL 使用包含 zhparser 扩展的镜像（如 abcfy2/zhparser）；Celery worker 和 beat 作为独立容器

### T-047: Alembic数据库迁移

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
- **实现提示**: T-003 中已生成初始迁移脚本的草稿，此任务负责完善和验证；分区表创建需手写 SQL 而非 autogenerate
