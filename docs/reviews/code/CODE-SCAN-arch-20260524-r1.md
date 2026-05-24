---
id: code-scan-arch-20260524-r1
doc_type: code-review
author: devops
status: draft
deps: [arch-intellisource-v1-modules, backlog-intellisource-v1]
---

# CODE-SCAN: 架构治理工具链首扫

> 范围：用 4 个工具对 `intellisource.*` 做架构契约 / 依赖卫生 / 死代码 / 依赖图四维度静态扫描，建立治理基线。
> 工具集（配置都在 [`pyproject.toml`](../../../pyproject.toml)）：
> - `import-linter==2.11` + `grimp==3.14` — 架构契约
> - `deptry>=0.20` — 依赖卫生
> - `vulture>=2.13` — 死代码
> - `pydeps>=3.0` — 依赖图可视化（需 Graphviz `dot`，仅 CI nightly 渲染）
> 一键入口：`make check`（Windows：直接 `uv run <tool>`）

## 0. 工具汇总

| 工具 | 扫描结果 | 退出码 | 修复条目 |
|------|---------|-------|---------|
| import-linter | 4 contracts kept / 4 broken / 8 violation groups | 1 | B-020 ~ B-024 |
| deptry | 30 issues (6 DEP002 + 24 DEP003) | 1 | B-026 / B-027 |
| vulture | 3 dead variables | 3 | B-028 |
| pydeps | OK（本机缺 graphviz） | 0 | — (nightly artifact) |

**CI 集成现状**：`.github/workflows/ci.yml` 的 lint job 已加入三步 (import-linter / deptry / vulture)，**当前 `continue-on-error: true` 观察模式**；新增 `arch-graph` job 仅 nightly + workflow_dispatch 触发，渲染依赖图为 artifact。强制门禁待 baseline 清零 → B-025。

---

# 第一部分：import-linter 架构契约

> 基于 [pyproject.toml `[tool.importlinter]`](../../../pyproject.toml) 的 8 条契约，扫描 147 文件 / 296 依赖边。
> 结果：**4 kept / 4 broken / 8 distinct violation groups / ~12 边**

---

## 1. 契约执行总览

| # | 契约 | 类型 | 结果 |
|---|------|-----|------|
| 1 | Layered architecture (top-down) | layers | ❌ BROKEN (6 边) |
| 2 | Pipeline 不准直接调 LLM (Sprint 6 红线) | forbidden | ✅ KEPT |
| 3 | Collector 纯 I/O，不依赖 LLM/agent | forbidden | ✅ KEPT |
| 4 | LLM 不准反向依赖更高层 | forbidden | ❌ BROKEN (2 边, V1 重复) |
| 5 | API routers 必须走 repository 不直接摸 ORM model | forbidden + allow_indirect | ❌ BROKEN (1 边) |
| 6 | Search 与 Distributor 互不依赖 | independence | ✅ KEPT |
| 7 | Collector sources / Distributor channels 互不依赖 | independence | ✅ KEPT |
| 8 | Config 不依赖 storage.models | forbidden | ❌ BROKEN (1 边) |

**Kept 项的意义**：Sprint 6 重构红线 (pipeline ↛ LLM) 至今保持 — collector / pipeline / search↔distributor / sources↔channels 这 4 块设计契约**已经"硬化"在代码里**，未来变更会被本扫描即时阻塞。

---

## 2. 违规清单与归因

### V1 — `llm.processors.filter` 反向依赖 `pipeline.{base,context}`

```
intellisource.llm.processors.filter -> intellisource.pipeline.base (l.7)
intellisource.llm.processors.filter -> intellisource.pipeline.context (l.8)
```

**事实**：[`src/intellisource/llm/processors/filter.py`](../../../src/intellisource/llm/processors/filter.py) 的 `ContentFilter` 继承 `pipeline.base.BaseProcessor`，但被放在 `llm/processors/` 包下。

- **category**: structure
- **root_cause**: self-caused（放错命名空间）
- **影响**：LLM 包成为环路一环；Sprint 6 重构红线只验了"pipeline 不调 LLM"，没验"LLM 不调 pipeline"
- **修复方向**：
  - 选项 A（推荐）：把 `ContentFilter` 物理移动到 `pipeline/processors/content_filter.py`，与其他 processor 同列；它本就不依赖 LLM。
  - 选项 B：保留位置，把 `BaseProcessor` / `PipelineContext` 抽到 `core/processor_base.py`，让 pipeline 和 llm 都依赖 core。代价更高。

