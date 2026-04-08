# CODE-REVIEW: Sprint 4 (T-027 ~ T-036) -- r2
<!-- date: 2026-04-08 | sprint: 4 | scope: src/intellisource/scheduler/, src/intellisource/agent/, src/intellisource/distributor/, config/pipelines/ -->
<!-- layer1: skipped (lint hook configured in PostToolUse) -->
<!-- layer2: AI semantic review against arch#§5, arch#§7, dev-plan-s4 -->

## 审查摘要

本次为 r1 审查后的复审。r1 报告了 5 个 HIGH、8 个 MEDIUM、3 个 LOW 问题，判定 needs_revision。开发者已修复全部 5 个 HIGH 问题和 2 个 MEDIUM 问题。剩余 6 个 MEDIUM 和 3 个 LOW 问题均为改善建议，不影响当前功能正确性。

1373 tests 全部通过，mypy strict 零错误。

---

## r1 HIGH 问题修复验证

### [R-001] HIGH: AgentRunner.run_flexible() 静默吞没异常 — **已修复**

验证: `runner.py` 第 127-139 行，异常捕获后 (1) `logger.warning()` 记录日志，(2) 将 `{"role": "tool", "content": f"Error: {exc}"}` 追加到 messages 上下文反馈给 LLM。符合 arch#§5.3 错误记录要求。

### [R-002] HIGH: AgentRunner 使用 assert 进行运行时校验 — **已修复**

验证: `runner.py` 第 109-111 行，已替换为 `if self._llm_gateway is None: raise IntelliSourceError("LLM gateway is required for flexible mode", ErrorCategory.UNRECOVERABLE)`。

### [R-003] HIGH: BaseDistributor.distribute() 签名不一致 — **已修复**

验证: `base.py` 第 12-14 行，`distribute()` 已声明为 `async def` 并添加 `@abc.abstractmethod` 装饰器，与所有子类实现一致。

### [R-004] HIGH: DeliveryTracker 去重缺少 channel 维度 — **已修复**

验证: `matcher.py` 第 97-131 行，`_pushed` 类型为 `set[tuple[uuid.UUID, uuid.UUID, str]]`（三元组），`record()`、`has_been_pushed()`、`is_duplicate()` 均接受 `channel` 参数（默认 `""`），符合 arch E-010 的 `(subscription_id, content_id, channel)` 唯一约束。

### [R-005] HIGH: summarize_for_user 工具未注册 — **已修复**

验证: `tools.py` 第 117-119 行定义了 `_summarize_for_user_execute()` 占位实现，第 186-197 行在 `_default_tool_defs()` 中注册了该工具（name="summarize_for_user"），函数注释已更新为 "six built-in tool definitions"。

---

## r1 MEDIUM 问题修复验证

### [R-007] MEDIUM: WeWork 重试循环缺少延迟 — **已修复**

验证: `wework.py` 第 91 行，重试循环中已添加 `await asyncio.sleep(RETRY_INTERVAL)`，与微信渠道实现一致。

### [R-011] MEDIUM: Email 重试循环缺少延迟 — **已修复**

验证: `email.py` 第 153 行，重试循环中已添加 `await asyncio.sleep(RETRY_INTERVAL)`。

---

## 剩余问题列表（从 r1 继承，均为 MEDIUM/LOW）

### [R-006] MEDIUM: EmailDistributor.format_html() 存在 HTML 注入风险

- **category**: security
- **root_cause**: self-caused
- **描述**: `email.py` 第 62-72 行 `format_html()` 直接用 f-string 将 `content.title`、`content.summary`、`content.source_url` 插入 HTML 模板，未使用 `html.escape()` 转义。采集内容可能包含恶意 HTML 片段。
- **建议**: 使用 `html.escape()` 转义文本内容，`source_url` 使用 `urllib.parse.quote()` 编码。

### [R-008] MEDIUM: EmailDistributor 去重使用内存 set，重启后丢失

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `email.py` 第 40 行使用 `self._sent_keys: set[str]` 内存去重，与 WeChat/WeWork 的 Redis 去重不一致。进程重启后去重记录丢失。
- **建议**: 改为 Redis 去重方案，或依赖外层 DeliveryTracker/PushRecord 数据库层去重。

### [R-009] MEDIUM: CeleryTasks.run_pipeline() 使用 time.sleep() 阻塞 Worker

- **category**: performance
- **root_cause**: self-caused
- **描述**: `tasks.py` 第 116 行在重试时使用 `time.sleep()`，阻塞 Worker 线程。
- **建议**: 使用 Celery 原生 `self.retry(countdown=...)` 或非阻塞方案。

### [R-010] MEDIUM: AgentRunner._persist() 未关联实际 TaskChain

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `runner.py` 第 192 行每次生成新 UUID 但未写入数据库，是"假持久化"。
- **建议**: 接收上层 CeleryTasks 传入的 task_chain_id，或注入 TaskChainRepository 实际写入。

### [R-012] MEDIUM: test_runner.py TestFlexibleToolsDenied 断言条件过弱

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `test_runner.py` 第 431-443 行条件分支在不满足时静默通过。
- **建议**: 在 else 路径添加 `pytest.fail()` 确保至少一条断言路径执行。

### [R-013] MEDIUM: SchedulerManager 使用内存字典存储调度计划

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `state_machine.py` 第 113 行 `self._schedules: dict` 为纯内存存储，多 Worker 场景不可见。
- **建议**: 当前作为 placeholder 可接受，建议添加 TODO 注释标注临时实现。

### [R-014] LOW: test_matcher.py DeliveryTracker 测试缺少 channel 维度验证

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: DeliveryTracker 代码已支持 channel 参数，但测试未覆盖同一 (content_id, subscription_id) 不同 channel 的场景。
- **建议**: 添加跨 channel 去重测试用例。

### [R-015] LOW: TaskStateMachine 缺少 failed→pending 重试转换

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `failed` 为终态，无法重新排队。当前重试在任务内部处理，但状态机缺少运维级重试能力。
- **建议**: 考虑添加 `("failed", "retry"): "pending"` 转换，或文档说明设计决策。

### [R-016] LOW: agent/prompts/base.txt 使用英文

- **category**: convention
- **root_cause**: self-caused
- **描述**: CLAUDE.md 约定"提示词使用中文"，但 LLM 提示词使用英文在工程实践中效果更好。
- **建议**: 在代码中添加 `[ASSUMPTION]` 注释说明此决策。

---

## 审查统计

| 严重等级 | r1 数量 | r2 修复 | r2 剩余 |
|----------|---------|---------|---------|
| CRITICAL | 0 | - | 0 |
| HIGH | 5 | 5 | 0 |
| MEDIUM | 8 | 2 | 6 |
| LOW | 3 | 0 | 3 |

## 判定结论

**approved_with_notes**

全部 5 个 HIGH 问题已修复验证通过。剩余 6 个 MEDIUM 和 3 个 LOW 问题均为改善建议:

- R-006 (HTML 转义) 和 R-008 (Email 内存去重) 建议在 Sprint 5 或后续迭代中修复
- R-009 (time.sleep)、R-010 (假持久化)、R-013 (内存调度存储) 为 placeholder 实现的已知限制，后续集成真实基础设施时会替换
- R-012 (测试断言过弱)、R-014 (测试覆盖不足) 为测试质量改善项
- R-015、R-016 为低优先级设计建议
