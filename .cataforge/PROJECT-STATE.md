# CataForge

> 本文件由 orchestrator 在主对话中持续维护，与 CLAUDE.md §项目状态 保持同步。两份文件中 CLAUDE.md 为人面向状态、本文件为框架内部镜像。

## 项目信息

- 项目名称: IntelliSource
- 技术栈: Python 3.11+ / FastAPI / Celery + Redis / PostgreSQL + pgvector / SQLAlchemy 2.0 / litellm
- 运行时: claude-code
- 框架版本: 0.4.1
- 语言定位: 中文框架（提示词/文档/交互用中文；代码/变量/CLI参数用英文）
- 执行模式: standard
- 阶段配置:
  - ui_design: N/A（backend-only 项目）
  - testing: 启用
  - deployment: 启用

## 项目状态 (orchestrator专属写入区，其他Agent禁止修改)

- 当前阶段: backlog-burndown — B-010 Deploy spec 闭环；剩余 B-011 / B-012 polish + B-014 / B-015 staging 验证 + B-016~B-018 框架学习 + B-019 上游反馈
- 下一步行动: B-016~B-018 框架学习 EXP 应用；或 B-019 上游反馈 triage
- 已完成阶段: [bootstrap, requirements, architecture, ui_design(N/A), dev_planning, sprint-1..7, retrospective, testing, sprint-7r, sprint-8r, sprint-9, sprint-8 P2, audit-fix-pr53, audit-fix-pr54, backlog-b001-b002, backlog-b003-b006, backlog-b007, backlog-b009-decision, backlog-b029-b030-polish, backlog-b008, backlog-arch-governance, backlog-b010]
- 当前 Sprint: N/A（backlog-burndown 模式，无 Sprint 推进）
- 当前回归基线: 2838 PASS / 0 FAIL / 0 skip / 0 xfail / 51 deselected；mypy --strict + ruff + lint-imports 8/8 + deptry + vulture clean
- 文档状态:
  - prd: approved
  - arch: approved
  - ui-spec: N/A
  - dev-plan: approved (主卷 + s1~s7 + s7r + s8r + s9 全 approved；dev-plan-s8 = draft)
  - test-report: approved
  - deploy-spec: approved (本次会话 B-010 闭环 — `deploy-spec-intellisource-v1` 755 行 + changelog；r1 needs_revision (2H+4M+3L) → r2 全部修复 → r2 audit approved)
  - backlog: approved
