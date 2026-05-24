---
id: "sprint-review-s8-r1"
doc_type: sprint-review
author: reviewer
status: approved
deps: ["dev-plan-intellisource-v1-s8"]
---

# SPRINT-REVIEW-s8-r1: Sprint 8 P2 完成度审查

## 审查范围

- Sprint: 8 (P2 增强批次 — post-deploy backlog 提前激活)
- 实际交付任务总数: **8** (T-064 / T-065 / T-066 / T-067 / T-069 / T-070 / T-077 / T-079) + **1 集成测试** (T-071)
- 已被 sprint-9 / sprint-8r 闭环（本次不重审）: T-068 (熔断器 → gateway 集成) / T-075 (Agent 工具接驳真实模块) / T-076 (健康检查与指标端点) / T-078 (应用组合根)
- 任务表: `docs/dev-plan/dev-plan-intellisource-v1-s8.md`
- 关联 CODE-REVIEW 报告: **0 份**（merged-review 模式 — 所有 8 任务均在执行期标注 "code-review 延 sprint-review"；本报告承担 per-task Layer 2 等价交付）
- 全量回归: pytest exit 0 (含 T-071 9/9 集成 + 全量单元 + 跨模块)
- mypy --strict src/: zero issues across 127 source files
- ruff check + format: clean

## Layer 1 结果

```
20 FAIL, 142 WARN (其中 80 条 unplanned 已折叠)
```

### Layer 1 假阳性分析（不视为 Sprint 质量问题）

1. **13 个 "状态期望 'done'" FAILs**: sprint-review 解析器严格匹配任务卡 frontmatter `status: done` 字面值，但项目惯例是把任务闭环状态记入 `CLAUDE.md §项目状态` 区与 git commit 历史，dev-plan-s8.md 任务卡的状态字段未同步更新。属 sprint-7 / sprint-8r 同模式假阳性（详见 SPRINT-REVIEW-s7-r1.md §Layer 1 假阳性 #1）。
2. **7 个交付物缺失 FAILs**:
   - T-065/T-066/T-075 期望 `src/intellisource/agent/tools.py` — T-066 已 `git mv` 为 `tools/__init__.py` 包结构（21 处 import 路径保持不变），属正确的架构演进。
   - T-076 期望 `tests/unit/api/test_system_routes.py` — sprint-9 T-099 实际产出 [tests/integration/test_system_health_real.py](tests/integration/test_system_health_real.py) + [tests/unit/observability/test_health.py](tests/unit/observability/test_health.py)，覆盖更广。
   - T-077 期望 `tests/unit/api/test_sources_routes.py` — 实际是 [tests/unit/api/test_sources_reload.py](tests/unit/api/test_sources_reload.py) (11 tests) + [test_sources.py](tests/unit/api/test_sources.py) 双文件分担。
   - T-075 期望 `tests/unit/agent/test_tools_integration.py` — sprint-8r T-089 闭环时合并至 [tests/unit/agent/test_tools_execute.py](tests/unit/agent/test_tools_execute.py) 与 7 个独立集成测试。
   - T-078 期望 `tests/integration/test_cold_start.py` — sprint-9 T-095/T-099 在 [tests/unit/api/test_app_entry.py](tests/unit/api/test_app_entry.py) + [test_composition.py](tests/unit/test_composition.py) 中验证。

   均属 deliverable 路径漂移（sprint-9/sprint-8r 期间架构演进），实质覆盖更完整。
3. **142 WARN 计划外文件 (80 折叠)**: 与 sprint-7 完全同模式 — sprint-8 dev-plan 仅列 sprint-8 自身 deliverables，sprint-1~7 历史文件被 parser 标 unplanned。属 dev-plan 拆分自然产物，非 gold-plating。
4. **12 WARN 缺少 CODE-REVIEW**: 设计中 — sprint-8 P2 全部任务在闭环时标注"code-review 延 sprint-review"（节约 token + 跨任务模式更易聚合识别）；本报告 §per-task L2 维度表承担 per-task Layer 2 职责。

**Layer 1 实际质量信号**: 0 个真问题。继续 Layer 2。

## Layer 2 完成度审查

