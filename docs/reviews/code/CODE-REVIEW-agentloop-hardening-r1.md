---
id: "code-review-agentloop-hardening-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["agentloop-hardening"]
---

# CODE-REVIEW: agent loop 加固批次 (P3/P5/P2/P8/P10/P1/P4)

Layer 1 delegated to hook（PostToolUse Edit → `lint_format`；全 11 源文件 `ruff check` 通过）。Layer 2 由三名 reviewer 子代理按"agent loop / LLM gateway / scheduler"三接缝对抗式深审，主审复核两处争议发现并校准严重度。

- 审查范围：18 个未提交改动（11 源 + 6 测试 + 1 新测试），main HEAD 4586b46 之上
- 初次 verdict：**needs_revision**（含 HIGH）
- 修订后：所有 HIGH/MEDIUM 已闭环或按决策接受 → **approved**（详见下方修订闭环）

## 修订闭环

在 `fix/agentloop-hardening-review` 分支按 TDD（RED 落断言层 → GREEN）逐项修复，全量门禁绿（ruff format/check + mypy --strict 265 文件 + unit 3536 passed）。

| 条目 | 处置 | 验证 |
|------|------|------|
| R-001 HIGH | 触发阈值改 `min(0.5*window, 48000)` 绝对预算，P10 真正生效 | `test_compress_if_needed_triggers_at_absolute_budget_not_half_window` |
| R-002 HIGH | 补流式 4 例（正常/挂起超时/中途异常+partial 不注入/aclose 抛错不拖垮） | `TestRunFlexibleStreamTimeout` |
| R-003 HIGH | 经 factory 注入 spy logger，断言 `pipeline_start`/`llm_call` 真触发 | `test_run_flexible_emits_pipeline_start_through_wired_logger` |
| R-004 MEDIUM | 追踪 `successful_model=candidate`，成功指标记真实模型 | `test_failover_success_metric_records_actual_model_not_primary` |
| R-005 MEDIUM | 入口 `_already_succeeded` 短路 redelivery（force 旁路）；订正 exactly-once 注释 | `test_already_succeeded_task_short_circuits_redelivery` + force 旁路 |
| R-006 MEDIUM | 决策=维持 narrowing；注释写明网关/worker 分工与故意排除 litellm/httpx 包装错误 | 注释订正 |
| R-007 MEDIUM | 补 dict 形状 embed 用例 | `test_embed_returns_vector_from_dict_shaped_data` |
| R-008 MEDIUM | 随 R-001 解决：阈值口径统一为绝对预算，docstring 写明触发条件 | 同 R-001 |
| R-009 LOW | `aclose()` 包 try/except 仅 warning | `test_aclose_failure_does_not_break_the_run` |
| R-010 LOW | `raise last_error or RuntimeError(...)` 去 `# type: ignore` | mypy --strict 绿 |
| R-011 LOW | **接受不修**：脆弱 substring 断言，归 Tier 5 minor cleanup | — |
| R-012 LOW | **接受不修**：超时常量单源 + 每轮 token 估算缓存，归 Tier 5 minor cleanup | — |
| R-013 | 证伪，无需处理 | — |

**R-005 决策余量（诚实标注）**：入口短路只覆盖 CollectTask-backed run（真实 task_id UUID）；非 UUID lock key（manual/source/fingerprint）无行可查仍 fall through，这部分 redelivery 幂等未覆盖，已在 `_already_succeeded` docstring 标注，归 backlog。

## 严重度分布
| SEVERITY | 数量 | 条目 |
|----------|------|------|
| CRITICAL | 0 | — |
| HIGH | 3 | R-001 R-002 R-003 |
| MEDIUM | 5 | R-004 R-005 R-006 R-007 R-008 |
| LOW | 4 | R-009 R-010 R-011 R-012 |
| 证伪（非问题）| 1 | R-013 |

---

## HIGH

