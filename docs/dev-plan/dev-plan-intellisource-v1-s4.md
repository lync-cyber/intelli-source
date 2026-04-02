# Development Plan 分卷 -- Sprint 4: IntelliSource
<!-- required_sections: ["## 3. 任务卡详细"] -->
<!-- volume_type: sprint -->
<!-- id: dev-plan-intellisource-v1-s4 | author: tech-lead | status: draft -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: sprint | split-from: dev-plan-intellisource-v1 -->

[NAV]

- §3 任务卡详细 → T-037..T-046 (Sprint 4: API/CLI/MCP与集成)
[/NAV]

## 3. 任务卡详细

### T-037: Webhook回调处理(微信/企业微信)

- **目标**: 实现微信和企业微信的消息回调处理，包括签名验证、消息解析和指令路由到 Agent
- **模块**: M-007
- **接口**: API-020, API-021
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-T037-1: WebhookHandler 验证微信签名（sha1(sort(token, timestamp, nonce))）
  - [ ] AC-T037-2: WebhookHandler 验证企业微信消息签名
  - [ ] AC-T037-3: 解析 XML 消息体提取用户消息内容
  - [ ] AC-T037-4: 文本消息通过 M-006 TriggerManager 触发 Agent 执行 user_search Playbook
  - [ ] AC-T037-5: 签名验证失败返回 403
  - [ ] AC-T037-6: 消息处理异步执行，5s 内先返回空响应（微信要求）
- **deliverables** (交付物):
  - [ ] `src/intellisource/distributor/webhooks.py` -- Webhook 回调处理
  - [ ] `tests/unit/distributor/test_webhooks.py` -- 回调处理测试
- **context_load**:
  - arch#§2.M-007
  - arch-intellisource-v1-api#API-020
  - arch-intellisource-v1-api#API-021
  - arch#§5.2（Webhook 签名验证）

### T-038: API路由层 -- 信源管理

- **目标**: 实现信源管理的 FastAPI 路由（CRUD + 配置重载）
- **模块**: M-011
- **接口**: API-001, API-002, API-003, API-004, API-005
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-061 映射: API 支持信源的创建/查询/更新/删除操作
  - [ ] AC-065 映射: FastAPI 自动生成 OpenAPI 文档
  - [ ] AC-T038-1: GET /api/v1/sources 支持分页和过滤（type/tag/status）
  - [ ] AC-T038-2: POST /api/v1/sources 创建信源，409 冲突正确处理
  - [ ] AC-T038-3: PATCH /api/v1/sources/{id} 部分更新
  - [ ] AC-T038-4: DELETE /api/v1/sources/{id} 删除信源
  - [ ] AC-T038-5: POST /api/v1/sources/reload 配置重载（白名单校验）
- **deliverables** (交付物):
  - [ ] `src/intellisource/api/routers/sources.py` -- 信源路由
  - [ ] `tests/unit/api/test_sources.py` -- 信源 API 测试
- **context_load**:
  - arch#§2.M-011
  - arch-intellisource-v1-api#API-001~API-005

### T-039: API路由层 -- 任务与工作流

- **目标**: 实现任务管理和工作流管理的 FastAPI 路由
- **模块**: M-011
- **接口**: API-006~API-011, API-026~API-029
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-062 映射: API 支持手动触发采集任务和查询任务状态
  - [ ] AC-063 映射: API 支持定义和执行自定义工作流
  - [ ] AC-065 映射: 自动生成 OpenAPI 文档
  - [ ] AC-T039-1: GET /api/v1/tasks 任务列表（分页+过滤）
  - [ ] AC-T039-2: POST /api/v1/tasks/collect 触发采集（返回 202）
  - [ ] AC-T039-3: 工作流 CRUD（GET/POST/PATCH/DELETE /api/v1/workflows）
  - [ ] AC-T039-4: POST /api/v1/workflows/{id}/run 执行工作流（返回 202）
- **deliverables** (交付物):
  - [ ] `src/intellisource/api/routers/tasks.py` -- 任务路由
  - [ ] `src/intellisource/api/routers/workflows.py` -- 工作流路由
  - [ ] `tests/unit/api/test_tasks.py` -- 任务 API 测试
  - [ ] `tests/unit/api/test_workflows.py` -- 工作流 API 测试
- **context_load**:
  - arch#§2.M-011
  - arch-intellisource-v1-api#API-006~API-011

### T-040: API路由层 -- 内容/检索/订阅/LLM/系统

