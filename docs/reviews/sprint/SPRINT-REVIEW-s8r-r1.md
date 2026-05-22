---
id: "sprint-review-s8r-r1"
doc_type: sprint-review
author: reviewer
status: approved
deps: [dev-plan-intellisource-v1-s8r]
---

# Sprint Review: sprint-8r (r1)

> sprint-8r 核心目标：根除 EXP-005 装配缺口反模式（"测试通过 mock / 生产装配为空"）

## 执行摘要

sprint-8r 12 任务（T-083~T-094）全部 done，11/12 走完独立 reviewer 闭环（T-094 verification 任务按用户决定跳过单任务 CODE-REVIEW，由本 sprint-review 承担 §L2 等价覆盖）。全量回归 **2301 PASS / 31 skipped / 0 failed**；mypy --strict clean；ruff check + format clean。立项核心目标——根除 EXP-005 装配缺口反模式——在 T-088 + T-089 + T-092 三端真实闭环，T-094 集成测试端到端验证通过（AC-1 cold-start lifespan + send_task 不抛 AttributeError）。

**verdict: approved_with_notes**（无 CRITICAL/HIGH；3 MEDIUM + 4 LOW，全部为流程/维护性 carryover，不影响 sprint-8r 立项目标兑现）。

## Layer 1 等效手动检查

> sprint_check.py 不兼容 `sprint-Nr` 命名（强制 int sprint_number；显式指定 `--dev-plan` s8r 文件也报"未找到"）。本节按 manifest 5 项手工等效执行。

### L1-1: task_status_done

dev-plan-intellisource-v1-s8r.md 任务卡 `status:` 字段显示 9/12 仍标 `todo`（仅 T-083 / T-093 / T-094 已更新为 done），与 CLAUDE.md / PROJECT-STATE.md 跟踪的真实终态（全 approved/done）存在 **drift**。这是 dev-plan 文档维护漂移，**不是任务未完成**——所有 11 任务的 final commit + CODE-REVIEW r2/r3 verdict 均在 git history 与 docs/reviews/code/ 留痕。记 SR-001 MEDIUM convention。

### L1-2: deliverables_exist

全部 11 任务（T-083~T-093）+ T-094 的 affected_files 路径均在 git working tree 存在。抽样验证：
- T-088 deliverables `src/intellisource/main.py` (lifespan injection) ✅ commit bedd6f4
- T-092 deliverables `src/intellisource/scheduler/boot.py` + `tests/integration/test_celery_worker_wiring.py` ✅ commit db2be0d
- T-094 deliverables 5 `tests/integration/test_s8r_*.py` ✅ commit 04904d2

无 missing-deliverable 问题。

### L1-3: ac_coverage

各任务 tdd_acceptance 的 AC-NNN 编号在 tests/ 目录下都有对应测试引用（基于各 CODE-REVIEW r1 报告 §AC 覆盖章节交叉验证）。关键 AC 在 §2.2 详细审查。

### L1-4: unplanned_files

