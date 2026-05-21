---
id: "code-review-T-091-r1"
doc_type: code-review
author: reviewer
status: approved
deps: [T-091]
---

# CODE-REVIEW T-091 r1 — ConfigWatcher 热加载 + reload API 真实实现

Layer 1 delegated to hook（`.claude/settings.json` 已配置 PostToolUse lint hook，编码阶段已实时修复 ruff 格式/lint 问题）

**HEAD commit**: `e91d4442a8f3b899eaf61e10f6eaeee70ae2c9c5`
**测试结果**: 24 PASSED / 0 FAILED（`tests/unit/config/test_config_watcher_wiring.py` 13 项 + `tests/unit/api/test_sources_reload.py` 11 项）

---

## §1 安全审查（security_sensitive=true — 必审维度）

| 维度 | 结果 | 说明 |
|------|------|------|
| AC-7 yaml.safe_load 执行 | PASS | `grep -rnE 'yaml\.(load\|full_load\|unsafe_load)\(' src/intellisource/config/` 返回空；`validator.py:74` 使用 `yaml.safe_load()`，`resolver.py:61` 使用 `yaml.safe_load()`，无不安全变体 |
| ConfigValidator 门控 DB 写入 | PARTIAL PASS — 有流程门控但门控为空操作，详见 R-001 | `reload_source_configs` 在 `bulk_upsert` 前调用 `validator.validate()`；`on_config_change` 在 `repo.upsert` 前调用 `validator.validate()`。调用顺序正确，但 `validate()` 本身是直接返回入参的 pass-through 实现，未做任何验证逻辑——门控存在但无效 |
| Watcher 优雅停止 | PARTIAL PASS — 内部任务正确停止，外部包装任务未追踪，详见 R-002 | `watcher.stop()` 取消并 `await self._task`（内部 `_watch` 任务），`CancelledError` 正确被捕获。但 `_lifespan` 中 `asyncio.create_task(watcher.start())` 的返回 Task 未被存储或 awaited，若 `start()` 内部抛出异常将静默丢失 |

---

## §2 完整性（completeness）

### [R-001] HIGH: ConfigValidator.validate() 是空实现，安全门控无效

- **category**: security
- **root_cause**: self-caused
- **描述**: `validator.py` 中新增的 `validate(config: SourceConfig) -> SourceConfig` 方法仅 `return config`，不执行任何校验逻辑。`reload_source_configs` 和 `on_config_change` 均将其作为写入 DB 前的安全门控调用，但门控实际无效——任何格式非法、字段缺失、URL 注入的 `SourceConfig` 均可直接写入数据库。arch#§5.2 明确要求"所有用户输入经 Pydantic 模型校验后方可进入业务逻辑层"；task 卡 AC-4 的验收条件"`ConfigValidator.validate()` 校验失败时，将错误计入 `errors`"在 pass-through 实现下永远不会触发。
- **建议**: `validate()` 应至少调用 `validate_source()` 或重用 Pydantic schema 对 `SourceConfig` 字段进行再校验（如 URL 格式、name 白名单、必填字段存在性）。若此实现为占位符等待 T-094 补全，必须添加 `# [ASSUMPTION]` 注释注明延迟原因与依赖任务，否则当前代码在生产路径上构成安全缺口。

### [R-002] MEDIUM: load_source_configs() 是空 stub，reload API 在生产环境永远返回 loaded_count=0

- **category**: completeness
- **root_cause**: self-caused
- **描述**: `ConfigLoader.load_source_configs()` 直接 `return []`，没有任何文件扫描逻辑。这意味着 `/api/v1/sources/reload` 端点的核心功能（从磁盘加载配置、同步到 DB）在生产环境完全不工作。commit message 标注"stub, real schema lookup deferred to T-094"，但代码中没有 `[ASSUMPTION]` 注释，违反 COMMON-RULES §全局约定（"标注 `[ASSUMPTION]` 给出合理默认值，确保可追溯"）。
- **建议**: 在 `load_source_configs()` 方法体内添加 `# [ASSUMPTION] 完整目录扫描实现延迟到 T-094 (integration)` 注释。若 T-091 范围已包含真实扫描实现（任务卡 AC-3 描述"真实调用 ConfigLoader.load_source_configs()"），则需实现目录遍历逻辑而非留空 stub。

