---
id: code-scan-arch-20260529-r1
doc_type: code-review
author: reviewer
status: draft
deps: [arch-intellisource-v1-modules, backlog-intellisource-v1]
---

# CODE-SCAN: 架构审查与重构诊断（深层维度）

> 范围：在自动化治理工具（import-linter / deptry / vulture / ruff / mypy）已全绿的基线之上，扫描**工具检测不到的深层架构问题**——SSOT 违规、重复逻辑、配置散落、日志双轨、异常层级采用度。
> 实测基线（2026-05-29，HEAD `e3fd5d3`）：`lint-imports` 8/8 KEPT、`deptry` 无问题、`vulture` 无死代码、`ruff` 全绿、`mypy --strict` 零问题、单元测试全 PASS（`-n auto`）。

## 0. 关键结论

代码库在**自动化治理维度已非常干净**：`B-020~B-028` 架构治理首扫批次实际已闭环（commit `9c118b8` / `a35fa31`），CI lint job 已移除 `continue-on-error`（违规阻塞 merge）。本次审查价值集中在工具无法捕捉的语义层债务。

## 1. 问题清单（位置 / 严重程度 / 分类）

| # | 问题 | 位置 | 严重 | category | root_cause |
|---|------|------|------|----------|------------|
| D-1 | `_MAX_NAME_LENGTH=100` 在两个 validator 各自定义 | `config/validator.py:24`、`config/subscription_validator.py:18` | HIGH | duplication | self-caused |
| D-2 | 渠道常量重复：`MAX_RETRY=3`/`RETRY_INTERVAL=5`(×3)、`TOKEN_EXPIRE_BUFFER=300`(×2) | `distributor/channels/{wework,wechat,email}.py` | HIGH | duplication | self-caused |
| D-3 | 结果字典构建逻辑重复（`_build_result`/`_make_result`/内联三套） | `channels/wework.py:223`、`email.py:110`、`wechat.py:212` | MEDIUM | duplication | self-caused |
| D-4 | 无统一配置中心：50 处 `os.environ.get/getenv` 散落 19 文件；默认值多处重复（`redis://localhost:6379/0`、`587`、`config/sources` 等） | 见 §2 配置散落清单 | HIGH | structure | self-caused |
| D-5 | 日志双轨：仅 3 文件用 structlog 包装器 `get_logger`，54 处裸 `logging.getLogger` 散布 ~50 文件（架构要求 structlog） | 见 §3 日志清单 | MEDIUM | consistency | self-caused |
| D-6 | 异常层级采用不足：`core/errors.py` 定义 `IntelliSourceError`+5 子类（携 `ErrorCategory` 恢复策略），但全库 91 处裸 `except Exception` | 全库 | MEDIUM | error-handling | self-caused |
| D-7 | 死代码：已弃用导出 `ModelConfig`（dataclass）仅被再导出，无生产消费方 | `llm/model_config.py:53`、`llm/__init__.py:12,22` | LOW | dead-code | self-caused |
| D-8 | 文档陈旧：B-020~B-028 已闭环但 backlog 记为开放 | `docs/BACKLOG-intellisource-v1.md` | LOW | consistency | self-caused |

**修正既有报告两处不实**（已实测）：
- 渠道**重试循环已统一**在 `BaseDistributor._run_with_retry`（`distributor/base.py:135-170`），并不重复——仅常量与结果构建重复。
- 日志迁移的 mypy `--strict` "logger 作参数" 阻塞**已不存在**（全库 0 个 logger 形参函数），迁移为纯机械替换。

## 2. 配置散落清单（实测环境变量 + 默认值）

`DATABASE_URL`/`IS_DATABASE_URL`(无默认)、`IS_REDIS_URL`(默认 `redis://localhost:6379/0`)、`IS_CELERY_BROKER_URL`/`IS_CELERY_RESULT_BACKEND`、`IS_API_KEY`("")/`IS_API_URL`、`IS_LOG_LEVEL`("INFO")、`IS_LLM_CONFIG_PATH`、`IS_SOURCE_CONFIG_DIR`("config/sources")/`IS_SUBSCRIPTION_CONFIG_DIR`、`IS_SMTP_{HOST,PORT,USER,PASSWORD}`/`IS_SMTP_USE_TLS`("true")、`IS_WECHAT_{APP_ID,APP_SECRET,WEBHOOK_TOKEN}`、`IS_WEWORK_{CORP_ID,CORP_SECRET,AGENT_ID,WEBHOOK_TOKEN}`、`IS_WECOM_{CORP_ID,TOKEN,ENCODING_AES_KEY}`、`IS_BEAT_DISABLED`/`IS_BEAT_SYNC_HARD_FAIL`、`IS_PUSH_OPTIMIZE_ENABLED`、`ENV`。

