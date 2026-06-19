---
id: "code-review-B-071-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["B-071"]
---

# CODE-REVIEW B-071 — arch [chat] 配置收敛 (r1)

Layer 1 delegated to hook（项目已配置 lint hook；提交前已过 ruff format/check + mypy --strict 268 files Success + 全量 unit 3703 passed/5 deselected）

---

## 审查维度概览

| 维度 | 结论 |
|------|------|
| 完整性（迁移遗漏）| 通过 |
| 分层（compaction.py 不 import Settings）| 通过 |
| 正确性（`_persist_chat_turn` budget 必填）| 通过，有一处低优先级备注 |
| 退役 2000 诚实性 | 通过 |
| test-quality | 通过，有两处低优先级改善点 |
| doc↔code 一致性 | 通过 |
| security / error-handling / dead-code / duplication | 无新增问题 |

---

## 问题列表

### [R-001] LOW: `test_cleanup_body_purges_expired_when_wired` 内重复 `cache_clear()`
- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `autouse` fixture `_clear_settings_cache` 已在每个测试前后各调用一次 `get_settings.cache_clear()`，但 `test_cleanup_body_purges_expired_when_wired` 在 `monkeypatch.delenv` 之后又手动调用了一次 `get_settings.cache_clear()`（第 76 行）。`monkeypatch.delenv` 本身不改 `lru_cache`，额外的 `cache_clear()` 是冗余调用，不会误报但会引发读者对"是否需要双清"的疑问。
- **建议**: 删除测试体内第二次 `get_settings.cache_clear()` 调用（第 76 行），依赖 `autouse` fixture 的前置清理即可。`test_chat_budget_reads_env` 等同类测试也有相同冗余（`test_b071_chat_config.py` 第 28、33、41、47、53 行）。

### [R-002] LOW: `_run_cleanup_capturing_before` 命名不符合 pytest helper 惯例
- **category**: convention
- **root_cause**: self-caused
- **描述**: `_run_cleanup_capturing_before` 是一个辅助函数，不是测试函数，但没有返回值类型注解中的 `before` 字段在类型签名层面不可见（返回 `dict[str, Any]`，调用方需依赖注释而非类型约束）。此外，函数名以 `_run_` 开头，与"setup helper"语义轻微错配——它既执行副作用又返回断言所需数据。这不影响正确性，但使测试意图略显模糊。
- **建议**: 可考虑将捕获的内容改为具名 `NamedTuple` 或 `dataclass`，或将函数改名为 `_run_cleanup_and_capture`，让"capture"意图显式。低优先级，不阻塞。

---

## 审查要点核对结果

### 1. 完整性：迁移遗漏扫描

全仓 `src/` + `tests/` 中不存在以符号形式引用 `CHAT_COMPACT_TOKEN_BUDGET` 或 `CHAT_SESSION_TTL_DAYS` 的文件（已排除 `__pycache__` 和 `IS_CHAT_*` 环境变量字符串字面量）。

`chat_sessions.py` 的所有调用路径：
- `persist_turn`（第 117 行）：`budget = max_tokens_budget or _compact_token_budget()` ✓
- `compact_history`（第 220 行）：`budget = max_tokens_budget or _compact_token_budget()` ✓
- `_bounded_history`（内部）：接收显式 `budget` 参数 ✓

`webhooks.py` 第 102 行：`_bounded_history(appended, gateway, _compact_token_budget())` 在函数体内调用，非模块级求值 ✓

`tasks.py` `_cleanup_chat_sessions_body`：`ttl_days = get_settings().chat_session_ttl_days` 在 async `_do` 闭包内，每次运行时读取最新值 ✓

外部 caller（`agent.py`、`search.py`）均通过 `max_tokens_budget` 参数显式传入（`int | None`），`None` 时回落到 `_compact_token_budget()` ✓

### 2. 分层：compaction.py 保持纯库

`compaction.py` 仅导入 `ModelProfile`、`PromptBuilder`、`get_logger`，未导入 `Settings` 或 `get_settings`。`_DEFAULT_CONTEXT_TOKEN_BUDGET=2000` 仅在以下场景作为 fallback 出现：
- `needs_compaction` 默认参数（agent 调用方每次显式传 `context_token_budget`）
- `compact_messages` 默认参数（agent 调用方每次显式传）
- `compact_agent_messages` 默认参数（同上）
- `compact_messages_for_chat` 的 `max_tokens` 默认参数（chat 调用方每次显式传 `max_tokens=budget`）

所有 chat 调用路径均显式传 budget，2000 在生产路径中实际上是死代码（纯 fallback）。分层边界完整 ✓

### 3. 正确性：`_persist_chat_turn` budget 必填

`_persist_chat_turn` 签名改为 `budget: int`（keyword-only，无默认值），唯一调用点为 `persist_turn` 第 120-128 行，调用时 `budget=budget` 显式传入，该 `budget` 在调用前已由 `max_tokens_budget or _compact_token_budget()` 保证非 None ✓

全仓无其他代码直接调用 `_persist_chat_turn`（已确认：search.py 的 `_persist_chat_turn_tx` 是完全独立的函数）✓

### 4. 退役 2000 诚实性

`compaction.py` 第 22-24 行注释明确说明：`_DEFAULT_CONTEXT_TOKEN_BUDGET` 是纯库内 fallback，chat 调用方从 `IS_CHAT_COMPACT_TOKEN_BUDGET` 读取，agent 循环传上下文窗口派生的触发值。注释不宣称它是 arch §5.1 的配置预算 ✓

