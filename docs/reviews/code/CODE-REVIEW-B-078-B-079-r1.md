---
id: "code-review-B-078-B-079-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["B-078", "B-079"]
---

# Code Review — B-078 / B-079 (r1)

**审查范围**: 分支 `claude/deploy-ux-b078-b079`，基线 `main`
**文件**:
- `src/intellisource/cli/commands/init.py` — 新增 `_resolve_api_key`，`init()` 内联块替换为单行调用
- `src/intellisource/cli/commands/doctor.py` — 新增 `_probe_api_auth`，`doctor()` `--check-api` 分支接入
- `tests/unit/cli/test_b078_init_key_idempotent.py`
- `tests/unit/cli/test_b079_doctor_auth_probe.py`

Layer 1: `ruff check` — passed；`ruff format --check` — 4 files already formatted；`mypy --strict` — no issues (2 source files + 2 test files)

---

## 问题列表

### [R-001] MEDIUM: `_resolve_api_key` 未过滤 `.env` 中的 API key 占位符，可导致占位符被静默复用

- **category**: security
- **root_cause**: self-caused
- **描述**: `docker/.env.example` 中 `IS_API_KEY=change-me-in-production`（即 `doctor.py` 的 `_API_KEY_PLACEHOLDER`）。若用户手动复制 `.env.example` 或先前 `init` 未完成写入，再次运行 `init` 时 `_load_dotenv_file` 会读到 `existing_key = "change-me-in-production"`，该字符串为 truthy，`_resolve_api_key` 会将其作为真实 key 返回并写入 `.env`——等价于把已知占位符当成合法 key 注入栈，导致 API 鉴权全面失效（与 B-078 修复目标相悖）。`doctor.py` 对同一占位符有显式过滤（line 283: `api_key != _API_KEY_PLACEHOLDER`），两处行为不一致。
- **建议**: `init.py` 中引入与 `doctor.py` 相同的 `_API_KEY_PLACEHOLDER = "change-me-in-production"` 常量（或从 `doctor` 模块导入），在 `_resolve_api_key` 中对 `existing_key` 做 `if not existing_key or existing_key == _API_KEY_PLACEHOLDER:` 过滤，跳过占位符进入生成路径。非交互路径的 `environ_key` 亦同理。

### [R-002] LOW: 交互路径未对 `user_input` 做 `.strip()`，纯空白字符串会被当作有效 API key 写入

- **category**: security
- **root_cause**: self-caused
- **描述**: `typer.prompt(...)` 返回值若用户输入若干空格，`if user_input:` 为 True（非空字符串），`"   "` 会作为 API key 写入 `.env`。后续 HTTP 请求以空白 key 鉴权，会静默失败且无明确提示。
- **建议**: 在 `user_input: str = typer.prompt(...)` 之后添加 `user_input = user_input.strip()`，确保纯空白输入落入空值分支。

### [R-003] LOW: 复用路径的安全属性（不回显 key 值）未被测试锁定

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `test_prints_reuse_message_when_blank` 断言 `captured.out` 包含 "IS_API_KEY" 和 "Reusing"/"沿用"，但**未断言 `_REAL_KEY` 不出现在输出中**。实现正确（`echo("Reusing existing IS_API_KEY from .env")` 不回显值），但若未来误改为 `f"Reusing {existing_key}"`，测试不会失败，无护栏。
- **建议**: 在该测试末尾增加 `assert _REAL_KEY not in captured.out` 以锁定不回显这一安全属性。

### [R-004] LOW: `_probe_api_auth` 的 `timeout` 参数传递未被任何测试验证

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `TestProbeApiAuth` 的所有用例 mock `httpx.get` 但未断言 `timeout` 参数被传入。若实现误删 `timeout=timeout`，`httpx.get` 将使用默认无超时，在网络不可达场景下 doctor 会挂起。
- **建议**: 在 `test_sends_x_api_key_header` 补充 `assert call_kwargs.get("timeout") == 3.0`，或新增 `test_passes_timeout_to_httpx` 用例。

---

## 验收条件覆盖验证

### B-078（6 条 AC）

| AC | 测试 | 结论 |
|----|------|------|
| AC1: interactive + blank + `.env` 有真实 key → reuse | `test_reuses_existing_env_key_when_blank` | 覆盖 |
| AC2: reuse 时打印含 "IS_API_KEY" + "Reusing" 的提示，不回显 key 值 | `test_prints_reuse_message_when_blank` | 正向覆盖；回显保护未锁定（见 R-003） |
| AC3: 无 `.env` 或无 IS_API_KEY → generate | `TestResolveApiKeyNewEnvironment` 三用例 | 覆盖 |
| AC4: interactive + 用户明确输入 → 使用用户输入 | `TestResolveApiKeyExplicitInput` 两用例 | 覆盖 |
| AC5: non_interactive + `.env` 有 key → reuse | `test_ac5_reuses_env_file_key_when_no_environ` | 覆盖 |
| AC6: non_interactive + `os.environ` 优先 | `test_ac6_os_environ_takes_priority_over_env_file` | 覆盖 |