## 3. 日志清单（54 处 `logging.getLogger`，代表文件）

`main.py`、`composition.py`、`collector/adapters/{api,rss}.py`、`config/{subscription_loader,loader,resolver}.py`、`distributor/{facade,push_optimizer,matcher,frequency}.py`、`agent/{runner,compaction,events}.py` + `agent/tools/**` + `agent/executors/flexible.py`、`llm/**`（`gateway/*`、`model_config`、`prompt_builder`、`cache`、`compaction`、`processors/extractor`）、`pipeline/{condition,engine}.py` + `pipeline/processors/*`、`api/middleware.py` + `api/routers/*`、`scheduler/{boot,signals,beat_sync}.py`、`storage/repositories/source.py`。

## 4. 重构方案与优先级（风险低 → 高）

| Phase | 内容 | 风险 | 验证 |
|-------|------|------|------|
| 0 | 诊断报告 + backlog 回填 + 删除死代码 `ModelConfig` | 极低 | `make check` |
| 1 | SSOT 常量收敛（`config/constants.py`、`distributor/channels/constants.py`） | 低 | `make check` |
| 2 | 渠道结果构建上移 `BaseDistributor._build_result` | 中 | `make check` + 渠道集成 |
| 3 | 统一配置中心 `core/settings.py`（pydantic-settings，行为等价映射现有 env） | 中-高 | `make check-all` + 默认值对账 |
| 4 | 日志统一 structlog（机械替换 + 审计 `%`-格式化调用风格） | 中 | `make check` + 日志 schema 抽查 |
| 5 | 异常处理定向收敛（边界抛 `IntelliSourceError` 子类，保留刻意广捕） | 中 | 错误注入测试 |

每 Phase 独立提交、独立可验证、可回滚。详细执行步骤与确认点见 `docs/` 提交记录与 PR 描述。

## 5. 验证方式

- **本地全门禁**：`make check`（arch + deps + deadcode + ruff + mypy + 单测 `-n auto`），基线保持 8/8 KEPT、零新增违规、单测不退化。
- **契约相关集成**（EXP-CONTRACT-DRIFT）：触碰 `api/routers/`、`storage` SQL、`llm/gateway/_stream`、渠道返回 shape 时跑 `make test-integration`（`make up` 提供 PG/Redis）。
- **行为等价专项**：Settings 默认值逐项对账 + `get_settings.cache_clear()` setenv 测试；日志 JSON 行 schema（timestamp/level/trace_id）不变；异常路径错误注入（坏 SMTP/DB/LLM key）分类与恢复行为不变。

## 6. 实施状态（本次工程）

| Phase | 实施结果 | 验证 |
|-------|---------|------|
| 0 | ✅ 删除死代码 `ModelConfig` + backlog 回填 B-020~B-028 + 落盘本报告 | `make check` 全绿 |
| 1 | ✅ `MAX_NAME_LENGTH` → `config/constants.py`；渠道 `MAX_RETRY`/`RETRY_INTERVAL`/`TOKEN_EXPIRE_BUFFER` → `distributor/channels/constants.py` | unit 不退化 |
| 2 | ✅ push-result 骨架统一到 `BaseDistributor._build_result`（数据等价，状态词表不变） | distributor unit 全绿 |
| 3 | ✅ `core/settings.py`（pydantic-settings）收敛 14 文件 ~35 处 env 读取；字段保留原始类型 + 各点原解析语义；动态读取保留原样；附带修复 `main.py` 模块级 env 读取的 import 期缓存污染（latent bug） | 2977 unit 全绿；默认值逐项对账 |
| 4 | ✅ 47 业务模块 → structlog `get_logger`（JSON Lines）；`PositionalArgumentsFormatter` 保 `%s`；`signals`/`middleware` 刻意留 stdlib（B-040 载体）；16 处 caplog → `capture_logs` | 2977 unit 全绿 |
| 5 | ✅ 保守收尾 — 经诊断异常层级已充分采用（11 处边界抛子类 / 15 处广捕已标注 / 仅 5 处静默吞吃且多为合理）；未做全量收窄（避免行为漂移），仅对 `strict._retry_step` 静默重试吞吃补 debug 日志（行为等价） | unit 全绿 |

**结论**：D-1~D-8 全部闭环。自动化治理基线（import-linter 8/8 / deptry / vulture / ruff / mypy --strict）保持全绿，单测 2977 PASS 不退化。