---

### V2 — `agent.factory` 反向依赖 `composition` (lazy import)

```
intellisource.agent.factory -> intellisource.composition (l.59, l.81)
```

**事实**：两次都是函数内 lazy import (`get_agent_runner_holder` / `CompositionError`)，已有运行时循环回避；但 import-linter 不区分顶层与函数内。

- **category**: structure (架构层次倒置 — 同时也是 wiring root 自身循环的征兆)
- **root_cause**: self-caused
- **修复方向**：见 V3/V4 合并方案 (composition 拆分)。

---

### V3 — `composition` 反向依赖 `api.webhook_crypto`

```
intellisource.composition -> intellisource.api.webhook_crypto (l.515)
```

**事实**：composition l.515 函数内 lazy import `WeComCrypto`，把它注入到 `app.state.wecom_crypto`。

- **category**: structure
- **root_cause**: self-caused
- **修复方向**：`WeComCrypto` 本质是加密原语，与 API 路由无关。应迁到 `intellisource.security/wecom_crypto.py` 或 `core/wecom_crypto.py`，让 composition 与 api.routers.webhooks 都依赖它。

---

### V4 — `scheduler.{boot,tasks,beat_sync}` 顶层 import `composition`

```
intellisource.scheduler.boot      -> intellisource.composition (l.23)
intellisource.scheduler.tasks     -> intellisource.composition (l.18)
intellisource.scheduler.beat_sync -> intellisource.composition (l.115)
```

**事实**：worker 进程入口依赖 `composition.build_worker_composition`、`SOURCE_TYPE_TO_PIPELINE` 等。这些都是**顶层 import**，不是 lazy。

- **category**: structure (架构层次倒置)
- **root_cause**: self-caused — composition 当前混合了两种职责：
  1. wiring root（依赖一切，被 `main` 调）
  2. 共享常量（如 `SOURCE_TYPE_TO_PIPELINE`，被下层 import）
- **修复方向（推荐）**：拆 composition：
  - `composition/api.py` — `build_api_composition`，被 `main` import
  - `composition/worker.py` — `build_worker_composition`，被 `scheduler.boot` import
  - `composition/constants.py` — `SOURCE_TYPE_TO_PIPELINE` / `CompositionError`，**最底层**，任何人可 import
  - `composition/runner_holder.py` — `get_agent_runner_holder`，下层
  - 拆完后 V2/V3/V4 一并消失，layers 契约可强制 wiring 入口（api/worker.py）位于最顶层。

---

### V5 — `search.chat_session` 反向依赖 `agent.compaction`

```
intellisource.search.chat_session -> intellisource.agent.compaction (l.16)
```

**事实**：`compact_messages_for_chat` 是对话历史 token 压缩函数，被 search 的会话管理器使用。

- **category**: structure
- **root_cause**: self-caused — 压缩函数命名空间归属判断错误
- **修复方向**：将 `compact_messages_for_chat` 从 `agent/compaction.py` 抽到 `llm/prompt_builder.py` 或新建 `core/conversation_compaction.py`；agent 与 search 都依赖该新位置。

---

### V6 — `distributor.push_optimizer` 依赖 `pipeline.processors.tools`

```
intellisource.distributor.push_optimizer -> intellisource.pipeline.processors.tools (l.12)
```

**事实**：[push_optimizer.py:12](../../../src/intellisource/distributor/push_optimizer.py) 用了 `filter_sensitive` 和 `truncate_for_push` 两个纯字符串函数。

- **category**: structure (同 row 跨域)
- **root_cause**: upstream-caused — `pipeline.processors.tools` 在 ARCH 文档里就被定义为 M-004 "原子化处理工具"（不持有 pipeline 状态），但物理上放在 pipeline 包下，造成"任何人想用原子工具都得依赖 pipeline"。
- **修复方向**：把 `pipeline.processors.tools` 重命名/迁移到 `intellisource.tools/`（顶层）或 `core/text_tools.py`；pipeline.processors 改为只放真正的 Processor 类；distributor/agent/search 都依赖新位置。**这条与 V1 同根**（基类与原子工具都困在 pipeline 包里）。

