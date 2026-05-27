---
id: "b032-pgvector-zhparser-image-options"
doc_type: research
author: research
status: approved
deps: ["b-032"]
---
# B-032 pgvector + zhparser 复合镜像方案调研

> 调研目的: B-032 backlog 给出选 A (自建 Dockerfile) vs 选 B (现成社区镜像) 两条路径, 调研后由用户拍板.
> 调研日期: 2026-05-27
> 触发场景: B-031 走查阶段 0 步骤 1 `CREATE EXTENSION zhparser` 在裸 `pgvector/pgvector:pg16` 镜像上失败, migration 001 当前用 `DO ... EXCEPTION` 块包裹优雅降级, 但 deploy-spec §2 R-005 把 zhparser 列为硬约束.

## 1. 关键发现

### 1.1 选 B (现成复合镜像) 不存在

调研 Docker Hub + GitHub 后, **公开域内不存在 pgvector + zhparser 二合一镜像**. 主要竞品分布:

| 镜像 | 含 pgvector | 含 zhparser | PG 16 支持 | 维护状态 |
|------|-------------|-------------|-----------|----------|
| [pgvector/pgvector:pg16](https://hub.docker.com/r/pgvector/pgvector) | ✓ | ✗ | ✓ | 官方, 活跃 (latest tag `0.8.2-pg18-trixie`) |
| [zhparser/zhparser:bookworm-16](https://github.com/amutu/zhparser) | ✗ | ✓ | ✓ | 上游官方, v2.3 (2025-01-24) |
| [abcfy2/docker_zhparser](https://github.com/abcfy2/docker_zhparser) | ✗ | ✓ | ✓ (13-17 全覆盖) | 社区, CI 自动构建 (Debian+Alpine 双变体) |
| [ChiChou/zhparser-docker](https://github.com/ChiChou/zhparser-docker) | ✗ | ✓ | 仅 PG ≤14 | 社区, 维护停滞 |

**结论**: 选 B 在公开仓库中没有可直接复用的镜像; 自建是唯一可行路径.

### 1.2 选 A 自建可行性高

自建复合镜像有两条等价子路径:

**A1 — 基于 pgvector 镜像加 zhparser 层 (推荐)**:
- 基底: `pgvector/pgvector:pg16` (Debian bookworm, 已含 pgvector 二进制)
- 加层: 重新 apt install build tools → 编译 SCWS 1.2.3 → 编译 zhparser → 卸载 build tools
- 参考: [abcfy2/docker_zhparser Dockerfile.debian](https://github.com/abcfy2/docker_zhparser/blob/main/Dockerfile.debian) 的 SCWS+zhparser 部分逻辑
- 增量 Dockerfile 约 25-30 行
- 镜像构建增量耗时: apt install (~30s) + SCWS configure+make (~30s) + zhparser make (~10s) ≈ 1-2 分钟

**A2 — 基于 zhparser 镜像加 pgvector 层**:
- 基底: `zhparser/zhparser:bookworm-16` (上游官方)
- 加层: COPY pgvector 二进制, 或重新编译 pgvector
- 风险: zhparser 上游镜像若停更, 项目被动绑死老 PG 版本
- 缺点: 上游 v2.3 (2025-01-24) 维护活跃, 但项目主要事实来源是 pgvector 而非 zhparser, 反向叠加语义不自然

### 1.3 上游维护状态

- **pgvector**: 官方 Dockerfile 仍活跃 (最新 tag `0.8.2-pg18-trixie`), `pgvector/pgvector:pg16` 长期 LTS
- **zhparser**: amutu/zhparser v2.3 (2025-01-24) 兼容 PG 16; 官方 docker `zhparser/zhparser:bookworm-16` 可用
- **SCWS** (zhparser 依赖): 1.2.3 (2015) 长期稳定, 无 PG 版本耦合

## 2. 选项对比矩阵

| 维度 | A1 (基底=pgvector) | A2 (基底=zhparser) | B (现成复合镜像) |
|------|-------------------|-------------------|------------------|
| 可行性 | ✓ | ✓ | ✗ (镜像不存在) |
| 镜像基底维护方 | pgvector 团队 (核心依赖) | zhparser/amutu (Chinese FTS 个人项目) | — |
| Dockerfile 行数 | ~25-30 | ~15-20 (pgvector 二进制可 COPY) | — |
| CI 构建增量耗时 | 1-2 min (首次, 之后 cached) | 1-2 min | 0 (但镜像不存在) |
| 长期演进风险 | 低 (pgvector 是主事实来源) | 中 (zhparser 上游若停更项目被动) | — |
| 上游 PG 版本升级跟随 | 跟随 pgvector tag, 自动获益 | 跟随 zhparser tag, 略滞后 | — |
| 项目语义对齐 | ✓ 主依赖在前 | ✗ 辅助依赖在前 | — |

## 3. 推荐 — 选 A1

**推荐路径**: A1 — 基于 `pgvector/pgvector:pg16` 自建 `docker/db.Dockerfile`, 在 pgvector 基底上叠加 SCWS + zhparser 编译层.

**理由**:
- pgvector 是项目语义检索的主依赖, 把它放基底符合主→辅的依赖层次
- pgvector 官方维护远超 zhparser 个人项目, 长期演进风险更低
- abcfy2/docker_zhparser Debian 变体已验证 SCWS+zhparser 在 postgres:16-bookworm 上可编译, 复用其编译指令风险极小
- 镜像构建增量在 CI 首次构建 1-2 分钟, buildx cache 后即时复用, 成本可接受

## 4. 实施草案 (供 B-032 实施任务参考)

### 4.1 新建 `docker/db.Dockerfile`

```dockerfile
FROM pgvector/pgvector:pg16

ARG SCWS_VERSION=1.2.3

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        postgresql-server-dev-16 \
        ca-certificates \
        wget \
        git; \
    \
    # Build SCWS \
    cd /tmp; \
    wget -q "http://www.xunsearch.com/scws/down/scws-${SCWS_VERSION}.tar.bz2"; \
    tar -xjf "scws-${SCWS_VERSION}.tar.bz2"; \
    cd "scws-${SCWS_VERSION}"; \
    ./configure --prefix=/usr/local; \
    make -j"$(nproc)"; \
    make install; \
    \
    # Build zhparser \
    cd /tmp; \
    git clone --depth=1 https://github.com/amutu/zhparser.git; \
    cd zhparser; \
    SCWS_HOME=/usr/local make -j"$(nproc)"; \
    SCWS_HOME=/usr/local make install; \
    \
    # Cleanup \
    apt-get remove -y --purge build-essential postgresql-server-dev-16 wget git; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/* /tmp/scws-* /tmp/zhparser; \
    ldconfig
```

### 4.2 `docker-compose.yml` 改造

```yaml
services:
  db:
    build:
      context: .
      dockerfile: docker/db.Dockerfile
    image: intellisource/db:pg16-pgvector-zhparser
    # ... 其余配置不变
```

### 4.3 migration 001 去 EXCEPTION 包裹

```sql
-- 现状
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS zhparser;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'zhparser unavailable, falling back to simple parser';
END $$;

-- 改为
CREATE EXTENSION IF NOT EXISTS zhparser;
```

### 4.4 `storage/vector.py` FTS 配置切换

```python
# 现状 (B-031 阶段 4 修正 #25)
- websearch_to_tsquery('simple', :query)
+ websearch_to_tsquery('zhparser', :query)
```

注意: PostgreSQL FTS configuration 与 parser 是两个层级 — 需要先 `CREATE TEXT SEARCH CONFIGURATION zhparser (PARSER = zhparser)` (migration 001 已含), 然后 SQL 中用 `'zhparser'` 引用 configuration 名.

### 4.5 验证清单

- 步骤 1 `SELECT extname FROM pg_extension` 输出含 `zhparser`
- 步骤 1 `\dF` 输出含 `zhparser` text search configuration
- storage/vector.py 单测覆盖中文 query (如 "搜索 引擎") 走分词路径
- B-031 步骤 10 重跑中文 query 时 FTS 返回非 0 结果
- 2790 PASS unit baseline 不退化

## 5. 风险与回滚

### 风险
- **R-1**: pgvector 官方 image 偶尔 retag pg16 (如 `0.8.0` → `0.8.1`) 导致基底变化 → 缓解: 锁定 digest 而非 tag
- **R-2**: SCWS 1.2.3 上游 URL (xunsearch.com) 失联 → 缓解: 备份到项目 vendor/ 或镜像仓库
- **R-3**: CI 首次构建耗时增加 1-2 分钟 → 缓解: buildx cache + 镜像推送到 ghcr.io 后, 后续 job 直接 pull

### 回滚
- 任意一步 fail → docker-compose `db` 服务 image 回退到 `pgvector/pgvector:pg16`
- migration 001 EXCEPTION 包裹保留为 git history 一键还原
- storage/vector.py FTS configuration 从 zhparser 回退到 simple 是单行 diff

## 6. 决策记录

- **考虑过的备选**: A2 (基底=zhparser), B (现成复合镜像)
- **未选 A2 原因**: pgvector 是主事实来源, 反向叠加语义不自然; zhparser 上游维护方相对单点
- **未选 B 原因**: 调研后确认公开域不存在该镜像
- **重新评估条件**: 若上游出现维护良好的 pgvector + zhparser 复合 image (Star > 100 + 近 6 月有 commit), 可切换到选 B 减少自维护负担

## 7. 来源

- [pgvector/pgvector Docker Hub](https://hub.docker.com/r/pgvector/pgvector) — 官方镜像, Debian bookworm 基底
- [pgvector Dockerfile (master)](https://github.com/pgvector/pgvector/blob/master/Dockerfile) — `FROM postgres:$PG_MAJOR-$DEBIAN_CODENAME`, 默认 bookworm; build tools 在编译后 remove
- [amutu/zhparser README](https://github.com/amutu/zhparser) — 上游, v2.3 (2025-01-24), 官方 docker `zhparser/zhparser:bookworm-16`
- [abcfy2/docker_zhparser](https://github.com/abcfy2/docker_zhparser) — 社区, PG 13-17, Debian+Alpine 双变体, CI 自动构建
- [abcfy2/docker_zhparser Dockerfile.debian](https://github.com/abcfy2/docker_zhparser/blob/main/Dockerfile.debian) — SCWS 1.2.3 + zhparser 源码编译参考实现
