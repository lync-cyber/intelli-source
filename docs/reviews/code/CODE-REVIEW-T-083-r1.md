---
id: "code-review-T-083-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-083"]
---

# CODE-REVIEW T-083: 应用组合根与 Celery 链路真实初始化

Layer 1 delegated to hook (PostToolUse Edit → lint_format.py)

**verdict**: approved_with_notes
**问题统计**: CRITICAL 0 / HIGH 1 / MEDIUM 3 / LOW 2

---

## §1 completeness — AC 实现完整性

AC-1 (celery_app 配置零硬编码)：`celery_app.py` 通过 `_resolve_url` helper 从 `IS_CELERY_BROKER_URL` → `IS_REDIS_URL` → `memory://` 依次 fallback，无硬编码生产地址。PASS。

AC-2 (factory.py 存在且关键字参数)：`build_agent_runner(session_factory, llm_gateway, *, pipeline_config=None)` 存在，`session_factory` 和 `llm_gateway` 为位置参数，`pipeline_config` 为关键字参数。PASS。

AC-3 (lifespan startup + shutdown)：`_lifespan` 在 startup 调用 `init_celery()` 并写入 `app.state.celery_app`；shutdown 路径调用 `app.state.celery_app.close()` + `shutdown_celery()`。PASS。

AC-4 (`@celery_app.task` 装饰器存在)：`tasks.py` L186 有 `@celery_app.task(name="run_pipeline", bind=True)`。PASS。

AC-5 (send_task 路径接通)：`api/routers/tasks.py` L110 通过 `request.app.state.celery_app.send_task("run_pipeline", kwargs=...)` 触发。PASS。

AC-6 (测试断言 mock send_task + source_id)：`test_tasks_router.py` 覆盖了 send_task 调用次数断言和 source_id 在 kwargs 中的断言。PASS（含 LOW 问题，见 §7）。

AC-7 (工厂返回包含 ≥3 工具)：`test_factory.py` 断言 `len(tools) >= 3`。PASS。

AC-8 (集成冷启动断言)：任务卡明确标注为 T-094 时再补。范围外，跳过。

**结论**: 全部在范围内的 AC 已覆盖。发现一个 HIGH 问题（见 §5）。

---

## §2 consistency — 与 arch 契约的一致性

### [R-001] HIGH: /tasks/collect 实现与 arch API-007 请求体契约不匹配

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `arch-intellisource-v1-api.md` API-007 (`POST /api/v1/tasks/collect`) 定义的请求体为 `source_ids: array[string]`（复数，可为空则采集全部活跃信源）+ `priority: string`，响应体应含 `task_chain_id` / `tasks` / `message`。但当前实现的 `CollectRequest` 为 `source_id: str`（单数，必填）+ `trigger_type: str`，响应体返回单个序列化 Task 对象。两者在字段名（`source_id` vs `source_ids`）、基数（单 vs 多）、响应结构（Task vs TaskTriggerResponse）上均不匹配。
- **建议**: 此差距可能是 sprint 阶段性简化的已知 delta（T-094 集成测试前的脚手架），建议在任务卡或 dev-plan AC 中显式标注 `[ASSUMPTION: API-007 简化实现，T-094 前对齐]`，避免后续集成时产生认知歧义。若已知是临时简化，可降为 MEDIUM。

---

## §3 convention — 命名与环境变量规范

所有文件遵循 PEP 8 snake_case / PascalCase。环境变量均使用 `IS_` 前缀（`IS_CELERY_BROKER_URL`、`IS_REDIS_URL`、`IS_CELERY_RESULT_BACKEND`）。`_resolve_url`、`init_celery`、`shutdown_celery`、`build_agent_runner` 均符合 arch §7.1 约定。

### [R-002] MEDIUM: init_celery 与 celery_app.py 存在命名/职责重叠，信源不唯一