### [R-001] HIGH: P10 压缩触发阈值对 1M 窗口永不触发，特性实际惰性
- **category**: structure
- **root_cause**: self-caused
- **file**: `src/intellisource/llm/gateway/__init__.py:165`、`config/llm_models.yaml:59-70`
- **描述**: `trigger = int(profile.context_window * 0.5)`，DeepSeek v4 `context_window=1000000` → 触发点 50 万 token。agent loop 受 `max_tokens_budget` 约束，正常 tool-heavy run 远到不了 50 万 token 就已终止，压缩永不触发。P10 声称解决的"长 run 撞 context 上限/预算墙"在默认配置下根本不会被覆盖——`compress_if_needed` 接进了 `_drive` 循环，但实际是死路径。
- **建议**: 触发点改为绝对预算与窗口比例取小：`trigger = min(int(profile.context_window * 0.5), AGENT_COMPACT_TOKEN_BUDGET)`，`AGENT_COMPACT_TOKEN_BUDGET` 取一个会真实触发的绝对值（如 32_000~50_000），或与本 run 的 `effective_budget` 挂钩。补一个"历史超过阈值 → 确实压缩"的集成测试。

### [R-002] HIGH: 流式 per-chunk 超时/异常路径零测试覆盖
- **category**: test-quality
- **root_cause**: self-caused
- **file**: `src/intellisource/agent/executors/flexible.py:590-619`；`tests/unit/agent/test_runner_run_flexible.py`（全文走非流式）
- **描述**: `_run_turn` 流式分支有独立超时逻辑（per-chunk `asyncio.wait_for` + `finally: await aclose()`），行为与非流式分支不同。测试全部走 `run_flexible`（stream=False），`run_flexible_stream` 的超时/中途异常/`aclose` 路径无任何覆盖。本项目 memory 明确记录"external-IO/有状态特性别跳 code-review、验证用有状态 mock"——流式超时正属此类。
- **建议**: 新增 `run_flexible_stream` 测试：正常流式完成、`__anext__` 挂起超时、流中途抛异常三例；用带 `aclose` 的有状态 async-gen mock，断言 `aclose` 被调用且不抛 `RuntimeError`，终态为 `{"type":"error"}`。

### [R-003] HIGH: event_logger 接通测试仅类型断言，未验证端到端埋点
- **category**: test-quality
- **root_cause**: self-caused
- **file**: `tests/unit/agent/test_factory.py:67-84`
- **描述**: P1 修复的核心是"原 `event_logger=None` 致全链路埋点静默"。两个测试只断言 `isinstance(runner._event_logger, PipelineEventLogger)` 与 `is custom`——只验证"对象被赋值"，不验证"执行时 `_emit_*` 真被调用产生埋点"。若 `AgentRunner.execute` 内部条件跳过了 emit，这两个测试不会失败，P1 的可观测性保证无回归防护。
- **建议**: 新增测试：spy `PipelineEventLogger.emit_pipeline_start`（或等价），跑一次 `runner.execute(...)` 后断言 spy 至少被调用一次，验证 wiring 落到真实执行链。

---

## MEDIUM

### [R-004] MEDIUM: chat failover 成功后指标记录为 primary 而非真实 candidate
- **category**: consistency
- **root_cause**: self-caused
- **file**: `src/intellisource/llm/gateway/_chat.py:252-253`（对照 227-231 的 `candidate`）
- **描述**: failover 循环成功 break 后 `_record_llm_call(success=True, model=resolved_model)` 硬编码 primary，不随实际成功的 `candidate` 更新。fallback 成功时 `llm_calls_total{model=primary}` +1 而真正完成请求的 fallback 不计，且同一 primary 标签上 success 与 failure counter 同时 +1，failover 成功率完全不可观测；cost log 走 `response.model` 正确，两源分歧反而增加排查难度。
- **建议**: 循环内 `break` 前记录 `successful_model = candidate`，成功分支 `_record_llm_call(..., model=successful_model)`。