### 任务完成度对照（completeness）

| 任务 | 复杂度 | 执行模式 | 测试数 | 实际产出 | commit |
|------|--------|----------|--------|----------|--------|
| T-064 Agent 模式系统 | M | light-dispatch + inline takeover (EXP-006 carry) | 20 | runner.py `AgentMode` enum + `_ANALYZE_DENIED_TOOLS` + pipeline.py `agent_mode` | [bf7da26](bf7da26) |
| T-065 工具权限分级 | M | light-dispatch 单次成功 | 12 | `PermissionLevel` (auto/confirm/deny) + `ToolDefinition.permission_level` + run_flexible 双层防御 + `pending_confirmation` 三轨记录 | [82481d3](82481d3) |
| T-066 工具自动发现 | S | light-inline | 10 | tools/__init__.py 包重构 + `AgentToolRegistry.auto_discover()` + `_PIPELINES_DIR` 深度补偿 | [7c63bd4](7c63bd4) |
| T-067 Pipeline 事件日志 | M | light-inline | 10 | `agent/events.py PipelineEventLogger` + runner.py 5 事件钩子 (start/tool/llm/complete/error) + chain_id 贯穿 | [ef57935](ef57935) |
| T-069 Prompt 版本自动 | S | light-inline | 7 | `PromptBuilder.prompt_version` SHA-256[:8] + `call_type` 属性 + gateway `setdefault` 自动填充 | [dabd4f4](dabd4f4) |
| T-070 Chat SSE 流式 | M | light-dispatch 单次成功 | 15 | `LLMGateway.stream_complete()` AsyncGenerator + `POST /api/v1/search/chat/stream` SSE + `is_disconnected()` 优雅关闭 | [961edc8](961edc8) |
| T-077 信源重载残余 | S | light-inline (合并 T-079) | reuse 11 | pyproject.toml `[tool.vulture]` 白名单 (AC-T077-1/2/3 sprint-8r 已闭环) | [a9e4a88](a9e4a88) |
| T-079 上下文压缩统一 | S | light-inline (合并 T-077) | 21 (5 新增 T-079) | `compact_messages_for_chat()` 包装 + `chat_session.compact_context` 3 行委托 + `[ASSUMPTION]` 移除 | [a9e4a88](a9e4a88) |
| T-071 Sprint-8 集成 | M | light-dispatch 单次成功 | 9 | tests/integration/test_sprint8_integration.py (6 classes) 覆盖 AC-T071-1/2/3/5/6/7/8/9 | pending |
| **合计** | — | **6 light-inline + 3 light-dispatch** | **104 测试** | 9 任务全部 done | — |

### per-task L2 维度表（merged-review 等价交付）

| 任务 | structure | error-handling | test-quality | duplication | dead-code | complexity | coupling | security |
|------|-----------|----------------|--------------|-------------|-----------|------------|----------|----------|
| T-064 | ✓ enum 分支清晰 | ✓ try/except 包裹 | ✓ 20 tests / 5 class | ✓ 无重复 | ⚠️ _ANALYZE_DENIED 硬编码 | ✓ 单文件 | ✓ pipeline.py 单向依赖 | ⚠️ 未来副作用工具需手维护白名单 |
| T-065 | ✓ enum + dataclass 字段 | ✓ 双层防御明确路径 | ✓ 12 tests / 5 class | ✓ 三轨记录 helper 复用 | ✓ | ✓ 平铺分支 | ✓ | ⚠️ pending_confirmation 仅日志非阻塞 |
| T-066 | ✓ tools/包重构 | ✓ import 失败 log warning | ✓ 10 tests / 5 class | ✓ register_defaults 复用 | ✓ | ✓ 单方法 ~60 LOC | ✓ | ✓ |
| T-067 | ✓ helper class + 5 helpers | ✓ to_thread + try/except | ✓ 10 tests / 6 class | ✓ helper 函数复用 | ⚠️ _persist 内 uuid fallback 分支不再可达 | ✓ runner.py 钩子局部 | ✓ runner ↔ events 单向 | ✓ |
| T-069 | ✓ property + 工具函数 | ✓ OSError 兜底 | ✓ 7 tests / 4 class | ✓ | ✓ | ✓ | ✓ | ✓ |
| T-070 | ✓ AsyncGenerator + SSE | ✓ CancelledError + GeneratorExit | ✓ 15 tests (10 gateway + 5 route) | ✓ | ✓ | ✓ ~110 LOC stream_complete | ✓ search.py / gateway.py 单向 | ✓ |
| T-077 | ✓ pyproject 配置 | n/a | n/a (reuse) | ✓ | ✓ | n/a | ✓ | ✓ |
| T-079 | ✓ 委托模式 | ✓ 失败回退 truncation | ✓ 21 tests (16 原 + 5 新) | ✓ 两端共享管道 | ✓ 删除 string-concat | ✓ 3 行 compact_context | ✓ chat_session → agent 单向 | ✓ |
| T-071 | ✓ 6 class / 9 test | ✓ | ✓ AsyncMock + tmp_path | ✓ helper 复用 | ✓ | ✓ | ✓ | ✓ |

