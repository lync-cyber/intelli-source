---
id: backlog-intellisource-v1
doc_type: backlog
author: orchestrator
status: approved
deps: []
---

# IntelliSource v1 Backlog

> 维护：本文件梳理 PR #53 / #54 audit 闭环之后的剩余工作。完成项请直接删除条目，新增项按优先级插入。
> 最后更新：2026-05-25 (post B-007 + B-009 + B-029 + B-030 闭环)

## 优先级语义

- **P0 — 阻塞**：影响生产正确性 / 安全 / 上线 go-no-go
- **P1 — 阻塞质量**：可观测性、性能边界、合规
- **P2 — 架构 / 功能完整性**：上帝类拆分、PRD 接受项功能缺口
- **P3 — 优化 / 规约**：硬编码、弱断言、风格

---

## P1 — Audit 残留质量项

> B-003 / B-004 / B-005 / B-006 已闭环（详见 [docs/reviews/code/CODE-REVIEW-backlog-p1-r1.md](reviews/code/CODE-REVIEW-backlog-p1-r1.md)，含 R-001 修订）

---

## P2 — 架构 / 功能完整性

> B-007 已闭环（详见 [docs/reviews/code/CODE-REVIEW-B-007-r1.md](reviews/code/CODE-REVIEW-B-007-r1.md)）— `gateway/__init__.py` 732 → 120 行，拆为 `_complete/_chat/_stream/_queue/_metrics/_protocols` 6 mixin，Protocol 自洽，2820 PASS 不退化
>
> B-009 已闭环（decision-only，reaffirm 选项 ②）— PRD AC-063 [ASSUMPTION] 在 sprint-9 已锁定 YAML-as-source-of-truth；`src/intellisource/api/routers/pipelines.py` 现状即决策实现（list/detail/run，无 CRUD）。完整 workflow CRUD（DB 存储 + 历史版本）保留为 v2+ 范畴，本 backlog 不立项。

### B-008 综合简报降级为字符串截断
- **关联**：原 audit F-38 / D6-4 / AC-023
- **现状**：[`src/intellisource/pipeline/processors/tools.py:262`](src/intellisource/pipeline/processors/tools.py:262) `truncate_summary` 字符串截前 3 句，`timeline` / `key_points` 恒 `[]`
- **修复方向**：接 LLM summarizer（PromptBuilder + `gateway.complete` + JSON schema {title, summary, timeline:[], key_points:[]}）；失败回退当前截断
- **决策选项**：v1 若不做，PRD AC-023 显式标 `[ASSUMPTION] v1 仅字符串截断，timeline/key_points 留 P2 backlog`
- **验证**：注入 LLM 返回真 timeline → 字段非空；LLM 失败 → 字段空 + log warning

### B-010 Deploy 阶段未启动
- **关联**：CLAUDE.md 原 backlog ③
- **现状**：`docs/deploy-spec/` 缺失；docker/ 下已有 Dockerfile + docker-compose + prometheus/，但缺正式 deploy-spec 文档梳理 staging/prod 部署清单、回滚 SOP、健康指标基线
- **修复方向**：devops 子代理产出 `docs/deploy-spec/deploy-spec-intellisource-v1.md` — 含部署架构图 / 环境变量清单 / smoke 测试 / 回滚步骤 / 监控 SLO
- **依赖**：B-003、B-005 完成后部署 spec 中的指标章节更准确

---

## P3 — 优化 / 规约

### B-011 263 处弱断言 `assert .* is not None`
- **关联**：原 audit F-49 / D6-7
- **现状**：跨 79 个测试文件，大量 `assert result is not None` 不验证语义
- **修复方向**：不批量改；新增测试时由 reviewer code-review Layer 1 检查命中
- **规约**：在 `.cataforge/rules/COMMON-RULES.md §通用 Anti-Patterns` 加一条"禁止单纯 `is not None` 断言无语义检查"