### B-079（5 条 AC）

| AC | 测试 | 结论 |
|----|------|------|
| AC1: health ok + key ok → [OK] auth accepted | `test_ac1_auth_ok_reports_accepted` | 覆盖 |
| AC2: health ok + 401 → [FAIL] + error count + rebuild hint；--strict → exit 1 | `test_ac2_auth_unauthorized_*` 两用例 | 覆盖 |
| AC3: inconclusive → [--] soft note，不计 error | `test_ac3_inconclusive_shows_soft_note_no_error` | 覆盖 |
| AC4: health 非 ok（down/starting）→ 跳过 auth probe | `test_ac4_health_down/starting_skips_auth_probe` | 覆盖 |
| AC5: IS_API_KEY 空或占位符 → 跳过 auth probe | `test_ac5_no_api_key/placeholder_skips_auth_probe` | 覆盖 |

---

## Dead-code / 残留检查

无 RED 阶段脚手架残留（无 `try/except ImportError`、无 `_skip_if_missing`）；无工作票号脚注；无变更叙事注释；docstring 仅描述当前职责。

---

## 安全专项（B-078 security_sensitive=true）

| 检查点 | 实现 | 测试锁定 |
|--------|------|---------|
| reuse 路径不回显 key 值 | 正确（`echo("Reusing existing IS_API_KEY from .env")`） | 未锁定（R-003） |
| generate 路径打印新 key | 正确（`echo(f"Generated: {new_key}")`，首次安装需用户看到） | 已覆盖 |
| 占位符过滤 | 缺失（R-001 MEDIUM）；doctor.py 已有但 init.py 未同步 | — |
| os.environ 优先级 | 正确实现 | 已覆盖 |
| _probe_api_auth 不打印 key | 正确，header 构造时 key 不出现在任何 echo | 已覆盖（`test_sends_x_api_key_header` 验证 header 传入） |
| _probe_api_auth 异常捕获 | `except Exception` 宽泛捕获正确；`noqa: BLE001` 已标注 | `test_does_not_raise_on_exception` 覆盖 |

---

## verdict: approved_with_notes

无 CRITICAL / HIGH 问题。存在 1 条 MEDIUM（R-001：占位符未过滤可致鉴权静默失效）和 3 条 LOW（R-002/R-003/R-004）。

B-078 幂等复用逻辑与 B-079 鉴权探针分类（401 vs 5xx vs 网络异常）实现正确，AC 全覆盖（6+5），门禁全绿。

**建议下次迭代优先处理** R-001（MEDIUM）：在 `_resolve_api_key` 中对 `existing_key` 和非交互路径的 `environ_key` 增加占位符过滤，保持与 `doctor.py` 一致。

---

## 整改记录（同分支闭环）

四条发现全部在同分支整改并重过门禁：

- **R-001（MEDIUM）已修**：`_resolve_api_key` 内联 `_real(value)` helper，对 `.env` 现有值与非交互 `os.environ` 值统一过滤 `_API_KEY_PLACEHOLDER`（从 `doctor.py` 导入，单一来源），占位符视为缺失 → 不复用、改生成。
- **R-002（LOW）已修**：交互 `user_input` 加 `.strip()`，纯空白输入回落到优先链（复用/生成）。
- **R-003（LOW）已修**：`test_prints_reuse_message_when_blank` 补 `assert _REAL_KEY not in captured.out`，锁定 reuse 路径不回显 key。
- **R-004（LOW）已修**：新增 `test_passes_timeout_to_httpx` 验证 `_probe_api_auth` 向 `httpx.get` 传入 `timeout`。
- 新增回归：`TestResolveApiKeyPlaceholderRejected`（3 例：交互/非交互 .env 占位符 + environ 占位符）+ `TestResolveApiKeyWhitespaceInput`（1 例）。

门禁复核：ruff format/check + `mypy --strict src/`（268）+ 全量 unit（exit 0）全绿。B-079 鉴权探针对真实漂移栈端到端验证：`[FAIL] API auth 401 — key drift detected` 正确触发（旧 doctor 此场景报全绿）。

整改后 verdict 等价 **approved**。
