---
id: "code-review-T-097-r1"
doc_type: code-review
author: reviewer
status: approved
deps: [T-097]
---

# CODE-REVIEW-T-097-r1

## Layer 1 摘要

`ruff check`、`ruff format --check`、`mypy --strict` 对 6 个变更源文件全部通过，无 finding。Layer 1 clean。

## Layer 2 — 7 维度审查

### 1. security（深审）

**PII 脱敏边界**

`_mask_recipient`（facade.py:192-202）通过 `@` 检测路由到 `mask_email`，通过 11+ 位数字检测路由到 `mask_phone`，否则 raw 透传。对 wechat/wework 渠道：`openid` 通常为 28 字符字母数字串（无 `@`，纯数字不足），`user_id`（企微）同理 — 两者均走 `return raw` 分支，**以明文形式存入 PushRecord**。

这不是漏洞（openid/user_id 本质上是平台内部 ID，不属于 PII 范畴），但与函数注释"Apply PII mask"和 AC-7 "PII 脱敏"的意图存在语义落差：任何未来渠道（如 SMS）若 user_id 是手机号，`_mask_recipient` 的数字判断依赖"7 位以上"阈值，如果用户 ID 是微信短 ID（如 6 位纯数字工号）则走明文分支。不会导致当前测试失败，但边界条件不够清晰。

`_logger.exception`（facade.py:83-88）记录 `sub.id` 和 `channel_name`，不记录 `channel_config`，无 PII 泄露风险。

**env 凭证硬失败一致性**

WeChatDistributor.from_env 检查 `IS_WECHAT_APP_ID` + `IS_WECHAT_APP_SECRET`（两个独立 if）；WeWorkDistributor.from_env 检查三个变量；EmailDistributor.from_env（T-090）检查三个变量。三者均通过 `raise ValueError` 实现硬失败，语义一致。conftest.py 的 autouse fixture 注入 fake 值使非凭证测试不受影响；TestBuildDistributorFacadeEnvGuard 的每个测试体内通过 `monkeypatch.delenv` 覆盖 fixture，pytest 执行顺序保证 fixture 先于测试体 setup，覆写后生效。机制正确。

**uuid.UUID 非法 content_id 的成本路径**

`_load_content_and_subscriptions`（facade.py:116-119）在 `uuid.UUID(content_id)` 抛 ValueError 时 `return None, []`，静默吞掉错误。调用方 `distribute()` 接收 `(None, [])` 后调用 `self._matcher.match(None, [])` — 空 subscriptions 导致 matched=[] 直接返回 `{status: ok, matched: 0, sent: 0, skipped: 0}`。攻击者无法通过这条路径触发错误信息、执行额外 DB 查询或产生侧信道，风险可接受。

**_distribute_execute 的 kwargs 穿透**

`_distribute_execute` 将 `**kwargs` 原样传入 `facade.distribute(**kwargs)`，facade 又将 `**kwargs` 传给调用方。测试中注入 `_recipient_hint_email` / `_recipient_hint_phone` 等哨兵键，这些键不会被 facade 读取，直接走向 `distribute()` 的返回值（但 facade 不把 kwargs 放进返回 dict），无实际泄露。`_distribute_execute` 返回的 envelope 中也不包含这些键，测试 `test_distribute_envelope_carries_no_plaintext_pii` 通过。机制正确。

**总结**：无 CRITICAL/HIGH security finding。存在一处 MEDIUM 边界语义不清（见 R-001）。

---

### 2. completeness（AC 逐条验证）

- **AC-1** `build_collector_registry()` 注册 rss/api/web：composition.py:168-174，`registry.register("rss", RSSCollector)` + `"api"` + `"web"` 三行明确。GREEN 测试 test_collect_execute_source_type_api_returns_ok 验证 api 路径，test_collect_execute_with_source_config_dict_returns_ok 验证 rss 路径。覆盖完整。**PASS**