### B-012 `keyword_tag` 默认值硬编码 `"未分类"`
- **关联**：原 audit F-50 / D6-8
- **现状**：[`src/intellisource/pipeline/processors/tools.py:305,310`](src/intellisource/pipeline/processors/tools.py:305) 硬编码中文字符串
- **修复方向**：抽常量 `DEFAULT_KEYWORD_TAG: str = "未分类"` 至模块顶层；i18n 非 v1 范围
- **成本**：单点改动

> B-029 + B-030 已闭环 — LLM/Push alert 按 model/channel 拆分 (annotations 模板化引用 label) + R-002 注释 + R-003 精确路径匹配 + R-004 register 集中化 (facade __init__)；2827 PASS (+7 测试)。

---

## PR #54 后续验证

### B-013 CI 在 ubuntu-latest 跑 integration（docker available 路径）
- **现状**：本地无 Docker 时 47 个 PG 集成测试 deselect；CI 必须真跑
- **修复方向**：GitHub Actions workflow 设 `IS_FORCE_DOCKER_TESTS=1` 或确保 docker daemon 启动；fail 时阻塞 merge
- **验证**：CI 输出显示 162 collected，0 deselected，47+ PASS

### B-014 staging 验证 /api/v1/metrics 暴露所有新 metric
- **现状**：本次新增 metric（http_/llm_/celery_/pushes_/llm_circuit_open）单测覆盖通过，但未在真实 deploy 验证 Prometheus scrape 抓得到
- **修复方向**：deploy staging 后 `curl /api/v1/metrics | grep -E "(http_requests_total|llm_calls_total|pushes_total|celery_tasks_total|llm_circuit_open)"`
- **依赖**：B-010 deploy-spec

### B-015 `promtool check rules` 验证 alerts.yml 语法
- **现状**：`test_alerts_yaml.py` 校验 YAML shape + metric 名引用一致，但未跑 `promtool check rules`
- **修复方向**：CI workflow 加一步 `docker run --rm -v $PWD/docker/prometheus:/etc/prometheus prom/prometheus:v2.55.1 promtool check rules /etc/prometheus/alerts.yml`
- **依赖**：B-013 CI 升级

---

## 框架学习应用（来自 RETRO）

### B-016 应用 6 EXP (sprint-1~7) 到 `.cataforge`
- **关联**：CLAUDE.md 原 backlog ①
- **现状**：[`docs/reviews/retro/RETRO-intellisource-v1.md`](docs/reviews/retro/RETRO-intellisource-v1.md) 列了 6 个改进点，应用决策 deferred
- **修复方向**：逐条评估 → 改 `.cataforge/skills/<id>/SKILL.md` 或 `agents/<role>/AGENT.md`

### B-017 应用 EXP-005 (sprint-9) 装配缺口 framework-level lint
- **关联**：CLAUDE.md 原 backlog ②
- **现状**：[`RETRO-intellisource-v1-sprint-9.md`](docs/reviews/retro/RETRO-intellisource-v1-sprint-9.md) — assembly-gap 5 次复发
- **修复方向**：`.cataforge/skills/code-review/scripts/lint_assembly.py` 检查 build_*_composition 必须把所有声明依赖注入下游 facade

### B-018 应用 EXP-006 / EXP-007 anti-truncation 协议到全角色
- **关联**：CLAUDE.md 原 backlog ② / RETRO-sprint-8
- **现状**：EXP-007 Mid-Progress Drop Contract 在 implementer / refactorer 见效；扩展到 reviewer / test-writer / debugger 未做
- **修复方向**：`.cataforge/agents/{reviewer,test-writer,debugger}/AGENT.md` 加 4 步契约 prompt 段

---

## 架构治理工具链首扫 (2026-05-24)