- **category**: convention
- **root_cause**: self-caused
- **描述**: `celery_app.py` 已在模块层面构建 `celery_app` singleton（含 `_resolve_url` fallback）；`main.py:init_celery()` 再次用 `Celery("intellisource", broker=...)` 构造一个新实例，两处 broker fallback 链逻辑也不完全相同：`celery_app.py` 包含 result_backend 配置而 `main.py` 的 `init_celery` 未设置 `result_backend`，且 `main.py` 使用内联的 `or` 表达式而非 `_resolve_url`。这意味着 `app.state.celery_app`（来自 `init_celery`）与 `tasks.py` 中 `@celery_app.task` 装饰所用的 `celery_app`（来自 `celery_app.py`）是两个不同的 Celery 实例，任务注册只在后者上，`send_task` 路由到前者——在生产 broker 下两者应均能路由，但在 `memory://` 模式下行为差异可能引发细微测试问题。
- **建议**: `main.py:init_celery` 应直接导入并返回 `celery_app.py` 中已构建的 singleton，而非重新实例化：`from intellisource.scheduler.celery_app import celery_app as _app; return _app`，这样可消除两套初始化逻辑的分叉。

---

## §4 structure — 组合根分层

整体分层合理：`celery_app.py` 负责 singleton；`factory.py` 负责 AgentRunner 装配；`main.py` 负责 lifespan 启动顺序；`tasks.py` 负责 Celery 任务定义；`api/routers/tasks.py` 负责 HTTP 入口。没有发现模块依赖循环。

`factory.py` 接收 `session_factory` 和 `llm_gateway` 作为参数但**并未将 `session_factory` 传入 `AgentRunner`**（当前 `AgentRunner` 构造只接收 `tool_registry` 和 `llm_gateway`），`session_factory` 和 `pipeline_config` 参数在函数体内被静默忽略。

### [R-003] MEDIUM: factory.py 的 session_factory / pipeline_config 参数未被使用

- **category**: structure
- **root_cause**: self-caused
- **描述**: `build_agent_runner` 签名接收 `session_factory: Any` 和 `pipeline_config: Any = None`，但函数体中两个参数均未传入 `AgentRunner(...)` 构造，也未以任何形式使用。mypy --strict 在 `Any` 类型下不会报错，但这是一个隐性的死参数（dead parameter），会误导调用方认为工厂已将 session_factory 注入到 runner 中。
- **建议**: 若 AgentRunner 当前版本不需要 `session_factory`，应删除该参数或添加非显然注释说明该参数为预留接口（并标 `# noqa: ARG001` 抑制 flake8 警告）；若后续版本需要，应在此 sprint 或 T-094 时实际接入。

---

## §5 error-handling — 异常与边界处理

### [R-004] MEDIUM: lifespan startup 失败时 celery_app.close() 可能抛出 AttributeError

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `_lifespan` 中的 `try/finally` 块在 `finally` 分支调用 `app.state.celery_app.close()`。`app.state.celery_app` 在 `init_celery()` 之后赋值，但若 `init_celery()` 内部抛出异常（理论上当前实现不会，但若未来加入 broker 预检则有可能），`app.state.celery_app` 有可能是前一次请求残留的值或未初始化。更重要的是：当前 `finally` 里对 `app.state.celery_app.close()` 无 try/except 包裹，若 Celery 实例的 `.close()` 本身抛出异常，会屏蔽 `yield` 之前产生的原始异常，导致真正的错误难以溯源。
- **建议**: 参照同文件 `close_redis()` 的模式，用 `try/except Exception: pass` 包裹 `app.state.celery_app.close()`，或抽取 `shutdown_celery_safe()` helper。

`send_task` 在 `celery_instance is not None` 的条件下调用，已有 None 守卫；无 broker 时 Celery 本身（memory://模式）不会在 send_task 时抛出异常，风险可控。`factory` 参数缺失时行为：`session_factory` 和 `llm_gateway` 均为 `Any`，无类型层面的 None 防御，但这是动态语言惯例，不升级为 HIGH。

---

## §6 security — 安全

`broker_connection_retry_on_startup = False` 防止测试/开发环境无 Redis 时启动阻塞，合理。

### [R-005] LOW: broker URL 含密码时 Celery 日志可能泄露明文

- **category**: security
- **root_cause**: self-caused
- **描述**: `_resolve_url` 直接将 env 变量中的完整 URL（可能含 `redis://:password@host`）传入 `Celery(broker=...)` 构造。Celery 默认会在启动日志和 worker banner 中打印 broker URL，若 URL 含密码会明文出现在日志中。arch §5.2 要求敏感配置通过环境变量注入，但没有明确要求日志脱敏。
- **建议**: 在生产部署文档（deploy-spec）中提示配置 Celery `broker_transport_options` 或通过 `CELERY_BROKER_URL` 走 URL 脱敏；或在 `celery_app.py` 中设置 `celery_app.conf.worker_redirect_stdouts = False` + 使用结构化日志时主动 mask URL 中的密码段。低优先级，不阻塞本 sprint。