### [R-003] MEDIUM: config_name 参数被接受但完全忽略，arch§5.2 路径遍历白名单防护缺失

- **category**: security
- **root_cause**: self-caused
- **描述**: `reload_source_configs(*, config_name: str | None = None)` 接受 `config_name` 参数，但实现中从未使用该参数。arch API-005 明确要求"仅接受文件名（不含路径），限白名单内文件名，为空则加载默认配置"；arch#§5.2 要求"API-005 重载配置接口仅接受文件名（不含路径），从预定义配置目录加载，白名单由 M-001 配置管理模块维护"。当前实现无论传入任何 `config_name`（含路径遍历字符 `../../../etc/passwd`）均被忽略，不返回 400，但也没有被使用——若 `load_source_configs` 未来实现时接受 `config_name` 参数，若此时无白名单校验将产生路径遍历漏洞。
- **建议**: 若本任务不实现 `config_name` 过滤（因 `load_source_configs` 为 stub），应在参数上添加注释说明白名单校验延迟到完整实现，并在当前实现中若 `config_name` 非 None 返回 400 或忽略（明确文档化）。完整实现时必须验证文件名不含路径分隔符，仅允许白名单内名称。

---

## §3 一致性（consistency）

### [R-004] MEDIUM: ConfigWatcher 构造参数 `on_change` 与 task 卡约定 `callback` 不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: task 卡 AC-1 明确描述 `ConfigWatcher(config_dir=settings.SOURCE_CONFIG_DIR, callback=on_config_change)`，但实现中构造函数参数名为 `on_change`，`_lifespan` 调用处为 `ConfigWatcher(config_dir=..., on_change=on_config_change)`。虽然 impl + tests + call site 三处一致（都用 `on_change`），参数名与 task 卡约定不一致会造成可追溯性问题，且测试 `test_startup_passes_callback_to_config_watcher` 同时检测 `on_change` 和 `callback`（第 102 行），掩盖了该差异。
- **建议**: 将参数名统一为 `callback` 以与 task 卡 AC-1 / AC-2 的约定对齐；或在 task 卡中更新约定。当前的双重检测方式（`kwargs.get("on_change") or kwargs.get("callback")`）降低了测试对参数名的约束效力。

---

## §4 错误处理（error-handling）

### [R-005] MEDIUM: on_config_change 使用 cast(AsyncSession, None) 实例化 SourceRepository，运行时必然导致 AttributeError

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `on_config_change` 中 `repo = SourceRepository(cast(AsyncSession, None))` 以 `None` 作为 session 构造 repository。任何调用 `await repo.upsert(validated)` 的路径都会在 `self._session.execute(...)` 处抛出 `AttributeError: 'NoneType' object has no attribute 'execute'`。该异常会被外层 `except Exception` 捕获并记录，不会直接崩溃，但意味着 ConfigWatcher 热加载路径的 DB 写入在所有情况下都会静默失败。`sources.py` 的 `SourceRepository(None)` 同理。这是与生产 DB session 注入机制的设计缺口，而非仅测试环境问题。
- **建议**: 若热加载路径需要 DB session，应通过 FastAPI 的 `app.state.db` 获取 session（类似其他路由通过 `Depends(get_db_session)`）或在 `on_config_change` 中通过 `DatabaseManager` 创建 session 上下文。若此为 T-094 前的占位（mock-friendly 设计），应添加 `[ASSUMPTION]` 注释并在 `upsert()` / `bulk_upsert()` 函数体头部添加 early-return 保护（`if self._session is None: return`）防止日志噪音。

