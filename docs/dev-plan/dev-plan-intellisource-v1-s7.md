---
id: dev-plan-intellisource-v1-s7
doc_type: dev-plan
author: tech-lead
status: approved
deps: [arch-intellisource-v1]
consumers: [developer, qa-engineer]
volume: s7
split_from: dev-plan-intellisource-v1
---
# Development Plan: IntelliSource — Sprint 7
<!-- id: dev-plan-intellisource-v1-s7 | author: tech-lead | status: approved -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: s7 -->

> **Sprint 主题**: LLM 韧性增强与配置治理（P1 改进项，源自 OpenCode 对标架构评审）
> **前置依赖**: Sprint 6 全部完成（T-047~T-056）
> **参考**: docs/research/architecture-review-opencode-benchmark.md

[NAV]

- §3 任务卡详细
  - T-057 LLM 调用指数退避重试 ✅ done
  - T-058 上下文压缩增强 ✅ done
  - T-059 配置分层合并机制 ✅ done
  - T-060 LLM 统计仪表盘 API ✅ done
  - T-061 LLM 配置 Pydantic Schema 验证 ✅ done
  - T-062 模型特化 Prompt 变体 ✅ GREEN（待 code-review）
  - T-063 Sprint 7 集成测试与回归
  - T-072 数据库会话 DI 接驳（新增，源自 CODE-SCAN R-001/R-007）
  - T-073 GET /api/v1/clusters 端点（新增，源自 CODE-SCAN R-003）
  - T-074 TaskChainRepository 实现（新增，源自 CODE-SCAN R-006）

[/NAV]

## 3. 任务卡详细

### T-057: LLM 调用指数退避重试 ✅ done

- **目标**: 为 `LLMGateway.complete()` 增加 tenacity 指数退避重试，仅对 `RECOVERABLE_TRANSIENT` 错误重试，耗尽后降级到 FallbackManager
- **模块**: M-005
- **接口**: internal
- **复杂度**: S
- **依赖**: T-053（ModelProfile.timeout_seconds）
- **status**: done（2026-05-03，code-review-T-057-r2 approved）
- **tdd_acceptance**:
  - [x] AC-T057-1: RECOVERABLE_TRANSIENT 错误自动重试最多 3 次
  - [x] AC-T057-2: 退避策略为 exponential(min=1s, max=30s)
  - [x] AC-T057-3: UNRECOVERABLE/RECOVERABLE_DEGRADED 错误不重试，直接降级
  - [x] AC-T057-4: 重试耗尽后调用 FallbackManager.execute_fallback()
  - [x] AC-T057-5: 每次重试记录到 LLMCallLog（status=retry, retry_attempt=N，call_type 透传业务 task_type）
  - [x] AC-T057-6: `litellm.acompletion()` 调用使用 `ModelProfile.timeout_seconds` 作为 timeout 参数
  - [x] AC-T057-7: mypy --strict 零错误
- **deliverables**:
  - [x] `src/intellisource/llm/gateway.py` — retry 逻辑（tenacity AsyncRetrying + _classify_error / _call_with_retry / _try_fallback / _log_retry）
  - [x] `tests/unit/llm/test_gateway_retry.py` — retry 行为测试（16 tests）
  - [x] 配套：`pyproject.toml`(+tenacity)、`cost_tracker.py`(LLMCallRecord.retry_attempt)、`storage/models.py`+`alembic/versions/001_initial_schema.py`(LLMCallLog.retry_attempt 列)
- **context_load**:
  - src/intellisource/llm/gateway.py (LLMGateway.complete)
  - src/intellisource/llm/fallback.py (FallbackManager)
  - src/intellisource/core/errors.py (ErrorCategory)

---

### T-058: 上下文压缩增强 ✅ done

