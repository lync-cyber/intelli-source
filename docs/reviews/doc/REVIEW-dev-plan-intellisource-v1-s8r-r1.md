---
id: "review-dev-plan-intellisource-v1-s8r-r1"
doc_type: review
author: reviewer
status: approved
deps: ["dev-plan-intellisource-v1-s8r"]
---

# REVIEW: dev-plan-intellisource-v1-s8r — r1

**被审文档**: `docs/dev-plan/dev-plan-intellisource-v1-s8r.md`（706 行，12 张任务卡 T-083~T-094）
**审查层次**: Layer 2 AI 语义审查（Layer 1 已 PASS，2 个预期 WARN）
**审查日期**: 2026-05-21

---

## 问题列表

### [R-001] HIGH: T-088 tdd_mode 标注为 light 但跨 2 个 arch 模块，违反 COMMON-RULES 升档规则

- **category**: consistency
- **root_cause**: self-caused
- **描述**: T-088 的 `tdd_mode: light` 与 COMMON-RULES §执行模式矩阵 的升档规则冲突。规则明确：LOC > `TDD_LIGHT_LOC_THRESHOLD`（150）**或** `security_sensitive: true` **或**跨模块，三者任一满足即升 standard。T-088 预估 LOC ~140（低于阈值），但任务卡 `模块` 字段显式列出 M-005（LLM 服务治理）和 M-011（API 路由）两个 arch 模块，满足"跨模块"条件，应升为 `tdd_mode: standard`。当前标注为 `light` 将导致 tdd-engine 以 RED+GREEN 合并的轻量模式执行，跳过熔断/队列接驳逻辑的独立 RED 阶段，削弱这类分布式基础设施变更的 TDD 保障。
- **建议**: 将 T-088 的 `tdd_mode` 改为 `standard`，与同样跨模块的 T-085（M-008/M-009，standard）保持一致。若 implementer 认为 LOC 确实很小，应在任务卡 risk 段说明为何该场景不触发跨模块升档规则（如：M-011 改动为单个 GET 端点，不构成跨模块抽象）。

---

### [R-002] HIGH: T-093 AC-5 引用不存在的 `re.search(..., timeout=1.0)` API

- **category**: feasibility
- **root_cause**: self-caused
- **描述**: T-093 AC-5 的文本为 `使用 re.search(pattern, text, timeout=1.0) 或等价 timeout 机制`。Python 标准库 `re.search()` 不接受 `timeout` 参数——该参数从未是标准库的一部分。实际上 task 卡的 mitigation 段已正确指出需要使用第三方 `regex` 库的 `regex.search(pattern, text, timeout=1.0)`。两处内容相互矛盾：AC 描述了一个不存在的调用方式，而 mitigation 给出了正确做法。若 implementer 按 AC 字面执行，会在运行时遇到 `TypeError: search() got an unexpected keyword argument 'timeout'`。
- **建议**: 将 AC-5 修改为：`/regex/` 分支使用 `regex.search(pattern, text, timeout=1.0)`（第三方 `regex` 库，已在 mitigation 中列为必选依赖），timeout 触发时捕获 `regex.TimeoutError` 并记录日志，该关键词返回 False。删除对 `re.search` 的引用。测试断言同样改为调用 `regex.search` 路径。

---

### [R-003] MEDIUM: 依赖图缺少 T-083 → T-087 直接边，与 T-087 任务卡依赖字段不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: T-087 任务卡的 `依赖` 字段明确列出三个前置任务：T-083（应用组合根）、T-084（PipelineEngine 接入）、T-086（LLMGateway.chat 方法）。但 §2 依赖图的 Mermaid 图中只有 `T-084 --> T-087` 和 `T-086 --> T-087` 两条边，缺少 `T-083 --> T-087` 直接边。虽然 T-083→T-084→T-087 和 T-083→T-086→T-087 均为 T-087 提供了传递路径，但依赖图与任务卡的直接依赖声明不一致，可能让 orchestrator 在推导执行计划时产生误解（实际直接依赖 vs 传递依赖）。
- **建议**: 在 Mermaid 图中补充 `T-083 --> T-087` 直接边，或在 T-087 的 `依赖` 字段将 T-083 从直接依赖改为注释说明（"通过 T-084/T-086 传递"），二选一，以消除不一致。

