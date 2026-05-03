---
id: dev-plan-intellisource-v1-s7
doc_type: dev-plan
author: tech-lead
status: draft
deps: [arch-intellisource-v1]
consumers: [developer, qa-engineer]
volume: s7
split_from: dev-plan-intellisource-v1
---
# Development Plan: IntelliSource — Sprint 7
<!-- id: dev-plan-intellisource-v1-s7 | author: tech-lead | status: draft -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: s7 -->

> **Sprint 主题**: LLM 韧性增强与配置治理（P1 改进项，源自 OpenCode 对标架构评审）
> **前置依赖**: Sprint 6 全部完成（T-047~T-056）
> **参考**: docs/research/architecture-review-opencode-benchmark.md

[NAV]

- §3 任务卡详细
  - T-057 LLM 调用指数退避重试 ✅ done
  - T-058 上下文压缩增强
  - T-059 配置分层合并机制
  - T-060 LLM 统计仪表盘 API
  - T-061 LLM 配置 Pydantic Schema 验证
  - T-062 模型特化 Prompt 变体
  - T-063 Sprint 7 集成测试与回归

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

### T-058: 上下文压缩增强

- **目标**: 重构 `compact_messages()` 为 token-based 保留策略 + 结构化摘要模板，替代当前的固定百分比消息截断
- **模块**: M-006, M-005
- **接口**: internal
- **复杂度**: M
- **依赖**: T-051（PromptBuilder）
- **tdd_acceptance**:
  - [ ] AC-T058-1: 保留策略基于 token 计数（使用 `LLMGateway.estimate_tokens()`）而非消息数量百分比
  - [ ] AC-T058-2: 摘要使用结构化模板 `compaction_summary.txt`（包含 Goal/Context/Changes/State/Next Steps 五段）
  - [ ] AC-T058-3: 工具输出优先裁剪 — role=tool 消息按时间从旧到新裁剪，保护最近 3 条工具结果
  - [ ] AC-T058-4: 自动触发阈值：当 estimated tokens > min(context_window * 0.8, context_token_budget) 时自动压缩（`context_window * 0.8` 为模型容量层上限，`context_token_budget`（arch §5.1 [chat] 配置，默认 2000）为系统配置层上限，取较小值保证两层约束均满足）
  - [ ] AC-T058-5: 压缩后消息列表 token 数 ≤ context_window * 0.6（留足生成空间）
  - [ ] AC-T058-6: LLM 摘要失败时 fallback 到 truncation 策略（保留最近 N 条原文，N 由 token budget 决定）
  - [ ] AC-T058-7: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/agent/compaction.py` — 重构
  - [ ] `src/intellisource/llm/prompts/compaction_summary.txt` — 结构化摘要模板
  - [ ] `tests/unit/agent/test_compaction.py` — 更新（≥10 tests）
- **context_load**:
  - src/intellisource/agent/compaction.py (现有 compact_messages)
  - src/intellisource/llm/gateway.py (estimate_tokens)
  - docs/research/architecture-review-opencode-benchmark.md §GAP-B2

---

### T-059: 配置分层合并机制

- **目标**: 实现 `ConfigResolver` 支持 defaults → project → env vars 三层配置深度合并，供 LLM 配置和源配置统一使用
- **模块**: M-001
- **接口**: internal
- **复杂度**: M
- **依赖**: T-053（ModelProfile YAML 配置）
- **tdd_acceptance**:
  - [ ] AC-T059-1: `config/defaults.yaml` 作为全局默认值层（版本控制内，提供所有配置项的合理默认值）
  - [ ] AC-T059-2: `config/llm_models.yaml` 作为项目覆盖层，覆盖 defaults.yaml 中的同名配置
  - [ ] AC-T059-3: `IS_*` 前缀环境变量作为最高优先级覆盖（`IS_LLM_DEFAULT_MODEL` → `default_model.model`）
  - [ ] AC-T059-4: 深度合并策略 — nested dict recursive merge，list 覆盖不合并
  - [ ] AC-T059-5: `ConfigResolver.resolve()` 返回最终合并后的 config dict
  - [ ] AC-T059-6: 合并结果通过 Pydantic model 验证（与 T-061 共享 LLMModelsConfig，schema 形状由 T-061 定义）
  - [ ] AC-T059-7: 缺少 defaults.yaml 时仅使用 project config + env vars（不报错）
  - [ ] AC-T059-8: mypy --strict 零错误
- **实现顺序**: T-059 与 T-061 存在双向引用（T-061 的 ConfigResolver 集成依赖 T-059；T-059 的 AC-T059-6 依赖 T-061 的 LLMModelsConfig）。推荐执行顺序：① 先完成 T-061 的 Pydantic model 定义部分（LLMModelsConfig + ModelTaskConfig 最小字段集）→ ② 实现 T-059 ConfigResolver 并在 AC-T059-6 中复用上述 schema → ③ T-061 完成剩余的 load_model_config() 集成与验证规则扩充。
- **deliverables**:
  - [ ] `src/intellisource/config/resolver.py` — ConfigResolver 类
  - [ ] `config/defaults.yaml` — 全局默认值文件
  - [ ] `tests/unit/config/test_resolver.py` — 分层合并测试（≥12 tests）
- **context_load**:
  - src/intellisource/config/loader.py (ConfigLoader)
  - src/intellisource/llm/model_config.py (load_model_config)
  - config/llm_models.example.yaml

---

### T-060: LLM 统计仪表盘 API

- **目标**: 新增 `GET /api/v1/llm/stats` 端点，聚合 LLMCallLog 数据提供 token 消耗和成本统计
- **模块**: M-005, M-011
- **接口**: API-026（新增；[ASSUMPTION] arch 待新增 API-026: GET /api/v1/llm/stats，由后续 arch 修订承接。arch M-005 中 LLMStatsAggregator 注释"供 API-019 增强端点使用"与 API-019 Prometheus text 格式不符，故新增独立接口编号）
- **复杂度**: S
- **依赖**: T-056（Sprint 6 全量回归确认 LLMCallLog 正常工作）
- **tdd_acceptance**:
  - [ ] AC-T060-1: GET `/api/v1/llm/stats?start=&end=` 按时间范围查询
  - [ ] AC-T060-2: 响应包含按模型维度聚合的 input_tokens/output_tokens/call_count
  - [ ] AC-T060-3: 响应包含按 task_type 维度聚合的 token 消耗
  - [ ] AC-T060-4: 响应包含 cached_calls/total_calls 比例
  - [ ] AC-T060-5: 响应包含 avg_latency_ms/p95_latency_ms 延迟统计
  - [ ] AC-T060-6: 无数据时返回空聚合结果（不报错）
  - [ ] AC-T060-7: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/api/routers/llm.py` — llm-stats 端点（复用已有 stub，URL: `/api/v1/llm/stats`）
  - [ ] `src/intellisource/storage/repositories/llm_call_log.py` — 聚合查询方法
  - [ ] `tests/unit/api/test_llm_routes.py` — 新增或更新（≥6 tests）