- **目标**: 重构 `compact_messages()` 为 token-based 保留策略 + 结构化摘要模板，替代当前的固定百分比消息截断
- **模块**: M-006, M-005
- **接口**: internal
- **复杂度**: M
- **依赖**: T-051（PromptBuilder）
- **status**: done（2026-05-03，code-review-T-058-r2 approved_with_notes，N-001 主线直改闭环；20 tests, 1672 全量回归 PASSED）
- **tdd_acceptance**:
  - [x] AC-T058-1: 保留策略基于 token 计数（使用 `LLMGateway.estimate_tokens()`）而非消息数量百分比
  - [x] AC-T058-2: 摘要使用结构化模板 `compaction_summary.txt`（包含 Goal/Context/Changes/State/Next Steps 五段）
  - [x] AC-T058-3: 工具输出优先裁剪 — role=tool 消息按时间从旧到新裁剪，保护最近 3 条工具结果
  - [x] AC-T058-4: 自动触发阈值：当 estimated tokens > min(context_window * 0.8, context_token_budget) 时自动压缩（`context_window * 0.8` 为模型容量层上限，`context_token_budget`（arch §5.1 [chat] 配置，默认 2000）为系统配置层上限，取较小值保证两层约束均满足）
  - [x] AC-T058-5: 压缩后消息列表 token 数 ≤ context_window * 0.6（留足生成空间）
  - [x] AC-T058-6: LLM 摘要失败时 fallback 到 truncation 策略（保留最近 N 条原文，N 由 token budget 决定）
  - [x] AC-T058-7: mypy --strict 零错误
- **deliverables**:
  - [x] `src/intellisource/agent/compaction.py` — 重构
  - [x] `src/intellisource/llm/prompts/compaction_summary.txt` — 结构化摘要模板
  - [x] `tests/unit/agent/test_compaction.py` — 更新（20 tests，含 R-001 边界 + N-001 litellm 风格异常回归）
- **context_load**:
  - src/intellisource/agent/compaction.py (现有 compact_messages)
  - src/intellisource/llm/gateway.py (estimate_tokens)
  - docs/research/architecture-review-opencode-benchmark.md §GAP-B2

---

### T-059: 配置分层合并机制 ✅ done

- **目标**: 实现 `ConfigResolver` 支持 defaults → project → env vars 三层配置深度合并，供 LLM 配置和源配置统一使用
- **模块**: M-001
- **接口**: internal
- **复杂度**: M
- **依赖**: T-053（ModelProfile YAML 配置）
- **status**: done（2026-05-03，与 T-061 合并 dispatch；CODE-REVIEW-T-059-T-061-r3 approved_with_notes，R-001~R-013 全闭环，R-014 LOW chore 余量）
- **tdd_acceptance**:
  - [x] AC-T059-1: `config/defaults.yaml` 作为全局默认值层（版本控制内，提供所有配置项的合理默认值）
  - [x] AC-T059-2: `config/llm_models.yaml` 作为项目覆盖层，覆盖 defaults.yaml 中的同名配置
  - [x] AC-T059-3: `IS_*` 前缀环境变量作为最高优先级覆盖（`IS_LLM_DEFAULT_MODEL` → `default_model.model`，含 `IS_LLM_*` 域前缀剥离 + 白名单防注入）
  - [x] AC-T059-4: 深度合并策略 — nested dict recursive merge，list 覆盖不合并
  - [x] AC-T059-5: `ConfigResolver.resolve()` 返回最终合并后的 config dict
  - [x] AC-T059-6: 合并结果通过可注入的 Pydantic validator 验证（resolver 接受 `validator: Callable | None`；调用方注入 `LLMModelsConfig.model_validate`）
  - [x] AC-T059-7: 缺少 defaults.yaml 时仅使用 project config + env vars（不报错）
  - [x] AC-T059-8: mypy --strict 零错误
- **实现顺序**: T-059 与 T-061 存在双向引用（T-061 的 ConfigResolver 集成依赖 T-059；T-059 的 AC-T059-6 依赖 T-061 的 LLMModelsConfig）。推荐执行顺序：① 先完成 T-061 的 Pydantic model 定义部分（LLMModelsConfig + ModelTaskConfig 最小字段集）→ ② 实现 T-059 ConfigResolver 并在 AC-T059-6 中复用上述 schema → ③ T-061 完成剩余的 load_model_config() 集成与验证规则扩充。
- **deliverables**:
  - [x] `src/intellisource/config/resolver.py` — ConfigResolver 类（含贪婪前缀匹配 + 白名单 + validator 注入）
  - [x] `src/intellisource/config/llm_schema.py` — Pydantic schema 迁移到 M-001（R-006 修订）
  - [x] `config/defaults.yaml` — 全局默认值文件
  - [x] `tests/unit/config/test_resolver.py` — 分层合并测试（30+ tests）
