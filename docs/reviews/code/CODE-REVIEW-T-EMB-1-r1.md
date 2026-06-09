---
id: "code-review-T-EMB-1-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["T-EMB-1"]
---

# Code Review: T-EMB-1 — 本地 BGE-M3 Embedding 路由 + 向量维度 1536→1024

Layer 1 已通过（ruff / mypy --strict），本报告为 Layer 2 AI 语义审查。

---

## 问题列表

### [R-001] HIGH: `embedding_api_key=""` 默认值导致 keyless TEI 静默降级

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `settings.embedding_api_key` 默认值为空字符串 `""`（`settings.py:95`），在 `_embed.py:63` 被无条件透传给 litellm：`api_key=settings.embedding_api_key`。运维部署 TEI 时通常无需鉴权，`IS_EMBEDDING_API_KEY` 极大概率不设置。litellm 的 OpenAI-compatible 客户端收到 `api_key=""` 后，等效于发出无效凭据请求，TEI 服务端若启用了认证则返回 401，litellm 抛出异常后被 `except Exception`（第 65 行）吞掉，embed() 返回 None。结果是：`api_base` 已正确配置、服务已就绪，却因 empty-key 导致 embedding 仍为 NULL，与"接入 TEI 恢复 embedding 写入"的任务目标相悖，且无任何可见的错误提示帮助运维定位。测试中均显式设置了 `IS_EMBEDDING_API_KEY="tei"`，因此 test-suite 不覆盖此路径（mock 绕过了 litellm 鉴权逻辑）。
- **建议**: 在 `_embed.py` 中于透传前做兜底处理：`api_key=settings.embedding_api_key or "tei"`。"tei" 是 TEI keyless 部署的公认占位符（HuggingFace 官方文档及 OpenAI 客户端均接受非空任意字符串作为 keyless 凭据）。同时补充一条单测：`IS_EMBEDDING_API_KEY` 未设置时 embed() 不返回 None（用 fake_aembedding 验证调用抵达且返回向量），以防回归。

---

### [R-002] MEDIUM: 遗留 1536 测试 `test_upsert_accepts_1536_dim_vector` 名称与断言具有主动误导性

- **category**: test-quality
- **root_cause**: self-caused
- **描述**: `tests/unit/storage/test_vector.py:83` 的测试名为 `test_upsert_accepts_1536_dim_vector`，docstring 为 "upsert() accepts exactly 1536-dimensional vectors without error"，断言 `assert len(embedding) == 1536`（第 93 行）。该测试在 mock DB 环境下通过，但其断言的是旧维度，与已生效的 Schema（`EMBEDDING_DIM=1024`，Vector(1024) 列）矛盾。若开发者未来查看此测试，会误认为 1536 维向量是被支持的有效输入，实际上真实 pgvector 列会拒绝写入 1536 维向量（维度不匹配）。这是 consistency + test-quality 的双重问题：测试"假绿"并主动发出错误信号。同类问题还存在于同文件的多处 `_random_vector(1536)` 调用（第 75、91、106–107 行等），但它们仅传给 mock session 不影响真实 DB；`test_upsert_accepts_1536_dim_vector` 因测试名+断言的组合而更具误导性。
- **建议**: 将该测试重命名为 `test_upsert_accepts_1024_dim_vector`，更新 docstring 和断言为 1024 维，并将 `_random_vector(1536)` 改为 `_random_vector(1024)`。同时建议将 `_random_vector` 函数的默认参数从 `dim=1536` 改为 `dim=1024`，使整个测试文件的向量维度与当前 schema 一致。

---

### [R-003] MEDIUM: `test_migration_embedding_dim.py:72` 测试 docstring 指向错误的 `down_revision`

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `tests/unit/storage/test_migration_embedding_dim.py:72` 的方法 docstring 写的是 `"Migration down_revision must be 'a7b8c9d0e1f2' (previous chain head)"`，但实际断言的常量 `_EXPECTED_DOWN_REVISION = "a2b3c4d5e6f7"`，且迁移文件本身也使用 `a2b3c4d5e6f7`（正确）。docstring 中的 `a7b8c9d0e1f2` 是修复前的错误值（RED 阶段误设），此处仅 docstring 未同步更新。虽然不影响测试正确性，但 docstring 与断言内容直接矛盾，审查或回归时会造成混淆。
- **建议**: 将该 docstring 更新为 `"Migration down_revision must be 'a2b3c4d5e6f7' (the rename_truncate_summary_tool revision)"`，与常量和迁移文件一致。

---

### [R-004] MEDIUM: `test_pg_vector_search.py:42` `_unit_vec` 的 docstring 说 "1536-dimensional" 但实际使用 1024

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `tests/integration/test_pg_vector_search.py:42` 处 `_unit_vec` 的 docstring 写的是 `"Return a 1536-dimensional unit vector"`，但函数体使用 `[0.0] * _DIM` 而 `_DIM = 1024`（第 38 行）。文件头部注释明确写了 `_DIM updated from 1536 → 1024`，可见 `_DIM` 已正确更新但 docstring 漏更。集成测试在真实 PostgreSQL 容器中运行，向量维度必须与 `Vector(1024)` 列匹配，因此实际行为是正确的；但 docstring 误导读者认为此函数产出 1536 维向量。
- **建议**: 将 docstring 改为 `"Return a 1024-dimensional unit vector with 1.0 at *hot_index*, 0.0 elsewhere."`。

---