---

### V7 — `api.routers.search.py:225` 直接 import `storage.models.ChatSession`

```
intellisource.api.routers.search -> intellisource.storage.models (l.225)
```

**事实**：函数内 `from intellisource.storage.models import ChatSession` 用于 `db_session.get(ChatSession, ...)`。

- **category**: structure (绕开 repository 边界)
- **root_cause**: self-caused
- **修复方向**：使用现成的 `ChatSessionRepository.get_by_id()`，删除 router 内对 ORM 类的直接引用。已经在同文件 l.250 有 `from intellisource.storage.repositories.chat_session import ChatSessionRepository`，复用即可。

---

### V8 — `config.loader` 直接依赖 `storage.models.Source`

```
intellisource.config.loader -> intellisource.storage.models (l.19)
```

**事实**：`ConfigLoader.load_source_configs()` 返回 `Source` ORM 列表，让 SourceRepository 的 `bulk_upsert` 直接吃 ORM。

- **category**: structure
- **root_cause**: self-caused — config 是最底层模块，依赖 storage 是反向耦合
- **修复方向**：
  - loader 返回 `SourceConfig` (Pydantic) 列表（`config.models.SourceConfig` 已存在）
  - `SourceRepository.bulk_upsert(configs: list[SourceConfig])` 内部做 Pydantic→ORM 转换
  - 这样 config 不再依赖 storage，符合架构图初衷

---

## 3. 违规归并与 Backlog 立项

8 条违规可归并为 5 个修复条目（注意 V2/V3/V4 同根、V1/V6 同根）：

| Backlog ID | 涉及违规 | 优先级 | 工作类型 |
|-----------|---------|------|---------|
| B-020 | V1 + V6 | P2 | 抽 pipeline.base + pipeline.processors.tools 出新 `intellisource.tools/` 命名空间 |
| B-021 | V5 | P2 | 把 `compact_messages_for_chat` 迁出 agent 包 |
| B-022 | V7 | P3 | 单点修复（5 行内）— search.py 用 ChatSessionRepository |
| B-023 | V2 + V3 + V4 | P2 | 拆 `composition.py` → `composition/{api,worker,constants,runner_holder}.py` |
| B-024 | V8 | P3 | config.loader 返回 `SourceConfig` 而非 `Source` ORM |
| B-025 | — | P2 | 把 `uv run lint-imports` 加进 CI（与 ruff/mypy 并列）+ pre-commit |

详细任务卡见 [BACKLOG-intellisource-v1.md](../../BACKLOG-intellisource-v1.md) 对应条目。

---

## 4. 验证后回归基线

修复 B-020 ~ B-024 后预期：

- 8 broken edges → 0
- 4 broken contracts → 0 broken / 8 kept
- `uv run lint-imports` 退出码 = 0
- 把 `lint-imports` 加进 CI 作为强制门禁（B-025）

---

---

# 第二部分：deptry 依赖卫生

> 配置：[pyproject.toml `[tool.deptry]`](../../../pyproject.toml)（已为 `asyncpg / psycopg / pgvector / alembic / aioredis / regex / opentelemetry-api / lxml` 8 个间接运行时依赖加 per-rule ignore）
> 结果：**30 issues** — 6 DEP002（声明未使用）+ 24 DEP003（直接 import 但是传递依赖）

## 4. DEP003: 直接 import 但是传递依赖 × 24（→ B-026）

5 个包被本项目代码直接 import，但 `[project] dependencies` 没声明，靠 fastapi / sqlalchemy / celery / litellm 间接拉入：

| 包 | 直接 import 处 (条) | 风险 |
|----|-----|------|
| `pydantic` | 9 — agent.dto / api.routers.{pipelines,search,sources,subscriptions,tasks} / api.schemas.search / config.{llm_schema,models,validator} / distributor.push_optimizer / llm.{gateway._routing,model_config} | fastapi 升级移除 pydantic v1 fallback 时静默崩溃 |
| `pyyaml` | 6 — agent.pipeline / api.routers.pipelines / config.{loader,resolver,validator} / llm.model_config | celery/litellm 升级可能不再依赖 yaml |
| `starlette` | 3 — api.middleware × 2 + main.py | fastapi 内部库，private API 风险 |
| `jsonschema` | 1 — llm.gateway._types | litellm 内部依赖 |
| `kombu` | 1 — scheduler.celery_app | celery 内部消息层 |

