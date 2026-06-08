---
id: backlog-intellisource-v1
doc_type: backlog
author: orchestrator
status: approved
deps: []
---

# IntelliSource v1 Backlog

> 维护：完成项请直接删除条目（闭环 prose 归档到 [HISTORY](HISTORY-intellisource-v1.md) + [CORRECTIONS-LOG](reviews/CORRECTIONS-LOG.md) + git），新增项按优先级插入。本文件只保留**仍需动作**的条目。
> release 已放行（B-031 用户 2026-05-29 签字 + 2026-06-08 大规模重构后真起栈走查全绿）；剩余全部非阻塞。

## 优先级语义

- **P0 — 阻塞**：影响生产正确性 / 安全 / 上线 go-no-go
- **P1 — 阻塞质量**：可观测性、性能边界、合规
- **P2 — 架构 / 功能完整性**：上帝类拆分、PRD 接受项功能缺口
- **P3 — 优化 / 规约**：硬编码、弱断言、风格

---

## P0 — 上线门禁（常驻 release-gate）

### B-031 执行 PRE-DEPLOY-WALKTHROUGH（pre_deploy 人工 go/no-go）
- **性质**：release-gate 而非一次性任务 —— 每次 prod 发布前或架构 / 关键模块大改后重新执行
- **关联**：[docs/deploy/PRE-DEPLOY-WALKTHROUGH.md](deploy/PRE-DEPLOY-WALKTHROUGH.md) / [deploy-spec §3.3](deploy-spec/deploy-spec-intellisource-v1.md)
- **现状**：2026-05-29 全 20 步签字 GO（B-059/B-060/B-040 等走查暴露项已闭环）；2026-06-08 大规模重构后复跑核心管线 + 受影响面全 GREEN 无回归（[CORRECTIONS-LOG 2026-06-08](reviews/CORRECTIONS-LOG.md)）
- **重新评估触发**：下次 prod 发布 / arch 大改

---

## 本会话已修复（待提交）

> 代码 + 测试 + 全门禁（mypy --strict / ruff / lint-imports 12/12）均绿；工作区在 main 未提交，提交前需拉 feature 分支。提交合入后删除本节对应条目。

- **B-064** (P3, observability)：`pushes_total` 跨进程暴露 —— [facade.py](../src/intellisource/distributor/facade.py) `_record_push_outcome`/`_register_metrics` 镜像写 `RedisMetricStore`；[system.py](../src/intellisource/api/routers/system.py) `_format_prometheus` 精准抑制"shared 已拥有的空 labeled counter"以避免重复 `# TYPE`（不误伤 llm_calls_total 等 B-014 族）
- **B-065** (P2, 开箱可用性)：内置 topic `enable` 开箱即空 digest —— [topic/models.py](../src/intellisource/topic/models.py) `build_subscription` 在 match_rules 缺 `source_names` 时注入本主题全部源名（强约束，不依赖 source→processed 标签传播）
- **B-066** (P2, 推送正确性)：realtime distribute 把 daily/weekly 订阅双发 —— [content.py](../src/intellisource/storage/repositories/content.py) `get_with_source_and_subscriptions` 的 `subscription_id=None` 广播分支加 `frequency=='realtime'` 过滤（显式 id 分支不受限）
- **TaskChain 进度回填** (LOW)：长链路 `completed_steps` 全程 0/N —— [task_chain.py](../src/intellisource/storage/repositories/task_chain.py) `update_status` 加可选 `completed_steps`，[tasks.py](../src/intellisource/scheduler/tasks.py) 成功分支传 `total_steps`（终态显示 N/N）

---

## 剩余项目级真债（非阻塞，保留跟踪）

- **BGE-M3 本地 embedding 暂缓**：deepseek 无 embedding 端点，`task_type=embed` graceful 降级（向量检索降级，zhparser FTS 补偿）。引入本地 embedding 服务后接 `_EmbedMixin.embed` 路由即可恢复 `processed_contents.embedding` 写入与 semantic 检索

---

## 已闭环（归档）

完整闭环 prose 见 [HISTORY-intellisource-v1.md](HISTORY-intellisource-v1.md) + 各 PR/commit + [CORRECTIONS-LOG](reviews/CORRECTIONS-LOG.md)。已闭环 B 号（删除条目仅保留编号便于回溯）：

- **audit (PR #53/#54)**：F-01 ~ F-49
- **早期质量项**：B-001 ~ B-010 / B-029 / B-030
- **B-031 走查 + 部署破口**：B-032 ~ B-049（含 B-037 worker bridge / B-039 tools 去重 / B-041 DeepSeek V4 / B-042 CostTracker / B-044 summarizer / B-045 embedder）
- **配置 UX + 三入口对齐**：B-050 / B-051 / B-054 ~ B-058
- **observability + 架构治理**：B-011 ~ B-015 / B-020 ~ B-028 / B-040 / B-060
- **稳定性 + 走查回归**：B-059 / B-061 / B-062 / B-063
- **框架级（移交上游 CataForge）**：B-016 ~ B-019 / B-036 / B-038 — [feedback bundle](feedback/feedback-suggest-framework-batch-20260529.md)
- **PR #78 ~ #94**：大规模死代码/shim 烧毁 + C1（任务生命周期）+ S-2（chat 会话）+ ConditionalProcessor + pipeline CRUD CLI