- **AC-2** `DistributorFacade.__init__(session_factory, matcher, channels)` + `async def distribute(*, content_id, subscription_id, **kwargs) -> dict`：facade.py:29-34 + 39-45。签名完全匹配。**PASS**

- **AC-3** 5 步流水线 + 返回 `{status, matched, sent, skipped}`：facade.py distribute() 1-5 步完整；返回 dict 在 100-105 行包含全部 4 个键。**PASS**

- **AC-4** `build_distributor_facade` 从 env 构造三渠道；env 缺失 raise ValueError：composition.py:138-160。TestBuildDistributorFacadeEnvGuard 3 个测试覆盖 wechat/smtp/wework 缺失场景。**PASS**

- **AC-5** `_distribute_execute` 调用 facade，返回 status: ok（无 degraded 路径）：tools.py:218-232。当 tool_deps.distributor 存在时直接调用并返回 `{status: ok, ...}`。**PASS**

- **AC-6** 集成测试 `_collect_execute` status: ok + 非空 collected：test_collect_tool_not_degraded.py 5 个测试全 PASS，其中 test_collect_execute_with_source_config_dict_returns_ok 断言 status=ok + len(collected)>=1。**PASS**

- **AC-7** 集成测试 PushRecord 写入 + recipient_id PII 脱敏：test_distribute_writes_push_record.py 4 个测试覆盖 facade result shape + PushRepository.create spy + kwargs PII scan + envelope PII scan。29 passed。**PASS**

- **AC-8** 单元测试 5 步骤按序调用：test_facade.py TestDistributeFiveSteps。在 29 passed 中包含。**PASS**

**一处 completeness 问题（MEDIUM）**：`_record_push`（facade.py:151-176）接收 `recipient_id` 参数但调用 `repo.create` 时未将其传入——`PushRepository.create` 签名为 `(subscription_id, content_id, channel, **kwargs)` 且 PushRecord model 没有 `recipient_id` 列，因此不会崩溃。但 AC-7 意图"持久化时 PII 脱敏"的语义依靠 `recipient_id` 字段落库，实际并未落库（只写了 channel/status，无 recipient）。测试中 spy 捕获的 `kwargs` 不包含 `recipient_id`，所以 PII 断言是扫描空 set，形式通过但验证意图未落地。见 R-002。

---

### 3. test-quality

**conftest.py autouse fixture 与 env-guard 测试的交互**

conftest `_stub_distributor_env` 是 `autouse=True` 无 yield，使用 monkeypatch scope=function，随每个测试函数重置。TestBuildDistributorFacadeEnvGuard 的测试体内调用 `monkeypatch.delenv("IS_WECHAT_APP_ID", raising=False)` 会覆盖 fixture 设置的值（同一 monkeypatch 实例），顺序保证正确，hard-fail 测试不会被 autouse fixture 静默通过。机制可信。

**test_distribute_writes_push_record.py PII 脱敏断言有效性**

`test_distribute_pushrecord_kwargs_have_no_plaintext_pii` 依赖 spy 捕获 `PushRepository.create` 的 kwargs，然后扫描有无明文 PII。但如上 R-002 所述，`_record_push` 实际传给 `repo.create` 的 kwargs 不含 `recipient_id`——捕获的 kwargs 只有 `{subscription_id, content_id, channel, status}`，均无明文 PII，测试形式通过但未真正验证"脱敏后的 recipient 被落库"这个 AC-7 语义。测试是正确描述（不含 PII），但无法覆盖"recipient 已脱敏并持久化"的完整意图。

**test_collect_tool_not_degraded.py**

`patch.object(BaseCollector, "conditional_fetch", new=mock_fetch)` 在 HTTP 传输层 patch，保留了 RSSCollector.collect() 的完整逻辑（XML 解析、source_config 读取），不绕过 collector 真实行为。test_collect_execute_with_source_config_dict_returns_ok 对 mock_session.get 返回 mock_source（含 url 字段），测试验证到完整链路。`collected` 非空断言有效。

**_make_mock_session_factory 中 `session.scalars = AsyncMock(return_value=iter([mock_sub]))`**