- **context_load**:
  - src/intellisource/api/routers/llm.py (已有 stub)
  - src/intellisource/storage/models.py (LLMCallLog E-011)
  - arch-intellisource-v1-modules#§2.M-005 (LLMStatsAggregator)

---

### T-061: LLM 配置 Pydantic Schema 验证

- **目标**: 为 `config/llm_models.yaml` 创建 Pydantic 验证模型，在 `load_model_config()` 中自动验证
- **模块**: M-001, M-005
- **接口**: internal
- **复杂度**: S
- **依赖**: T-059（ConfigResolver 集成）
- **tdd_acceptance**:
  - [ ] AC-T061-1: `LLMModelsConfig` Pydantic model 覆盖所有 YAML 字段（default_model, models, profiles）
  - [ ] AC-T061-2: `ModelTaskConfig` 子模型验证 model/provider/temperature/max_tokens
  - [ ] AC-T061-3: `load_model_config()` 加载后自动通过 LLMModelsConfig 验证
  - [ ] AC-T061-4: 无效配置抛出 `ValidationError` 并指明具体字段（如 `temperature 必须在 0.0~2.0 之间`）
  - [ ] AC-T061-5: 缺少可选字段时使用 Pydantic 默认值（不报错）
  - [ ] AC-T061-6: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/llm/model_config.py` — LLMModelsConfig + ModelTaskConfig Pydantic models
  - [ ] `tests/unit/llm/test_model_config.py` — 验证测试（≥8 tests）
- **context_load**:
  - src/intellisource/llm/model_config.py (load_model_config)
  - config/llm_models.example.yaml

---

### T-062: 模型特化 Prompt 变体

- **目标**: PromptBuilder 根据 `ModelProfile.prompt_style` 选择 prompt 模板变体文件，支持不同模型家族使用优化的 prompt 格式
- **模块**: M-005
- **接口**: internal
- **复杂度**: S
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

- **目标**: 验证 Sprint 7 所有改进在集成场景下正常工作，全量 pytest + mypy 通过
- **模块**: 全模块
- **接口**: internal
- **复杂度**: M
- **依赖**: T-057~T-062
- **tdd_acceptance**:
  - [ ] AC-T063-1: LLM 重试 + fallback 端到端测试（模拟连续失败 → 重试 → 降级）
  - [ ] AC-T063-2: ConfigResolver 三层合并集成测试（defaults + project + env）
  - [ ] AC-T063-3: PromptBuilder 变体加载 + ModelProfile 集成测试
  - [ ] AC-T063-4: 上下文压缩在 AgentRunner flexible 模式中正确触发
  - [ ] AC-T063-5: 全量 `pytest` 通过（无 import 错误、无残留引用）
  - [ ] AC-T063-6: `mypy --strict src/` 零错误
- **deliverables**:
  - [ ] `tests/integration/test_sprint7_integration.py` — 集成测试
  - [ ] 全量 pytest + mypy 通过报告
- **context_load**:
  - 所有 T-057 ~ T-062 deliverables