> 扫描报告全文见 [docs/reviews/code/CODE-SCAN-arch-20260524-r1.md](reviews/code/CODE-SCAN-arch-20260524-r1.md)
> 工具集：`uv run lint-imports` / `uv run deptry src` / `uv run vulture` / `uv run pydeps`（配置在 [`pyproject.toml`](../pyproject.toml) `[tool.importlinter|deptry|vulture|pydeps]`）；本地一键 `make check`
> 基线：
> - **import-linter**: 147 文件 / 296 依赖边 / 4 kept / 4 broken / 8 violation groups → B-020~B-024
> - **deptry**: 30 issues (6 DEP002 + 24 DEP003) → B-026 / B-027
> - **vulture**: 3 dead variables → B-028
> - **pydeps**: 渲染依赖图 SVG（CI nightly artifact）
> - **CI 集成**: 已加入 lint job + nightly `arch-graph` job，**当前观察模式** (`continue-on-error: true`) → B-025 升级为强制门禁

### B-020 抽 `pipeline.base` + `pipeline.processors.tools` 出新 `intellisource.tools/` 包
- **关联**：CODE-SCAN-arch V1 + V6
- **现状**：
  - `llm.processors.filter` 顶层 import `pipeline.base.BaseProcessor` / `pipeline.context.PipelineContext` ([src/intellisource/llm/processors/filter.py:7-8](../src/intellisource/llm/processors/filter.py))
  - `distributor.push_optimizer` 顶层 import `pipeline.processors.tools.{filter_sensitive,truncate_for_push}` ([src/intellisource/distributor/push_optimizer.py:12](../src/intellisource/distributor/push_optimizer.py))
- **根因**：`BaseProcessor` 与原子工具被困在 pipeline 包内，导致任何复用方都"被迫"反向依赖 pipeline；ARCH 文档把 `pipeline.processors.tools` 定义为 M-004 "原子化工具"但物理位置归属 M-003
- **修复方向**：
  - 抽 `BaseProcessor` / `PipelineContext` 出来到 `intellisource.tools.processor_base` (或 `core/processor_base`)
  - 抽 `filter_sensitive` / `truncate_for_push` / `tfidf_keywords` / `truncate_summary` / `keyword_tag` 等纯函数到 `intellisource.tools.text/`
  - pipeline.processors.tools 改为再导出薄层兼容旧路径（一个 deprecation 周期后删除）
- **验证**：`lint-imports` 中 V1 + V6 消失；distributor/llm 不再依赖 pipeline

### B-021 `compact_messages_for_chat` 从 `agent.compaction` 抽到中性命名空间
- **关联**：CODE-SCAN-arch V5
- **现状**：[src/intellisource/search/chat_session.py:16](../src/intellisource/search/chat_session.py) 反向依赖 `agent.compaction`；该函数实质是"对话历史 token 压缩工具"，与 agent 编排无关
- **修复方向**：迁到 `intellisource.tools.conversation` 或 `intellisource.llm.prompt_builder`（与 PromptBuilder 同包，语义贴近）；agent 与 search 都改 import 新位置
- **成本**：单文件移动 + 2 处 import 路径更新
- **验证**：`lint-imports` V5 消失

### B-022 `api.routers.search` 单点直接 import `storage.models.ChatSession`
- **关联**：CODE-SCAN-arch V7
- **现状**：[src/intellisource/api/routers/search.py:225](../src/intellisource/api/routers/search.py) 函数内 `from intellisource.storage.models import ChatSession` 用 `db_session.get(ChatSession, ...)`
- **修复方向**：复用同文件 l.250 已有的 `ChatSessionRepository.get_by_id()`，删除函数内 ORM 直引
- **成本**：~5 行
- **验证**：`lint-imports` V7 消失；现有 chat session 单测仍 PASS