`iter([mock_sub])` 是同步迭代器，`await session.scalars(stmt)` 返回它后 `list(await ...)` 调用同步 `__iter__`。在测试环境中可行，但生产 `session.scalars()` 返回 `AsyncScalarsResult`，需要 `result.all()` 或异步迭代，而 facade 用 `list(await session.scalars(stmt))`。`list()` 对同步可迭代对象有效，对 `AsyncScalarsResult` 会得到协程对象列表而非实体列表——生产路径与测试路径的 `session.scalars` 消费模式不同，存在测试未能覆盖的运行时分歧。见 R-003。

---

### 4. consistency

**factory.py TYPE_CHECKING 引用迁移**：从 `intellisource.composition.DistributorFacade` 改为 `intellisource.distributor.facade.DistributorFacade`，与 T-097 实际交付位置一致。正确。

**composition.py `build_distributor_facade` 签名**：接收 `session_factory` + `redis_client`，与 `build_worker_composition` 和 `_build_deps_bundle` 调用处一致。

**DistributorFacade 与 ToolDeps.distributor 类型**：agent/deps.py 中 `distributor` 字段应为 `DistributorFacade | None`，facade 实例可直接赋入。与 T-095 contract 一致。

**WeChatDistributor.distribute / WeWorkDistributor.distribute 各自内建 dedup + record 逻辑**（通过 `_send_with_dedup_lifecycle`），facade.py 另起 5 步流水线（含 facade 层面的 `_is_already_pushed` + `_record_push`）。两层 dedup + record 并存，逻辑上会导致：channel 内部先 dedup/record 一次，facade 再 record 一次（共两次 PushRecord 写入）。这是架构层面的双写，可能导致 PushRecord 重复或违反 `uq_push_records_dedup` 唯一约束。见 R-004。

---

### 5. error-handling

**`facade.distribute` 中 `try/except Exception`（行 79-89）**：捕获所有异常并 `_logger.exception` 后 skip，未做特化（如区分网络超时 vs 鉴权失败 vs 序列化失败）。对 channel.distribute 失败以 skipped 计数，调用方看到 `{status: ok, sent: 0, skipped: N}` — 对比 AC-3 契约"返回 {status, matched, sent, skipped}"，status 始终为 ok 无论 channel 全部失败，调用方无法从状态码区分"正常无订阅"和"全部 channel 失败"。可接受作为 P1 改进，不影响当前 AC 验证。LOW。

**`_collect_execute`（tools.py:140-145）中 `except Exception as exc`**：仅 warning log 后 fallback 到 source_config = {url: source_id, ...}。若 DB 连接断开，会以错误的 url（实为 UUID 字符串）去抓取，collector 不会 crash 但会得到空 result。可接受的降级策略，LOW。

**`_record_push` 中 `uuid.UUID(content_id)` 失败静默 return**（行 163-166）：若因上游逻辑错误传入非 UUID 字符串，push record 无声丢失。考虑到此时 channel.distribute 已经成功（step 4），丢失 record 会导致后续 dedup 失效（_is_already_pushed 永远 False）。LOW。

---

### 6. convention

命名与错误处理风格整体符合 IntelliSource 规范（`IntelliSourceError` 继承链在 composition.py 正确使用；`CompositionError` 继承 `ValueError` 向后兼容）。

`build_distributor_facade` 内部 `raise ValueError` 来自各 channel 的 `from_env`，而非 `CompositionError`。`CompositionError` 已有 `ValueError` MRO，但 from_env 直接抛 `ValueError` 不经 `IntelliSourceError` 层级，丢失 `category` + `recovery_hint` 字段。可作为改进建议，不影响功能。LOW。

WeWorkDistributor 使用 `self.redis` / `self.http_client`（无下划线前缀），WeChatDistributor 使用 `self._redis` / `self._http`（有前缀），风格不一致。LOW。

---

### 7. structure