---

### [R-004] MEDIUM: T-093 AC-2 边界条件自相矛盾，quiet_hours 边界值语义模糊

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: T-093 AC-2 的测试描述为："UTC 00:00（北京时间 08:00），不在 quiet_hours 内（若 quiet_hours 为 22:00-08:00 则 UTC 00:00 北京 08:00 刚好在边界）"。该描述同一句话内先说"不在 quiet_hours 内"又说"刚好在边界"，未说明边界值（08:00 恰好命中 quiet_hours 结束时间）属于 in 还是 out。而对应的 T-094 AC-4 则直接断言"UTC 00:00（北京 08:00）断言返回 False"（即不在安静时间内），与 AC-2 括号内的"刚好在边界"描述依然有歧义——实现者无法从 AC-2 单独推断边界语义。
- **建议**: 在 AC-2 中明确边界包含/排除规则：例如"quiet_hours 结束时间 08:00 为开放端点（`<`），`08:00` 不属于安静时间"。同时删除括号内的自我说明，将边界语义作为正式约束写入 AC。

---

### [R-005] MEDIUM: B-12 阻断项跨 T-083 和 T-092 双卡映射，拆分边界未明确说明

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: 背景上下文和 §1 均将 B-12 映射到 T-083（"B-01 + B-12 基础层"）和 T-092（"B-12 + B-13"）两张任务卡。T-083 负责"B-12 基础层"（`celery_app.py` 建立 module-level singleton），T-092 负责"B-12 配置层"（`task_routes` + `task_queues` 配置）。然而两张任务卡本身未明确说明 B-12 的哪个子项归哪张卡，只在标题括号中有暗示。如果 implementer 只看单张任务卡，无法确认 B-12 已被完整覆盖还是只完成了一半。
- **建议**: 在 T-083 的 `目标` 段添加一句"本卡覆盖 B-12 基础层（celery_app singleton 建立）；B-12 的 task_routes/task_queues 配置部分由 T-092 覆盖"；在 T-092 中对称注明"本卡覆盖 B-12 配置层（task_routes + task_queues）；基础层由 T-083 覆盖"。

---

### [R-006] MEDIUM: T-091 security_sensitive=true 但 AC 未要求 yaml.safe_load，存在 YAML 反序列化安全漏洞风险

- **category**: security
- **root_cause**: self-caused
- **描述**: T-091 标注 `security_sensitive: true`，理由是"配置加载路径：恶意配置文件可注入非法参数"。然而任务卡的 AC 和 deliverables 均只提到 `ConfigLoader.load_file()`、`ConfigValidator.validate()` 的调用，未对底层 YAML 解析方式作任何约束。若 `ConfigLoader` 内部使用 `yaml.load()`（不带 Loader 参数）或 `yaml.full_load()`，则攻击者通过恶意 sources YAML 文件可触发任意代码执行（Python YAML 反序列化漏洞）。`yaml.safe_load()` 是此场景的标准防护手段。
- **建议**: 在 T-091 的 AC（或 deliverables 的 ConfigLoader 修改条目）中新增约束："`ConfigLoader.load_file()` 内部必须使用 `yaml.safe_load()` 解析 YAML 文件，禁止使用 `yaml.load()` 不带显式 `Loader=yaml.SafeLoader`"。如果 ConfigLoader 已在 T-083 之前的代码中实现，则在本任务验收时通过 grep 确认无 `yaml.load(` 或 `yaml.full_load(` 调用。

---

### [R-007] MEDIUM: T-090 PushRecord 持久化未考虑 PII 字段的存储与日志脱敏