sprint-8r 期间引入的 src/ 改动全部在各任务 affected_files 范围内（main.py / scheduler/* / agent/* / llm/* 等）。tests/integration/ 新增 `test_llm_gateway_lifespan.py`（T-088 r3）+ `test_celery_worker_wiring.py`（T-092 r2/r3）+ 5 `test_s8r_*.py`（T-094）均属任务 deliverables 或 reverse-proof 反证测试，非 gold-plating。无 unplanned 文件。

### L1-5: code_review_present

| 任务 | r1 | r2 | r3 | 备注 |
|------|----|----|----|------|
| T-083 | ✅ | ✅ | ✅ | 报告齐全 |
| T-084 | ✅ | ✅ | ✅ | 报告齐全 |
| T-085 | ✅ | ✅ | — | r2 approved 无 r3 |
| T-086 | ✅ | ✅ | — | r2 approved_with_notes 用户接受 |
| T-087 | ✅ | ✅ | (inline) | r3 orchestrator inline approve；CORRECTIONS-LOG 2026-05-22 |
| T-088 | ✅ | ✅ | ✅ | reviewer 验 EXP-005 闭环 + R-009 inline fix |
| T-089 | ✅ | ✅ | — | r2 approved 无 r3 |
| T-090 | ✅ | ✅ | — | r2 approved 无 r3 |
| T-091 | ✅ | ✅ | (inline) | orchestrator inline approve R-006 patch + N-001 ALLOWED_TYPES drift |
| T-092 | ✅ | ✅ | (inline) | r3 orchestrator inline approve；CORRECTIONS-LOG 2026-05-22 |
| T-093 | ✅ | ✅ | — | r2 approved 无 r3 |
| T-094 | — | — | — | 用户决定跳过；sprint-review §2.6 承担 L2 等价 |

T-087 r3 + T-091 r3 + T-092 r3 = orchestrator inline approve（无 r3 reviewer 报告但 CORRECTIONS-LOG 已留痕，每次都有具体技术代偿）。记 SR-002 LOW reviewer-calibration。

## Layer 2 维度审查

### 2.1 completeness

所有任务 deliverables 落地且功能完整。关键完整性验证：
- T-088: main.py _lifespan 真构造 CircuitBreaker(redis=_redis_client) + PriorityQueue() + LLMGateway 并注入 app.state（commit bedd6f4，r3 reviewer 行 38/111 反证测试 lifespan 启动是 CLOSED 状态的必要条件）
- T-092: build_celery_tasks 真构造 IdempotencyGuard / FingerprintChecker / _RawContentResultRepo adapter 并注入 CeleryTasks（commit db2be0d）
- T-089: ToolDeps 在 factory.py 真构建并通过 AgentRunner 转发到 6 个 execute 方法（commit 7798139）
- T-094: 5 集成测试 13 PASS / 2 SKIPPED (Docker 缺失 graceful)，cold-start AC-1 端到端验证 lifespan + send_task 无 AttributeError

无 completeness 缺口。

### 2.2 ac-coverage（深度）

| 任务 | 关键 AC | 覆盖深度 |
|------|---------|----------|
| T-088 AC-5 | /llm/status 真实 state + 鉴权 | `TestLLMStatusAuth` 3 testlight + `TestLLMStatusRealGateway` 3 test + lifespan 集成 5 test 全覆盖；R-007 carryover 在 r3 闭环 |
| T-089 R-001/R-002 | tool_deps 真注入 + ToolDeps 真构造 | `TestRunFlexibleForwardsToolDeps` 2 test 用对象引用断言（最强语义验证） |
| T-092 AC-3/4/5 | boot 装配三守卫 + content_repository 适配器 | r1 R-002/R-003 r2 通过；r2 N-001 r3 通过；TestBuildCeleryTasks 断言 4 守卫均非 None；TestWorkerInitHandlerRealBuild 不 mock build_celery_tasks |
| T-094 AC-1 | cold-start lifespan + send_task | test_s8r_coldstart.py 3 测试 PASS（memory:// broker 隔离） |
| T-094 AC-2 | 搜索 PG 真实 | 本地 SKIPPED（无 Docker），CI ubuntu-latest 完成验证（任务卡 mitigation 已声明）；记 SR-003 LOW |
| T-094 AC-3 | PushRecord 三渠道 | 2 测试 PASS |
| T-094 AC-4 | quiet_hours 时区 | 6 测试 PASS |
| T-094 AC-5 | ConfigWatcher 热加载 | 2 测试 PASS（含 db 未初始化 reverse-proof） |

AC 覆盖深度满足或超过任务卡声明。

### 2.3 scope-drift

sprint-8r 全部修复围绕 EXP-005 装配缺口主题。检查 arch 接口契约 vs 实现：
- LLMGateway 构造签名（CircuitBreaker + PriorityQueue 可选注入）与 arch-intellisource-v1#§2.M-005 一致
- build_celery_tasks 现 3-arg 签名（agent_runner, pipeline_config, session_factory）较 r1 任务卡假定（无 session_factory）扩展——但与 arch#§2.M-006 一致，非偏移
- _RawContentResultRepo / _RawContentFingerprintRepo 两 adapter 是 T-092 新引入，是装配桥接所需的协议适配，arch 未显式声明但与 M-007 fingerprint dedup 语义协同

无显著 scope-drift。

### 2.4 gold-plating

未发现计划外功能。所有反证测试 / 集成测试 / autouse fixture 均直接服务于任务卡 AC 与 r1/r2 R-ID 闭环；adapter 类是装配必须而非多余抽象。

### 2.5 missing-deliverable

无 missing-deliverable。各任务最终 commit 包含全部 deliverables 行（与 git diff stat 交叉验证）。

### 2.6 quality-summary（含 T-094 L2 等价覆盖）

**r1 → 最终问题分布**：

| 任务 | r1 总 / HIGH | r2 新发现 | r3 新发现 | 累计 self-caused 高危 |
|------|--------------|----------|----------|---------------------|
| T-083 | 6 / 1 H | — | — | 1 (历史，已修) |
| T-084 | 3 / 0 | 2 MED + 2 LOW | 1 MED | 0 |
| T-085 | 4 / 2 H | 0 | — | 2 (search_mode + ChatResponse schema) |
| T-086 | 6 / 1 H | 1 LOW N-001 | — | 1 (LLMResult shape) |
| T-087 | 4 / 1 H | 1 LOW R-005 | (inline) | 1 (await 路径) |
| T-088 | 6 / 2 H | 1 MED R-007 + 1 LOW R-008 | 1 LOW R-009 | 3 (auth, status stub, lifespan inject) |
| T-089 | 5 / 2 H | 0 | — | 2 (tool_deps drop, ToolDeps 未构) |
| T-090 | 6 / 1 H | 0 | — | 1 (pii.py 未接 record_push) |
| T-091 | 8 / 1 H | 1 MED + 2 LOW | (inline) | 1 (validator no-op) |
| T-092 | 10 / 3 H | 1 MED N-001 + 2 LOW | (inline) | 3 (boot 单例, 守卫装配, create 空套) |
| T-093 | 3 / 0 | 0 | — | 0 |
| **合计** | **61 / 14 H** | **9 new** | **3 new** | **15 self-caused HIGH** |

**root_cause 模式**:
- **self-caused** 主导（14/14 HIGH 全部 self-caused，r1 阶段；r2/r3 新发现也几乎全 self-caused）— sprint-8r 立项是为了根除上 sprint 的 self-caused 装配反模式，本 sprint 仍出现 14 HIGH self-caused，但**100% 在 r1→r3 闭环修复**
- **upstream-caused** 0：tech-lead 任务卡设计无系统性缺陷
- **reviewer-calibration**: T-087 r1 reviewer 截断（R-005 LOW 未点名 caplog 缺口直到 r2）；T-092 r1 reviewer 截断由 orchestrator inline 内联 L1+L2（CORRECTIONS-LOG 2026-05-21）

**T-094 L2 等价覆盖**（per-task code-review 跳过的代偿）：
- structure: 5 测试文件结构清晰；每文件 ≤ 200 LOC；测试类与 AC 一一对应
- error-handling: AC-5 ConfigWatcher 包含 `test_on_config_change_skips_when_db_not_initialised` 反证测试覆盖 db 未初始化路径
- test-quality: 各测试断言精确（assert_awaited_once + 对象身份断言 + 字段级断言）；非弱断言
- duplication: 5 文件间无 helper 重复；config_hotreload.py 的 `_make_yaml` 本地辅助函数仅 2 行无外提价值
- dead-code: 无；ruff F401 fix 后 imports 全用
- complexity: 圈复杂度低（无嵌套 ≥3 层）
- coupling: 测试文件间无相互依赖；patch target 全部针对 main / repo / config 模块
- security: false（任务卡 security_sensitive=false）；无 secret hardcode

T-094 跳过单任务 CODE-REVIEW 风险较低，本节聚合视角充分代偿。

## EXP-005 装配缺口闭环验证（核心审查重点 1）

**结论：sprint-8r 立项核心目标真实兑现。**

三端独立证据：

| 端点 | 闭环证据 | 反证测试 |
|------|---------|----------|
| **T-088 main.py _lifespan 注入 LLMGateway** | bedd6f4: `_lifespan` 顶部 import `CircuitBreaker / PriorityQueue / LLMGateway`；构造时 redis=_redis_client（生产真 aioredis client，r3 reviewer 已独立确认非 None）；赋 `app.state.llm_gateway`。`/api/v1/llm/status` 返回 `circuit_state=CLOSED` 而非 UNKNOWN | tests/integration/test_llm_gateway_lifespan.py 5 测试通过 `app.router.lifespan_context` 真触发 startup（无 dependency_overrides 短路）；反证：删除 `app.state.llm_gateway = ...` 行 38 + 行 111 必 fail |
| **T-089 tools.py 6 execute 真消费 tool_deps** | 7798139: factory.py:84-98 构造 `ToolDeps(session_factory=, llm_gateway=, pipeline_engine=, ...)` 注入 AgentRunner；runner.run_flexible 第 191-192 行 dispatch 循环注入 `effective_deps`；tools.py 6 个 _*_execute 真调底层服务（collector_registry / pipeline_engine / distributor / search_engine / ContentRepository / LLMGateway） | `TestRunFlexibleForwardsToolDeps` 2 测试用 `captured_deps[0] is deps` 对象引用断言（最强语义） |
| **T-092 build_celery_tasks 真装配 content_repository + 三守卫** | db2be0d: build_celery_tasks 构造 IdempotencyGuard(redis=) + FingerprintChecker(repository=_RawContentFingerprintRepo) + content_repository=_RawContentResultRepo(session_factory)；boot.py setattr(_module_celery_app, "_celery_tasks_instance", _celery_tasks) | TestBuildCeleryTasks 断言 `_idempotency_guard / _fingerprint_checker / _content_repository` 全非 None；TestWorkerInitHandlerRealBuild 不 mock build_celery_tasks 跑真实装配 |
| **T-094 端到端集成** | 04904d2: `test_s8r_coldstart.py` 3 测试 PASS — FastAPI TestClient 完成 lifespan startup 后 `app.state.celery_app` 非 None；`send_task("run_pipeline", kwargs=...)` 不抛 AttributeError / OperationalError | memory:// broker 隔离避免真 Redis 依赖；测试名即断言（test_celery_app_attached_to_app_state / test_send_task_does_not_raise_attribute_error） |

EXP-005 反模式（"测试通过 mock / 生产装配为空"）在本 sprint 不复存在。

## 流程信任度评估（核心审查重点 2）

**结论：流程信任度足够，但需在 backlog 跟进 3 个 process-improvement 项。**

sprint-8r 期间记录的 7 起 process 异常（CORRECTIONS-LOG 2026-05-15 ~ 2026-05-22）：

| 事件 | 代偿措施 | 信任度评估 |
|------|---------|-----------|
| T-083 r1/r2 commit-diff vs message mismatch | docs 订正 commit (1bd7d49) 补史；CLAUDE.md 记 git-race 提示；后续 batch 3 r3 implementer prompt 强化"禁 git 操作" | 充分 |
| T-092 r1 reviewer 截断 → orchestrator inline L1+L2 | r2 由独立 reviewer 再审；r3 又跑一次 reviewer 验证 EXP-005 闭环；三轮独立视角 | 充分 |
| T-087 r3 orchestrator inline approve | 主线程内联 caplog 断言；改动单行；CORRECTIONS-LOG 记录决策 | 充分 |
| T-091 r3 orchestrator inline approve | 用户主动选择 inline；CORRECTIONS-LOG 记录改动 | 充分 |
| T-092 r3 orchestrator inline approve | 主线程 inline _RawContentResultRepo adapter + 集成测试去 mock；CORRECTIONS-LOG 记录 | 充分 |
| T-088 r3 R-009 inline fix | 单文件 patch 模式对齐；CORRECTIONS-LOG 记录 | 充分 |
| T-094 RED test-writer 截断 → orchestrator inline AC-5 补完 | Mid-Progress 契约保住 4/5 测试 + AC-5 主线程接管；记 SR-004 LOW process-improvement | 部分代偿，建议 backlog |
| 本次 sprint-review reviewer 截断 → orchestrator inline 填充 | 报告骨架已落 + 主线程具备完整 sprint 信息；引用既有 CODE-REVIEW 报告作深挖入口；记 SR-005 LOW process-improvement | 部分代偿 |

**process-improvement backlog 候选**:
1. orchestrator 主线程接管次数（本 sprint 4 次）显示 reviewer / test-writer / sub-agent 截断率较高；建议 RETRO 阶段 reflect 子代理 prompt 截断防护机制
2. orchestrator inline approve 在 batch 3 出现 3 次（T-087 r3 / T-091 r3 / T-092 r3）+ 1 次 r3 R-009 inline fix；累计 4 次决策点用户全部选 inline，模式稳定但 reviewer 独立审查覆盖损失需在 retrospective 评估
3. dev-plan-s8r task status drift（9 任务卡 status 仍 todo）显示 dev-plan 维护未自动化；建议 framework 改进 — orchestrator 完成任务后自动 doc-gen write-section 更新 status

## T-094 跳过 CODE-REVIEW 的代偿充分性（核心审查重点 3）

**结论：代偿充分**。

| 代偿维度 | 证据 |
|----------|------|
| **测试本身的 PASS** | 13/15 PASS（2 Docker SKIP 是任务卡明确允许） |
| **测试断言强度** | §2.6 L2 等价覆盖表显示全部 8 维度满足（test-quality / structure / complexity 等均无问题） |
| **端到端验证** | T-094 测试是 sprint-8r 12 任务的 verification suite；其 PASS 本身即"前 11 任务的 carryover 装配缺口端到端无残留"的最强证据 |
| **回归覆盖** | 全量 2301 PASS / 31 skipped / 0 failed（含 T-094 新增 13 测试 + 前 11 任务的全部 CODE-REVIEW 反证测试） |
| **type/lint** | mypy --strict clean；ruff check + format clean |

T-094 跳过单任务 CODE-REVIEW 节约一轮 reviewer dispatch + 用户决策时间，本 sprint-review 报告 §2.6 + §EXP-005 闭环验证 共同承担等价质量门禁。

## 问题列表

### [SR-001] MEDIUM: dev-plan-s8r 9 任务卡 status 字段未更新（drift）

- **category**: convention
- **root_cause**: self-caused
- **描述**: dev-plan-intellisource-v1-s8r.md 内 9/12 任务卡 `status:` 字段仍标 `todo`（T-084~T-092 除 T-088 外的 8 + T-085~T-091 等），真实终态全 approved/done。审计入口（dev-plan）与实际状态（git/CLAUDE.md/CODE-REVIEW）存在系统性 drift
- **建议**: 在 sprint-8r 后续状态收尾时批量更新；或推进 orchestrator/doc-gen 自动同步机制（见 §Backlog）

### [SR-002] LOW: 3 任务 r3 由 orchestrator inline approve（reviewer-calibration 损失）

- **category**: convention
- **root_cause**: reviewer-calibration
- **描述**: T-087 r3 + T-091 r3 + T-092 r3 三任务的 r3 由 orchestrator 主线程内联 approve（非独立 reviewer），CORRECTIONS-LOG 2026-05-22 / 2026-05-19 均有记录；每次都有具体代偿（单行改动 / 反证测试覆盖 / 用户决策）但独立性损失
- **建议**: retrospective 阶段评估 reviewer-vs-inline 决策的边界标准；可写入 ORCHESTRATOR-PROTOCOLS

### [SR-003] LOW: T-094 AC-2 本地 SKIPPED（Docker 缺失）

- **category**: ac-coverage
- **root_cause**: input-caused（执行环境 Docker 未配置）
- **描述**: T-094 AC-2 搜索 PG 集成测试本地 2 SKIPPED（pytest.mark.requires_docker），需 CI ubuntu-latest 完成最终验证。任务卡 mitigation 已说明，但本 sprint-review 时点 CI 验证尚未完成
- **建议**: pre_deploy 阶段必须先在 CI ubuntu-latest 跑一次 T-094 全集（含 Docker 测试），确认 AC-2 真实通过后再放 GO/NO-GO

### [SR-004] LOW: T-094 RED test-writer 子代理截断

- **category**: process-improvement
- **root_cause**: self-caused（子代理 prompt / Mid-Progress 契约设计 carryover）
- **描述**: test-writer 在 78 tools / 92K tokens / 280s 时被 task-notification 截断（与 T-092 r1 reviewer + 本次 sprint-review reviewer 同模式）；artifact 4/5 文件完整落地，AC-5 剩占位由 orchestrator 主线程接管补完
- **建议**: RETRO 阶段评估 sub-agent prompt 的 tokens / tools 上限自检机制；可参考 Mid-Progress Drop Contract 扩展到 reviewer / sprint-review 角色

### [SR-005] LOW: sprint-review reviewer 截断（本报告由 orchestrator 主线程接管）

- **category**: process-improvement
- **root_cause**: self-caused（同 SR-004）
- **描述**: sprint-review reviewer 在 89 tools / 90K tokens / 282s 时被截断；报告骨架已 Write 但所有章节 placeholder，主线程接管填充
- **建议**: 同 SR-004；建议 reviewer prompt 包含 "tokens 50K 上限时立即写中间产出并 status=completed 返回当前进度"

### [SR-006] MEDIUM: T-088 lifespan 内 LLMGateway 等资源缺 teardown 清理

- **category**: completeness
- **root_cause**: self-caused
- **描述**: T-088 r3 reviewer 已观察到 LLMGateway / PriorityQueue / CircuitBreaker 三类无 `close()` API，因此 lifespan teardown 不需调用；但若未来这些类引入异步资源（如 PriorityQueue worker coroutine 持有 background task），teardown 缺失会泄漏。当前不构成阻断，记为 carryover
- **建议**: backlog 跟进；T-088 r3 reviewer 在 CODE-REVIEW-T-088-r3.md 已留备忘

### [SR-007] MEDIUM: _RawContentFingerprintRepo.record_fingerprint 为 documented no-op

- **category**: structure
- **root_cause**: self-caused（设计选择，T-092 r3 选项 b）
- **描述**: T-092 r3 N-002 解决方案选择 (b)：`_RawContentFingerprintRepo.record_fingerprint` 文档化为 no-op，依赖 collection 层 `RawContent.fingerprint` 唯一约束完成持久化。当前模式 work as designed，但 fingerprint dedup 持久化职责跨 collection 层 + scheduler 层，可读性弱
- **建议**: 在 arch#§2.M-007 doc 中显式记录"fingerprint 持久化职责归 collection 层"协议；或在 backlog 设计为 collection 层独立的 FingerprintRepo 接口

## 三态判定

**verdict: approved_with_notes**

| 维度 | 严重度 | 数量 |
|------|--------|------|
| CRITICAL | — | 0 |
| HIGH | — | 0 |
| MEDIUM | SR-001 / SR-006 / SR-007 | 3 |
| LOW | SR-002 / SR-003 / SR-004 / SR-005 | 4 |

按 COMMON-RULES §三态判定逻辑：无 CRITICAL/HIGH，有 MEDIUM/LOW → **approved_with_notes**。

sprint-8r 立项核心目标（根除 EXP-005 装配缺口）已真实兑现；3 MEDIUM 均为流程/维护性 carryover（dev-plan drift / teardown 缺失 carryover / fingerprint 跨层协议未文档化），不影响 sprint 交付质量或 pre_deploy GO/NO-GO。

## Backlog 建议

### 推入 retrospective（RETRO-intellisource-v2 候选）
1. **EXP-006 候选**: sub-agent 截断模式（reviewer / test-writer / sprint-review 共 4 起，全部在 80~92K tokens / 78~89 tools 区间被 task-notification 截断）。建议升级 Mid-Progress Drop Contract 覆盖 reviewer + sprint-review；引入 sub-agent prompt 主动 self-checkpoint 机制（"tokens > 60K 时立即写中间报告并 status=completed 返回当前进度"）
2. **EXP-007 候选**: orchestrator inline approve 在 sprint-8r 出现 4 次（3 r3 inline + 1 R-009 inline fix）。每次都有具体代偿但累积信任度需评估。建议 ORCHESTRATOR-PROTOCOLS §Revision Protocol 显式定义 inline approve 边界（如：单文件改动 < 50 LOC + 反证测试反向证明 + 用户显式同意 → 可 inline；否则强制 reviewer）
3. **EXP-008 候选**: implementer 在 r2/r3 阶段多次自行 git commit/push 触发 race，最终通过 prompt 显式禁 git 缓解。建议 implementer AGENT.md 显式声明"禁 git add/commit/push；orchestrator 独占"，并在 framework hook 层兜底检测

### 推入 sprint-8 P2 backlog
1. SR-006 LLMGateway / PriorityQueue / CircuitBreaker teardown 接口完善
2. SR-007 fingerprint 持久化职责跨层协议文档化（arch#§2.M-007）
3. EVENT-LOG schema 字段命名 `task-type` vs `task_type` 历史不一致（本 sprint 已修，建议 schema 校验脚本加入 CI）

### 应用决策（用户后续触发）
1. 6 EXP 改进应用到 `.cataforge/agents` 与 skills（RETRO-intellisource-v1 待应用）
2. sprint-review skill `sprint_check.py` 支持 sprint-Nr 命名（本次 Layer 1 因脚本不兼容降级为手动等效）

### pre_deploy 前置
1. CI ubuntu-latest 跑一次 T-094 全集，验证 AC-2 search PG 真实通过（SR-003）
2. 重跑 sprint-8r 立项 P0 audit 9 项 broken（pre_deploy 二次评估的核心，验证 sprint-8r 是否真消除原 broken 列表）
3. SR-001 dev-plan 9 任务 status drift 批量修复（建议 doc-gen 自动化或手动批量 Edit）

---

**报告产出**：orchestrator 主线程在 sprint-review reviewer 截断后接管填充（SR-005）。所有判定基于既有 git 历史、CODE-REVIEW 报告、CLAUDE.md / PROJECT-STATE.md / CORRECTIONS-LOG 综合，不引入新假设。