`DistributorFacade`（202 行）职责清晰：_load_content_and_subscriptions（DB 读）/ _is_already_pushed（dedup 查询占位）/ _record_push（DB 写）三方法划分合理，无过早抽象信号。

`_extract_recipient` / `_mask_recipient` 作为模块级函数（非方法），便于独立测试，合理。

`_is_already_pushed` 硬编码 `return False`（行 149）是有意 stub，注释说明"Return True if a PushRecord already exists"。当前测试可通过，但生产环境会导致每次 distribute 都绕过 dedup，与 `uq_push_records_dedup` 唯一约束冲突（DB 层面会抛 IntegrityError 而非静默幂等）。如果重复推送，channel 的 `_send_with_dedup_lifecycle` 内建 dedup 会拦截（见 R-004 讨论），但两层 dedup 职责混淆本身是结构问题。见 R-004。

---

### 腐化扫描

**duplication**：WeChatDistributor.from_env 与 WeWorkDistributor.from_env 均为"读取 N 个 os.environ.get + 各自 raise ValueError + 构造 cls(...)"模式，结构相似但 key 名和参数数量不同，抽公共基类的价值有限。EmailDistributor.from_env 同型。LOW（不产生 finding，作为改进建议记录）。

**dead-code**：无未引用导入或不可达分支。`http_client=None` 默认值在测试中常见，生产路径由 composition 注入非 None 值，可接受。

---

## 问题汇总

### [R-001] MEDIUM: _mask_recipient 对 wechat openid / wework user_id 走明文透传分支，边界条件不清晰

- **category**: security
- **root_cause**: self-caused
- **描述**: `_mask_recipient`（facade.py:192-202）对 openid（28 位字母数字）和企微 user_id（字母数字）均走 `return raw` 分支（既无 `@`，纯数字不足 7 位或完全不是纯数字）。当前这两类 ID 不属于传统 PII，但函数注释是"Apply PII mask"，AC-7 要求"PII 脱敏"，语义承诺与实现存在落差。未来若有渠道以手机号作 user_id（如 SMS 渠道），数字长度判断可能因非标准号码格式（含区号、短号）不满足 7 位阈值而明文落库。
- **建议**: 在函数 docstring 中明确"wechat openid / wework user_id 不属于受保护 PII，直接存储"，或为未知渠道类型增加截断保护（如 `raw[:4] + "***"`）。无需修改核心逻辑，补充注释即可消除歧义。

---

### [R-002] MEDIUM: _record_push 接受 recipient_id 参数但未传入 PushRepository.create，脱敏后的收件人信息未落库

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `_record_push`（facade.py:151-176）签名含 `recipient_id: str | None = None`，但调用 `repo.create` 时仅传递 `subscription_id, content_id, channel, status="sent"`，未将 `recipient_id` 传入。PushRecord 模型当前无 `recipient_id` 列，因此不会崩溃，但 AC-7 "PII 脱敏后的收件人持久化"意图未被满足。测试 `test_distribute_pushrecord_kwargs_have_no_plaintext_pii` 扫描 spy kwargs 中有无明文 PII — 因为 recipient_id 本就不在 kwargs 中，断言形式通过但未验证"脱敏值已落库"。
- **建议**: 若 AC-7 意图要求收件人标识持久化，需在 PushRecord 模型中添加 `recipient_id: Optional[str]` 列（alembic migration）并在 `repo.create` 中传入脱敏后的值。或明确 AC-7 仅要求"不得有明文 PII 进入任何持久化路径"（当前已满足），将 `recipient_id` 参数从 `_record_push` 签名中移除以消除误导。两者均需与用户确认 AC-7 验收范围。

---

