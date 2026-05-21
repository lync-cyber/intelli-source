---
id: "code-review-T-086-r1"
doc_type: code-review
author: reviewer
status: approved
deps: [T-086]
---
# 代码审查报告: T-086 — LLMGateway chat 方法 + JSON Mode / Function Calling

Layer 1 delegated to hook (lint hook 已配置 Edit|Write 触发)；全量 ruff check + mypy --strict 均 clean，通过门禁。

---

## §1 安全维度专项审查 (security_sensitive=true)

| 安全维度 | 结论 | 说明 |
|---------|------|------|
| SS-1: `_validate_tools()` 在 litellm 前阻断 | **PASS** | `if tools is not None: self._validate_tools(tools)` 在 `litellm.acompletion` 调用前执行；测试用 `assert_not_awaited()` 验证 litellm 未被触及 |
| SS-2: messages 内容透传无修改 | **PASS** | `call_kwargs["messages"] = messages` 直接赋值；docstring 标注 "Passed to litellm without modification (SS-2)"；测试覆盖含 prompt-injection 语义及 SQL 风格特殊字符的 messages |
| SS-3: SchemaEnforcer 非递归，最多一次 | **PASS** | `try: json.loads(content) except JSONDecodeError` 后创建新 `SchemaEnforcer(schema)` 调用 `validate()` 一次后直接 raise `LLMOutputError`；有计数器测试验证 call_count == 1 |
| SS-4: `LLMOutputError` 可从稳定路径导入 | **PASS — 带注记** | `LLMOutputError` 定义于 `intellisource.llm.gateway`，但**未加入** `src/intellisource/llm/__init__.py` 的 `__all__`；下游捕获需从 `gateway` 直接导入，非公共 API 路径 |
| SS-5: `LLMCallRecord` / 日志路径是否持久化原始 messages | **信息性注记** | 当前 `LLMCallRecord.input_length` 仅记录长度总和（`sum(len(str(m.get("content",""))) for m in messages)`），不持久化原始文本；无 PII/消息内容落库风险。此设计符合 arch§5.2 "仅发送必要文本片段，不发送用户身份信息" |

---

## §2 completeness — AC 覆盖

**AC-1** (chat 方法调用 messages-style API): 实现存在，`messages` 参数透传到 `call_kwargs`，3 项测试验证。**PASS**

**AC-2** (tools 参数透传 Function Calling): `if tools is not None: call_kwargs["tools"] = tools` 正确条件注入；无 tools 时不携带该 key，测试双向验证。**PASS**

**AC-3** (response_format 透传 complete() 和 chat()): 两个方法均实现；`complete()` 在 `call_kwargs` 组装后条件注入；`chat()` 同理。3 项测试。**PASS**

**AC-4** (SchemaEnforcer 兜底 + LLMOutputError): 实现符合规格。**注意**: 见 R-001。

**AC-5** (CostTracker call_type='chat'): `LLMCallRecord(... call_type="chat" ...)` + `log_call()` 调用路径正确；3 项测试验证 call_type / token 计数。**PASS**

**AC-6** (grep 证据): `grep -rn "response_format|tool_choice|tools=" src/intellisource/llm/` 命中 7 处，≥2 阈值满足。**PASS**

---

## §3 consistency — 签名与接口契约一致性

### [R-001] HIGH: runner.py 以 dict 方式消费 LLMResult，实际返回 LLMResult 对象导致运行时 AttributeError

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `arch#§2.M-006` 中 `AgentRunner.run_flexible()` 已存在，其代码直接对 `chat()` 返回值调用 `response.get("usage", {})` 和 `response.get("done")` 等字典方法（runner.py L144-153）。然而 `LLMGateway.chat()` 返回 `LLMResult` 对象（`@dataclass`，含 `content: str` 和 `metadata: dict`），不是 dict。这意味着任何调用 `run_flexible()` 的实际路径都会在 `response.get(...)` 处抛出 `AttributeError: 'LLMResult' object has no attribute 'get'`。任务卡 `context_load` 明确引用 `arch#§2.M-006` 说明实现者已读取该接口契约，但签名与消费者期望不匹配。
- **建议**: 在本任务内应使 runner.py 与 `LLMResult` 形状对齐，或在 `chat()` 返回后包装为 runner.py 期望的 dict 结构（`{"usage": {...}, "tool_calls": [...], "done": bool}`）。推荐路径：修改 `run_flexible()` 改用 `LLMResult.content` / `LLMResult.metadata`，同时删除 `response.get("tool_calls")` 等基于 dict 的消费逻辑，改为解析 LLM response 中 tool_calls 字段（通过 `result.metadata` 携带）。此缺口在 sprint-8r 各模块接驳完成前会导致 T-094 集成测试失败。

---

### [R-002] MEDIUM: `LLMOutputError` 未加入 `llm/__init__.py` __all__，下游 FallbackManager 捕获路径不稳定

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `LLMOutputError` 是 `FallbackManager` 上游触发 catch 的目标异常类（arch §5.3 降级策略：LLM 输出格式失败 → 降级传统处理）。当前 `src/intellisource/llm/__init__.py` 的 `__all__` 中包含 `SchemaValidationError` 但不含 `LLMOutputError`。任何 `from intellisource.llm import LLMOutputError` 都会失败（不在 `__all__`），下游需直接 `from intellisource.llm.gateway import LLMOutputError`，破坏公共 API 契约，且 T-087 `_llm_complete_execute` 路径极可能需要捕获它。
- **建议**: 将 `LLMOutputError` 加入 `src/intellisource/llm/__init__.py` 的 imports 和 `__all__`，与 `SchemaValidationError` 并列。

---

## §4 error-handling — 错误处理与边界