### [R-005] MEDIUM: "副作用幂等键"按字面只满足一半，跨 redelivery 非 exactly-once
- **category**: error-handling
- **root_cause**: self-caused
- **file**: `src/intellisource/scheduler/tasks.py:330-378`、`src/intellisource/scheduler/idempotency.py:7`
- **描述**: 本轮把副作用移出重试循环 → 单次任务执行内只跑一次（retry-replay 动机已结构性消除）。但未加真正的副作用幂等键：`IdempotencyGuard` 锁 TTL=300s « Celery broker visibility timeout（默认 3600s），且锁在 `finally` 完成即释放——worker 在返回后/ack 前被 kill 触发 broker redelivery 时，新 worker 重新 acquire 成功，`content_repository.create(result)` 再次执行。生产 `fingerprint_checker.record` 为 no-op，不提供去重。即 L359 注释承诺的 "side effects run exactly once" 在 redelivery 场景不成立。
- **建议**（决策项，见整合计划 Tier 3）: 三选一——(a) `content_repository.create` 改 upsert / ON CONFLICT DO NOTHING；(b) 任务入口加"已 success → 短路"检查；(c) 锁 TTL > broker visibility timeout。并同步修订注释与测试。

### [R-006] MEDIUM: worker 重试白名单 `(ConnectionError, TimeoutError)` 漏接 httpx/openai/DB 瞬断
- **category**: error-handling
- **root_cause**: reviewer-calibration（主审从 HIGH 下调）
- **file**: `src/intellisource/scheduler/tasks.py:340,344`
- **描述**: 白名单是标准库 `ConnectionError`/`TimeoutError`；litellm 网络错误为 `openai.APIConnectionError`/`httpx.ConnectError`（均不继承标准库 `ConnectionError`），SQLAlchemy `OperationalError` 也不在内 → 命中 `except Exception: break` fail-fast。**校准说明**：LLM 瞬断已被网关 tenacity 自重试 4 次（narrowing 正是为消除双重重试放大，是有意设计），故 LLM 路径残留风险低；真实残留 gap 仅是 `execute()` 内 DB 瞬断 fail-fast。
- **建议**（决策项，见 Tier 3）: 若要 worker 兜底网络/DB 瞬断，白名单加 `httpx.TransportError`/`sqlalchemy.exc.OperationalError`；否则维持 narrowing 并在注释明确"LLM 瞬断由网关负责，worker 只兜底标准库 socket 级错误"。

### [R-007] MEDIUM: embed dict 形状返回路径无测试（R-EMB 假绿模式复发）
- **category**: test-quality
- **root_cause**: self-caused
- **file**: `src/intellisource/llm/gateway/_embed.py:94`；`tests/unit/llm/test_gateway_embed.py:58-65`
- **描述**: `_embed.py:94` 显式支持 dict（`item["embedding"]`）与对象（`item.embedding`）两种形状，但 `_make_embedding_response` 只造 `MagicMock(embedding=vec)`（对象形状），dict 路径零覆盖。对照 memory「外部 SDK mock 要忠实形状」，属已知学习的复发。
- **建议**: 加一组 `resp.data = [{"embedding": vec}]` 的 dict 形状测试，断言正确返回向量。

### [R-008] MEDIUM: `compress_if_needed` 触发与成本/防溢出意图不清
- **category**: ambiguity
- **root_cause**: self-caused
- **file**: `src/intellisource/llm/gateway/__init__.py:156-166`、`compaction.py:282`
- **描述**: 与 R-001 同源的设计澄清。`compact_agent_messages` 内部 `threshold = min(0.8*window, context_token_budget)` 与 `compress_if_needed` 外部 `0.5*window` 两套阈值叠加，语义（成本控制 vs 防 OOM）未声明，调用者难判定何时真正压缩。
- **建议**: 统一为单一显式预算口径（绝对 token 上限），在 `compress_if_needed` docstring 写明触发条件。

---

## LOW

### [R-009] LOW: 流式超时 `finally: await aclose()` 缺防御性 wrap
- **category**: error-handling
- **root_cause**: self-caused
- **file**: `src/intellisource/agent/executors/flexible.py:616-619`
- **描述**: Python 3.11 `asyncio.wait_for` 超时取消是 best-effort；极端时序下对刚被取消的 async-gen 调 `aclose()` 可能抛 `RuntimeError`，若抛出会逸出 `_run_turn` 覆盖原 error。风险低但 wrap 成本极小。
- **建议**: `aclose()` 包 `try/except Exception` 仅记 warning，确保任何状态都不让 close 失败拖垮 turn。

