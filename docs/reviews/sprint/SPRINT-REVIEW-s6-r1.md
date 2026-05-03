---
id: sprint-review-s6-r1
doc_type: sprint-review
author: reviewer
status: approved
---
# SPRINT-REVIEW: Sprint 6 (处理器/智能体架构重构) -- r1
<!-- date: 2026-04-10 | sprint: 6 | tasks: T-047..T-056 | reviewer: sprint-review -->
<!-- layer1: fail (降级入 Layer 2) -->
<!-- layer2: AI semantic review (代替 per-task code-review，由用户 Path B 授权) -->

## 审查背景

Sprint 6 代码已通过 PR #28/#29 合入 main（commits c417e0c, d7c3fa5, 6c60fbb），但：
- dev-plan 主概览表（`docs/dev-plan/dev-plan-intellisource-v1.md` L94–103）T-047~T-056 状态仍为 `todo`
- `docs/reviews/code/` 下缺少 T-047~T-056 的 per-task CODE-REVIEW 报告
- `dev-plan-intellisource-v1-s6.md` 中所有 AC 复选框未勾选

用户授权采用 **Path B**：由本次 Sprint-level 深度审查一次性代替 per-task code-review，同时事后同步任务状态。

## Layer 1 脚本结果

`sprint_check.py 6` 返回 exit 1，失败项:
1. **10 个任务状态=todo**（T-047~T-056 均未 done）
2. **10 个任务缺 CODE-REVIEW 报告**（T-047~T-056）

按 skill 规则 exit 1 即终止，本次经用户 Path B 授权降级进入 Layer 2。

## Layer 2 语义审查

### 完成度 (completeness)

| 任务 | 关键交付物 | 磁盘存在 | 备注 |
|------|----------|---------|------|
| T-047 | `pipeline/processors/schemas/{extract,classify,summarize}.json` + `schema_validator.py` + `test_schema_validator.py` | ✅ | Schema 文件齐全，validator 测试通过 |
| T-048 | `pipeline/processors/tools.py` (10 个原子工具) + `test_tools.py` | ✅ | 无 LLMGateway 依赖；40 tests 收集（AC 要求 ≥30） |
| T-049 | 移除 `ExtractionProcessor/ClassificationProcessor/SummarizationProcessor` | ✅ | grep 确认无残留 import |
| T-050 | `llm/prompt_builder.py` + `test_prompt_builder.py` + `prompts/templates/` | ✅ | 28 tests 通过 |
| T-051 | `llm/model_config.py` + `config/llm_models.yaml` + `test_model_config.py` | ✅ | 29 tests 通过，ModelProfile dataclass 完整 |
| T-052 | `llm/cache.py` + Gateway 集成 + `test_cache.py` | ⚠️ 部分 | Cache 类存在但 Gateway 未集成 LLMCallLog（见 [SR-002]） |
| T-053 | `agent/tools.py` (ToolRegistry + ToolDefinition) + `test_agent_tools.py` | ✅ | 注册表与装饰器 API 完整 |
| T-054 | `agent/runner.py` run_flexible + `test_runner.py` | ⚠️ 部分 | 预算追踪正确但 results 累积缺失（见 [SR-004]） |
| T-055 | `agent/orchestration.py` (PipelineOrchestrator) + `test_orchestration.py` | ✅ | 8 tests 通过 |
| T-056 | `config/pipelines/{extract_and_classify,research_agent}.yaml` | ✅ | 两个 YAML 配置存在 |

### AC 覆盖 (ac-coverage)

逐任务核对 tdd_acceptance 与实际测试引用:
- **T-047 ~ T-051, T-053, T-055, T-056**: 所有 AC 均有对应测试，测试逻辑有效。
- **T-052**: AC-T052-1/2/5/6 验证通过；**AC-T052-3/4 存在问题**（见 [SR-002], [SR-005]）。
- **T-054**: AC-T054-1/2/8 验证通过（system_prompt、tool 结果序列化、budget_exhausted flag）；**results 累积未验证**（见 [SR-004]）。

### 范围偏移 (scope-drift)