- **context_load**:
  - src/intellisource/config/loader.py (ConfigLoader)
  - src/intellisource/llm/model_config.py (load_model_config)
  - config/llm_models.example.yaml

---

### T-060: LLM 统计仪表盘 API ✅ done

- **目标**: 实现 `GET /api/v1/llm/stats` 端点，聚合 LLMCallLog 数据，响应结构完整对齐 API-017 规范
- **模块**: M-005, M-009, M-011
- **接口**: API-017（已定义；本任务期间通过 architect amendment 更新字段命名以对齐 AC，闭环 R-005）
- **复杂度**: S
- **依赖**: T-021（LLMCallLog 模型与成本追踪）、T-056（Sprint 6 全量回归）
- **扫描背景**: CODE-SCAN R-004/R-005/R-013 — `api/routers/llm.py` 中的 stub `LLMCallLogRepository` 永远返回 `{}`；`CostTracker.get_stats()` 仅有 3 个字段，缺少 `avg_latency_ms`/`by_model`/`by_date`/`total_tokens`；Repository 类错误地定义在路由文件而非存储层
- **status**: done（2026-05-03，CODE-REVIEW-T-060-r3 approved_with_notes；r1 needs_revision → r2 approved_with_notes → r3 approved_with_notes 共 3 轮修订；R-001/R-002/R-003/R-004/R-005/R-007 全闭环；R-006 MEDIUM 升级 → sprint-7 retrospective EXP；19 target tests + 1739 全量回归 PASSED；mypy strict src/ + ruff clean）
- **tdd_acceptance**:
  - [x] AC-T060-1: `GET /api/v1/llm/stats?period=day` 支持 `period` 参数（day/week/month）查询时间窗口
  - [x] AC-T060-2: 响应字段包含 `period`、`total_calls`、`total_tokens`（input+output 之和）、`total_input_tokens`、`total_output_tokens`（对齐 API-017）
  - [x] AC-T060-3: 响应字段包含 `avg_latency_ms`（`AVG(latency_ms)` 全局聚合，`LLMCallLog.latency_ms` 列已存在）
  - [x] AC-T060-4: 响应字段包含 `by_model[]`（`GROUP BY model`，每项含 `model`/`call_count`/`input_tokens`/`output_tokens`/`error_rate`）
  - [x] AC-T060-5: 响应字段包含 `by_date[]`（`GROUP BY DATE(created_at)`，每项含 `date`/`call_count`/`total_tokens`）
  - [x] AC-T060-6: 无数据时返回空聚合结果（`total_calls=0`，`by_model=[]`，`by_date=[]`，不报错）
  - [x] AC-T060-7: 支持可选 `model` 和 `call_type` 过滤参数
  - [x] AC-T060-8: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/storage/repositories/llm_call_log.py` — `LLMCallLogRepository` 含 `get_stats()` 多维 SQL 聚合（移出路由文件）
  - [ ] `src/intellisource/api/routers/llm.py` — 替换内联 stub，改为 `Depends(get_db_session)` + 真实 `LLMCallLogRepository`
  - [ ] `src/intellisource/storage/repositories/__init__.py` — 导出 `LLMCallLogRepository`
  - [ ] `tests/unit/api/test_llm_routes.py` — ≥8 tests（覆盖各字段、空数据、过滤参数）
- **context_load**:
  - src/intellisource/api/routers/llm.py (现有 stub)
  - src/intellisource/storage/models.py (LLMCallLog E-011，含 latency_ms/model/call_type/created_at 列)
  - src/intellisource/llm/cost_tracker.py (CostTracker 现有聚合参考)
  - docs/arch/arch-intellisource-v1-api.md#API-017 (响应字段规范)

---

### T-061: LLM 配置 Pydantic Schema 验证 ✅ done

- **目标**: 为 `config/llm_models.yaml` 创建 Pydantic 验证模型，在 `load_model_config()` 中自动验证
- **模块**: M-001, M-005
- **接口**: internal
- **复杂度**: S
- **依赖**: T-059（ConfigResolver 集成）
- **status**: done（2026-05-03，与 T-059 合并 dispatch；CODE-REVIEW-T-059-T-061-r3 approved_with_notes）
- **tdd_acceptance**:
  - [x] AC-T061-1: `LLMModelsConfig` Pydantic model 覆盖所有 YAML 字段（default_model, models, profiles）
  - [x] AC-T061-2: `ModelTaskConfig` 子模型验证 model/provider/temperature/max_tokens
  - [x] AC-T061-3: `load_model_config()` 加载后自动通过 LLMModelsConfig 验证
  - [x] AC-T061-4: 无效配置抛出 `ValidationError` 并指明具体字段（如 `temperature 必须在 0.0~2.0 之间`）
  - [x] AC-T061-5: 缺少可选字段时使用 Pydantic 默认值（不报错）
  - [x] AC-T061-6: mypy --strict 零错误
- **deliverables**:
  - [x] `src/intellisource/config/llm_schema.py` — LLMModelsConfig + ModelTaskConfig + DefaultModelConfig + ModelProfileConfig Pydantic models（R-006 迁移到 M-001）
  - [x] `src/intellisource/llm/model_config.py` — re-export 保持向后兼容；`load_model_config()` 自动校验
  - [x] `tests/unit/llm/test_model_config_validation.py` — 验证测试（17 tests，含 R-010 LLMGateway 包装回归）
- **context_load**:
  - src/intellisource/llm/model_config.py (load_model_config)
  - config/llm_models.example.yaml

---

### T-062: 模型特化 Prompt 变体 ✅ GREEN（待 code-review）

- **目标**: PromptBuilder 根据 `ModelProfile.prompt_style` 选择 prompt 模板变体文件，支持不同模型家族使用优化的 prompt 格式
- **模块**: M-005
- **接口**: internal
- **复杂度**: S
- **tdd_mode**: light（dispatch 模式：执行模式=standard 不走 inline）
- **status**: GREEN done（2026-05-04，commit d355560；implementer self-report refactor_needed=false；43 target tests + 1754 全量回归 PASSED；mypy --strict src/ clean (102 files)；ruff check + format clean。Option A：summarizer.structured.txt 沿用现有命名约定，summarization.* deliverable 字面偏离已说明并采纳）
- **依赖**: T-051（PromptBuilder）, T-053（ModelProfile.prompt_style）
- **tdd_acceptance**:
  - [ ] AC-T062-1: `llm/prompts/` 支持 `{name}.{style}.txt` 变体文件命名（如 `extraction.structured.txt`）
  - [ ] AC-T062-2: PromptBuilder 优先加载 `{name}.{prompt_style}.txt`，文件不存在时 fallback 到 `{name}.txt`
  - [ ] AC-T062-3: 至少为 `extraction` 和 `summarization` 提供 `structured` 变体（适合 Claude 系列模型的 XML 结构化指令）
  - [ ] AC-T062-4: 至少为 `extraction` 提供 `concise` 变体（适合 GPT 系列的简洁直接指令）
  - [ ] AC-T062-5: `load_prompt()` 函数签名不变（向后兼容），style 通过新的可选参数传入
  - [ ] AC-T062-6: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/llm/prompts/__init__.py` — 变体加载逻辑
  - [ ] `src/intellisource/llm/prompts/extraction.structured.txt` — 结构化变体
  - [ ] `src/intellisource/llm/prompts/extraction.concise.txt` — 简洁变体
  - [ ] `src/intellisource/llm/prompts/summarization.structured.txt` — 摘要结构化变体
  - [ ] `tests/unit/llm/test_prompt_builder.py` — 变体加载测试（≥6 tests）