### [R-006] LOW: 外部 asyncio.create_task(watcher.start()) 返回值被丢弃，启动异常静默丢失

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `_lifespan` 中 `asyncio.create_task(watcher.start())` 的返回 Task 未被存储。`watcher.start()` 的工作仅是创建内部 `_watch` task 并 `sleep(0.1)`，通常不会抛出异常；但若抛出（如 event loop 被关闭），该异常将以 `Task exception was never retrieved` 记录到 asyncio 日志，不会向 lifespan 传播。`watcher.stop()` 也不等待或取消该外部包装 Task（该 Task 实际已完成，stop 逻辑仍正确）。
- **建议**: 将 `asyncio.create_task(watcher.start())` 返回的 Task 存储在 lifespan 局部变量中，shutdown 时检查是否完成（如 `_start_task = asyncio.create_task(watcher.start()); ...; _start_task.cancel()`），或直接将 `create_task` 内联到 `watcher.start()` 中（当前已在 `start()` 内部 `create_task(_watch)`），改 `_lifespan` 为直接 `await watcher.start()`（非 blocking，因 start 快速返回）。

---

## §5 代码结构（structure）

### [R-007] MEDIUM: upsert 逻辑在 source.py 和 loader.py 之间重复

- **category**: duplication
- **root_cause**: self-caused
- **描述**: `SourceRepository.upsert()` 中的字段赋值（`existing.type`, `existing.url`, `existing.tags` 等 8 个字段）与 `loader.py` 中的 `_update_source_from_config()` 函数完全重复；同样，`upsert()` 中的 Source 构造逻辑与 `_create_source_from_config()` 也重复。这是 Type-1 代码克隆，两处不同步时将产生静默 bug。
- **建议**: `SourceRepository.upsert()` 应调用 `loader.py` 中已有的 `_update_source_from_config()` / `_create_source_from_config()` 辅助函数，或将这两个辅助函数移到 `SourceRepository` 中供 `sync_to_db` 和 `upsert` 共用。

---

## §6 测试质量（test-quality）

### [R-008] LOW: test_startup_creates_background_task_for_watcher 包含死代码断言 `or True`

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `test_startup_creates_background_task_for_watcher` 第 144 行有 `assert len(tasks_created) >= 1 or True`，该断言因 `or True` 永远为真，完全无效，不验证任何内容。最终有效断言是第 151-158 行 `started` 变量的检查，但 `started = ... or len(tasks_created) >= 1` 包含了"list 非空即为 True"的分支，也使断言极为宽松（只要任何 asyncio.create_task 被调用就通过，与 watcher 无关）。
- **建议**: 移除 `or True` 后缀并删除第 144 行无效断言；将最终 `started` 断言收紧为明确检查 `watcher.start()` 被调用或 `create_task` 调用次数恰好为 1 且参数为 watcher coroutine。

---

## §7 整体 AC 覆盖小结

| AC | 覆盖状态 | 说明 |
|----|---------|------|
| AC-1 | 通过 | lifespan 正确实例化 ConfigWatcher、create_task(start)、stop() |
| AC-2 | 通过 | on_config_change 调用 load_file → validate → upsert，顺序有专项测试 |
| AC-3 | 部分通过 | reload_source_configs 调用路径正确，但 load_source_configs 为空 stub，真实 loaded_count 永远为 0 |
| AC-4 | 通过 | 验证失败捕获入 errors，继续处理剩余 |
| AC-5 | 通过 | bulk_upsert 调用一次，传入 validated list |
| AC-6 | 通过 | app.state.config_watcher 非 None |
| AC-7 | 通过 | 未发现 unsafe yaml.load 调用 |

---

## 最终判定

**verdict: needs_revision**

存在 1 HIGH（R-001: `validate()` 空实现导致安全门控无效，属 security 类问题，任务卡 security_sensitive=true）和 4 MEDIUM（R-002 stub 无 ASSUMPTION 标注、R-003 config_name 白名单缺失、R-004 参数名不一致、R-005 null session 导致热加载 DB 写入永远失败）。

需修订项（CRITICAL/HIGH）:
- R-001: `ConfigValidator.validate()` 必须添加实质校验逻辑或 `[ASSUMPTION]` 注释，否则安全门控形同虚设

建议同批修订（MEDIUM）:
- R-002: `load_source_configs` stub 添加 `[ASSUMPTION]` 注释
- R-005: `on_config_change` / `reload_source_configs` 中 None session 问题需要设计决策（保护性 early-return 或真实 session 注入）