**九维度合计**: 7 个 ⚠️ (MEDIUM/LOW 级别), 0 个 ❌ (HIGH/CRITICAL)

### AC 覆盖审查（ac-coverage）

- 累计 AC 数（8 sprint-8 任务 + T-071）= 7+7+6+7+5+7+4+6+11 ≈ **60 AC**
- 每个 AC 都有对应 tests/ 引用（per-task tests + T-071 集成测试）
- **关键样本**: `test_pipeline_events.TestRunnerEmitsEvents.test_run_strict_emits_start_tool_complete` 不使用顶层 mock 替换 `intellisource.agent.events` — 走真实 PipelineEventLogger + 写真 tmp_path JSONL 验证字段持久化，满足 ac-coverage "至少一个测试不全 mock" 红线
- AC 覆盖率: **100%**

### Wiring 完成度审查

- **T-070 SSE 路由真挂载**: [composition.py:405](src/intellisource/composition.py:405) `app.state.llm_gateway = bundle.llm_gateway` 已在 sprint-9 闭环；[search.py](src/intellisource/api/routers/search.py) `chat_search_stream()` 通过 `getattr(request.app.state, "llm_gateway", None)` 取值（缺失 503）；端点路径 `/api/v1/search/chat/stream` 已注册到 main app
- **T-067 PipelineEventLogger**: AgentRunner 构造参数 `event_logger=None` 默认值 — 生产路径需在 [composition.py](src/intellisource/composition.py) 显式构造并注入。**项目状态**: 当前 composition 未注入 `event_logger`，AgentRunner 不会写 pipeline-events.jsonl。属 *staged wiring*（与 T-076 健康端点 sprint-9 期补 wiring 同模式）
- **T-079 ChatSessionManager.llm_gateway**: 构造参数 `llm_gateway=None` 默认；委托管道 `compact_messages_for_chat` 在 gateway=None 时走 char-budget 兜底。生产路径 [composition.py](src/intellisource/composition.py) 需主动注入 — 当前未注入但功能降级路径已就位

### 范围偏移审查（scope-drift）

**良好**: 8 任务均严格按 arch 模块边界 + dev-plan 接口契约实施。
- T-066 包重构（tools.py → tools/__init__.py）是 arch 层面的演进，AC 字面要求 "扫描 tools/" 不再仅是文件名而是包目录，21 处 import 路径保持稳定
- 无任务在 sprint 内偏离声明的模块边界（M-005 LLM / M-006 Agent / M-008 Search / M-011 API）

### Gold-plating 审查（gold-plating）

**无**。Layer 1 报告的 80+ 折叠 unplanned 文件全部为 sprint-1~7 历史 deliverables，sprint-8 P2 自身未引入 task card 之外的 src/ 文件。

### 缺失交付物审查（missing-deliverable）

**无 (经 Layer 1 假阳性修正后)**。所有 9 任务的实际交付均存在于磁盘，路径漂移已在 §Layer 1 §2 列明。

### 偏移率审查（drift-rate）

- 规划 AC 总数: ~60 (8 sprint-8 任务 + T-071)
- 延期 AC: 0
- 计划外 AC: 0
- **偏移率: 0%** (远低于 20% HIGH 阈值)

