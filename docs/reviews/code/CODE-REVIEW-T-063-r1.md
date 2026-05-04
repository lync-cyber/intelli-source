---
id: "code-review-t-063-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-063"]
---

# CODE-REVIEW-T-063-r1: sprint-7 集成测试与回归

> Layer 1 delegated to hook (PostToolUse `lint_format.py`)
> Layer 2 限定 test-quality / structure 维度（deliverable 仅为 `tests/integration/test_sprint7_integration.py`，无 src/ 改动）

## 审查范围
- `tests/integration/test_sprint7_integration.py` (新建, 857 LOC, 22 tests across 7 TestClasses)

## 量化指标
- 22/22 target tests PASSED
- 1862 全量回归 PASSED + 1 SKIPPED + 0 FAILED
- mypy --strict src/ — Success: no issues found in 106 source files
- ruff check / format — clean
- 实施轮数：1（light-dispatch 一次过）

## AC 覆盖核对

| AC | 测试类 | tests | 路径质量 |
|----|--------|-------|----------|
| AC-T063-1 LLM retry+fallback | TestLLMRetryFallback | 2 | **强**：真 LLMGateway + `tenacity.wait_none()` 跳过 backoff 但保留 retry 链；mock `litellm.acompletion` 控制成败序列；call_count==3 / fallback content 真断言 |
| AC-T063-2 ConfigResolver 三层合并 | TestConfigResolverMerge | 3 | **强**：真写 tmp YAML 文件 + `monkeypatch.setenv`，验证 env > project > defaults 优先级 |
| AC-T063-3 PromptBuilder + ModelProfile | TestPromptBuilderModelProfile | 4 | **强**：真组件实例 + 真 prompt 模板加载 |
| AC-T063-4 AgentRunner compaction | TestAgentRunnerCompaction | 2 | **强**：构造超过 token 阈值的 messages 触发压缩 |
| AC-T063-5 GET /api/v1/llm/stats | TestLLMStatsEndpoint | 2 | **强**：真 `httpx.AsyncClient + ASGITransport(create_app())` + 真 SQLite session 经 `_FakeDB` 适配器；HTTP 200 + 聚合字段断言 |
| AC-T063-6 GET /api/v1/clusters | TestClustersEndpoint | 5 | **强**：4 个真 E2E (pagination/limit/cursor-400/per-item-fields) + 1 个 router-layer 验证（tag filter，因 PG `@>` 限制 mock 了 repo） |
| AC-T063-7 TaskChainRepository CRUD | TestTaskChainRepositoryCRUD | 4 | **强**：真 SQLite session + repo.create + commit + repo.get + update_status roundtrip，每字段断言 |
| AC-T063-8 全量 pytest 通过 | — | 命令验证 | 1862 PASSED 0 FAILED |
| AC-T063-9 mypy strict 零错误 | — | 命令验证 | 106 files clean |

## 问题列表

### [R-001] LOW: 模块级 monkey-patch `SQLiteTypeCompiler.visit_JSONB` 是全局副作用
- **category**: structure
- **root_cause**: self-caused
- **描述**: `test_sprint7_integration.py:24-32` 在 import 时给 `sqlalchemy.dialects.sqlite.base.SQLiteTypeCompiler` 全局添加 `visit_JSONB` 方法。虽然有 `_visit_jsonb_patched` flag guard 保证幂等，且仅添加 JSONB → JSON 方法（无破坏性覆盖），但 import 副作用会泄漏到任何后续在同一进程加载的测试模块。pytest 测试隔离依赖单元测试不污染全局状态，这种模块级 patch 违反了该原则。
  现状：`tests/unit/storage/conftest.py` 已有同款 patch 注释；本文件第 21 行注释也指出这是 mirror。
- **建议**: 把 patch 逻辑迁移到 fixture（`@pytest.fixture(autouse=True, scope="session")` 或 conftest），用 `setattr` + teardown 时 `delattr` 还原。或抽到 `tests/conftest.py` 由所有需要 SQLite-with-JSONB 的测试共享。**当前不阻塞**——已有先例，且 guard 保证幂等。

