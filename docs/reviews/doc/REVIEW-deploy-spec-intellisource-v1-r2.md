---
id: "review-deploy-spec-intellisource-v1-r2"
doc_type: review
author: reviewer
status: approved
deps: ["deploy-spec-intellisource-v1"]
---

# 文档审查报告：deploy-spec-intellisource-v1 (r2)

**审查对象**: `docs/deploy-spec/deploy-spec-intellisource-v1.md`（755 行，r1 后由 devops 修订）
**审查层**: Layer 2 增量审查（仅复核 r1 报告 9 项问题的修订）
**审查日期**: 2026-05-26
**审查者**: orchestrator inline (基于 r1 reviewer 报告项逐条对位核查)
**verdict**: **approved**

---

## r1 → r2 修订核查

| 编号 | r1 严重等级 | r2 修订结果 | 核查依据 |
|------|------------|-------------|---------|
| R-001 | HIGH | ✅ 已修 | §3.6 回滚改为 `git checkout "${PREV_TAG}" && docker compose build api worker` 模式（选项 B），原 `-e "IMAGE_TAG=..."` 无效命令已删除；prebuilt 镜像（选项 A）改造步骤以说明形式保留 |
| R-002 | HIGH | ✅ 已修 | §3.4 smoke grep 仅 `grep -E "run_pipeline"`；不存在的 `collect_source` / `distribute_content` 已删除 |
| R-003 | MEDIUM | ✅ 已修 | §3.4 smoke 指标 grep 补全至 11 项，与 §3.5 严格 1:1（`http_request_duration_seconds` / `llm_call_latency_seconds` / `celery_task_failures_total` / `scheduler_beat_sync_failed_total` 全部 grep 已落地）|
| R-004 | MEDIUM | ✅ 已修 | §3.4 注释改为"metrics 端点为公开可达（已在 AuthMiddleware 中豁免认证）"；§2.4 轮换步骤 4 已去除误导性 `X-API-Key` 头 |
| R-005 | MEDIUM | ✅ 已修 | §1.1 前置条件加入 zhparser 要求并 reference arch#§1.4；§4.1 发布检查清单增加 `SELECT extname FROM pg_extension WHERE extname = 'zhparser'` 验证项 |
| R-006 | MEDIUM | ✅ 已修 | §2.5 队列名改为 `queue.priority.high / queue.priority.normal / queue.priority.low`；说明容器化部署下默认无需 `--queues` |
| R-007 | LOW | ✅ 已修 | §4.4 "六项"→ "11 项"（与修订后 §3.4 严格匹配）|
| R-008 | LOW | ✅ 已修 | §2.4 密钥清单表新增 `IS_WECHAT_WEBHOOK_TOKEN` / `IS_WEWORK_WEBHOOK_TOKEN` 两行 |
| R-009 | LOW | ✅ 已修 | §4.5 promtool 检查项已内联可执行的 `docker run --rm -v ... prom/prometheus:v2.55.1 promtool check rules ...` 命令 |

---

## 反模式自检（anti-regression）

| 关键词 | 期望 | 实测 |
|--------|------|------|
| `collect_source` / `distribute_content` | 0 命中 | 0 命中 ✅ |
| `-e "IMAGE_TAG=` | 0 命中 | 0 命中 ✅ |
| 字面"六项" | 0 命中 | 0 命中 ✅ |
| `git checkout` (rollback redesign) | ≥1 命中 | 1 命中 ✅ |
| `run_pipeline` (smoke grep) | ≥1 命中 | 多处 ✅ |
| `zhparser` (R-005) | §1.1 + §4.1 双处 | §1.1 + §4.1 命中 ✅ |
| `queue.priority.` | 表格 + 启动参数 ≥1 | 多处命中 ✅ |
| `IS_WECHAT_WEBHOOK_TOKEN` / `IS_WEWORK_WEBHOOK_TOKEN` | §2.4 密钥清单 | 两行新增 ✅ |

---

## 新发现问题

无。Layer 1 仍 PASS；仅余唯一 WARN「文档行数(755) 超 300 行阈值」为软建议（多功能复合文档保持单卷便于交叉引用，决策保留）。

---

## 审查总结

r2 修订对 r1 全部 9 项问题（2 HIGH + 4 MEDIUM + 3 LOW）逐条闭环，文档与实现侧 `docker-compose.yml` / `scheduler/tasks.py` / `scheduler/queues.py` / `api/middleware.py` / `alembic/versions/001_initial_schema.py` 全部对齐。SBOM / 漏洞扫描 / 密钥管理章节完整覆盖上线门禁要求；B-014 metric 列表 11 项与 B-015 promtool 检查双处对齐。

**verdict**: **approved**

后续动作（由 orchestrator 执行）：
- 将 deploy-spec-intellisource-v1.md frontmatter `status: draft` → `approved`
- 同步 CLAUDE.md §项目状态 与 PROJECT-STATE.md 中 deploy-spec 状态
- BACKLOG 中删除 B-010 条目；B-014 / B-015 标记可独立推进
