# CataForge

## 项目信息
- 项目名称: IntelliSource
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.4.0
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
  <!-- 可选值: standard | agile-lite | agile-prototype。矩阵见 COMMON-RULES §执行模式矩阵 -->
- 阶段配置: ui_design=N/A（backend-only），testing=启用，deployment=启用
- model 继承: AGENT.md 中 `model: inherit` 继承父会话模型

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)
- 当前阶段: development — sprint-8 P2 完成（含 T-071 集成 + sprint-review approved_with_notes）
- 下一步行动: 进入 deploy 阶段 (devops → deploy-spec) — 或决定先做 retrospective / 处理 5 个 sprint-8 SR-NNN backlog
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(N/A), dev_planning, sprint-1..7, retrospective, testing, sprint-7r, sprint-8r, sprint-9, sprint-8 P2]
- 当前Sprint: sprint-8 P2 ✅ done — 8 任务 + T-071 集成 + sprint-review-s8-r1 approved_with_notes (5 issues: 1 MEDIUM + 4 LOW, 全部 non-blocking)
- 文档状态: prd / arch / dev-plan(主卷+s1~s7+s7r+s8r+s9) / test-report = approved；ui-spec = N/A；dev-plan-s8 = draft (信任原 AC)；deploy-spec = 未开始
- sprint-8 现状核查矩阵 (2026-05-24):
  - ✅ 已闭环 (sprint-9 / sprint-8r 自然覆盖)：
    - T-068 外部 API 熔断器 — circuit_breaker.py 完整状态机 + gateway 集成
    - T-075 Agent 工具层接驳真实模块 — sprint-8r T-089 闭环，7 个 _execute 真消费 tool_deps
    - T-076 健康检查与指标端点 — sprint-9 T-099 完成
    - T-078 应用组合根 — sprint-9 T-095 完成 (composition.py + Celery 单例)
  - ✅ sprint-8 P2 真增量全部闭环 (T-064~T-070 + T-077 + T-079, 8 任务)
  - ✅ T-071 集成测试 — implementer light-dispatch 单次成功 + 9/9 passed (test_sprint8_integration.py 6 class)
  - ✅ sprint-review-s8-r1 — orchestrator inline takeover (reviewer opus 子代理 EXP-006 mid-narration 截断后接管) — verdict=approved_with_notes; 5 issues (SR-001 MEDIUM analyze deny 硬编码 + SR-002~005 LOW 全部 non-blocking)