**修复**：见 [B-026](../../BACKLOG-intellisource-v1.md#b-026)。把这 5 个包加入 `[project] dependencies` + 加合理 `>=` 下限。

## 5. DEP002: 声明但未使用 × 6（→ B-027）

`[project.optional-dependencies] dev`（旧 PEP 621）与 `[dependency-groups] dev`（新 PEP 735）并存导致 deptry 误把 dev deps 当 runtime extras：

```
pytest / pytest-asyncio / mypy / ruff / testcontainers / pydantic-settings
```

`pydantic-settings` 需单独 grep 确认是否仍 import；其余 5 个迁到 `[dependency-groups]` 即可。

**修复**：见 [B-027](../../BACKLOG-intellisource-v1.md#b-027)。

---

# 第三部分：vulture 死代码

> 配置：[pyproject.toml `[tool.vulture]`](../../../pyproject.toml) (`min_confidence=80`，FastAPI/pytest 装饰器已加 ignore_decorators)
> 结果：**3 dead variables**（100% confidence）

## 6. `_unified_call_with_retry` 三个参数定义未使用（→ B-028）

[src/intellisource/llm/gateway/_retry.py:44-47](../../../src/intellisource/llm/gateway/_retry.py)：

```python
async def _unified_call_with_retry(
    self,
    call_fn: Callable[[], Awaitable[Any]],
    *,
    model: str,
    call_type: str,
    operation_id: str,        # ← 调用方传值，函数体未使用
    enable_fallback: bool = True,   # ← 同上
    enable_circuit_breaker: bool = True,
    fallback_input: str = "",       # ← 同上
    task_type: str | None = None,
) -> Any:
```

三个调用点（gateway/__init__.py 第 385/469/580 行）按位传参，但函数体只用了 `model / call_type / enable_circuit_breaker / task_type`，其余三个仅在 docstring 提到。

- **category**: dead-code（接口契约腐化）
- **root_cause**: self-caused — sprint-8 拆 Gateway 时遗失了语义
- **修复**：见 [B-028](../../BACKLOG-intellisource-v1.md#b-028)。要么删参数、要么真正消费它们（建议后者，因为语义本身有用）

---

# 第四部分：pydeps 依赖图（CI nightly）

> 本机缺 Graphviz `dot`，未在本扫描本地生成 SVG；CI `arch-graph` job 已配置 nightly 渲染 + upload artifact。
> 运行命令：`uv run pydeps src/intellisource --max-bacon=2 --cluster --noshow -o docs/arch/deps-graph.svg`

预期产出（首次运行后接入对照）：
- 全 11 模块依赖图 SVG，已按 cluster 分组
- 循环依赖以蓝色框高亮 — 本次 import-linter 已发现的 8 处违规会在图上直观体现
- Bacon distance ≤ 2 过滤掉过远节点，避免图过密

---

## 7. verdict

- **verdict**: `approved_with_notes`
- **notes_summary**:
  - import-linter: 8 类违规归并为 5 个修复条目（B-020 ~ B-024）；V1/V6 同根、V2/V3/V4 同根
  - deptry: 24 个 DEP003（B-026）+ 6 个 DEP002（B-027）
  - vulture: 3 个真实接口腐化（B-028）
  - 总体未触及 CRITICAL/HIGH；当前回归基线（2766 PASS / mypy strict / ruff clean）不受影响
- **CI 状态**: 三工具均已挂 lint job + 当前 `continue-on-error: true` 观察模式（B-025）；nightly arch-graph job 已就位
- **建议**：
  1. 本次产出（pyproject 配置 + CI workflow + Makefile + backlog 立项 + 报告）作为单一 PR 合并
  2. B-022 / B-028 是单点小改，建议作为下一个 PR 把治理工具链先"擦干净一部分"
  3. B-020 / B-023 是真正的两块结构性重构，每个独立 PR
  4. baseline 清零后摘掉 `continue-on-error`，从此架构腐化无法静默入主干
