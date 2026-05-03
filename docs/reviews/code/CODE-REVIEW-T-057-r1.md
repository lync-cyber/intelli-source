---
id: "code-review-T-057-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-057", "dev-plan-intellisource-v1-s7", "arch-intellisource-v1"]
---
# CODE-REVIEW: T-057 LLM 调用指数退避重试 (r1)
<!-- date: 2026-05-03 | reviewer: orchestrator-as-reviewer | task: T-057 | sprint: sprint-7 -->
<!-- Layer 1 delegated to hook (PostToolUse Edit → cataforge.hook.scripts.lint_format) -->
<!-- Layer 2: 已执行（task_kind=feature, AC=7 → 不命中 light 短路） -->

## 审查范围

- impl: `src/intellisource/llm/gateway.py`（+130 行核心改动：tenacity AsyncRetrying、_classify_error、_call_with_retry、_try_fallback、_log_retry，LLMGateway.__init__ 增 fallback_manager / _retry_wait）
- 配套小改：`src/intellisource/llm/cost_tracker.py`（LLMCallRecord.retry_attempt 字段）、`src/intellisource/storage/models.py`（LLMCallLog.retry_attempt 列）、`alembic/versions/001_initial_schema.py`（同步加列）、`pyproject.toml`（tenacity>=8.0）
- test: `tests/unit/llm/test_gateway_retry.py`（14 tests，6 test classes，覆盖 AC-T057-1~6 + _classify_error 单元测试）
- 上游契约：`arch-intellisource-v1#§5.3`（重试策略表已点名 Sprint 7 引入 tenacity，min=1s/max=30s, 3 次重试），`arch#§7`（命名/风格规范）

## 验证结果

- ✅ `uv run pytest -q tests/unit/llm/`：227 PASSED（14 new + 213 regression，无破坏既有测试）
- ✅ `uv run mypy --strict src/intellisource/llm/gateway.py src/intellisource/llm/cost_tracker.py src/intellisource/storage/models.py`：零错误
- ✅ implementer self-report `refactor_needed=false`，函数行数与嵌套深度未触发 `TDD_REFACTOR_TRIGGER`（complexity / duplication / coupling）
- ✅ AC ↔ 测试映射完整（每条 AC 至少 1 个测试，AC-T057-7 由 mypy strict 兜底）

## Layer 2 结果

### 完整性 (completeness)
- AC-T057-1 ~ AC-T057-6 全部由测试覆盖；AC-T057-7 由 CI mypy strict 兜底
- 边界路径（fallback_manager=None / task_type 未注册触发 KeyError）有专项测试
- ARCH §5.3 契约（"切换备用模型 → 传统处理逻辑"）当前实现仅"传统处理逻辑"分支（fallback registry）。"切换备用模型"留待后续 Sprint 任务（不属本卡范围，无需补充）

### 一致性 (consistency)
- 与 arch §5.3 重试策略表完全一致（次数=3、min=1s/max=30s、tenacity、降级 → fallback registry）
- 与 prd#§2 F-007 AC-029 熔断机制兼容（CircuitBreaker 在 retry 之上层，未冲突）
- 命名遵循 arch §7.1（snake_case 函数、PascalCase 类、UPPER_SNAKE 模块级常量 `_TRANSIENT_EXCEPTION_NAMES`）

### 错误处理 (error-handling)
- 异常分类逻辑双轨（IntelliSourceError.category 优先、litellm 异常按类名映射）合理避免了不同 litellm 版本导致的 import 失败
- retry_if_exception 的 lambda 仅基于 _classify_error 判断；对未知异常归 RECOVERABLE_DEGRADED 不重试，符合"保守降级"原则

### 测试质量 (test-quality)
- 14 测试 ≥ 8 阈值；按 AC 分组组织清晰
- mock 策略合理：`patch("intellisource.llm.gateway.litellm")` 整体替换，`wait_fixed(0)` 注入消除真实退避等待

### 安全 (security)
- 无敏感数据暴露；retry 日志 `input_length=0` 等占位符不泄漏 prompt 内容
- 异常分类按类名映射（白名单）安全合理，未引入反射调用风险

## 问题列表