- sprint-8 批次 1 闭环检查点:
  - T-064 status=done [light-dispatch + inline takeover, commit bf7da26] — implementer 67K tokens / 19 tools 单 turn output cap 截断（mid-narration 软截断 EXP-006 carryover），orchestrator inline 补齐 pipeline.py agent_mode 字段 + analyze runtime guard + runner.py 终止响应 messages-mutation 修复；20/20 test_agent_mode + 2519 PASS / 0 FAIL；code-review 延 sprint-review；refactor_needed=false
  - T-065 status=done [light-dispatch 单次成功, commit 82481d3] — implementer 76K tokens / 67 tools / 20min（输出 budget 内无 truncation，Mid-Progress Drop Contract 强制 4 步契约见效）；PermissionLevel(auto/confirm/deny) 枚举 + ToolDefinition.permission_level 字段 + register(permission_level) + distribute 默认 confirm + PipelineConfig.tool_permissions 字段 YAML 覆盖 + run_flexible 双层防御（_filter_tools deny 过滤 + 运行时 tool_call deny 硬拒）+ pending_confirmation logger/messages/tool_results 三轨记录；12/12 test_tool_permissions + 2571 PASS / 0 FAIL；mypy + ruff clean；code-review 延 sprint-review；refactor_needed=false
  - T-066 status=done [light-inline, commit 7c63bd4] — orchestrator 主线程直接执行（complexity=S, 范围小, 避免 EXP-006 dispatch 风险）；git mv tools.py → tools/__init__.py 保 21 处 import 路径不变 + 修正 _PIPELINES_DIR parents[3]→[4] 防 path drift + AgentToolRegistry.auto_discover(tools_dir) 扫描 *.py / TOOL_DEFINITION 常量 / 手注册优先 / import error 容错；10/10 test_tool_discovery + 全量回归 exit 0 / mypy --strict clean (126 src files) / ruff check + format clean；code-review 延 sprint-review；refactor_needed=false
  - T-067 status=done [light-inline, commit ef57935] — orchestrator 主线程（complexity=M but 范围聚焦 events.py + runner 钩子, ~150 LOC, 边界明确）；events.py PipelineEventLogger（JSONL 追加 + asyncio.to_thread 异步 + 5 helpers + try/except 失败 log warning 不抛）+ runner.py 集成（event_logger 构造参数 + run_strict/batch/flexible 入口 uuid 预生成 chain_id 贯穿事件 + time.monotonic 计时 + LLM chat() 抽 usage 拆 prompt/completion tokens + _persist 内 emit pipeline_complete + try/except 入口包裹 emit pipeline_error）；10/10 test_pipeline_events + 全量回归 exit 0 / mypy --strict clean (127 src files) / ruff check + format clean；code-review 延 sprint-review；refactor_needed=false
  - T-069 status=done [light-inline, commit dabd4f4] — orchestrator 主线程（complexity=S, ~30 LOC src + ~140 LOC test）；prompt_builder.py 新增 _resolve_template_path 工具 + 存 _call_type/_prompt_style/_template_path + @property call_type 暴露字段 + @property prompt_version 返回 SHA-256(file_bytes)[:8] 文件缺失返回 "unknown"；gateway.py complete() 新增 prompt_builder 参数 setdefault 自动填充 cache_key_parts.call_type/prompt_version（显式值优先 via setdefault 语义）；7/7 test_prompt_version + 全量回归 exit 0 / mypy --strict clean (127 src files) / ruff check + format clean；code-review 延 sprint-review；refactor_needed=false
  - T-070 status=done [light-dispatch 单次成功, commit 961edc8] — implementer 71K tokens / 31 tools / 4.5min（Mid-Progress Drop Contract 4 步契约见效，零截断）；gateway.py stream_complete() AsyncGenerator 包装 litellm.acompletion(stream=True) 逐 chunk yield {"content","done":false} 终结 {"content":"","done":true,"metadata":...} + 流结束 LLMCallRecord 统一记 success（AC-T070-5）+ asyncio.CancelledError / GeneratorExit 优雅关闭；search.py POST /api/v1/search/chat/stream 端点 FastAPI StreamingResponse + media_type=text/event-stream + json.dumps payload + await request.is_disconnected() 客户端断开短路 + app.state.llm_gateway 缺失 503；15/15（test_gateway_stream 10 + test_search_routes 5，覆盖 AC-T070-1~7 7 个 AC）+ 全量回归 exit 0 / mypy --strict clean (127 src files) / ruff check + format clean；code-review 延 sprint-review；refactor_needed=false；wiring 验证：app.state.llm_gateway 已在 composition.py:405 注入，implementer 误报 wiring gap
  - T-077 + T-079 status=done [light-inline 合并, commit a9e4a88] — T-077 真增量仅剩 AC-T077-4 (前期已闭环 AC-T077-1 sources reload 真实实现 / AC-T077-2 runner.py 顶层 import json)，pyproject.toml 新增 [tool.vulture] ignore_names=["names","a","kw"] 消除 circuit_breaker.py:21 Protocol *names 参数 + database.py:82 _closed_creator(*a,**kw) 闭包假阳性；T-079 compaction.py 暴露 compact_messages_for_chat(messages, gateway, max_tokens, model) 包装函数 — 内部构造合成 ModelProfile(context_window=max(max_tokens*2, 8192)) 委托 compact_messages 复用 T-058 token-aware pipeline + 暴露 _truncation_fallback_no_gateway 在 gateway=None 时按 char 估算 _CHARS_PER_TOKEN=4 + role=tool 优先裁剪；chat_session.py ChatSessionManager.__init__(session, llm_gateway=None) 注入 + compact_context() 改为 3 行委托 + 删除 keep_count=len/10 + summary_parts string-concat + [ASSUMPTION] docstring；21/21 test_chat_session（原 16 + 5 新 T-079: TestT079DelegationToAgentCompaction 1 + TestT079LLMSummarySuccess 1 + TestT079LLMFailureFallbackTruncation 1 + TestT079RoleToolPrunedFirst 1 + TestT079AssumptionDocstringRemoved 1, 原 test_compacted_summary_becomes_system_prefix 更新为注入 mock_gateway）+ 全量回归 exit 0 / mypy --strict clean (127 src files) / ruff check + format clean；code-review 延 sprint-review；refactor_needed=false