### B-023 拆分 `composition.py` 解耦 wiring root 与共享常量
- **关联**：CODE-SCAN-arch V2 + V3 + V4
- **现状**：[`composition.py`](../src/intellisource/composition.py) 同时承担 wiring root（依赖一切）和共享常量提供者（`SOURCE_TYPE_TO_PIPELINE`、`CompositionError`、`get_agent_runner_holder`），导致 scheduler.{boot,tasks,beat_sync}（3 处顶层 import）+ agent.factory（lazy import）反向依赖
- **修复方向**：拆为 `composition/` 包：
  - `composition/constants.py` — `SOURCE_TYPE_TO_PIPELINE` / `CompositionError` / `get_agent_runner_holder`（最底层）
  - `composition/api.py` — `build_api_composition`（顶层，仅被 `main` import）
  - `composition/worker.py` — `build_worker_composition`（顶层，仅被 `scheduler.boot` import）
  - 顺带把 `WeComCrypto` (l.515) 抽到 `intellisource.tools.wecom_crypto`（V3）
- **影响范围**：composition / agent.factory / scheduler.{boot,tasks,beat_sync} / api.routers.tasks
- **验证**：`lint-imports` V2/V3/V4 全部消失；现有装配测试 PASS

### B-024 `config.loader` 返回 `SourceConfig` 而非 `Source` ORM
- **关联**：CODE-SCAN-arch V8
- **现状**：[src/intellisource/config/loader.py:19](../src/intellisource/config/loader.py) 顶层 import `storage.models.Source`；loader 直接生产 ORM 实例传给 `bulk_upsert`
- **修复方向**：
  - loader 返回 `list[SourceConfig]` (`config.models.SourceConfig` 已存在)
  - `SourceRepository.bulk_upsert(configs: list[SourceConfig])` 内部做 Pydantic → ORM 转换
  - config 包不再依赖 storage，符合架构图分层
- **验证**：`lint-imports` V8 消失；source CRUD / reload 路径单测 PASS

### B-025 架构治理工具链 CI 升级为强制门禁
- **关联**：架构契约首扫 + 依赖卫生 + 死代码扫描的执行保障
- **现状（已落地一半）**：
  - `pyproject.toml` 已注册 4 工具配置：`[tool.importlinter]` / `[tool.deptry]` / `[tool.vulture]` / `[tool.pydeps]`
  - `Makefile` 新增 `arch` / `deps` / `deadcode` / `deps-graph` / `check` 目标
  - `.github/workflows/ci.yml` 已加 3 步（import-linter / deptry / vulture），**当前 `continue-on-error: true`** 观察模式；并新增 nightly `arch-graph` job 渲染依赖图为 artifact
- **未完成（待 baseline 清零再设强制）**：
  - 移除 `continue-on-error: true`，使违规阻塞 merge
  - 新增 `.pre-commit-config.yaml` 挂钩 import-linter + deptry
- **强制门禁的前置条件**：B-020 ~ B-024（import-linter）+ B-026 ~ B-028（deptry / vulture）全部闭环 → 三工具退出码 = 0
- **验证**：故意提交一处违规 → CI 红 → merge 阻塞

### B-026 显式声明 transitive 运行时依赖（deptry DEP003 × 24）
- **关联**：架构治理工具链首扫 (deptry, 2026-05-24)
- **现状**：5 个包被项目直接 import，但依赖于 fastapi/sqlalchemy/celery/litellm 等间接引入：
  - `pydantic`（9 处 import — agent.dto / api.routers.* / config.* / llm.gateway._routing / llm.model_config / push_optimizer / api.schemas.search）
  - `pyyaml` / `yaml`（6 处 — agent.pipeline / api.routers.pipelines / config.loader / config.resolver / config.validator / llm.model_config）
  - `starlette`（3 处 — api.middleware × 2 + main.py）
  - `jsonschema`（1 处 — llm.gateway._types）
  - `kombu`（1 处 — scheduler.celery_app）
- **风险**：上游升级时 transitive 链路可能改变，例如 fastapi 移除 pydantic v1 fallback，本项目无版本约束 → 静默漂移
- **修复方向**：把 `pydantic / pyyaml / starlette / jsonschema / kombu` 加入 [`pyproject.toml`](../pyproject.toml) `[project] dependencies`，每个加合理的 `>=` 版本下限
- **验证**：`uv run deptry src` DEP003 计数 = 0；`uv sync --upgrade` 不破坏现有测试

