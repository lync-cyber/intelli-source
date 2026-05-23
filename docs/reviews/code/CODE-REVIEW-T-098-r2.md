---
id: "code-review-T-098-r2"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-098"]
---

# CODE-REVIEW T-098 r2

**任务范围**: T-098 [standard, security_sensitive] — /search/chat flexible mode + Webhooks router + 微信/企微 CS clients
**提交**: e4e3c06 (PR #51) — fixes on top of r1 baseline 87512aa
**审查模式**: standard, Layer 1 + Layer 2 (orchestrator inline，sprint-9 累计 truncation 4/4 后用户裁决 inline 修 r2 + inline approve；与 sprint-8r T-087/T-092 r3 inline 同源协议)
**前置**: CODE-REVIEW-T-098-r1.md verdict=needs_revision (2 CRITICAL + 4 HIGH + 4 MEDIUM + 3 LOW)
**用户裁决**: R-004 (arch amendment) + R-006 (REFACTOR duplication) 合并入 r2 一并修

## Layer 1 结果

`uv run ruff check .` clean；`uv run ruff format --check .` clean；`uv run mypy --strict src/` clean (122 src files，+1 base_cs_client.py)；`uv run pytest` 2475 PASS / 43 SKIP / 0 FAIL（vs r1 baseline 2452 PASS / 43 SKIP / 0 FAIL，+23 new tests）。

## Verdict: approved

所有 13 个 r1 findings 已修复并新增反证测试。无新引入 CRITICAL/HIGH 问题。详见下方逐项验收。

## R1 → R2 逐项验收

### CRITICAL (2/2 修复)

#### R-001 — webhook 4 状态项装配缺口
- **修复路径**: `composition.py` 新增 `_install_webhook_state(app, redis_client)`，在 `build_api_composition` 末尾装配 4 个状态项 + `background_tasks: set`。env 读取规则:
  - `IS_WECHAT_WEBHOOK_TOKEN` / `IS_WEWORK_WEBHOOK_TOKEN` → 直接 set 到 app.state（空字符串时 router 走 403）。
  - `IS_WECHAT_APP_ID` + `IS_WECHAT_APP_SECRET` → 部分 set 触发 `from_env` ValueError 硬失败启动；全空 → cs_messenger 留 None。
  - `IS_WEWORK_CORP_ID` + `IS_WEWORK_CORP_SECRET` + `IS_WEWORK_AGENT_ID` → 同上模式（全空 skip，部分 set 硬失败）。
  - 都空时启动期 `logger.warning` 显式提示 webhook 不会响应。
- **反证测试**: `tests/integration/test_composition_wires_webhook_state.py` 8 个 lifespan 测试（tokens 设/未设、CS messenger 设/未设、部分 env 硬失败 WeChat + WeWork、background_tasks 初始化）。
- **空 token 攻击面**: `routers/webhooks.py:_verify_sha1` 加 `not token or not signature` 短路 — 空 token 直接 False，攻击者无法用公开 sha1("",ts,nonce) 平凡伪造（即便 R-001 装配缺口本身被无视，此处第二道闸已立）。
- **EXP-005 闭环**: composition._install_webhook_state 统一装配, 部分 env hard-fail 符合 sprint-9 locked policy。与 T-088 R-007 (lifespan collectors) / T-092 N-001 (build_celery_tasks content_repository) / T-089 r1 (tool_deps 未注入) 三处先例对齐。

#### R-002 — WeWork POST 无签名验证
- **修复路径**: `routers/webhooks.py:wework_message` 函数体首行加：
  ```python
  token = getattr(request.app.state, "wework_webhook_token", "")
  if not _verify_sha1(token, signature=msg_signature, timestamp=timestamp, nonce=nonce):
      return PlainTextResponse("forbidden", status_code=403)
  ```
  与 wechat_message:147-148 对称。
- **反证测试**: `tests/unit/api/test_wework_webhooks_signature.py` 7 测试，含 `test_post_wrong_signature_returns_403` + `test_post_empty_signature_returns_403` 双断言。

### HIGH (4/4 修复)

#### R-003 — WeWork CS client agentid 缺失
- **修复路径**: `wework_cs_client.py:WeWorkCustomerServiceClient.__init__` 加 `agent_id: int` 必填参数；`from_env` 读 `IS_WEWORK_AGENT_ID` env（缺失硬失败 ValueError）；`_build_send_payload` 返回 `{"touser":..., "msgtype":"text", "agentid": self._agent_id, "text":{...}}`。
- **反证测试**: `test_wework_cs_client.py::test_from_env_raises_when_agent_id_missing` + `test_send_text_payload_contains_agentid`。

#### R-004 — ChatResponse schema 偏 API-013 (upstream-caused)
- **修复路径**:
  1. `docs/arch/arch-intellisource-v1-api.md` API-013 amendment：保留 `query_time_ms`（SLA），新增 `steps_executed` + `task_chain_id` 字段说明 + `session` + `max_tokens_budget` 入参 + 503 错误码 + flexible-mode reference link。
  2. `schemas/search.py:ChatSearchResponse` 增 `query_time_ms: int` 字段。
  3. `routers/search.py:chat_search` `time.monotonic()` 计算 elapsed_ms 填入 response。
- **反证测试**: `test_search_chat_schema.py::test_response_has_query_time_ms` + 改名 `test_response_serializes_six_fields` 含全 6 字段断言。

#### R-005 — WeWork 测试黑洞
- **修复路径**: 新建 `tests/unit/api/test_wework_webhooks_signature.py` 7 测试（GET 正/错/空签名 + POST 错/空/正签名 + dispatch_chat_reply 触发集成）。镜像 WeChat 测试结构。
- **效果**: WeWork POST 现有完整行为覆盖；R-002 漏洞回归会被测试套件拦截。

#### R-006 — wechat/wework CS clients 95% 同构 (TDD_REFACTOR_TRIGGER)
- **修复路径**: 新建 `distributor/base_cs_client.py:BaseCustomerServiceClient`：
  - 类变量：`api_base / token_path / send_path / token_cache_key`（平台差异）。
  - 抽象方法：`_build_token_query() -> str` + `_build_send_payload(openid, content) -> dict`（子类必须实现）。
  - 共享：`get_access_token()` + `send_text()` 主流程含 Redis 缓存 + errcode 校验 + DistributorError 抛出。
  - WeChat/WeWork client 各精简至 70 行（差异 + payload builder）。
- **回归保护**: 原 50+ 个 CS client 单元测试全部通过；新 errcode + agentid + http_client 反证测试通过。
- **未来扩展**: 加 微博/钉钉/飞书 CS 渠道时各 70 行子类即可。

### MEDIUM (4/4 修复)

#### R-007 — assert 用于 None 校验 (-O 风险)
- **修复路径**: `base_cs_client.BaseCustomerServiceClient.__init__` 强制 `if http_client is None: raise ValueError("http_client is required ...")`。两 client 子类均在 super().__init__() 时验证。
- **反证测试**: `test_wechat_cs_client.py::TestWeChatCsClientRequiresHttpClient::test_init_raises_when_http_client_is_none`。

#### R-008 — errcode 未校验
- **修复路径**: `base_cs_client.get_access_token` 检查 `data.get("errcode", 0) != 0 → DistributorError(category=EXTERNAL)`。同 send_text。两路径错误信息含 errcode + errmsg。
- **反证测试**: WeChat 2 + WeWork 2 = 4 个 errcode 测试覆盖 token + send 两端。

#### R-009 — handle_message echo stub dead code
- **修复路径**: `distributor/webhooks.py:WeWorkWebhookHandler.handle_message` 改为 legacy no-op stub（保留 parse_message 调用，剥离 echo 行为），docstring 明确"新代码不应调用 — routers/webhooks._dispatch_chat_reply 是唯一真实路径"。
- **保留原因**: AC-10 单测 `test_handle_message_exists_and_is_coroutine` 依赖方法存在 — no-op 形态满足契约但不再误导调用方。

#### R-010 — asyncio.create_task 弱引用 + silent log
- **修复路径**:
  1. `routers/webhooks.py` 加 `_spawn_background_dispatch(app, runner, cs_messenger, openid, user_text)`：从 `app.state.background_tasks` 取 set，`task.add_done_callback(set.discard)` 让任务自管生命周期。
  2. `_dispatch_chat_reply` 异常日志加 `extra={"alert": True}` 标记。
  3. `composition._install_webhook_state` 初始化 `app.state.background_tasks = set()`。
- **覆盖**: WeChat + WeWork POST 两端都走 `_spawn_background_dispatch`。`test_wework_webhooks_signature.py::test_post_correct_signature_dispatches_chat_reply` 反证 dispatch 真正被调用。

### LOW (3/3 修复)

#### R-011 — _TOKEN_TTL=7000 未引用
- **修复**: WeChat client 在抽 base 过程中自然消除，未引用常量已删除。base 使用 `_TOKEN_TTL_BUFFER_SECONDS=200` 含义清晰。

#### R-012 — 函数级 import
- **修复**: `routers/webhooks.py:14` `from intellisource.agent.tools import load_pipeline_config` 移到模块顶部 import 块。

#### R-013 — chat_search sources=[] 硬编码
- **修复**: `routers/search.py:_extract_sources(flex_result)` 从 `flex_result["results"]` 找 `step["tool"] == "hybrid_search"`，解析 `output["contents"]` 或 `output["items"]` 列表 → 映射到 `ChatSource(content_id=..., title=..., url=...)`。chat_search 路由替换 `sources=_extract_sources(flex_result)`。

## 新增反证测试统计

| 类别 | 数量 | 文件 |
|------|------|------|
| WeWork webhook signature | 7 | tests/unit/api/test_wework_webhooks_signature.py |
| Composition wiring | 8 | tests/integration/test_composition_wires_webhook_state.py |
| WeChat errcode + http_client | 3 | tests/unit/distributor/test_wechat_cs_client.py |
| WeWork errcode + agentid | 3 | tests/unit/distributor/test_wework_cs_client.py |
| ChatResponse 6 fields | 2 | tests/unit/api/test_search_chat_schema.py |
| **合计** | **23** | — |

新测试覆盖维度：CRITICAL(R-001/R-002) + HIGH(R-003/R-004/R-005) + MEDIUM(R-007/R-008/R-010) 全部有反证回归保护。

## REFACTOR 触发处置

R-006 duplication 已通过 BaseCustomerServiceClient 抽象在 r2 闭合，无需单独 REFACTOR 阶段。TDD_REFACTOR_TRIGGER `[complexity, duplication, coupling]` 维度复审 r2 代码：
- complexity：最大圈复杂度 webhooks router GET/POST handler ≤5，无超阈值。
- duplication：base_cs_client 抽出后无跨文件重复。
- coupling：composition._install_webhook_state 是单向 import，不引入循环。

## EXP-005 + EXP-006 跨任务观察

**EXP-005 装配缺口**：sprint-9 批次 2 截至 r2 闭环 4 次（T-088 R-007 + T-092 N-001 + T-089 r1 + T-098 R-001）。reflector 立项 sprint-9 retrospective 时建议：
1. 框架级 lint 规则：`app.state.X` 读但全 src 无写 → ruff plugin 或 doc-review checker 自动告警。
2. tech-lead 任务卡 template 加 "lifespan wiring checklist" — 任务包含新 app.state.* 字段时必须列出 composition.py 装配点。

**EXP-006 truncation 频率**：sprint-9 累计 4/4（T-095 r1 reviewer + T-096 r1 reviewer + T-098 RED test-writer + T-098 GREEN implementer），三角色全发生。r2 由 orchestrator inline 完成避免第 5 次复发。retrospective 立项强制建议：
1. AGENT.md 加 anti-truncation 默认指令（tools 预算上限 70 / finalize-before-return / stage-by-stage commit）。
2. tdd-engine + agent-dispatch 调度时 cap tools 预算并强制 stage-by-stage 渐进 commit。

## 结论

T-098 r2 全部 13 findings 闭环 + 23 反证测试 + 22 src 模块行数缩减（base_cs_client 重构 -100 行 同构 + 50 行新装配 = 净 -50 行 src）。verdict=approved，无 r3 需要。

**下一步**: T-098 status=approved；继续 sprint-9 批次 2 串行下一任务 T-099 [light]（含 R-004 已经处理的 arch amendment 余项校验）。