- sprint-9 / sprint-8r 详细闭环记录: 参见 docs/reviews/code/CODE-REVIEW-*.md 与 docs/reviews/sprint/SPRINT-REVIEW-*.md (sprint-9 全 6 任务 + sprint-8r T-087/088/089/092/094 全 approved；全量回归 2519 PASS / 43 skip / 0 fail；mypy --strict + ruff clean)
- 项目级 WIP 警示: 全量 ruff check 当前 13 errors 跨 6 个 test 文件 (test_pipeline_collect_process_distribute_e2e / test_app_entry / test_pipelines_router / test_search_chat_response_parsing / test_push_dedup / test_push_optimize_trigger / test_push_optimizer)，**非 T-064 自引入**（这些文件在 session 起始 git status 已为 M）。可能是 sprint-9 r2 修复 / sprint-8r 批次 4 残留未跑 ruff format 闭环，建议下次 sprint-review 前批量修
- Learnings Registry:
  - [RETRO-intellisource-v1.md](docs/reviews/retro/RETRO-intellisource-v1.md) — 6 EXP (sprint-1~7)，应用决策 deferred to backlog
  - [RETRO-intellisource-v1-sprint-9.md](docs/reviews/retro/RETRO-intellisource-v1-sprint-9.md) — 2 EXP 强制立项 (EXP-005 装配缺口 5 次复发 + EXP-006 truncation 4/4 跨 3 角色)
  - [SKILL-IMPROVE-*.md](docs/reviews/retro/) — 8 份建议
- 上游反馈: [docs/feedback/](docs/feedback/) — 1 bug + 1 suggest
- Backlog: ① 6 EXP 改进 (sprint-1~7) 应用到 .cataforge ② sprint-9 2 EXP 强制改进应用 (EXP-005 framework-level lint + EXP-006 anti-truncation 协议固化扩展到 reviewer/refactorer/debugger) ③ deploy 阶段 (devops → deploy-spec) ④ sprint-8 SR-001~005 5 issues (1 MEDIUM analyze deny 硬编码 / 4 LOW)

## 执行环境
- 包管理器: uv（fallback: pip）
- 安装: `uv sync`
- 测试: `uv run pytest`（全量）；`uv run pytest tests/unit/<path>` 单文件
- 类型: `uv run mypy --strict src/`
- 格式: `uv run ruff format . && uv run ruff check .`
- 容器: docker / docker-compose（docker/）
- 迁移: `uv run alembic upgrade head`

## 文档导航
- 索引: `docs/.doc-index.json`（通过 `cataforge docs load` 查询；缺失时 `cataforge docs index` 重建）
- 通用规则: .cataforge/rules/COMMON-RULES.md
- 子代理协议: .cataforge/rules/SUB-AGENT-PROTOCOLS.md
- 编排协议: .cataforge/agents/orchestrator/ORCHESTRATOR-PROTOCOLS.md
- 状态码 Schema: .cataforge/schemas/agent-result.schema.json
- 加载原则: 按需通过 `cataforge docs load` 加载章节，不全量加载

## 全局约定
- 命名: PEP 8（snake_case / PascalCase）
- Commit: Conventional Commits（feat/fix/docs/chore/refactor/test）
- 分支: GitHub Flow（main + feature branches）
- 设计工具: none
- 人工审查检查点: [pre_dev, pre_deploy]
- 文档类型命名: 小写 kebab-case
- 效率原则: 最小传递 (doc_id#section)、不确定调研、选择题优先、长文按 `DOC_SPLIT_THRESHOLD_LINES` 拆分

## 框架机制
- Agent 编排: orchestrator 通过 agent-dispatch skill 激活子代理
- DEV 阶段: orchestrator 通过 tdd-engine 编排 RED/GREEN/REFACTOR
- 状态持久化: CLAUDE.md（人面向） + .cataforge/PROJECT-STATE.md（框架镜像） + docs/
- 写权限: 项目状态由 orchestrator 独占；其他 Agent 只写 docs/ 或 src/
- 统一配置 `.cataforge/framework.json`：`upgrade.source` 保留 / `upgrade.state` 保留 / `features` `migration_checks` 全量覆盖