- audit-fix-pr53 闭环 (commit 7e10e77): F-01~F-11 P0 + F-12~F-27 P1 + F-28~F-48 P2/P3 — 39 项，详见 PR #53 描述
- audit-fix-pr54 闭环 (commit 31bddde): F-11 receiver_id / F-25 health 豁免 / F-42 PG /search 真链路 / idempotency RuntimeWarning / F-20+F-21 health 并发 / F-22 metrics 4 路径 / F-23 trace_id 跨 worker / F-24 alerts.yml / F-26 priority queue / F-27 content_not_found / 2 xfail (HybridIndex tags/date) / 1 placeholder skip 删 / 46 docker skip 转 deselect — 14 项
- backlog-b001-b002 闭环: B-001 `/search/chat/stream` 切 `AgentRunner.run_flexible_stream` (新增 RAG-aware 流式入口 + LLMGateway.stream_complete 支持 messages 参数 + FlexibleLoop.run_stream) + B-002 `SearchRequest.date_from/to: str → datetime`（非法值 422 而非 500）；SSE 事件契约 step/sources/token/done/error
- backlog-b003-b006 闭环 (inline 批次，3 batch): B-006 storage fixture ARRAY→JSON conftest mutation (单跑 PASS) / B-003 `intellisource_health_status` labeled gauge + HealthDegradedFor5m alert / B-004 `scheduler.dispatch.send_task_with_trace()` facade + guardrail (src/ 范围) / B-005 MetricsCollector labeled counter (pushes_total{channel,status} + llm_calls_total{model})；code-review verdict approved_with_notes → R-001 inline 修订 (counter+gauge 子系统 labelnames 强约束对齐) → 最终 approved；详见 [docs/reviews/code/CODE-REVIEW-backlog-p1-r1.md](../docs/reviews/code/CODE-REVIEW-backlog-p1-r1.md)
- backlog-b007 闭环: LLMGateway 单类 732 行拆为 6 mixin (`_complete` 200 / `_chat` 200 / `_stream` 185 / `_queue` 54 / `_metrics` 44 / `_protocols` 80) + facade `__init__.py` 120 行；`_GatewayProtocol` mypy --strict self-type 兜底；公共 API (complete/chat/stream_complete) 零破坏；2820 PASS 不退化；code-review verdict approved 0 issue；详见 [docs/reviews/code/CODE-REVIEW-B-007-r1.md](../docs/reviews/code/CODE-REVIEW-B-007-r1.md)
- backlog-b009-decision 闭环 (decision-only, reaffirm 选项 ②): PRD AC-063 [ASSUMPTION] 已在 sprint-9 锁定 YAML-as-source-of-truth；pipelines router 现状即决策实现 (list/detail/run, 无 HTTP CRUD)；完整 workflow CRUD (DB 存储 + 历史版本) 保留 v2+ 范畴，不立项；无代码改动；BACKLOG B-009 删除
- backlog-b008 闭环: `truncate_summary` 接入 LLM summarizer（`summarizer.structured` 模板 + `gateway.complete(response_format=json_object)` + `tool_deps` 注入）；产出 `{title, summary, timeline[], key_points[]}` 结构化摘要；3 层 fallback（LLM 异常 / JSON 解析失败 / 缺必要字段 → 回退字符串截断）；PRD AC-023 [ASSUMPTION] 移除；2834 PASS (+7 测试)
- backlog-b029-b030-polish 闭环: B-029 alerts.yml `LLMCallFailureRateHigh` + `PushFailureRateHigh` 按 `model`/`channel` label 拆分 (`sum by (model)` / `sum by (channel)` + annotations `{{ $labels.* }}` 模板化) / B-030 R-002 guardrail 注释显式化范围 + R-003 `_ALLOWED_POSIX` 精确路径匹配 + R-004 `DistributorFacade.__init__` + `LLMGateway.__init__` 集中 `register_labeled_counter` (hot-path 重复 register 移除)；2827 PASS (+7 测试)
- backlog-arch-governance 闭环: B-020~B-024 import-linter V1~V8 全部消除 (tools/ 新包 + composition 拆分 + chat_session 中性化 + config 返 Pydantic) / B-025 CI 升级为 blocking gate (`continue-on-error: false`) + pre-commit hook / B-026 DEP003 × 24 显式补 transitive deps / B-027 DEP002 × 6 dev deps 统一到 `[dependency-groups]` / B-028 vulture × 3 删除 `_unified_call_with_retry` 未消费参数；2838 PASS；详见 [docs/reviews/code/CODE-SCAN-arch-20260524-r1.md](../docs/reviews/code/CODE-SCAN-arch-20260524-r1.md)
- backlog-b010 闭环 (本次会话): devops 子代理产出 `deploy-spec-intellisource-v1` (755 行) + `changelog-intellisource-v1`；4 模板必填段 (构建流程 / 环境配置 / CI/CD 流水线 / 发布检查清单) 全覆盖；§2 含 dev/staging/prod 三环境矩阵 + zhparser DB 镜像要求 + 11 项指标家族 (B-014) + queue.priority.* 实际队列名；§3 含 promtool check rules (B-015) + SBOM (syft/buildx) + trivy/grype 门禁 + run_pipeline 唯一注册任务 smoke + git checkout+rebuild 回滚方案；§4 8 段签字含 zhparser/pgvector 双扩展验证 + webhook token 轮换。reviewer r1 = needs_revision (2 HIGH + 4 MEDIUM + 3 LOW)；devops r2 = 9 项全部闭环；orchestrator inline r2 audit = approved；详见 [docs/reviews/doc/REVIEW-deploy-spec-intellisource-v1-r1.md](../docs/reviews/doc/REVIEW-deploy-spec-intellisource-v1-r1.md) + [REVIEW-deploy-spec-intellisource-v1-r2.md](../docs/reviews/doc/REVIEW-deploy-spec-intellisource-v1-r2.md)
- Learnings Registry:
  - [RETRO-intellisource-v1.md](../docs/reviews/retro/RETRO-intellisource-v1.md) — 6 EXP (sprint-1~7)，应用决策 deferred → backlog B-016
  - [RETRO-intellisource-v1-sprint-9.md](../docs/reviews/retro/RETRO-intellisource-v1-sprint-9.md) — 2 EXP 强制立项 (EXP-005 装配缺口 5 次复发 → B-017 / EXP-006 truncation 4/4 跨 3 角色)
  - [RETRO-intellisource-v1-sprint-8.md](../docs/reviews/retro/RETRO-intellisource-v1-sprint-8.md) — 1 正向 EXP-007 立项 (Mid-Progress Drop Contract 通用化 → B-018)
  - SKILL-IMPROVE-*.md — 8 份建议
- 上游反馈: [docs/feedback/](../docs/feedback/) — 1 bug + 1 suggest (B-019 未闭环)
- Backlog 总入口: [docs/BACKLOG-intellisource-v1.md](../docs/BACKLOG-intellisource-v1.md) — 剩余 B-011 / B-012 / B-014 / B-015 / B-016~B-019，按 P3 polish + staging 验证 + 框架学习 + 上游反馈 分组
- 框架升级备注: framework.json 版本 0.4.1（autocrlf=false + cataforge mirror sync 完成于 commit a2b9095）