### [R-001] MEDIUM: 多处 `pytest.raises(Exception)` 过宽，无法捕获回归
- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `test_retry_count_capped_at_3`（line 151）、`test_unrecoverable_error_does_not_retry`（line 191）、`test_degraded_error_does_not_retry`（line 204）、`test_no_fallback_manager_raises_after_exhaustion`（line 246）均使用裸 `pytest.raises(Exception)`。这等价于"任何异常都通过"，若未来某次重构错误地包装/替换原始异常（例如改抛 `RuntimeError("retry exhausted")`），测试仍 PASS — 失去断言强度。
- **建议**: 改为具体异常类，例如：
  - retry 耗尽路径：`pytest.raises(litellm.exceptions.Timeout)`（reraise=True 应原样抛出最后一次 transient 异常）
  - UNRECOVERABLE 路径：`pytest.raises(litellm.exceptions.BadRequestError)`
  - DEGRADED 路径：`pytest.raises(litellm.exceptions.AuthenticationError)`
- **影响范围**: 4 个测试函数；本卡可在 GREEN 后立即微调，也可作为 Sprint 7 内的轻量跟进项

### [R-002] LOW: `_log_retry` 的 `call_type="retry"` 与既有 `_log_cache_hit` 风格不一致
- **category**: consistency
- **root_cause**: self-caused
- **描述**: 兄弟方法 `_log_cache_hit` 中 `call_type=call_type`（业务真实类型）+ `status="cached"`；`_log_retry` 则把 `call_type` 也写成 `"retry"`。这造成 cost_tracker 聚合查询时无法按业务 task_type 维度统计 retry 次数 — 例如想看 "structured_extraction 任务的 retry 率" 时所有 retry 都归并到一个 call_type 下。
- **建议**: `_log_retry` 接受 `task_type` / `call_type` 参数，内部写 `call_type=task_type or "unknown"`，仅 `status="retry"` 表示状态。`_call_with_retry` 调用时把 `call_kwargs` 上下文中的 `task_type` 透传过来（或在 `complete()` 顶部就把 task_type 暂存到 call_kwargs/上下文）。
- **影响范围**: gateway.py 一处签名改动 + 一处调用点 + 1 个新测试断言；非阻断，可在 R-001 一并跟进或独立小改

### [R-003] LOW: `_try_fallback` 仅捕获 `KeyError`，fallback 函数自身异常会丢失原始 transient
- **category**: error-handling
- **root_cause**: self-caused
- **描述**: 当 fallback registry 已注册 task_type 但 fallback 函数本身抛错时，原始 transient 异常被覆盖。当前行为虽然合理（最近异常更具诊断价值），但未在测试或注释中显式声明此契约。
- **建议**: 二选一：
  1. 在 `_try_fallback` docstring 中显式声明"fallback 函数本身的异常优先级高于原 transient"；
  2. 或加一条测试 `test_fallback_function_raises_propagates_fallback_error`，固化该行为。
- **影响范围**: gateway.py docstring 一行 + 可选 1 个测试

### [R-004] LOW: AC-T057-6 仅断言首次调用 timeout，retry 路径未验证
- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `test_acompletion_uses_profile_timeout` 仅在成功首次调用时断言 `timeout=45`。重试路径下同一 `call_kwargs` 字典被复用，timeout 隐式保留 — 但无显式断言，未来若重构成每次重试重建 call_kwargs 而忘记 profile.timeout，回归会漏检。
- **建议**: 增加 `test_acompletion_timeout_preserved_across_retries`：mock side_effect=[transient, success]，断言两次 acompletion 调用 kwargs 中的 timeout 都为 45。
- **影响范围**: 1 个新测试，约 15 行

## 判定

无 CRITICAL / HIGH 问题；2 个 MEDIUM（test-quality）+ 2 个 LOW（consistency / error-handling）。

**Verdict: approved_with_notes**

按 COMMON-RULES §三态判定逻辑：无 CRITICAL/HIGH 但有 MEDIUM/LOW → approved_with_notes。orchestrator 应展示问题列表并询问用户：
- 选项 A：接受并继续推进（将 R-001~R-004 作为 Sprint 7 内轻量跟进项 / 或纳入下一卡 T-058 一并处理）
- 选项 B：要求 implementer 在 T-057 卡内当场修订 R-001（MEDIUM）

R-002 / R-003 / R-004 可独立推迟，不影响 T-057 标记 done。