- **category**: security
- **root_cause**: self-caused
- **描述**: T-090 将三渠道的推送目标信息（手机号/邮箱/企业微信 ID 等）写入 `PushRecord`，而任务卡的 AC 和 deliverables 均未涉及 PII 敏感字段的处理策略：`PushRecord` 中存储的接收方标识符若为手机号或邮箱，直接明文落库；`error_message` 字段在记录失败原因时可能包含原始接收方信息（如 HTTP 响应体中的邮箱地址）。这与 arch §5 非功能架构的安全要求存在潜在冲突。
- **建议**: 在 T-090 的 AC 或 deliverables 说明中补充：① `PushRecord.recipient_id`（或等价字段）应存储脱敏/哈希后的标识符，或仅存储 subscription_id 而非原始联系方式；② `error_message` 字段写入前进行 PII 脱敏（如将邮箱中的账号部分替换为 `****`）。如 arch 文档另有约定，以 arch 为准，但 AC 中应显式引用该约定。

---

### [R-008] MEDIUM: T-086 JSON Mode 未涉及 prompt injection 防护

- **category**: security
- **root_cause**: self-caused
- **描述**: T-086 标注 `security_sensitive: true`，任务目标包含将用户/调用方输入的内容通过 `LLMGateway.chat(messages=[...])` 发送给 LLM 并期望得到 JSON 格式输出。AC-4 要求 `SchemaEnforcer` 对 LLM 返回值做兜底校验，但 AC 未要求在输入到 LLM 之前对 messages 内容做注入防护：攻击者可在 `messages` 的 `content` 字段中嵌入指令（prompt injection），引导 LLM 忽略 system prompt 的格式约束，绕过 `response_format={"type":"json_object"}` 要求，输出非预期结构。SchemaEnforcer 的兜底仅处理格式问题，无法阻止语义级注入。
- **建议**: 在 T-086 的 AC 或 mitigation 中补充：当 `messages` 来自不受信任的用户输入时，应对 `content` 字段做长度限制（`MAX_USER_MESSAGE_LENGTH`）并过滤已知的 prompt injection 模式（如 `ignore previous instructions`）；如果 messages 仅由系统内部构造（不含用户原文），则在 deliverables 说明中显式注明，以说明为何 prompt injection 风险不适用。

---

### [R-009] MEDIUM: T-094 AC-6 基线 PASS 数未文档化，验收标准不可独立执行

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: T-094 AC-6 要求"PASS 数 ≥ 前一轮（T-082 完成后的 PASSED 数），0 FAILED"，但"T-082 完成后的 PASSED 数"是一个外部状态，未在任何 deliverables 或 docs 中记录具体数值。新加入的 implementer 无法独立确认基线数，只能通过运行 T-082 阶段的测试或查询历史 CI 日志获得，而这些信息并不总是可达。若基线数不清楚，该 AC 实际上退化为"0 FAILED"这一不完整约束。
- **建议**: 两种解决方案任选其一：① 在 T-094 的任务卡中直接记录基线值，例如"基线 PASSED 数 = N（截至 T-082 完成时）"；② 将 AC-6 改为纯增量表述，如"`uv run pytest` 新增测试用例全部 PASS，且已有测试无回归（0 FAILED，0 ERROR）"，去掉需要外部查询的绝对基线比较。

---

### [R-010] LOW: T-092 risk 段包含 "supersedes T-075" 的对比叙事，违反禁止设计阶段残留规则

- **category**: convention
- **root_cause**: self-caused
- **描述**: T-092 的 `risk` 段包含一句："supersedes T-075（sprint-8 P2 backlog，Agent 工具接驳）的 Celery worker 初始化部分 — sprint-8 P2 未执行，本任务独立完整实现"。COMMON-RULES §禁止设计阶段与变更说明残留 明确禁止在长期文档中出现 "supersedes / 替代了 / 不再使用 X" 等对比叙事语句。这类信息是变更历史，应仅出现在 commit message 或 PR 描述中，不属于任务卡的现状说明。
- **建议**: 删除 `supersedes T-075...` 句子。如需保留背景知识，改写为仅描述当前状态，例如"本任务独立实现 Celery worker 初始化逻辑，无需依赖外部 P2 任务"。