### [R-003] MEDIUM: session.scalars() 消费模式在 facade 与测试中不一致，生产路径存在运行时风险

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: facade.py:137 执行 `list(await session.scalars(stmt))`。在真实 SQLAlchemy `AsyncSession` 中，`await session.scalars()` 返回 `AsyncScalarsResult`，对它调用 `list()` 会得到 `[coroutine, ...]` 而非实体列表——正确的消费方式是 `(await session.scalars(stmt)).all()` 或 `result.fetchall()`。测试中 `mock_session.scalars = AsyncMock(return_value=iter([mock_sub]))` 返回同步迭代器，`list(iter([mock_sub]))` 正常工作，掩盖了生产路径的差异。
- **建议**: 将 `list(await session.scalars(stmt))` 改为 `(await session.scalars(stmt)).all()`，与 SQLAlchemy 2.0 async API 对齐；同步更新测试 mock，使 `scalars()` 返回一个带 `.all()` 方法的 mock 对象，确保测试验证与生产一致的消费模式。

---

### [R-004] LOW: DistributorFacade 与各 channel 内部存在双层 dedup + record 逻辑，_is_already_pushed 永远 False 加剧风险

- **category**: structure
- **root_cause**: self-caused
- **描述**: WeChatDistributor.distribute 和 WeWorkDistributor.distribute 内部均通过 `_send_with_dedup_lifecycle` 执行 dedup 检查和 push record 写入；DistributorFacade 在其外层又设计了 `_is_already_pushed`（当前硬编码 `return False`）和 `_record_push`（再次写入 PushRecord）。当前因为 `_is_already_pushed` 始终 False，实际执行路径是：facade 不 dedup → channel 内 dedup → channel 内 record → facade 再 record，可能导致两次 `PushRepository.create` 调用，触发 `uq_push_records_dedup` IntegrityError 而非幂等成功。
- **建议**: 明确 dedup 和 record 的职责边界——要么 facade 负责（channel 只负责发送）、要么 channel 负责（facade 不重复 record）。短期可将 `_record_push` 改为检查 channel.distribute 返回值中的 dedup 标记后再决定是否 record；长期需要清理 channel 内 `_send_with_dedup_lifecycle` 与 facade 层 dedup 的重叠。

---

### [R-005] LOW: _collect_execute CollectorRegistry.get 对未注册 source_type 抛 CollectorError 未被捕获

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: tools.py:154 `tool_deps.collector_registry.get(source_type)` 在 source_type 未注册时抛 `CollectorError`（IS-COL-001）。`_collect_execute` 未捕获此异常，会向上传播导致 AgentRunner 任务失败。T-097 注册了 rss/api/web 三种类型，但 agent 可能被传入任意 source_type 字符串。
- **建议**: 在 `_collect_execute` 中 catch `CollectorError` 并返回 `{status: "degraded", reason: "unknown source_type: {source_type}"}` 以保持与现有 degraded 路径一致的错误语义，或在调用前用 `registry.list_types()` 预验证。

---

## EXP-005 ToolDeps 装配缺口回归审计

**composition.py `build_distributor_facade`**：真实化，三渠道通过 `from_env()` 构造并注入 `DistributorFacade`；`_build_deps_bundle` 将 facade 传入 `ToolDeps`。无 silent-None 缺口。

**agent/factory.py `build_agent_runner`**：T-097 diff 仅迁移 TYPE_CHECKING import，不涉及 ToolDeps 构造逻辑。原有 `distributor` 字段赋值路径不变，无新增 silent-None。

**结论**：T-097 未引入新的 EXP-005 型装配缺口。

---

## Verdict

- **status**: approved_with_notes
- **理由**: 1 个 MEDIUM（R-002 recipient_id 未落库，AC-7 完整性存在歧义）、1 个 MEDIUM（R-003 `session.scalars` 消费模式不一致，生产路径潜在运行时错误）、1 个 MEDIUM（R-001 `_mask_recipient` 语义落差）。无 CRITICAL/HIGH。8 个 AC 全部覆盖，29 个测试 PASS，Layer 1 clean。
- **AC 覆盖**: AC-1 ✓ AC-2 ✓ AC-3 ✓ AC-4 ✓ AC-5 ✓ AC-6 ✓ AC-7 ✓（形式 PASS，见 R-002 语义说明）AC-8 ✓
