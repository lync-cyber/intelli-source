---
id: "code-review-T-091-r2"
doc_type: code-review
author: reviewer
status: approved
deps: [T-091]
---

# CODE-REVIEW T-091 r2 — ConfigWatcher 热加载 + reload API 真实实现（修订后复检）

Layer 1 delegated to hook（`.claude/settings.json` 已配置 PostToolUse lint hook）

**修订 commit**: `a3caef25e1ca791d8654c01c0d5268da7b3756f4`  
**测试结果**: 111 passed / 0 failed（config/ + api/test_sources_reload.py）；全量 2112 passed / 0 failed

---

## §0 r1 复检

| 编号 | 严重等级 | 标题 | 复检结论 | 说明 |
|------|---------|------|---------|------|
| R-001 | HIGH | ConfigValidator.validate() 空实现 | **RESOLVED** | validate() 现在强制检查 name 非空/长度/路径穿越字符、type 白名单、URL http(s) scheme；ConfigValidationError 类存在且可导入 |
| R-002 | MEDIUM | load_source_configs() 空 stub | **RESOLVED** | 实现扫描 `IS_SOURCE_CONFIG_DIR` 下 `*.yaml`/`*.yml`，逐文件 load_file + 异常捕获继续；无 [ASSUMPTION] 残留 |
| R-003 | MEDIUM | load_file() 路径穿越防护缺失 | **RESOLVED** | `Path(file_path).resolve()` + `resolved.relative_to(allowed_dir)` 守卫；ConfigPathError 可导入；resolve() 正确跟随 symlink，symlink 穿越场景也被拦截 |
| R-004 | MEDIUM | 参数名 on_change 与 task 卡约定不一致 | **RESOLVED** | ConfigWatcher.__init__ 统一改为 `callback=`；main.py lifespan 及所有测试一致使用 `callback=`；双名检测已删除 |
| R-005 | MEDIUM | None session 导致热加载 DB 写入永远失败 | **RESOLVED** | on_config_change 通过 `_db_manager.get_session()` async CM 获取真实 session；sources.py `reload_source_configs` 通过 `Depends(get_db_session)` 注入 session；SourceRepository(None) 消除 |
| R-006 | LOW | watcher_task 返回值被丢弃 | **RESOLVED** | `app.state.config_watcher_task = asyncio.create_task(watcher.start())` 存储 |
| R-008 | LOW | `or True` 死断言 | **RESOLVED** | 移除 `or True`；tightened 为 `len(tasks_created) == 1` 且 `watcher.start.called` |

---

## §1 安全审查（security_sensitive=true — 必审维度）