- **目标**: 实现内容查询、检索、订阅管理、LLM 统计和系统端点的 FastAPI 路由
- **模块**: M-011
- **接口**: API-012~API-019, API-022~API-025
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-061 映射: 内容列表/详情/聚类 API 正确路由
  - [ ] AC-065 映射: 自动生成 OpenAPI 文档
  - [ ] AC-T040-1: GET /api/v1/contents 内容列表（分页+过滤）
  - [ ] AC-T040-2: POST /api/v1/search 混合检索（调用 search_hybrid 原子操作）
  - [ ] AC-T040-3: POST /api/v1/search/chat 即时问答（触发 Agent user_search）
  - [ ] AC-T040-4: 订阅规则 CRUD（/api/v1/subscriptions）
  - [ ] AC-T040-5: GET /api/v1/llm/stats LLM 用量统计
  - [ ] AC-T040-6: GET /api/v1/health 和 GET /api/v1/metrics 系统端点
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
  - arch-intellisource-v1-api#API-012~API-025

### T-041: 原子操作API端点(自动生成)

- **目标**: 从 ToolRegistry 自动为每个原子操作生成 POST /api/v1/tools/{tool_name} 端点
- **模块**: M-011, M-003
- **接口**: API-030
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-066 映射: 所有注册的原子操作通过 /api/v1/tools/{tool_name} 可调用
  - [ ] AC-T041-1: ToolsRouter 遍历 ToolRegistry，为每个 ToolSpec 自动生成 POST 端点
  - [ ] AC-T041-2: 请求体自动按 ToolSpec.parameters JSON Schema 校验
  - [ ] AC-T041-3: 响应体符合 ToolSpec.returns 定义
  - [ ] AC-T041-4: 未注册的 tool_name 返回 404
  - [ ] AC-T041-5: 自动生成的端点出现在 OpenAPI 文档中
- **deliverables** (交付物):
  - [ ] `src/intellisource/api/routers/tools.py` -- 原子操作 API 端点
  - [ ] `tests/unit/api/test_tools.py` -- 原子操作 API 测试
- **context_load**:
  - arch#§2.M-011
  - arch#§2.M-003
  - arch-intellisource-v1-api#API-030

### T-042: MCP Server

- **目标**: 实现 MCP Server，从 ToolRegistry 自动生成 MCP Tool 定义，支持 stdio 和 SSE 传输
- **模块**: M-012
- **接口**: MCP 协议端点
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-066 映射: 所有原子操作通过 MCP 协议可调用
  - [ ] AC-067 映射: MCP Tool 定义从 ToolSpec 自动生成，无需手动维护
  - [ ] AC-068 映射: 外部 Agent 可通过 MCP 完成完整采集-处理-存储-分发流程
  - [ ] AC-070 映射: MCP 调用共享认证和可观测性基础设施
  - [ ] AC-T042-1: MCPServer 启动时从 ToolRegistry 加载所有工具
  - [ ] AC-T042-2: ToolSpec.name → MCP tool name, ToolSpec.parameters → MCP input_schema 映射正确
  - [ ] AC-T042-3: 支持 stdio 传输模式（本地进程间通信）
  - [ ] AC-T042-4: 支持 SSE 传输模式（远程 HTTP）
  - [ ] AC-T042-5: MCP 调用结果包含 trace_id 用于链路追踪
- **deliverables** (交付物):
  - [ ] `src/intellisource/mcp/server.py` -- MCP Server 实现
  - [ ] `src/intellisource/mcp/__init__.py` -- 模块导出
  - [ ] `tests/unit/mcp/test_server.py` -- MCP Server 测试
- **context_load**:
  - arch#§2.M-012
  - arch-intellisource-v1-api#API-030（MCP Server 端点说明）
- **实现提示**: 使用 mcp Python SDK；工具注册使用 @server.tool 装饰器；测试可使用 mcp SDK 的 test client

### T-043: 认证中间件与请求追踪