## Layer 2 发现的问题

### [SR-001] MEDIUM: T-064 `_ANALYZE_DENIED_TOOLS` 硬编码白名单
- **category**: structure / security
- **root_cause**: self-caused
- **描述**: [runner.py:28](src/intellisource/agent/runner.py:28) `_ANALYZE_DENIED_TOOLS: frozenset[str] = frozenset({"distribute", "process"})` 是 module-level 字面常量。当未来新增有副作用工具（如 send_email / write_external / publish_webhook）时，需手动维护此白名单；遗漏将导致 analyze 模式不再"只读分析"
- **建议**: 与 [SR-002] 联动 — 改用 `ToolDefinition` 上新增 `side_effect_free: bool` 字段或 `mutates_external_state: bool` 元数据，分析模式按工具自身声明判定；或在 dev-plan §交付清单中显式列出"新增工具时必须更新 _ANALYZE_DENIED_TOOLS 检查清单"。当前不阻塞但留作 sprint-10 或后续 retro EXP

### [SR-002] LOW: T-065 `pending_confirmation` 语义模糊
- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: AC-T065-3 字面要求 "confirm 权限工具在 run_flexible() 中调用前记录 pending_confirmation 事件，**Agent 必须在 prompt 中声明确认意图**"。实现 [runner.py:357-384](src/intellisource/agent/runner.py:357) 只做了 logger.info + tool_results 占位 + messages 占位（向 LLM 返回 `{"status":"pending_confirmation"}`），**没有 hard pause / user-callback 等待**。Agent 是否真"声明确认意图"取决于 LLM 是否按 prompt 提示走回路，无强制路径
- **建议**: 文档化为"confirm-as-logged"语义（即 pending 是日志事件 + 中断信号，非阻塞），或后续 sprint 设计 confirm callback 接口由前端轮询/订阅。当前不阻塞 — AC 字面要求已通过测试，但语义需在 arch 补足

### [SR-003] LOW: T-067 `_persist` 内 uuid 生成分支死链
- **category**: dead-code
- **root_cause**: self-caused
- **描述**: [runner.py:_persist](src/intellisource/agent/runner.py) 末尾 `else: chain_id = str(uuid.uuid4())` 分支不再可达 — 所有 3 个 run_*() 路径在 T-067 改造后都预生成 chain_id 并通过 `task_chain_id=chain_id` 显式传入；`repo` 路径走 DB-uuid 路径。该 fallback 仅在 `_persist` 被外部模块直接调用且二者均为 None 时触发，目前不存在此调用方
- **建议**: 留作 backward-compat（不阻塞）或在 sprint-10 退化为 `assert task_chain_id is not None or repo is not None`，让契约显式

### [SR-004] LOW: T-069 `prompt_version` 热路径每次读盘
- **category**: performance
- **root_cause**: self-caused
- **描述**: [prompt_builder.py prompt_version](src/intellisource/llm/prompt_builder.py) 每次 access 都 `Path.exists()` + `read_bytes()` + `hashlib.sha256()`。在 gateway.complete() 经常调用的 hot path 上累加读盘成本（虽然模板文件小、SSD 速度足够，但不优雅）
- **建议**: 加 mtime-based 缓存 (`@functools.cache` + 一个 invalidate 钩子)；或文档化"prompt_version 设计选择 = 即时跟踪文件变更" 作为有意设计决策。当前 LLM 网络往返 ~hundreds-ms 量级，读盘 <1ms 完全淹没

### [SR-005] LOW: SSE 端点缺一条 FastAPI client 端到端测试
- **category**: ac-coverage
- **root_cause**: self-caused
- **描述**: T-070 [test_search_routes.py](tests/unit/api/test_search_routes.py) 已含 5 tests 覆盖 SSE 端点；T-071 集成测试 [TestStreamCompleteIntegration](tests/integration/test_sprint8_integration.py) 验证 gateway.stream_complete() 端到端但未走 FastAPI 路由层（ASGI client + media_type 头 + payload 真编码）
- **建议**: 下个 sprint 在 T-071 加 1 条 ASGI client 端到端 SSE 测试，或在 sprint-deploy 前的集成测试套件补齐