- ✅ T-048 原子工具全部无 LLMGateway 依赖，与 arch 重构目标一致
- ✅ T-049 LLM 处理器删除彻底，无循环 import
- ✅ T-053 ToolRegistry 采用 arch 定义的装饰器模式
- ✅ T-055 PipelineOrchestrator 与 AgentRunner 分层清晰

### Gold-plating

未发现计划外额外功能。

### 质量聚合 (quality-summary)

- **pytest**: `1636 passed in 18.28s` (+73 Sprint 6 新测试，无 skipped/xfail)
- **mypy --strict**: `Success: no issues found in 99 source files`
- **ruff**: 无新增告警（基于 commit d7c3fa5 pre-commit 记录）

---

## 问题列表

### [SR-001] MEDIUM: Sprint 6 缺 per-task CODE-REVIEW 报告
- **category**: convention
- **root_cause**: self-caused
- **描述**: T-047~T-056 的 10 个任务均无独立 `docs/reviews/code/CODE-REVIEW-T-0{47..56}-*.md`，违反 TDD engine 正常流程。本次经用户 Path B 授权由 Sprint-level 审查代替，但流程门禁被绕过。
- **建议**: 事后补登本报告为 10 个任务的合并 code-review 记录；未来 Sprint 必须在每次 REFACTOR 后触发 code-review skill，不可跳过。

### [SR-002] HIGH: AC-T052-4 未实现 — LLMGateway 无 LLMCallLog 集成
- **category**: completeness / ac-coverage
- **root_cause**: upstream-caused
- **描述**: AC-T052-4 要求"缓存命中时 LLMCallLog 记录 status=cached, input_tokens=0"。实际 `src/intellisource/llm/gateway.py` L150–158 在缓存命中时直接 `return cached`，**无任何 LLMCallLog 写入逻辑**；gateway 文件整体未 import `LLMCallLog`。`test_cache.py` 与 `test_gateway.py` 亦无对应断言。LLMCallLog 模型存在于 `storage/models.py` 且被 `cost_tracker.py`、`fallback.py`、`api/routers/llm.py` 使用，但 gateway 层未接入。
- **归因说明**: AC 在 dev-plan 中描述了"LLMCallLog 在 gateway 缓存命中路径写入"，但 Sprint 5 建立 gateway 时已未定义此接线；AC 作者隐含假设 gateway 已与 LLMCallLog 对接，属上游 dev-plan 授权与实际 gateway 设计的断层。
- **建议**: 三选一:
  - (a) **补实现**: 在 `gateway.py` 缓存命中路径注入 `LLMCallLogRepository`，写入 `status=cached, input_tokens=0, output_tokens=metadata.output_tokens`；补 test_gateway.py 对应断言。工作量: ~40 LOC + 3 tests。
  - (b) **降级延期**: 将 AC-T052-4 明确标记为 deferred，移入 Sprint 7 backlog（结合 Sprint 7 已规划的 observability 增强工作）。
  - (c) **AC 重写**: 确认本 AC 不必要（缓存命中已由 `LLMCache` metrics 覆盖），从 dev-plan 移除。

### [SR-003] MEDIUM: LLMCache.invalidate() 使用 redis.keys() 阻塞反模式
- **category**: performance
- **root_cause**: self-caused
- **描述**: `src/intellisource/llm/cache.py:141-152` `invalidate()` 使用 `await self._redis.keys(pattern)`。Redis `KEYS` 命令在大 keyspace 下为 O(N) 阻塞操作，生产环境会引发请求堆积。
- **建议**: 改用 `SCAN` 游标（`redis.scan_iter(match=pattern, count=100)`）逐批删除。工作量: ~10 LOC。不影响 AC-T052-5 接口形状。

### [SR-004] MEDIUM: run_flexible() 持久化 results=[] 丢失工具调用输出
- **category**: completeness
- **root_cause**: self-caused
- **描述**: `src/intellisource/agent/runner.py:177-182` `run_flexible` 分支调用 `self._persist(status="success", ..., results=[], ...)`，恒为空列表。实际工具调用输出仅累积在 `messages` 局部变量内，未回填至返回值 `results`。调用方（如 PipelineOrchestrator 或 API 层）无法从 TaskChain 记录中获取工具执行轨迹。
- **建议**: 在工具调用循环内追加 `tool_results.append({"tool": tc["name"], "output": result})`（或错误记录），并在 `_persist` 调用处传入 `results=tool_results`。补 test_runner.py 断言。工作量: ~15 LOC + 2 tests。