### B-027 dev deps 统一到 `[dependency-groups]`（deptry DEP002 × 6）
- **关联**：架构治理工具链首扫 (deptry, 2026-05-24)
- **现状**：[`pyproject.toml`](../pyproject.toml) 同时存在两套 dev 配置 — 旧 PEP 621 的 `[project.optional-dependencies] dev = [...]` 与新 PEP 735 的 `[dependency-groups] dev = [...]`；deptry 把前者当 extras 看，对 `pytest / pytest-asyncio / mypy / ruff / testcontainers / pydantic-settings` 报 DEP002
- **修复方向**：
  - 合并：把 `[project.optional-dependencies] dev` 的所有条目迁到 `[dependency-groups] dev` 后删除前者
  - `pydantic-settings` 单独评估：grep 全库确认是否仍有 import；如无则连同删除
  - `uv sync --all-extras` 改为 `uv sync` 或 `uv sync --group dev`（CI 同步更新）
- **验证**：`uv run deptry src` DEP002 计数 = 0；CI `uv sync` 步骤仍能拉齐 dev deps

### B-028 删除 `_unified_call_with_retry` 三个未使用参数（vulture × 3）
- **关联**：架构治理工具链首扫 (vulture, 2026-05-24)
- **现状**：[src/intellisource/llm/gateway/_retry.py:44-47](../src/intellisource/llm/gateway/_retry.py) `_unified_call_with_retry` 签名包含 `operation_id` / `enable_fallback` / `fallback_input`，但函数体只在 docstring 提到，未在逻辑中引用；三处调用方（[gateway/__init__.py:385,469,580](../src/intellisource/llm/gateway/__init__.py)）都按位传参 — 是删了实现忘了同步签名的残留
- **修复方向**：
  - 选 A（推荐）：删除三个参数与对应 docstring；调用方相应去掉关键字参数
  - 选 B：在函数体内实际消费它们（如把 `operation_id` 用于 log 关键字 / 把 `enable_fallback` 接入 fallback 分支判断 / 把 `fallback_input` 转发给 `_fallback_manager.execute_fallback`），这是 sprint-8 拆 Gateway 时遗失的语义
- **验证**：`uv run vulture` 退出码 = 0；gateway chat/complete/stream 三个调用路径单测仍 PASS

---

## 上游反馈跟进

### B-019 [`docs/feedback/`](docs/feedback/) 1 bug + 1 suggest 未闭环
- **关联**：CLAUDE.md 原"上游反馈"段
- **现状**：feedback 目录有 2 条未处理
- **修复方向**：逐条 triage → 关联到现有 backlog 项或新开

---

## 已完成（PR #53 + PR #54 历史档案）

完整闭环参见 commit `7e10e77` (PR #53) 与 `31bddde` (PR #54) — 共 39 + 14 项 audit 修复：
- P0：F-01 ~ F-11（数据正确性 + agent/LLM + docker + 企微加密 + receiver_id + /metrics 鉴权 + PG 真链路）
- P1：F-12 ~ F-27（LLM 治理 + 采集真链路 + health 并发 + 4 路径埋点 + trace_id + priority queue + content_not_found + alerts）
- P2：F-28 ~ F-29 / F-31 ~ F-37 / F-39 / F-41 ~ F-48（上帝类拆分 + 持久化 + 杂项清理）
- P3：F-46 / F-47 / F-48
- 测试质量：2 xfail 修复 + 1 placeholder skip 删除 + 46 docker skip 转 deselect
- 框架基础：EXP-006 mid-narration recovery 多次实战 + EXP-007 Mid-Progress Drop Contract 验证有效

回归基线：2766 PASS / 0 FAIL / 0 skip / 0 xfail / 51 deselected；mypy --strict + ruff clean。
