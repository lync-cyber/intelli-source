# CODE-REVIEW: 交付物合规性审查（深度审查） — r2
<!-- date: 2026-04-09 | scope: 全量合规审查 — Sprint 1-5 遗留问题 + 交付物偏离 | reviewer: orchestrator -->

## 审查目标

在 r1 审查基础上进行全面深度审查：
1. 检查历次 Sprint 审查中 MEDIUM/LOW 级别问题是否有遗漏未修复
2. 检查实际交付物是否偏离设计文档
3. 验证 r1 修复的正确性和完整性

---

## 审查范围

- 设计文档: `docs/arch/arch-intellisource-v1*.md`, `docs/prd/prd-intellisource-v1.md`
- Sprint 审查: `docs/reviews/sprint/SPRINT-REVIEW-s1-r*.md` 至 `s5-r1.md`
- 代码审查: `docs/reviews/code/CODE-REVIEW-sprint2-r1.md` 至 `sprint5-r2.md`
- 文档审查: `docs/reviews/doc/REVIEW-arch-intellisource-v1-r3.md`, `REVIEW-dev-plan-intellisource-v1-r4.md`
- 代码目录: `src/intellisource/` 全量
- 上次审查: `CODE-REVIEW-deliverable-compliance-r1.md`

---

## 第一部分: r1 修复验证

### r1 已修复问题核实

| r1 ID | 描述 | 验证结果 |
|-------|------|---------|
| R-001 | llm/prompts/ 模板化 | ✅ 6 个 .txt 模板已创建，5 个处理器已重构使用 `load_prompt()` |
| R-002 | agent/compaction.py | ✅ 已创建，含 LLM 压缩 + 截断 fallback |
| R-003 | llm/processors/optimizer.py | ⚠️ 文件已创建，但仍使用硬编码 prompt（见 NEW-001） |
| R-004 | api/deps.py | ✅ 已创建，含 `get_db_session()` 和 `require_api_key()` |
| R-005 | llm/schemas/ 补全 | ✅ dedup.json, cluster.json, summarize.json, tag.json 已创建 |

---

## 第二部分: Sprint 审查遗留问题核实

### 已被静默修复的历史问题

| 来源 | ID | 严重等级 | 描述 | 核实结果 |
|------|-----|---------|------|---------|
| S4-CODE-R2 | R-006 | MEDIUM | EmailDistributor HTML 注入风险 | ✅ 已修复 — `html.escape()` 已正确使用 |
| S4-CODE-R2 | R-009 | MEDIUM | CeleryTasks `time.sleep()` 阻塞 worker | ✅ 已修复 — 代码中无 `time.sleep()` 调用 |

### 仍然存在的历史遗留问题（v1 可接受）

以下问题经核实仍存在于代码中，但均在各 Sprint 审查中被明确标记为 v1 可接受的限制，有 [ASSUMPTION] 标注：

| 来源 | ID | 严重等级 | 类别 | 描述 | 标注位置 |
|------|-----|---------|------|------|---------|
| S4-CODE-R2 | R-008 | MEDIUM | consistency | EmailDistributor 内存去重 vs WeChat/WeWork Redis 去重不一致 | agent/runner.py [ASSUMPTION] |
| S4-CODE-R2 | R-010 | MEDIUM | completeness | `AgentRunner._persist()` 假持久化（返回 dict 不写 DB） | agent/runner.py 注释说明 |
| S4-CODE-R2 | R-013 | MEDIUM | consistency | `SchedulerManager` 内存存储，多 worker 不可见 | scheduler/state_machine.py [ASSUMPTION] |
| S5-CODE-R2 | R-007 | LOW | test-quality | MetricsCollector 单例测试状态共享 | conftest.py fixture 重置 |
| S5-CODE-R2 | R-008 | LOW | security | XML 解析使用 xml.etree.ElementTree | webhook 控制场景可接受 |
| S5-CODE-R2 | R-010 | LOW | convention | 文件路径偏离 (chat_session.py vs session.py) | SPRINT-REVIEW-s5-r1 记录 |

**判定**: 以上问题已在审查记录中被明确接受为 v1 限制，不计为遗漏。Phase 7 部署集成时应优先处理 R-008、R-010、R-013。

---

## 第三部分: 本次新发现的问题