- **context_load**:
  - src/intellisource/llm/prompts/__init__.py (load_prompt, _read_template)
  - src/intellisource/llm/prompt_builder.py (PromptBuilder)
  - docs/research/prompt-management-analysis.md §2.2

---

### T-063: Sprint 7 集成测试与回归

- **目标**: 验证 Sprint 7 所有改进（含新增基础设施任务 T-072~T-074）在集成场景下正常工作，全量 pytest + mypy 通过
- **模块**: 全模块
- **接口**: internal
- **复杂度**: M
- **依赖**: T-057~T-062, T-072~T-074
- **tdd_acceptance**:
  - [ ] AC-T063-1: LLM 重试 + fallback 端到端测试（模拟连续失败 → 重试 → 降级）
  - [ ] AC-T063-2: ConfigResolver 三层合并集成测试（defaults + project + env）
  - [ ] AC-T063-3: PromptBuilder 变体加载 + ModelProfile 集成测试
  - [ ] AC-T063-4: 上下文压缩在 AgentRunner flexible 模式中正确触发
  - [ ] AC-T063-5: `GET /api/v1/llm/stats` 集成测试（含真实 DB session，验证聚合字段）
  - [ ] AC-T063-6: `GET /api/v1/clusters` 集成测试（分页、tag 过滤）
  - [ ] AC-T063-7: TaskChainRepository 写入 + 读取集成测试
  - [ ] AC-T063-8: 全量 `pytest` 通过（无 import 错误、无残留引用）
  - [ ] AC-T063-9: `mypy --strict src/` 零错误