### [SR-005] MEDIUM: AC-T052-3 "仅缓存 status=success" 不可验证
- **category**: ac-coverage / consistency
- **root_cause**: upstream-caused
- **描述**: AC-T052-3 要求"仅缓存 status=success 的 LLMResult"。但 `LLMResult` 数据类（`gateway.py:62-67`）**只有 `content` 和 `metadata` 两个字段，无 `status` 字段**。`cache.py:82-102` `set()` 无条件缓存任何传入的 LLMResult，无状态检查；且"失败"通常由 Gateway 抛异常（`SchemaValidationError`/`LLMError`）完成，永远不会构造 LLMResult 进入 cache.set()。AC 本质上被异常路径隐式满足，但形式上不可直接断言。
- **建议**: 在 dev-plan 中将 AC-T052-3 改写为"LLMGateway 抛出异常时不调用 cache.set()"，或在 test_cache.py 补注释说明 LLMResult 存在即代表成功路径。不需要代码改动。

### [SR-006] LOW: PromptBuilder.build_messages 硬编码系统提示
- **category**: completeness
- **root_cause**: upstream-caused
- **描述**: `src/intellisource/llm/prompt_builder.py:107-111` `build_messages()` 固定注入 `"You are a helpful assistant."`，未读取模板 YAML 中定义的 system prompt。当前 `prompts/templates/` 下各模板的 `system` 字段未被消费。
- **建议**: 扩展 `build_messages(template_id, variables)` 从模板加载 system 字段，缺失则回退到当前默认值。工作量: ~15 LOC。

### [SR-007] LOW: truncate_content 字符比例截断未校验截断后 token 数
- **category**: feasibility
- **root_cause**: upstream-caused
- **描述**: `prompt_builder.py:128-146` 使用 40%/10% 字符比例做"前段 + 尾段"截断，但截断后未重新 `token_counter` 验证是否真的低于 `max_tokens`。在 CJK 密集文本下字符比 ≠ token 比，可能仍超限。
- **建议**: 截断后 while 循环缩减至 token 数合规；或改为二分查找。当前 AC 未强制验证，仅作改进项。

### [SR-008] LOW: dev-plan 状态区未同步
- **category**: convention
- **root_cause**: self-caused
- **描述**: `docs/dev-plan/dev-plan-intellisource-v1.md` L94–103 T-047~T-056 均为 `todo`；`dev-plan-intellisource-v1-s6.md` 所有 AC 复选框未勾选；`dev-plan-intellisource-v1-s6.md` 头部 status 仍为 `draft`。与 main 已合入的代码严重不一致。
- **建议**: 本 Sprint 审查通过后立即由 doc-gen 同步状态（主概览表 → done，AC 复选框 → checked，s6 分卷 status → approved）。

---

## 三态判定

| 严重等级 | 数量 | 列表 |
|---------|------|------|
| CRITICAL | 0 | — |
| HIGH | 1 | SR-002 |
| MEDIUM | 4 | SR-001, SR-003, SR-004, SR-005 |
| LOW | 3 | SR-006, SR-007, SR-008 |

**初步结论（按 COMMON-RULES §三态判定）**: **needs_revision**（触发条件：存在 1 个 HIGH [SR-002]）

**归因复核**: [SR-002] root_cause 为 upstream-caused — AC 作者隐含假设 gateway 已接线 LLMCallLog。如用户选择：
- 路径 (a) 补实现 → 需进入 Revision Protocol，启动 tdd-engine 对 T-052 做补丁 + 新 CODE-REVIEW
- 路径 (b) 延期到 Sprint 7 → 将 SR-002 从 HIGH 降至 MEDIUM（已知债务），Sprint 结论变为 **approved_with_notes**
- 路径 (c) AC 重写删除 → 直接由 doc-gen 修订 dev-plan-s6，SR-002 消除，Sprint 结论变为 **approved_with_notes**

其余 MEDIUM/LOW 均不阻断 Sprint 通过。SR-008 的状态同步为本报告审查通过后的强制后续动作。