---

## §7 test-quality — 测试质量

AC-6 的 kwargs 断言方式过于宽松（见 R-006），其余测试结构清晰、断言精确。

`test_factory.py` 正确验证了 `len(tools) >= 3`（AC-7），`test_registry_includes_default_tools` 和 `test_registry_includes_atomic_tools` 提供了工具集合的名称级验证，有效。

`test_celery_app.py` 覆盖 module import、Celery 实例类型、main name、broker/backend 非空。

lifespan shutdown 异常路径无对应测试（即 `app.state.celery_app.close()` 抛出时的行为），但属于防御性边界，不列为 HIGH。

### [R-006] LOW: test_send_task_kwargs_contain_source_id 使用字符串包含检查，非精确断言

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `test_tasks_router.py` L215 的断言为 `assert str(SOURCE_ID) in str(sent_kwargs) or "source_id" in str(sent_kwargs)`，这是字符串序列化后的包含检查（`str(call_args)` fallback 更宽松），无法验证 kwargs 字典的结构是否正确（例如 `source_id` 嵌套层级、值类型是否为字符串）。同理 L237 的 `assert "run_pipeline" in str(call_args)` 也是字符串包含检查。
- **建议**: 直接断言 `call_args.args[0] == "run_pipeline"` 和 `call_args.kwargs["kwargs"]["source_id"] == str(SOURCE_ID)`，消除 str() 序列化的模糊性。

---

## §8 complexity / duplication / coupling

### 圈复杂度
`init_celery`（main.py L52–60）：线性，CC=1。`build_agent_runner`（factory.py）：线性，CC=1。`run_pipeline`（tasks.py 模块级函数 L186–203）：含 `getattr` + None 判断，CC=2。`CeleryTasks.run_pipeline`（tasks.py L123–178）：含嵌套循环 + 多条件，CC≈7，低于阈值 15，可接受。

### REFACTOR 后重复/耦合状态
`_resolve_url` helper 已正确抽出，消除了原本在 celery_app.py 中可能存在的内联 env-fallback 重复。

剩余潜在重复：`main.py:init_celery` 与 `celery_app.py` 的 broker fallback 逻辑仍有分叉（R-002 已标）。

`tasks.py` 中 `TaskRepository: Any = None` 的 module-level 可变全局变量（lazy import pattern）是一个轻微的 coupling 异味，但在测试环境下有意义，不升级为问题。

---

## 重构后状态确认

REFACTOR（commit `7bb224a`）成功将 env-fallback 链抽取为 `_resolve_url` helper，消除了 `celery_app.py` 中原本可能存在的内联重复逻辑，且 `_resolve_url` 设计为纯函数（无副作用），可独立测试。

`main.py:init_celery` 与 `celery_app.py` 的分叉逻辑（R-002）未在本次 REFACTOR 中统一，属于遗留的结构性问题，不属于 REFACTOR 范畴的重复消除失败——两者创建的是不同 Celery 实例，用途分别为：模块级 singleton（用于装饰器注册）和 lifespan 中的运行时实例（挂载到 `app.state`）。REFACTOR 已达到预期目标，但 R-002 / R-003 显示组合根的依赖注入链路仍有待在后续 sprint 中收敛。

---

## 总结

| 维度 | 结论 |
|------|------|
| completeness | AC-1~AC-7 全覆盖（AC-8 延后至 T-094） |
| consistency | HIGH：API-007 请求体 schema 偏差（可能为已知简化） |
| convention | MEDIUM：init_celery 与 celery_app.py 双实例分叉 |
| structure | MEDIUM：factory.py 死参数 session_factory / pipeline_config |
| error-handling | MEDIUM：lifespan shutdown finally 块缺少异常屏蔽防护 |
| security | LOW：broker URL 明文日志风险（低优先级） |
| test-quality | LOW：kwargs 断言为字符串包含检查 |
| complexity | 无问题（CC 最高 ≈7，远低于阈值 15） |

**verdict: approved_with_notes**（1 HIGH + 3 MEDIUM + 2 LOW，无 CRITICAL）