- **目标**: 实现 API Key 认证中间件、请求日志中间件和请求链路追踪中间件
- **模块**: M-011
- **接口**: 全部需认证的 API
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-T043-1: AuthMiddleware 校验 X-API-Key 请求头，无效时返回 401
  - [ ] AC-T043-2: API Key 通过环境变量配置（IS_API_KEY）
  - [ ] AC-T043-3: 健康检查和 Webhook 端点豁免认证
  - [ ] AC-T043-4: RequestLogger 记录每个请求的 method/path/status_code/duration_ms
  - [ ] AC-T043-5: TracingMiddleware 为每个请求注入 trace_id 到日志上下文和响应头
  - [ ] AC-T043-6: 原子操作端点 /api/v1/tools/* 共享同一认证机制
- **deliverables** (交付物):
  - [ ] `src/intellisource/api/deps.py` -- FastAPI 依赖注入（认证）
  - [ ] `src/intellisource/api/middleware.py` -- 中间件（日志/追踪）
  - [ ] `tests/unit/api/test_middleware.py` -- 中间件测试
- **context_load**:
  - arch#§2.M-011
  - arch#§5.2（认证机制）

### T-044: CLI工具

- **目标**: 实现基于 typer 的 CLI 工具，封装常用 API 操作
- **模块**: M-011
- **接口**: 无（CLI 通过 HTTP 调用 API）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-064 映射: CLI 工具封装常用 API 操作
  - [ ] AC-T044-1: `intellisource source list/add/update/delete` 信源管理命令
  - [ ] AC-T044-2: `intellisource task trigger/status` 任务操作命令
  - [ ] AC-T044-3: `intellisource workflow list/create/run` 工作流命令
  - [ ] AC-T044-4: `intellisource search <query>` 检索命令
  - [ ] AC-T044-5: `intellisource tool <tool_name> <params_json>` 原子操作直接调用命令
  - [ ] AC-T044-6: CLI 输出格式化为表格（默认）或 JSON（--json 参数）
  - [ ] AC-T044-7: API 地址和 Key 通过环境变量或 --api-url/--api-key 参数配置
- **deliverables** (交付物):
  - [ ] `src/intellisource/cli/main.py` -- typer CLI 入口
  - [ ] `tests/unit/cli/test_main.py` -- CLI 测试
- **context_load**:
  - arch#§2.M-011
  - arch#§6（cli/ 目录结构）

### T-045: FastAPI应用入口与Docker部署

- **目标**: 组装 FastAPI 应用入口（注册路由/中间件/生命周期），编写 Dockerfile 和 docker-compose.yml
- **模块**: M-011
- **接口**: 全部 API + MCP
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-065 映射: /docs 自动提供 OpenAPI/Swagger 文档
  - [ ] AC-T045-1: main.py 注册所有路由组（含 tools 路由）和中间件
  - [ ] AC-T045-2: 应用启动时初始化数据库连接池、Redis 连接、Celery app、ToolRegistry
  - [ ] AC-T045-3: 应用关闭时正确释放所有资源
  - [ ] AC-T045-4: Dockerfile 构建成功且镜像大小合理（多阶段构建）
  - [ ] AC-T045-5: docker-compose.yml 包含 app/celery-worker/celery-beat/postgres(zhparser)/redis/mcp-server 服务
  - [ ] AC-T045-6: `docker compose up` 一键启动全部服务
  - [ ] AC-T045-7: MCP Server 作为独立进程运行（stdio 模式）或作为 FastAPI 子路由（SSE 模式）
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
- **实现提示**: PostgreSQL 使用包含 zhparser 扩展的镜像；Celery worker 和 beat 作为独立容器；MCP Server 可通过环境变量选择传输模式

### T-046: Alembic数据库迁移

- **目标**: 配置 Alembic 迁移框架，基于 ORM 模型（含 E-013）生成初始迁移脚本
- **模块**: M-009
- **接口**: 无
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-054 映射: 数据库表结构与 ORM 模型一致
  - [ ] AC-T046-1: `alembic upgrade head` 从空库创建全部表和索引
  - [ ] AC-T046-2: `alembic downgrade base` 回退所有迁移
  - [ ] AC-T046-3: 迁移脚本包含 pgvector 扩展创建
  - [ ] AC-T046-4: 迁移脚本包含 zhparser 扩展创建
  - [ ] AC-T046-5: E-007 LLMCallLog 分区表正确创建
  - [ ] AC-T046-6: E-013 AgentExecutionLog 表正确创建
- **deliverables** (交付物):
  - [ ] `alembic/env.py` -- Alembic 环境配置
  - [ ] `alembic/versions/{initial}.py` -- 初始迁移脚本（完整版）
  - [ ] `tests/integration/test_migration.py` -- 迁移测试
- **context_load**:
  - arch-intellisource-v1-data#§4（全部实体含 E-013）
  - arch#§1.4（pgvector, zhparser）