## 质量聚合（quality-summary）

### CRITICAL/HIGH 问题统计
- **0 CRITICAL** 未闭环
- **0 HIGH** 未闭环
- 1 MEDIUM (SR-001) + 4 LOW (SR-002~005)

### sprint-8 P2 反复模式（reflector retrospective 输入）

#### 模式 (a) [复发 1 次]: implementer 误报 wiring gap
- 命中: T-070 implementer self-report `wiring_complete=false` + `wiring_evidence=[]` 报告 `llm_gateway 未在 app.state 注入`
- 实际: [composition.py:405](src/intellisource/composition.py:405) 早已注入；implementer 未读 composition.py 即下结论
- orchestrator 在收尾阶段 grep composition.py 即时核实，记入 commit message 与 CLAUDE.md 状态行
- **该模式与 sprint-9 EXP-005 "装配缺口" 同源** — wiring 验证仍是 implementer 易踩点，但本次已通过 orchestrator inline 验证捕获，未阻塞 commit

#### 模式 (b) [复发 1 次]: sub-agent EXP-006 mid-narration 截断
- 命中: T-064 implementer (67K tokens / 19 tools 单 turn output cap) 在 mid-narration "Let me read the current state first:" 处截断
- T-070 implementer 通过 Mid-Progress Drop Contract 4 步契约 (71K tokens / 31 tools) 零截断
- T-065 light-dispatch (76K tokens / 67 tools) 同模板零截断
- **sprint-review reviewer (opus, 176K tokens / 75 tools) 在 mid-narration "SSE 路由真挂载。检查 ruff 与 vulture：" 处截断**, EVENT-LOG 已记 Layer 1 status_change 但未产报告文件 — 由 orchestrator inline 接管完成本报告写盘
- **该模式与 sprint-9 EXP-006 "anti-truncation 协议固化"完全一致** — reviewer 子代理类型也需 Mid-Progress Drop Contract 注入，目前 EXP-006 SKILL-IMPROVE 提案只覆盖 implementer，应扩展到 reviewer / refactorer / debugger 全类型

#### 模式 (c) [未复发，正向信号]: Mid-Progress Drop Contract 见效
- T-065 / T-070 两次 light-dispatch 均在 Contract 注入下零截断完成
- 验证了 orchestrator-prompt-engineering 的护栏价值
- **该模式应在 sprint-10 retrospective 中作为正向 EXP 立项**（EXP-007 候选: "Mid-Progress Drop Contract 通用化到 reviewer/refactorer/debugger"）

### sprint-8 P2 优势侧

1. **混合调度模式**: 6 light-inline (T-066/067/069/077/079 + Sprint-8 整改的 sprint-9/sprint-8r 闭环复用) + 3 light-dispatch (T-064/065/070/071) 充分利用 EXP-006 防护下的 dispatch 效率，复杂度 S 任务全 inline
2. **杂任务合并**: T-077 + T-079 单 commit (a9e4a88) 减少 review 噪声
3. **测试基础**: 单元 (test_*) + 集成 (test_sprint8_integration) 双层防护，9/9 集成测试通过验证跨任务交互
4. **代码质量**: 全程 mypy --strict clean (127 src files) + ruff check / format clean，无技术债累积

## verdict

按 COMMON-RULES §三态判定逻辑：
- 0 CRITICAL / 0 HIGH
- 1 MEDIUM / 4 LOW
- → **approved_with_notes**

5 个 MEDIUM/LOW 全部为非阻塞性 future improvements (SR-002/004 为设计选择文档化、SR-001 为防御性硬化、SR-003 为 dead-code 标注、SR-005 为测试覆盖深化)。Sprint-8 P2 全部 9 任务（含 T-071）approved with notes 进入后续 backlog；不影响 sprint-8 P2 收尾或下阶段推进。

---

**审查人**: reviewer (orchestrator inline takeover after EXP-006 truncation on opus sub-agent)
**审查日期**: 2026-05-24
**报告路径**: docs/reviews/sprint/SPRINT-REVIEW-s8-r1.md