### [R-001] MEDIUM: optimizer.py 仍使用硬编码 prompt
- **category**: consistency
- **root_cause**: self-caused
- **描述**: `PushOptimizer._try_llm_optimize()` 中 prompt 仍为硬编码 f-string，而 r1 修复要求所有处理器统一使用 `load_prompt()`。其他 5 个处理器（extractor, dedup, cluster, summarizer, tagger）已完成重构，但 optimizer 遗漏。
- **建议**: 创建 `llm/prompts/optimizer.txt` 模板，重构 `_try_llm_optimize()` 使用 `load_prompt("optimizer", ...)`。

### [R-002] MEDIUM: ChatSessionRepository 不存在
- **category**: completeness
- **root_cause**: self-caused
- **描述**: 架构文档 M-009 存储模块列出 `ChatSessionRepository`。实际 `storage/repositories/` 目录下有 6 个 Repository（base, content, push, source, subscription, task），但缺少 ChatSession 对应的 Repository。ChatSession ORM 模型已存在于 `storage/models.py`。
- **建议**: 创建 `storage/repositories/chat_session.py`，实现 `ChatSessionRepository(BaseRepository[ChatSession])`，包含 CRUD、按 channel+user 查询、超时清理。
- **修复状态**: ✅ 已修复 — 创建 `chat_session.py`，更新 `__init__.py` 导出

### [R-003] LOW: 新增文件缺少专门的单元测试
- **category**: test-quality
- **root_cause**: self-caused
- **描述**: r1 新增的 `agent/compaction.py`、`llm/processors/optimizer.py`、`api/deps.py` 三个文件缺少对应的单元测试。虽然现有 1563 个测试全部通过，但新增代码路径未被覆盖。
- **建议**: 补充 `test_compaction.py`、`test_optimizer.py`、`test_deps.py` 三个测试文件。

### [R-004] LOW: ChatSession ORM 模型实体编号注释错误
- **category**: convention
- **root_cause**: self-caused
- **描述**: `storage/models.py` 中 ChatSession 类的注释标记为 `# E-011: ChatSession`，但根据架构文档 arch-data，E-011 是 PushRecord，ChatSession 应为 E-012。
- **建议**: 修正注释为 `# E-012: ChatSession`。

---

## 第四部分: 设计文档层面的历史审查问题（已核实）

以下问题曾在 arch-r3 和 dev-plan-r4 审查中记录为 needs_revision。经本次核实，**所有问题均已在文档中修复**：

| 来源 | ID | 严重等级 | 描述 | 核实结果 |
|------|-----|---------|------|---------|
| arch-r3 | R-001 | HIGH | E-007 LLMCallLog.call_type 枚举缺少 "context_compress" | ✅ 已修复 — arch-data line 176 已包含 context_compress |
| arch-r3 | R-002 | MEDIUM | M-009 未列出 ChatSessionRepository | ✅ 已修复 — arch-modules line 146 已列出 |
| arch-r3 | R-004 | MEDIUM | ER 图缺少 ChatSession 实体 | ✅ 已修复 — arch-data ER 图 lines 39-45 已包含 |
| dev-plan-r4 | R-001 | HIGH | 依赖图缺少 T-019→T-039 边 | ✅ 已修复 — dev-plan line 155 已包含 |

**说明**: 以上历史审查问题均已在当前文档中修正，无需进一步操作。

---

## 修复清单

### 本次修复 (r2)

| 修复项 | 文件 | 变更类型 |
|--------|------|---------|
| R-001 | `src/intellisource/llm/processors/optimizer.py` | 修改 — 使用 load_prompt |
| R-001 | `src/intellisource/llm/prompts/optimizer.txt` | 新增 — prompt 模板 |
| R-002 | `src/intellisource/storage/repositories/chat_session.py` | 新增 — ChatSessionRepository |
| R-002 | `src/intellisource/storage/repositories/__init__.py` | 修改 — 导出 ChatSessionRepository |
| R-003 | `tests/unit/agent/test_compaction.py` | 新增 — compaction 测试 |
| R-003 | `tests/unit/llm/test_optimizer.py` | 新增 — optimizer 测试 |
| R-003 | `tests/unit/api/test_deps.py` | 新增 — deps 测试 |
| R-004 | `src/intellisource/storage/models.py` | 修改 — 注释 E-011→E-012 |

---

## 审查统计

| 严重等级 | 数量 | 已修复 |
|----------|------|--------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 2 | 2 (R-001, R-002) |
| LOW | 2 | 2 (R-003, R-004) |

## 判定结论

**approved** — 全部 4 个代码层面问题已修复（R-001 optimizer prompt 提取, R-002 ChatSessionRepository 创建, R-003 新增测试, R-004 实体编号注释修正）。第四部分文档层面历史问题经核实均已在设计文档中修复。