两处 docstring 变更（`needs_compaction` 第 61 行、`compact_messages` 第 166 行）均将 "System-level budget from config.chat (arch §5.1, default 2000)" 改为 "Compaction budget supplied by the caller" ✓

arch 文档中旧表（含 `context_token_budget=2000`、`compress_after_turns`、`compress_model`、`session_timeout_hours`）已完全替换为新表。全仓 arch docs 无 2000 残留 ✓

### 5. test-quality

**`test_b071_chat_config.py`（新建）**：
- `test_chat_budget_default_is_6000`：断言 `get_settings().chat_compact_token_budget == 6000`，直接断言字段值 ✓
- `test_chat_budget_reads_env`：env=12345 → Settings 字段=12345，强断言 ✓
- `test_compact_token_budget_helper_resolves_from_settings`：env=777 → `_compact_token_budget() == 777`，验证 helper 真实消费 Settings ✓
- `test_session_ttl_default_is_30` / `test_session_ttl_reads_env`：结构对称，断言强度一致 ✓
- `get_settings.cache_clear()` 隔离：autouse fixture 前后双清 + 部分测试体内额外清（见 R-001）

**`test_cleanup_chat_sessions.py`（改）**：
- `test_cleanup_cutoff_reads_settings_ttl`：env=1 → `captured["before"]` 约为 `now - 1天`，3600 秒容差（≈1小时）足够宽松不造成 flakiness ✓
- `_Repo.cleanup_expired` 捕获 `before` 参数，断言真实消费了 TTL 值，非空断言 ✓
- `_run_cleanup_capturing_before` 返回 `dict[str, Any]`，`captured["before"]` 的存在依赖 `_Repo.cleanup_expired` 必然被调用——若调度链路断裂则 `KeyError`，形成隐式护栏 ✓

**边界覆盖**：未覆盖非正整数（如 `IS_CHAT_SESSION_TTL_DAYS=0` 或负数），pydantic `int` 字段会接受 `0` 并在 `timedelta(days=0)` 时删除所有历史。此为 MEDIUM 级别改善（不是 B-071 的 AC，可在后续加入 `ge=1` validator）。

### [R-003] MEDIUM: Settings 字段缺少正值约束
- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `chat_compact_token_budget` 和 `chat_session_ttl_days` 均为 `int` 类型，接受 `0` 或负值。若运维错误设置 `IS_CHAT_SESSION_TTL_DAYS=0`，`timedelta(days=0)` 会将截止时间设为当前时间，导致所有历史会话被 beat 任务一次性删除（包括活跃会话，若 `last_active_at` 未来秒级刷新则幸免，但语义错误）。同样，`IS_CHAT_COMPACT_TOKEN_BUDGET=0` 会使 `_bounded_history` 每次触发全量压缩，无论消息多短。这与 B-071 的决策范围相关，属于新引入 Settings 字段的防御性缺失。
- **建议**: 为两个字段加 pydantic `ge=1` 约束：`Field(6000, validation_alias="IS_CHAT_COMPACT_TOKEN_BUDGET", ge=1)` 和 `Field(30, validation_alias="IS_CHAT_SESSION_TTL_DAYS", ge=1)`。配套补测 `test_chat_budget_rejects_zero` / `test_ttl_rejects_zero`（预期 `ValidationError`）。

### 6. doc↔code 一致性

| 对账项 | arch §5.1 | `.env.example` | 实现 | 结论 |
|--------|----------|----------------|------|------|
| `IS_CHAT_COMPACT_TOKEN_BUDGET` 默认值 | 6000 | 6000 | `Field(6000, ...)` | ✓ |
| `IS_CHAT_SESSION_TTL_DAYS` 默认值 | 30 | 30 | `Field(30, ...)` | ✓ |
| `MAX_HISTORY_TURNS` 注记 | "固定为 10（内部行为常量，非环境可调）" | 无（正确，不需在 .env 暴露）| `MAX_HISTORY_TURNS: int = 10` 常量 | ✓ |
| 压缩方式描述 | "token-aware 摘要压缩为 [summary, ...recent]" | "token-aware summarised into [summary, ...recent]" | `compact_messages_for_chat` 返回 `[summary_msg, *recent]` | ✓ |
| 幽灵参数清除 | `compress_after_turns`/`compress_model` 已删 | 无 | 无对应实现 | ✓ |
| `data.md` 清理策略 | `IS_CHAT_SESSION_TTL_DAYS`（默认 30 天） | — | `timedelta(days=ttl_days)` | ✓ |

### 7. security / error-handling / dead-code / duplication

- `_compact_token_budget()` 是一个无参 getter，无注入面 ✓
- `get_settings()` 内的 `lru_cache` 已在测试中正确通过 `cache_clear()` 绕开，无跨测试污染风险 ✓
- `CHAT_COMPACT_TOKEN_BUDGET` / `CHAT_SESSION_TTL_DAYS` 旧常量已从 `tasks.py` 和 `chat_sessions.py` 删除，无死常量残留 ✓
- 无新增重复逻辑（`_compact_token_budget()` 是 Settings 访问的单一入口，不重复） ✓

---

## Verdict

**approved_with_notes**

无 CRITICAL / HIGH 问题。存在：
- R-001（LOW）：测试体内冗余 `cache_clear()` 调用
- R-002（LOW）：辅助函数命名惯例
- R-003（MEDIUM）：Settings 字段缺少 `ge=1` 正值约束（新引入字段的防御性缺失，建议后续加入，不阻塞合并）