### [R-003] MEDIUM: `chat()` 中 `content: str = response.choices[0].message.content` 在 Function Calling 响应中可能为 None

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: OpenAI/litellm Function Calling 规范中，当模型返回 `tool_calls` 时，`choices[0].message.content` **可以是 `None`**（模型输出完全由 tool_calls 承载，不附文本）。当前 `chat()` 在 L435 直接注解为 `content: str`，若实际值为 `None`，后续 `LLMResult(content=content)` 构造不报错，但 `len(content)` 在 CostTracker 的 `output_length=len(content)` 处会抛出 `TypeError: object of type 'NoneType' has no len()`。此路径无测试覆盖，且 mypy strict 中 litellm response 类型为 `Any`，不会在静态分析阶段捕获。
- **建议**: 加 None 防护：`content: str = response.choices[0].message.content or ""`；同时可在 `metadata` 中补充 `tool_calls` 字段（`response.choices[0].message.tool_calls`），以便下游 AgentRunner 解析，消解 R-001 的根本原因。

---

### [R-004] MEDIUM: `chat()` 不经 `_call_with_retry` 路径，无 retry / fallback 保护

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `complete()` 通过 `_call_with_retry()` + `_try_fallback()` 实现三次指数退避重试和 FallbackManager 降级（arch§5.3 LLM 重试策略）。`chat()` 直接调用 `await litellm.acompletion(...)` 不经任何 retry 包装；任何 `RateLimitError` / `APIConnectionError` 直接向调用方传播。任务卡 risk 项已提及 "litellm 不同提供商对 tools/response_format 支持程度不一；需捕获 `NotSupportedError`" 但实现中未捕获也未降级。
- **建议**: 将 `await litellm.acompletion(**call_kwargs)` 包装进 `_call_with_retry()`，或最小化处理：用 `try/except` 捕获 litellm transient 错误并遵循 arch 重试约定。至少应捕获 `UnsupportedParamsError`（已在 `_UNRECOVERABLE_EXCEPTION_NAMES` 中定义）并在出现 tools/response_format 不支持时降级为不带这些参数的调用（任务卡 mitigation 已要求，但未实现）。

---

## §5 structure — 架构与耦合

### [R-005] LOW: `**kwargs` 接收后未转发至 litellm，docstring 描述与实现不符

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `chat()` 签名声明 `**kwargs: Any` 并在 docstring 中写 "Additional kwargs forwarded to litellm"，但实现中 `call_kwargs` 仅包含 `model`, `messages`, 以及条件性的 `tools` / `response_format`——`**kwargs` 内容从未被加入 `call_kwargs`，也未传递给 `litellm.acompletion`。此为 dead parameter，产生误导性文档。
- **建议**: 要么删除 `**kwargs` 参数（更安全，防止未知参数静默丢失），要么用 `call_kwargs.update(kwargs)` 实际转发，并在 docstring 中说明哪些 kwargs 白名单可以透传。

---

## §6 test-quality — 测试质量

**整体评价**: 23 个测试覆盖所有 AC 及 3 个 SS guard，mock 边界正确（`patch("intellisource.llm.gateway.litellm")`，在模块命名空间级别 mock），断言有效性高。

### [R-006] LOW: 测试对 Function Calling 模式下 content=None 无覆盖

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: 所有测试均使用 `_make_litellm_response(content="...")` 固定返回非 None content。Function Calling 的典型响应是 content=None + tool_calls 列表，此路径完全未被测试（关联 R-003）。
- **建议**: 增加一个测试：`resp.choices[0].message.content = None; resp.choices[0].message.tool_calls = [...]`，断言 `chat()` 不因 content=None 抛出 TypeError，且返回的 `LLMResult.content` 为空字符串或对应处理结果。

---

## §7 complexity / duplication

实现者自报 `refactor_needed: false`，审查确认：`chat()` 新增 93 LOC，无与 `complete()` 的逻辑克隆（两方法构型完全不同：complete 用 prompt + system_prompt + token truncation + retry；chat 用 messages-style + tools + schema fallback）；`_validate_tools()` 是独立辅助函数无重复。`TDD_REFACTOR_TRIGGER` 未命中，self-report 确认正确，**refactor 可跳过**。

---

## §8 convention

所有新增代码符合 PEP 8（snake_case 函数、PascalCase 类）；无新增环境变量读取；`IS_` 前缀约定未被破坏。Conventional Commit 消息格式正确 (`feat(llm): T-086 GREEN`)。**PASS**

---

## 问题汇总

| ID | 严重等级 | category | 一句话描述 |
|----|---------|----------|-----------|
| R-001 | HIGH | consistency | runner.py 以 dict 消费 LLMResult 对象，运行时 AttributeError |
| R-002 | MEDIUM | completeness | LLMOutputError 未加入 llm/__init__ __all__，下游捕获路径不稳定 |
| R-003 | MEDIUM | error-handling | Function Calling 时 content 可为 None，output_length=len(None) 抛 TypeError |
| R-004 | MEDIUM | error-handling | chat() 不经 retry/fallback 包装，transient 错误及 NotSupportedError 未处理 |
| R-005 | LOW | consistency | **kwargs 声明后未转发，docstring 描述误导 |
| R-006 | LOW | test-quality | Function Calling content=None 路径无测试 |

---

## 最终判定

**verdict: needs_revision**

存在 1 个 HIGH 问题（R-001），按 §三态判定逻辑判定为 needs_revision。

修订优先级：R-001（HIGH，运行时必断）→ R-003（MEDIUM，Function Calling 会触发）→ R-004（MEDIUM，架构合规）→ R-002（MEDIUM，公共 API 完整性）→ R-005/R-006（LOW，可并入修订）。