- **deliverables**:
  - [ ] `tests/integration/test_sprint7_integration.py` — 集成测试（含 T-072~T-074 场景）
  - [ ] 全量 pytest + mypy 通过报告
- **context_load**:
  - 所有 T-057 ~ T-062, T-072 ~ T-074 deliverables

---

### T-072: 数据库会话 DI 接驳

> **来源**: CODE-SCAN-20260503-r1 R-001/R-007（HIGH）

- **目标**: 将 `DatabaseManager` 接入 FastAPI lifespan 和依赖注入体系，消除所有路由的 `yield None` 占位，统一通过 `api/deps.py:get_db_session()` 注入真实会话
- **模块**: M-009, M-011
- **接口**: internal（DI 配置）
- **复杂度**: M
- **依赖**: T-002（DatabaseManager 已实现）
- **tdd_acceptance**:
  - [ ] AC-T072-1: `main.py` lifespan 在 startup 阶段实例化 `DatabaseManager` 并存入 `app.state.db`，shutdown 阶段调用 `db.close()`
  - [ ] AC-T072-2: `api/deps.py:get_db_session()` 从 `request.app.state.db.get_session()` yield 真实 `AsyncSession`
  - [ ] AC-T072-3: 6 个路由文件（sources/contents/tasks/subscriptions/search/llm）中的局部 `get_session()` 定义全部删除，替换为 `Depends(get_db_session)` from `api.deps`
  - [ ] AC-T072-4: `main.py` 的 `init_redis()` 补充真实 Redis 连接初始化逻辑（`aioredis.from_url`）；`init_celery()` 补充 Celery app 初始化
  - [ ] AC-T072-5: 全量测试仍通过（现有 mock-based 测试不因此破坏，session 注入层由 conftest 覆写）
  - [ ] AC-T072-6: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/main.py` — lifespan 补充 DatabaseManager/Redis/Celery 真实初始化
  - [ ] `src/intellisource/api/deps.py` — `get_db_session()` 接驳 `app.state.db`
  - [ ] `src/intellisource/api/routers/{sources,contents,tasks,subscriptions,search,llm}.py` — 删除局部 `get_session()`，改用 `from intellisource.api.deps import get_db_session`
  - [ ] `tests/conftest.py` — 确保 DB session fixture 覆写路径正确（`app.dependency_overrides`）
- **context_load**:
  - src/intellisource/storage/database.py (DatabaseManager.get_session)
  - src/intellisource/api/deps.py
  - src/intellisource/main.py

---

### T-073: GET /api/v1/clusters 端点

> **来源**: CODE-SCAN-20260503-r1 R-003（HIGH）

- **目标**: 新增 `GET /api/v1/clusters` 端点，对齐 API-016 契约，补充 `ClusterRepository`
- **模块**: M-009, M-011
- **接口**: API-016（已定义）
- **复杂度**: M
- **依赖**: T-003（ContentCluster ORM 模型已存在）、T-005（pgvector，clusters 含向量相关字段）
- **tdd_acceptance**:
  - [ ] AC-T073-1: `GET /api/v1/clusters` 返回集群列表，支持 cursor 分页（`cursor` + `limit` 参数，默认 `limit=20`）
  - [ ] AC-T073-2: 支持 `tag` 过滤参数（按 `ContentCluster.tags` 字段）
  - [ ] AC-T073-3: 支持 `date_from` / `date_to` 过滤参数（按 `ContentCluster.created_at`）
  - [ ] AC-T073-4: 每条集群响应包含 `id`/`label`/`tags`/`item_count`/`created_at` 字段
  - [ ] AC-T073-5: 无集群时返回 `{"items": [], "next_cursor": null}`
  - [ ] AC-T073-6: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/storage/repositories/cluster.py` — `ClusterRepository`（`list_clusters` 含分页/过滤）
  - [ ] `src/intellisource/api/routers/clusters.py` — GET /api/v1/clusters 端点
  - [ ] `src/intellisource/storage/repositories/__init__.py` — 导出 `ClusterRepository`
  - [ ] `src/intellisource/main.py` — 注册 clusters router
  - [ ] `tests/unit/api/test_clusters_routes.py` — ≥6 tests