---

### [R-011] LOW: T-083 AC-4 使用 `bind=True` 但未说明任务函数签名变化

- **category**: ambiguity
- **root_cause**: self-caused
- **描述**: T-083 AC-4 要求 `CeleryTasks.run_pipeline` 被 `@celery_app.task(name="run_pipeline", bind=True)` 装饰。当 `bind=True` 时，Celery 在调用任务时会将任务实例作为第一个参数 `self` 注入，这要求 `run_pipeline` 方法签名必须是 `def run_pipeline(self, ...)` 而非 `def run_pipeline(...)`（原 `CeleryTasks` 方法如果是普通方法或类方法可能与此不兼容）。AC 未说明这一签名变化，implementer 容易遗漏。
- **建议**: 在 AC-4 末尾补充："`run_pipeline` 函数签名必须为 `def run_pipeline(self, **kwargs)`（`bind=True` 注入的 `self` 为 Task 实例，与 `CeleryTasks` 类的 `self` 语义不同）；或改为 standalone task 函数（移出 CeleryTasks 类），届时无需处理双 self 歧义"。

---

### [R-012] LOW: `expected_tool_budget` 字段仅 T-083 标注，其余 11 张任务卡缺失，约定不一致

- **category**: convention
- **root_cause**: self-caused
- **描述**: T-083 包含 `expected_tool_budget: ~100`，其余 11 张任务卡（T-084~T-094）均未标注此字段。根据 dev-plan 的任务卡模板约定，该字段存在就应该在所有卡片中一致使用；若是可选字段，则已有标注的任务卡打破了一致性期望。
- **建议**: 两种处理方式任选其一：① 为所有任务卡补充 `expected_tool_budget` 估算；② 从 T-083 删除该字段，统一为不在 sprint 卡中标注 tool budget（该字段通常由 orchestrator 在任务调度时动态设置）。

---

## 阻断项覆盖矩阵

以下汇总 15 个阻断项（B-01~B-15）与 12 张任务卡的映射完整性：

| 阻断项 | 任务卡 | 覆盖状态 |
|--------|--------|---------|
| B-01 | T-083 | 覆盖 |
| B-02 | T-085 | 覆盖 |
| B-03 | T-084 | 覆盖 |
| B-04 | T-087 | 覆盖（4 子项：VectorStore 补全 + _llm_complete_execute + SchemaEnforcer + ContentCluster 写入） |
| B-05 | T-088 | 覆盖 |
| B-06 | T-086 | 覆盖 |
| B-07 | T-090 | 覆盖 |
| B-08 | T-089 | 覆盖（6 execute stubs） |
| B-09 | T-091 | 覆盖 |
| B-10 | T-093 | 覆盖 |
| B-11 | T-086 | 覆盖 |
| B-12 | T-083 + T-092 | 覆盖（拆分，见 R-005） |
| B-13 | T-092 | 覆盖 |
| B-14 | T-093 | 覆盖 |
| B-15 | T-093 | 覆盖 |

所有 15 个阻断项均有对应任务卡覆盖，无遗漏。

---

## 审查结论

| 严重等级 | 数量 |
|---------|------|
| CRITICAL | 0 |
| HIGH | 2（R-001、R-002） |
| MEDIUM | 7（R-003 ~ R-009） |
| LOW | 3（R-010 ~ R-012） |

**verdict**: **needs_revision**

存在 2 个 HIGH 问题需要修正后方可进入 sprint-8r 执行：
1. R-001（T-088 tdd_mode 违反 COMMON-RULES 跨模块升档规则）必须修正，否则 tdd-engine 以错误模式运行。
2. R-002（T-093 AC-5 引用不存在的 `re.search(timeout=...)` API）必须修正，否则 implementer 将基于错误的 AC 编写测试和实现。

7 个 MEDIUM 问题（R-003~R-009）中安全类（R-006/R-007/R-008）建议在对应任务卡修正前处理，其余可在执行阶段同步修正。