| 维度 | 结论 | 说明 |
|------|------|------|
| yaml.safe_load only | PASS | grep 空返回；validator.py:114 `yaml.safe_load`，无不安全变体 |
| ConfigValidator.validate() 门控 | PASS | 名称非空/长度≤100/禁止 `..`/`/`/`\`、type 白名单、URL http(s) scheme 均实施；ConfigValidationError 抛出后在 reload 和 on_config_change 的 except Exception 中捕获并记录 |
| load_file() 路径穿越守卫 | PASS（附注） | `Path.resolve()` + `relative_to()` 正确拦截 `../` 和 symlink 穿越。**附注**: 当 `IS_SOURCE_CONFIG_DIR` 未设置时 `_config_dir = None`，`load_file()` 跳过路径守卫（可接受：此时 `load_source_configs()` 也早返回空列表，实际上不会扫描任何文件；`on_config_change` 从 watchfiles 收到的路径限定在被监视目录内，不存在外部注入风险）|
| _db_manager None-guard | PASS | `if _db_manager is None: log + return`，防止 lifespan 启动前被意外调用时 AttributeError |

---

## §2 净增问题（net-new findings）

### [R-001] MEDIUM: ConfigValidator._ALLOWED_SOURCE_TYPES 包含 SourceConfig.type Literal 中不存在的类型

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `_ALLOWED_SOURCE_TYPES = {"rss", "atom", "html", "api", "web"}`，而 `SourceConfig.type` 的 Pydantic Literal 约束为 `Literal["rss", "api", "web"]`（3 种）。任何进入 `validate(config: SourceConfig)` 的对象已被 Pydantic 限制为这三种类型；`"atom"` 与 `"html"` 的白名单条目永远不会触发，属于维护陷阱——若后续将 Literal 扩展到 `atom`/`html`，validate() 的白名单不会拦截；反之若 validate() 白名单收紧，也不影响 Pydantic 层的实际约束。两层防线定义不同步将在扩展类型时产生静默漏洞。
- **建议**: 将 `_ALLOWED_SOURCE_TYPES` 与 `SourceConfig.type` 的 Literal 保持同步（3 种或同步扩展），或将白名单的 source-of-truth 统一到 SourceConfig 模型（通过 `get_args(SourceConfig.model_fields["type"].annotation)` 动态读取），避免双重维护。

### [R-002] LOW: ConfigValidator.validate() 的新规则没有专项单元测试

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: r2 在 validator.py 中新增了 5 条语义检查规则（name 非空、name 长度 ≤ 100、name 不含 `..`/`/`/`\`、type 白名单、url http(s) scheme）以及新异常类 `ConfigValidationError`。现有 `test_validator.py` 的 `TestValidateSource` 类仅测试 `validate_source()`（Pydantic 层），未添加任何针对 `validate()` 新规则的用例。边界行为（例如：name 恰好 100 字符通过、101 字符失败；name 含 `..` 失败；url 前导空格失败；type `atom` 失败）均未经测试。
- **建议**: 在 `test_validator.py` 中增加 `TestConfigValidatorValidate` 测试类，覆盖：name 空字符串、name 101 字符、name 含 `../`、name 含 `\`、type `unknown` 失败、type `atom` 失败（在当前 SourceConfig Literal 约束下无法直达 — 可 mock `config.type`）、url `ftp://` 失败、url 前导空格失败、以及所有规则通过的 happy path。这些规则是 security gate 的核心逻辑，缺乏专项测试降低了安全保障可信度。

### [R-003] LOW: load_source_configs / load_file 路径守卫没有专项测试

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `load_file()` 新增的路径穿越守卫（`ConfigPathError` + `relative_to` 检查）以及 `load_source_configs()` 的目录扫描逻辑（包括 `_config_dir is None` 早返回、目录不存在早返回、多文件扫描）均未在 `test_loader.py` 中添加专项测试。`TestConfigLoaderLoadFile` 类中没有任何用例设置 `IS_SOURCE_CONFIG_DIR` 来激活守卫，路径穿越拦截行为在 CI 中完全无验证。
- **建议**: 在 `test_loader.py` 中增加：①设置 `IS_SOURCE_CONFIG_DIR` 的前提下，`load_file(str(tmp_path / "../outside.yaml"))` 抛出 `ConfigPathError`；②合法路径通过；③`load_source_configs()` 在空目录返回 `[]`；④`load_source_configs()` 扫描含两个 YAML 的目录返回正确数量。

---

## §3 AC 覆盖复检小结

| AC | 状态 | 说明 |
|----|------|------|
| AC-1 | 通过 | lifespan 正确实例化 ConfigWatcher(callback=)、存储 watcher_task、停止 |
| AC-2 | 通过 | on_config_change 调用 load_file → validate → upsert，测试验证顺序及 _db_manager 注入 |
| AC-3 | 通过 | reload_source_configs 调用真实 load_source_configs，loaded_count 反映实际数量 |
| AC-4 | 通过 | validate 失败捕获入 errors，继续处理剩余 |
| AC-5 | 通过 | bulk_upsert 调用一次，传入 validated list |
| AC-6 | 通过 | app.state.config_watcher 非 None |
| AC-7 | 通过 | 仅 yaml.safe_load，无不安全变体 |

---

## 最终判定

**verdict: approved_with_notes**

r1 所有 HIGH（R-001）及 MEDIUM（R-002、R-003、R-004、R-005）均已完整修复；LOW（R-006、R-008）已修复。净增 3 个问题：1 MEDIUM（R-001 _ALLOWED_SOURCE_TYPES 与 SourceConfig.type 两层定义不同步，可能在类型扩展时形成安全盲区）+ 2 LOW（R-002、R-003 新规则缺乏专项单元测试）。无 CRITICAL / HIGH，代码可继续推进。建议后续任务补齐 validate() 和路径守卫的专项测试用例。