### [R-002] LOW: `test_clusters_filter_by_tag_forwards_to_repository` 不是真集成测试
- **category**: test-quality
- **root_cause**: upstream-caused (CORRECTIONS-LOG 已记录的 PG @> SQLite 不兼容 limitation)
- **描述**: `TestClustersEndpoint::test_clusters_filter_by_tag_forwards_to_repository` mock 了 `ClusterRepository.list_clusters` 方法，仅验证 router 层把 `tag="ai"` kwarg 正确转发到 repo。这是 router-layer unit test 的精度，不是真集成测试——SQL 层的 PG `@>` 操作符行为根本未被覆盖。
  CORRECTIONS-LOG (T-073) 已记录"ContentRepository LIKE 通配符 / cluster JSONB tag 过滤的 SQLite 兼容性 carryover"——本测试是该 limitation 的延续，不是新问题。
- **建议**: 标注为 carryover，等 storage 测试迁移到 Postgres test fixture（如 testcontainers-postgres）后改为真 E2E。当前接受。

### [R-003] LOW: `test_update_status_missing_id_does_not_raise` 断言过弱
- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `TestTaskChainRepositoryCRUD::test_update_status_missing_id_does_not_raise` (line 817-825) 仅靠"无异常即 PASS"，没有断言任何可观测状态（如 affected_rows == 0、表中行数不变、return value）。如果未来 `update_status` 改成"missing id 时 silently insert"也会通过此测试。
- **建议**: 追加 `result = await repo.get(...); assert result is None` 或 `count_before == count_after` 验证 missing id 路径无副作用。

## 良好实践 (Highlights)

- **真 HTTP 路径**：5 个 `/api/v1/clusters` 测试中 4 个走 `ASGITransport(create_app())` 真 lifespan 经过 middleware → router → controller → repo → SQLite，端到端覆盖 T-072 lifespan + T-073 cluster route + T-074 TaskChainRepository 多任务集成路径
- **`tenacity.wait_none()` 模式**：跳过 retry backoff 等待但保留 retry 装饰器逻辑，是异步 retry 测试的最佳实践
- **`_FakeDB` 适配器**：`_make_db_manager_for_engine` 用一个匿名类提供 `get_session()` async context manager，干净地把 SQLite engine 桥接到 FastAPI `app.state.db` 接口，避免 mock DatabaseManager 内部细节
- **JSONB → JSON SQLite 兼容层**：虽然在 R-001 中作为副作用被指出，但实现本身（gated patch + JSON fallback + `_remove_pg_only_indexes` + `_patch_vector_columns`）是允许 sprint-7 各任务在 in-memory SQLite 跑集成测试的关键基础设施
- **adaptive-review 注入红线遵守**：implementer self-report `refactor_needed=false` 准确（857 LOC 单文件分块清晰，无逻辑重复）；未自行 commit；ruff/mypy 修改后均运行验证

## 审查结论

**approved**

3 个 LOW 问题（R-001 全局 patch 副作用 / R-002 carryover / R-003 弱断言）均不阻塞；R-001 与 R-003 可在后续 storage 测试迁移到 Postgres 时一并优化。**T-063 可标记 done**，sprint-7 全部任务（10/10 + T-063 = 11/11，含 T-063）实施闭环。

## sprint-7 整体质量观察（前置 sprint-review 输入）
- 22 + 11 个 sprint-7 新增 integration tests 提供了跨任务集成防护
- 1862 PASSED + 1 SKIPPED + 0 FAILED 全量回归零回归
- mypy strict 持续保持零错误（106 source files）
- 同模式 carryover：T-073 → T-075 → T-063 三任务都涉及"PG @> / JSONB / LIKE 通配符 SQLite 兼容性"——sprint-review 时建议合并标注 storage 测试基础设施待 Postgres-fixture 迁移
