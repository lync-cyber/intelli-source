# IntelliSource

AI-powered intelligent information aggregation and distribution platform.

## 快速上手（新用户）

零基础把系统跑起来（先装 [Docker Desktop](https://www.docker.com/products/docker-desktop/) 与 [uv](https://docs.astral.sh/uv/)）：

```bash
# 1. 安装依赖并注册 intellisource 命令
uv sync

# 2. 交互式初始化（生成 docker/.env、播种配置模板、写入起始信源）
uv run intellisource init

# 3. 一键启动全栈（db / redis / 迁移 / api / worker / beat）
uv run intellisource up

# 4. 自检配置（含运行中 API 健康检查）
uv run intellisource doctor --check-api

# 5. 加载订阅并触发第一次采集
uv run intellisource subscriptions reload
uv run intellisource source list             # 找到 source id
uv run intellisource task trigger <source-id>
```

Windows PowerShell / macOS / Linux 命令**完全一致**——`intellisource up/down/migrate/logs/ps` 跨平台封装 `docker compose`，无需安装 `make`。装了 `make`（Linux/macOS）也可用等价的 `make up` / `make bootstrap`。

**核心概念**（理解这 4 个即可上手）：

| 概念 | 含义 | 配置位置 |
|------|------|----------|
| **source** 信源 | 内容从哪来（RSS / API / 网页） | `config/sources/` |
| **subscription** 订阅 | 把匹配内容推给谁、走哪个渠道 | `config/subscriptions/` |
| **channel** 渠道 | 推送目的地（企业微信 / 公众号 / 邮件）凭据 | `docker/.env` |
| **pipeline** 流水线 | 采集 → 处理 → 分发的自动编排 | `config/pipelines/` |

完整链路需要 **source + subscription + channel** 三者都配置好才会有推送。

> `intellisource init` 在**宿主机**运行（容器以只读挂载 `config`，容器内无法写）。任何"配置不生效"先跑 `uv run intellisource doctor` 自检。本地直接 `uv run uvicorn`/`celery` 时，进程会自动加载 `docker/.env` 中的 `IS_*` 与 LLM provider key。

## 开发环境

```bash
uv sync
uv run alembic upgrade head
```

## 测试运行

### 单元测试

单元测试无外部依赖，可直接在本地运行：

```bash
uv run pytest tests/unit/ -q --tb=short
```

### 集成测试

集成测试分为两类：

**不依赖 Docker 的集成测试**（本地可直接运行）：

```bash
uv run pytest tests/integration/test_celery_worker_wiring.py -q --tb=short
```

**依赖 Docker 的集成测试**（`pg_container` / `pg_session` / `pg_truncate` fixtures）：

这类测试需要本地 Docker daemon 运行，使用 `pgvector/pgvector:pg16` 镜像启动临时 PostgreSQL 容器。Docker 不可用时，pytest 会自动跳过相关测试（通过 `pytest_collection_modifyitems` hook），并输出跳过原因：

```
SKIPPED — Docker daemon not available locally — integration tests skipped;
GREEN verification deferred to CI (ubuntu-latest with built-in Docker)
```

启动 Docker 后即可本地运行全部集成测试：

```bash
uv run pytest tests/integration/ -q --tb=short
```

### CI 验证

GitHub Actions 使用 `ubuntu-latest`（内置 Docker），所有集成测试在 CI 中完整运行。详见 `.github/workflows/ci.yml`。

### 全量测试

```bash
uv run pytest -q --tb=short
```

## 质量门禁

本项目用 ruff / mypy / pytest / import-linter / deptry / vulture / pydeps 七件套覆盖风格、类型、功能、架构、依赖、死代码、可视化。本地一键跑全套：

```bash
make check         # arch + deps + deadcode + ruff + mypy + pytest
```

| 命令 | 工具 | 目的 |
|------|------|------|
| `make arch` | `uv run lint-imports` | 架构契约（分层 / 禁止依赖 / 独立模块），配置见 [`pyproject.toml`](pyproject.toml) `[tool.importlinter]` |
| `make deps` | `uv run deptry src` | 依赖卫生（未声明 / 未使用 / transitive 直 import） |
| `make deadcode` | `uv run vulture` | 死代码（参数 / 变量 / 方法），allowlist 在 [`.vulture_whitelist.py`](.vulture_whitelist.py) |
| `make deps-graph` | `uv run pydeps ...` | 渲染依赖图 SVG（需本机装 Graphviz `dot`） |
| `make lint-fix` | `ruff format` + `ruff check --fix` | 自动修复风格问题 |

Windows 用户没 `make` 时直接跑 `uv run <tool>`：

```powershell
uv run lint-imports --no-cache
uv run deptry src
uv run vulture
uv run pydeps src/intellisource --max-bacon=2 --cluster --noshow -o docs/arch/deps-graph.svg
```

### CI 集成

- 每个 PR：`lint` job 跑 ruff + mypy + import-linter + deptry + vulture，**架构治理三工具当前为 observation 模式** (`continue-on-error: true`)，等基线条目（见 [BACKLOG `B-020 ~ B-028`](docs/BACKLOG-intellisource-v1.md)）清零后切为强制门禁
- 每日 02:00 UTC：`arch-graph` job 自动渲染 `docs/arch/deps-graph.svg` 并 upload 为 artifact
- 手动触发：`gh workflow run CI`

新增违规不会被 observation 模式静默 — 会在 CI 日志显式打印，方便 PR 作者在新代码上即时发现。

### 治理基线快照

最新一次扫描见 [docs/reviews/code/CODE-SCAN-arch-20260524-r1.md](docs/reviews/code/CODE-SCAN-arch-20260524-r1.md)。