### [R-005] MEDIUM: `test_models.py:555` 章节注释遗留 "VECTOR(1536)" 字样

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `tests/unit/storage/test_models.py:555` 的章节分隔注释为 `# AC-T003-4: pgvector VECTOR(1536) field definition`，而 `TestVectorFields.test_vector_dimension_1024`（第 583 行）已正确断言 `dim == 1024`。注释与测试逻辑矛盾，维护者在阅读测试文件时会产生困惑。
- **建议**: 将该注释更新为 `# AC-T003-4: pgvector VECTOR(1024) field definition`。

---

### [R-006] MEDIUM: `test_embedding_processor.py` 中 `[0.1]*1536` / `[0.42]*1536` 向量维度与当前 schema 不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `tests/unit/pipeline/test_embedding_processor.py` 的以下位置仍使用 1536 维向量：第 70–83 行（`vec = [0.1] * 1536`，`assert len(out) == 1536`）、第 126 行（`[0.0] * 1536`）、第 237 行（`embedding_vec = [0.42] * 1536`）。这些测试均通过 `AsyncMock(return_value=...)` 模拟 embed() 返回值，mock DB 不拒绝向量维度，因此测试为"假绿"状态。单独看每条测试，逻辑上自洽；但在 1024 维 schema 下，这些测试声称 EmbeddingProcessor 返回 1536 维向量，与 BGE-M3 实际维度及 `ProcessedContent.embedding` 列约定不一致。当测试套件在 integration 环境下互相参照时，会引发对"哪个维度是规范维度"的混淆。
- **建议**: 将这三处的 `1536` 统一改为 `1024`，使 EmbeddingProcessor 单测与实际 embed() 合约保持一致。

---

### [R-007] LOW: `test_hybrid.py` 的 `_random_vector(dim=1536)` 默认参数与 schema 不一致

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `tests/unit/search/test_hybrid.py:44` 定义 `_random_vector(dim: int = 1536)`，但 `test_hybrid.py` 中的所有调用均未在 mock 环境下与实际 DB 交互，向量维度对测试正确性无影响。问题仅在于默认参数 `1536` 是一个已废弃的隐式约定；后续开发者复用此 helper 时可能无意间生成错误维度的向量。
- **建议**: 将默认参数改为 `dim: int = 1024`，与项目 `EMBEDDING_DIM` 常量对齐。

---

## 已确认正确的关键设计决策

以下几点经独立审查确认，无问题：

1. **embed() 门控逻辑正确**：`api_base` 为空时立即返回 None，不调用 litellm。门控前置于 Settings 读取之后，符合"无服务即降级"契约。
2. **迁移链唯一头**：通过遍历 `alembic/versions/` 确认只有一个 head（`g0h1i2j3k4l5`），无分叉。`down_revision=a2b3c4d5e6f7` 与链上前序节点一致，迁移链健全。
3. **HNSW 索引名一致性**：迁移文件 drop/recreate 使用 `ix_processed_contents_embedding`，与 `models.py` 中声明的 Index 名一致。`content_clusters.centroid` 在 ORM 中无 HNSW 索引（仅 `ix_content_clusters_tags` GIN + `ix_content_clusters_updated_at`），迁移不处理 centroid 索引是正确的。
4. **维度 1024 在 schema 层完全一致**：`EMBEDDING_DIM=1024`、两列 `Vector(EMBEDDING_DIM)`、迁移 `Vector(1024)`、settings `embedding_dimension=1024` 默认值相互一致。
5. **`content_clusters.centroid` 聚类代码不受影响**：`VectorStore.find_nearest_cluster()` 使用 pgvector `<=>` 运算符，参数为运行时传入的 embedding 向量，不包含任何硬编码维度。查询在列维度改变后自动适配，无需代码同步修改。
6. **migrate 的 NULL 数据安全性**：`existing_nullable=True`，现有 NULL embedding 列在 `ALTER COLUMN TYPE` 时无需回填，迁移安全。
7. **`settings.embedding_dimension` 字段存在但 embed() 不读取它**：embed() 直接返回 litellm response 中的向量，维度由 BGE-M3 模型本身决定，`embedding_dimension` 字段当前仅供下游使用（如 pgvector 列维度校验）。这是合理的设计，embed() 不对返回向量做维度裁剪/扩展。

---

## verdict

**needs_revision**

存在 1 个 HIGH 问题（[R-001] keyless TEI 的 `api_key=""` 静默降级，破坏核心目标）和 5 个 MEDIUM 问题（遗留 1536 测试误导性，文档/注释与 schema 不一致）。高优先级修复 [R-001]；[R-002]~[R-006] 建议随 R-001 一并修复以保持测试套件可读性。

| 严重等级 | 数量 |
|---------|------|
| CRITICAL | 0 |
| HIGH | 1 |
| MEDIUM | 5 |
| LOW | 1 |

---

## 修订闭环（r1）

R-001 ~ R-007 全部修复并经 orchestrator 验证：

- **R-001**：`_embed.py` 透传改 `api_key=settings.embedding_api_key or "tei"`；新增回归测试 `test_embed_keyless_tei_uses_placeholder_api_key`（key 未设时 `_aembedding` 被调用、`api_key=="tei"`、返回非 None）。
- **R-002~R-007**：遗留 1536 测试/docstring/注释统一对齐 1024（test_vector.py 含测试重命名 + `_random_vector` 默认值、test_migration_embedding_dim.py docstring、test_pg_vector_search.py docstring、test_models.py 注释、test_embedding_processor.py 三处、test_hybrid.py 默认值）。

验证：受影响单测全套全绿（含新回归测试），命名测试文件无 1536 真实路径残留，mypy --strict `_embed.py` 通过，ruff 仅余 pre-existing E501。**最终 verdict：approved**。
