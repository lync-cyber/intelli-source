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