### [R-010] LOW: `raise last_error` 在 `MAX_RETRIES=0` 边界可能 `raise None`
- **category**: error-handling
- **root_cause**: self-caused
- **file**: `src/intellisource/scheduler/tasks.py:357`
- **描述**: `last_error: Exception | None`，理论边界（循环未进 except 即退出且未 succeeded）下为 None，`raise None` → `TypeError`。当前 `MAX_RETRIES=3` 不触发，但 `# type: ignore[misc]` 已承认类型不安全。
- **建议**: `raise last_error or RuntimeError("pipeline failed: no exception captured")`，去掉 ignore。

### [R-011] LOW: 超时 error detail 用脆弱 substring 断言
- **category**: test-quality
- **root_cause**: self-caused
- **file**: `tests/unit/agent/test_runner_run_flexible.py:539`
- **描述**: `assert "Timeout" in result["detail"]` 依赖 `_describe_exc(TimeoutError())` 回退到类名 `"TimeoutError"`，异常类型/截断逻辑变动会静默失效。
- **建议**: 改精确断言 `== "TimeoutError"`，或为 `_describe_exc` 加专项单测，上层测试只验行为（error + detail 非空）。

### [R-012] LOW: 超时默认值 120.0/60.0 跨模块 4 处硬编码 + 每轮全量 token 估算
- **category**: convention / performance
- **root_cause**: self-caused
- **file**: `pipeline_models.py:59,60,187,188`、`flexible.py:829,830`；`flexible.py:213`
- **描述**: (1) 超时默认值在 `PipelineConfig.__init__` / `from_dict` / `flexible` 模块常量共 4 处独立硬编码，数值相同靠隐式约定，改时易漂移。(2) `_compress_history` 每轮循环顶部对全量消息估算 token（本地计算，非 IO），长循环累积可观。
- **建议**: 抽 `_DEFAULT_*_TIMEOUT_S` 到 `intellisource.config.constants` 单源 re-export；`_drive` 维护增量 token 计数避免每轮全量估算。

---

## 证伪（已核实非问题）

### [R-013] REFUTED: `_safe_cut_points` 将带 tool_calls 的 assistant 标为切点是安全的
- **file**: `src/intellisource/llm/compaction.py:238-314`
- **核实**: 切点取在 assistant(tool_calls) 索引 `cut` 时，`tail = messages[cut:]` 同时包含该 assistant **及其后续 tool 应答**，`_validate_history(tail)` 通过；切点永远不会落在 assistant 与其应答之间（那里 open_ids 非空，不会被 `_safe_cut_points` 收录）。head 被整体摘要为字符串。结果 `[*head, summary, *tail]` 配对完整。非 bug，不修。

---

## 已证伪的其他对抗假设（安全）
- chat failover 的 `_classify_error` 对 litellm transient（`APIConnectionError` 等）返回 `RECOVERABLE_TRANSIENT`、未知异常默认 `RECOVERABLE_DEGRADED`，不会误判 UNRECOVERABLE 跳过 failover（`_routing.py:90-128`）。
- `compress_if_needed` 正确把 routing model 传入 `compact_agent_messages`，`gateway.complete()` 走 DeepSeek default routing，不会调用默认参数里的 `gpt-4o-mini`（`gateway/__init__.py:156-166`）。
- embed retry predicate 只重试 `RECOVERABLE_TRANSIENT`；空文本/malformed 在 retry 层外返回 None，None 契约不破（`_embed.py:36-99`、`_retry.py:164-185`）。
- P8 终止条件改 `not tool_calls` 对 `finish_reason=="length"`+tool_calls 的行为与改动前一致，非新回归（`flexible.py:278`）。
- 非流式 chat 超时抛 `asyncio.TimeoutError`（是 `Exception`），被 `except Exception` 正确捕获，不会被 `CancelledError` 静默吞掉（`flexible.py:635-661`）。
- `_session_messages` 调用点唯一，丢弃 tool round-trip 无其他生产消费点依赖旧行为（`flexible.py:186,974-998`）。
