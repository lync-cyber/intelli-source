---
id: remote-host-readiness-v1
doc_type: deploy-spec
author: devops
status: draft
deps: [deploy-spec-intellisource-v1, pre-deploy-walkthrough-v1]
consumers: [devops]
---

# 远端部署主机就绪指南：IntelliSource

> **定位**：本文档填补 README §快速上手（localhost 本地）与公网可访问的远端生产部署之间的"主机层"空白。覆盖反向代理、TLS/域名、防火墙、webhook 公网可达性、进程托管、冷启动代价六个方面。
>
> **适用读者**：负责在云主机或裸金属服务器上部署 IntelliSource 的 DevOps 工程师。
>
> **前置条件**：已完成 `PRE-DEPLOY-WALKTHROUGH.md` 全部 20 步本地 go/no-go 验证，服务可在 `localhost:8000` 正常响应。
>
> **不覆盖**：应用层部署矩阵、密钥注入、数据库迁移、回滚 SOP、CI/CD 流水线——这些见 [deploy-spec-intellisource-v1](../deploy-spec/deploy-spec-intellisource-v1.md)；功能性烟测见 [PRE-DEPLOY-WALKTHROUGH.md](PRE-DEPLOY-WALKTHROUGH.md)。

---

## 目录

- [§1 主机层缺口清单](#1-主机层缺口清单)
- [§2 反向代理](#2-反向代理)
- [§3 TLS 与域名](#3-tls-与域名)
- [§4 防火墙](#4-防火墙)
- [§5 入站 webhook 公网可达性](#5-入站-webhook-公网可达性)
- [§6 进程托管（systemd）](#6-进程托管systemd)
- [§7 冷启动与回滚代价](#7-冷启动与回滚代价)
- [§8 交叉引用](#8-交叉引用)

---

## 1 主机层缺口清单

以下是从 localhost 快速上手迁移到公网远端部署时，应用层文档（`deploy-spec`、`PRE-DEPLOY-WALKTHROUGH`）未覆盖的主机层配置项：

| 缺口 | 风险 | 本文覆盖章节 |
|------|------|-------------|
| `docker-compose.yml` 中 `api` 服务 `ports: 8000:8000` 将 API 直接暴露到公网 | 无 TLS、无反代过滤，API key 以明文在公网传输 | §2、§4 |
| 无 HTTPS 终结，所有流量明文 | 凭据泄露、中间人攻击 | §3 |
| 防火墙未配置，8000 等内部端口对公网开放 | 攻击面扩大 | §4 |
| webhook 回调（企业微信/公众号）要求公网 HTTPS URL | 渠道后台无法验证并路由入站消息 | §5 |
| 无进程守护，主机重启后栈不自启 | 不可用 | §6 |
| 远端首次构建和回滚需重建 zhparser（源码编译） | 冷启动耗时不可预期 | §7 |

---

## 2 反向代理

### 2.1 问题

`docker/docker-compose.yml` 的 `api` 服务当前配置：

```yaml
ports:
  - "8000:8000"
```

在远端主机上这等同于将未加密 HTTP 端口直接对公网开放。**建议**将 `ports` 改为 `expose`（仅 Docker 内部网络可见），由反代独占 80/443 接收外部流量：

```yaml
# 建议改法（不强制，按运维实际情况决策）
expose:
  - "8000"
# 删除 ports: 块，反代通过 Docker 内部网络 http://api:8000 访问
```

> 如果修改 compose 文件，必须同步检查 `PRE-DEPLOY-WALKTHROUGH.md` 中所有用 `localhost:8000` 的 smoke 测试步骤，改为通过反代入口验证。

### 2.2 Nginx 最小配置

适用：系统已安装 nginx，TLS 证书已就绪（见 §3）。

```nginx
# /etc/nginx/sites-available/intellisource
server {
    listen 80;
    server_name your-domain.example.com;
    # 将所有 HTTP 请求重定向到 HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name your-domain.example.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.example.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # 健康检查（公开路径，无需 API key）
    location /health {
        proxy_pass         http://127.0.0.1:8000/health;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    # Prometheus metrics（建议限制来源 IP 或通过 BasicAuth 保护）
    location /api/v1/metrics {
        # 示例：仅允许监控系统 IP 访问（按实际情况修改）
        # allow 10.0.0.0/8;
        # deny all;
        proxy_pass         http://127.0.0.1:8000/api/v1/metrics;
        proxy_set_header   Host $host;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    # 企业微信入站 webhook 回调
    location /api/v1/webhooks/wework/ {
        proxy_pass         http://127.0.0.1:8000/api/v1/webhooks/wework/;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }

    # 微信公众号入站 webhook 回调
    location /api/v1/webhooks/wechat/ {
        proxy_pass         http://127.0.0.1:8000/api/v1/webhooks/wechat/;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }

    # 其他 API 请求（需 X-API-Key 头，由应用层校验）
    location /api/ {
        proxy_pass         http://127.0.0.1:8000/api/;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        # SSE 流式响应（/search/chat/stream）
        proxy_buffering    off;
        proxy_cache        off;
    }

    # Chat Web UI
    location /chat {
        proxy_pass         http://127.0.0.1:8000/chat;
        proxy_set_header   Host $host;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

启用并重载：

```bash
sudo ln -s /etc/nginx/sites-available/intellisource /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 2.3 Caddy（替代方案，自动 TLS）

Caddy 内置 Let's Encrypt 自动证书，配置更简洁：

```caddyfile
# /etc/caddy/Caddyfile
your-domain.example.com {
    # 健康检查
    handle /health {
        reverse_proxy localhost:8000
    }

    # webhook 回调路径
    handle /api/v1/webhooks/* {
        reverse_proxy localhost:8000
    }

    # SSE 流式响应
    handle /api/v1/search/chat/stream {
        reverse_proxy localhost:8000 {
            flush_interval -1
        }
    }

    # 其余所有请求
    handle {
        reverse_proxy localhost:8000
    }
}
```

```bash
sudo systemctl reload caddy
```

Caddy 会自动获取并续期 Let's Encrypt 证书；无需额外执行 certbot。

> **提示**：Caddy 方案与 §3 的 certbot 步骤二选一，无需同时部署。

---

## 3 TLS 与域名

### 3.1 域名 A 记录

在域名注册商处将 `your-domain.example.com` 的 A 记录指向主机公网 IP。TTL 建议 300 秒（方便迁移），稳定后可调高。

```
your-domain.example.com.  300  IN  A  <主机公网 IP>
```

验证解析生效：

```bash
dig +short your-domain.example.com
# 应返回主机公网 IP
```

### 3.2 Let's Encrypt（certbot + nginx）

适用于选择 nginx 方案（§2.2）的场景：

```bash
# 安装 certbot
sudo apt install certbot python3-certbot-nginx

# 获取证书并自动改写 nginx 配置
sudo certbot --nginx -d your-domain.example.com

# 验证自动续期定时任务
sudo systemctl status certbot.timer
# 或：
sudo certbot renew --dry-run
```

certbot 会将证书写入 `/etc/letsencrypt/live/your-domain.example.com/`，并向 crontab 或 systemd timer 注册自动续期任务（默认每 12 小时检查一次，到期前 30 天续期）。

### 3.3 证书就绪验证

```bash
curl -I https://your-domain.example.com/health
# 期望：HTTP/2 200，响应头含 strict-transport-security
```

---

## 4 防火墙

### 4.1 目标规则

公网只放行：

| 端口 | 协议 | 用途 |
|------|------|------|
| 22 | TCP | SSH 管理 |
| 80 | TCP | HTTP → 重定向到 HTTPS |
| 443 | TCP | HTTPS（反代入口） |

关闭对外：8000（API）、9090（Prometheus）、5432（DB）、6379（Redis）——这些端口仅 Docker 内部网络使用。

### 4.2 UFW 配置

```bash
# 重置为默认拒绝（慎用：确认 SSH 端口先放行，否则断连）
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 放行 SSH（若改过默认端口，替换 22）
sudo ufw allow 22/tcp

# 放行反代入口
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# 明确拒绝内部端口（docker-compose 默认 8000:8000 映射绕过 iptables INPUT 链，
# 需用 DOCKER-USER chain 或删除 ports 映射；下方规则仅作 INPUT 层保险）
sudo ufw deny 8000/tcp
sudo ufw deny 9090/tcp

# 启用
sudo ufw enable
sudo ufw status verbose
```

> **重要**：Docker 的端口映射（`ports: 8000:8000`）通过直接插入 iptables FORWARD/NAT 规则绕过 UFW 的 INPUT 链，导致 UFW 的 deny 8000 **不能**阻止外部直接访问 8000。根本解法是删除 `ports` 映射，改为 `expose`（见 §2.1），让反代通过 Docker 内部网络 `http://api:8000` 或 `http://127.0.0.1:8000` 访问（若反代在宿主机运行）。
>
> 若暂时保留 `ports: 8000:8000`，可在 UFW 的 `before.rules` 中通过 iptables DOCKER-USER 链过滤，但这超出本文档范围；**最简且最安全的做法是删除 `ports` 映射**。

### 4.3 云安全组（AWS/阿里云等）

如果主机位于云平台，需同步在安全组（Security Group）层面只放行 22/80/443，并确认 8000/9090 等端口的入站规则已删除。UFW 与安全组是独立的两层，建议同时配置形成双重防护。

---

## 5 入站 webhook 公网可达性

### 5.1 链路概览

企业微信和微信公众号的 webhook 回调要求平台能从公网主动访问 IntelliSource 的回调端点，链路为：

```
企业微信/公众号服务器
        │  HTTPS POST
        ▼
your-domain.example.com/api/v1/webhooks/wework/   (或 /wechat/)
        │  nginx/Caddy 反代
        ▼
容器内 api:8000/api/v1/webhooks/wework/
        │  签名验证（IS_WECOM_TOKEN + IS_WECOM_ENCODING_AES_KEY）
        ▼
业务处理
```

### 5.2 docker/.env 中的公网回调 URL

在 `docker/.env` 中设置公网域名（不是 `localhost`）：

```bash
# 企业微信入站 webhook（AES 加密回调）
# 在企业微信后台"接收消息 → 接收消息服务器地址"填写此 URL
IS_WECOM_CORP_ID=ww<your-corp-id>          # 与 IS_WEWORK_CORP_ID 相同值
IS_WECOM_TOKEN=<your-token>                # 企业微信后台生成的 Token
IS_WECOM_ENCODING_AES_KEY=<43-char-key>   # 企业微信后台生成的 EncodingAESKey

# 微信公众号 webhook Token（后台"服务器配置 → Token"）
IS_WECHAT_WEBHOOK_TOKEN=<your-token>
```

回调 URL 示例（在渠道后台填写）：

| 渠道 | 回调 URL |
|------|---------|
| 企业微信（应用回调） | `https://your-domain.example.com/api/v1/webhooks/wework/` |
| 企业微信（客服回话） | `https://your-domain.example.com/api/v1/webhooks/wework/kf/` |
| 微信公众号 | `https://your-domain.example.com/api/v1/webhooks/wechat/` |

### 5.3 配置验证步骤

1. 确认 TLS 可访问：`curl -I https://your-domain.example.com/health` 返回 200。
2. 在企业微信/公众号后台填写回调 URL 后点击"验证"或"保存"——平台会发送一条签名验证 GET 请求，应用需正确返回 echostr。
3. 查看 API 容器日志确认签名验证通过：

   ```bash
   docker compose -f docker/docker-compose.yml logs -f api | grep webhook
   ```

4. 发送测试消息或触发推送，在日志中确认入站消息被正确路由处理。

> **关键约束**：企业微信和微信公众号的回调**必须是公网可达的 HTTPS URL**，localhost / 内网 IP 均无法通过平台验证。本地开发调试可借助 ngrok 或 Cloudflare Tunnel 临时暴露，生产环境必须走正式域名 + TLS。

---

## 6 进程托管（systemd）

### 6.1 目标

用 systemd unit 托管 `docker compose up`（或 `intellisource up`），实现开机自启和崩溃后自动重启。

### 6.2 systemd unit 模板文件

systemd unit 定义位于 `docker/intellisource.service`。该文件使用 `__WORKING_DIRECTORY__` 占位符，由 `scripts/provision-remote.sh` 在安装时替换为实际仓库路径（默认 `/opt/intellisource`）。

手动安装（不使用置备脚本）：

```bash
# 将占位符替换为实际路径后安装
sudo sed 's|__WORKING_DIRECTORY__|/opt/intellisource|g' \
    docker/intellisource.service \
    > /etc/systemd/system/intellisource.service
sudo chmod 644 /etc/systemd/system/intellisource.service
sudo systemctl daemon-reload
sudo systemctl enable intellisource.service
sudo systemctl start intellisource.service
sudo systemctl status intellisource.service
```

查看日志：

```bash
sudo journalctl -u intellisource.service -f
```

### 6.3 版本钉选与溯源（registry 模式）

registry 模式以 `--no-build` 启动，主机不本地构建，因此部署版本不由构建期 `GIT_SHA` 决定，而由 `IS_IMAGE_TAG`（镜像 sha tag）决定（缺省 `latest`，生产建议钉到具体 sha）。在 `docker/intellisource.service` 以可选 `EnvironmentFile` 加载的 `/etc/intellisource/deploy.env` 中设置：

```bash
# /etc/intellisource/deploy.env
IS_IMAGE_TAG=<deployed-sha>
IS_DB_IMAGE_TAG=pg16-pgvector-zhparser
```

已部署镜像对应的提交可从镜像 `org.opencontainers.image.revision` label 回溯（构建时由 `docker/Dockerfile` 写入）：

```bash
docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
    ghcr.io/lync-cyber/intellisource:${IS_IMAGE_TAG:-latest}
```

---

## 7 冷启动与回滚代价

### 7.1 DB 镜像冷启动代价

`docker/db.Dockerfile` 的 `db` 镜像基于 `pgvector/pgvector:pg16`，在构建阶段从源码编译 SCWS（中文分词库）和 zhparser（PostgreSQL 中文全文检索扩展）：

- 编译依赖：`build-essential`、`postgresql-server-dev-16`、`autoconf`、`automake`、`libtool`、`git`
- 源码克隆：SCWS `1.2.3` + zhparser `v2.3`，各需网络下载
- 编译耗时：视主机 CPU 核数，通常 3–10 分钟

**远端首次部署**：需在目标主机完整构建 `db` 镜像（`docker compose build db`），不能直接拉取 dockerhub 标准 pgvector 镜像。

**回滚场景**：若目标主机没有已缓存的 `intellisource/db` 镜像层（例如清理了 docker cache 或迁移到新主机），回滚也需重新触发完整编译。这是当前 `build:` 模式的固有代价。

### 7.2 缓解建议（先构建后切换）

在 registry 镜像方案（见 §7.3）落地之前，建议：

1. **提前构建**：在正式切流量前，在目标主机预先构建 `db` 镜像并验证：

   ```bash
   docker compose -f docker/docker-compose.yml build db
   docker images intellisource/db
   ```

2. **保留旧镜像层**：不要在正式部署前执行 `docker system prune`，保留旧版本镜像缓存，回滚时可复用。

3. **分阶段构建**：可将 `db` 镜像构建与 `api/worker` 镜像构建分开执行，互不阻塞：

   ```bash
   # 先构建 db（耗时较长）
   docker compose -f docker/docker-compose.yml build db &
   # 并行构建 api（依赖 uv sync，较快）
   docker compose -f docker/docker-compose.yml build api worker beat migrate
   wait
   ```

4. **回滚时保留数据卷**：回滚 `db` 服务时，务必保留 `db_data` 命名卷；只切换镜像 tag，不重建卷：

   ```bash
   docker compose -f docker/docker-compose.yml stop db
   # 修改 docker-compose.yml 中 db service 的 image tag（如有）
   docker compose -f docker/docker-compose.yml up -d db
   ```

### 7.3 Registry 镜像模式（GHCR）

预构建镜像已推送到 GHCR，消除远端 zhparser 源码编译步骤。

**镜像地址**：

| 镜像 | 说明 |
|------|------|
| `ghcr.io/lync-cyber/intellisource:<sha>` | App 镜像（api / worker / beat / migrate） |
| `ghcr.io/lync-cyber/intellisource:latest` | App 镜像最新 main 构建 |
| `ghcr.io/lync-cyber/intellisource-db:pg16-pgvector-zhparser` | DB 镜像（pgvector + zhparser） |
| `ghcr.io/lync-cyber/intellisource-db:<sha>` | DB 镜像特定 sha 版本 |

**拉取镜像**（`docker/docker-compose.registry.yml` 作为 override）：

```bash
# 登录 GHCR（需具备 packages:read 权限的 PAT 或 GitHub Actions GITHUB_TOKEN）
echo $CR_PAT | docker login ghcr.io -u <github-username> --password-stdin

# 拉取全部 5 个服务镜像
docker compose \
    -f docker/docker-compose.yml \
    -f docker/docker-compose.registry.yml \
    pull

# 启动（--no-build 确保使用拉取的镜像，不触发本地构建）
docker compose \
    -f docker/docker-compose.yml \
    -f docker/docker-compose.registry.yml \
    up -d --no-build
```

指定特定 sha tag（秒级回滚）：

```bash
IS_IMAGE_TAG=<prev-sha> docker compose \
    -f docker/docker-compose.yml \
    -f docker/docker-compose.registry.yml \
    up -d --no-build --no-deps --force-recreate api worker
```

**置备脚本**：`scripts/provision-remote.sh` 自动执行上述 pull 步骤，以及防火墙、systemd unit 安装等所有主机层配置：

```bash
sudo bash scripts/provision-remote.sh --working-dir /opt/intellisource
# 预演（不实际修改系统）：
sudo bash scripts/provision-remote.sh --working-dir /opt/intellisource --dry-run
```

---

## 8 交叉引用

| 主题 | 文档 | 章节 |
|------|------|------|
| 应用层部署架构与网络端口矩阵 | `deploy-spec-intellisource-v1.md` | §2.1 部署架构 |
| 环境变量完整清单（IS_* 变量） | `deploy-spec-intellisource-v1.md` | §2.3 环境变量清单 |
| 密钥清单与轮换策略 | `deploy-spec-intellisource-v1.md` | §2.4 密钥清单与轮换 |
| 镜像构建（GIT_SHA / SBOM / 漏洞扫描） | `deploy-spec-intellisource-v1.md` | §1 构建流程 |
| 生产回滚 SOP | `deploy-spec-intellisource-v1.md` | §3.5 回滚 SOP |
| 功能性烟测（20 步 go/no-go） | `PRE-DEPLOY-WALKTHROUGH.md` | 全文 |
| 本地快速上手（localhost 流程） | `README.md` | §快速上手（新用户）|
| embedding 冷启动（TEI ~1105s） | `docker/docker-compose.yml` | `embedding.healthcheck.start_period` |
| zhparser 源码编译细节 | `docker/db.Dockerfile` | 全文 |
