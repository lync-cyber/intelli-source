# IntelliSource

AI-powered intelligent information aggregation and distribution platform.

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