- **context_load**:
  - src/intellisource/storage/models.py (ContentCluster E-007)
  - src/intellisource/storage/repositories/content.py (参照 ContentRepository 分页模式)
  - docs/arch/arch-intellisource-v1-api.md#API-016

---

### T-074: TaskChainRepository 实现

> **来源**: CODE-SCAN-20260503-r1 R-006（MEDIUM）

- **目标**: 补充 `TaskChainRepository`，接入 `scheduler/tasks.py` 和 `agent/runner.py` 的占位路径，使 TaskChain 记录正常写入数据库
- **模块**: M-009
- **接口**: internal
- **复杂度**: S
- **依赖**: T-003（TaskChain ORM 模型已存在于 `storage/models.py:99`）
- **tdd_acceptance**:
  - [ ] AC-T074-1: `TaskChainRepository.create(task_chain: TaskChain) -> TaskChain` — 持久化一条 TaskChain 记录
  - [ ] AC-T074-2: `TaskChainRepository.get(chain_id: str) -> TaskChain | None` — 按 ID 查询
  - [ ] AC-T074-3: `TaskChainRepository.update_status(chain_id: str, status: str) -> None` — 更新状态字段
  - [ ] AC-T074-4: `scheduler/tasks.py` 中移除 `TaskChainRepository: Any = None` 全局占位，改为运行时从 DI/session 获取实例
  - [ ] AC-T074-5: `agent/runner.py:250` 的注释占位替换为真实 `TaskChainRepository` 写入调用
  - [ ] AC-T074-6: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/storage/repositories/task_chain.py` — `TaskChainRepository`
  - [ ] `src/intellisource/storage/repositories/__init__.py` — 导出 `TaskChainRepository`
  - [ ] `src/intellisource/scheduler/tasks.py` — 移除 `Any = None` 占位，注入真实 repository
  - [ ] `src/intellisource/agent/runner.py` — 替换注释占位为 `TaskChainRepository` 写入
  - [ ] `tests/unit/storage/test_task_chain_repository.py` — ≥5 tests
  - [ ] (R2-004 顺手) `src/intellisource/storage/models.py` — 抽出 `TimestampMixin`（含 `created_at` / `updated_at`）与可选的 `ExecutionTimingMixin`（含 `started_at` / `finished_at`），消除 jscpd 报告的 7 处列模板内部克隆。要求：现有 ORM 表结构与迁移产物 (`alembic/versions/`) 不变
- **context_load**:
  - src/intellisource/storage/models.py (TaskChain E-008，lines 99~)
  - src/intellisource/scheduler/tasks.py (TaskChainRepository 占位，line 28)
  - src/intellisource/agent/runner.py (注释占位，line 250)
  - src/intellisource/storage/repositories/task.py (参照 TaskRepository 模式)
  - docs/reviews/code/CODE-SCAN-20260503-r2.md#R2-004 (TimestampMixin 顺手清理)
