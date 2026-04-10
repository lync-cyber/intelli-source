# Development Plan: IntelliSource — Sprint 6
<!-- id: dev-plan-intellisource-v1-s6 | author: tech-lead | status: draft -->
<!-- deps: arch-intellisource-v1 | consumers: developer, qa-engineer -->
<!-- volume: s6 -->

## 3. 任务卡详细

### T-047: 架构文档修订与Sprint 6 dev-plan

- **目标**: 更新架构文档 M-004/M-005/M-006 模块定义，反映处理器/智能体分离设计变更；创建 Sprint 6 开发计划
- **模块**: docs
- **接口**: internal
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-T047-1: arch-intellisource-v1-modules.md 中 M-004 描述更新为"原子化处理工具模块"
  - [ ] AC-T047-2: M-005 描述新增 PromptBuilder/LLMCache/ModelProfile 组件
  - [ ] AC-T047-3: M-006 描述新增 Agent 作为 LLM 编排层、llm_complete 元工具
  - [ ] AC-T047-4: Sprint 6 dev-plan 分卷文件创建且格式与 S1-S5 一致
- **deliverables**:
  - [ ] `docs/arch/arch-intellisource-v1-modules.md` -- M-004/M-005/M-006 更新
  - [ ] `docs/dev-plan/dev-plan-intellisource-v1-s6.md` -- Sprint 6 分卷
  - [ ] `docs/dev-plan/dev-plan-intellisource-v1.md` -- Sprint 6 总览表
- **context_load**:
  - docs/research/prompt-management-analysis.md (OpenCode 调研)

---

### T-048: 原子化工具函数模块

- **目标**: 从旧 LLM 处理器的降级/非 LLM 逻辑中提取 10 个纯原子函数，放置在 pipeline/processors/tools.py，作为 Agent 可调用的工具
- **模块**: M-004→M-003
- **接口**: internal（通过 M-006 AgentToolRegistry 暴露）
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-T048-1: `regex_extract(body_text, patterns)` 从文本中按正则提取结构化数据
  - [ ] AC-T048-2: `fingerprint_generate(title, body_text)` 返回 64 字符 SHA-256 hex 字符串
  - [ ] AC-T048-3: `vector_search_similar(embedding, threshold, vector_store)` 返回候选列表
  - [ ] AC-T048-4: `fingerprint_dedup(title, body_text, known_fps)` 返回 is_duplicate 布尔值
  - [ ] AC-T048-5: `find_nearest_cluster(embedding, threshold, vector_store)` 返回最近聚类或 None
  - [ ] AC-T048-6: `tfidf_keywords(title, body_text)` 返回 top-5 关键词字符串
  - [ ] AC-T048-7: `truncate_summary(cluster_contents)` 返回 {title, summary, timeline, key_points} dict
  - [ ] AC-T048-8: `keyword_tag(body_text, title, tag_library)` 返回匹配标签列表
  - [ ] AC-T048-9: `filter_sensitive(text, sensitive_words)` 返回匹配敏感词列表
  - [ ] AC-T048-10: `truncate_for_push(title, body_text)` 返回 {title, summary} dict
  - [ ] AC-T048-11: 所有函数为 async callable，返回 JSON 可序列化结果
  - [ ] AC-T048-12: 无任何 LLMGateway 依赖（不 import gateway 模块）
  - [ ] AC-T048-13: mypy --strict 零错误
- **deliverables**:
  - [ ] `src/intellisource/pipeline/processors/tools.py` -- 10 个原子工具函数
  - [ ] `tests/unit/pipeline/test_tools.py` -- 每个函数至少 3 个测试用例（≥30 tests）
- **context_load**:
  - src/intellisource/llm/processors/extractor.py (_regex_fallback)
  - src/intellisource/llm/processors/dedup.py (fingerprint flow)
  - src/intellisource/llm/processors/cluster.py (_tfidf_topic)
  - src/intellisource/llm/processors/summarizer.py (_truncation_fallback)
  - src/intellisource/llm/processors/tagger.py (_keyword_fallback)
  - src/intellisource/llm/processors/optimizer.py (_truncation_fallback)
  - src/intellisource/llm/processors/fingerprint.py (FingerprintGenerator)
  - src/intellisource/llm/processors/filter.py (ContentFilter)

---

### T-049: 删除旧LLM处理器 + 重写测试

- **目标**: 删除 6 个旧 LLM 处理器文件及其测试，清理所有 import 引用，确保代码库无残留依赖
- **模块**: M-004
- **接口**: internal
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-T049-1: extractor.py/dedup.py/cluster.py/summarizer.py/tagger.py/optimizer.py/_async_compat.py 全部删除
  - [ ] AC-T049-2: 对应 7 个测试文件全部删除
  - [ ] AC-T049-3: `grep -r "from intellisource.llm.processors.extractor"` 等在 src/ 和 tests/ 中返回零结果
  - [ ] AC-T049-4: llm/processors/**init**.py 清理已删除模块导出
  - [ ] AC-T049-5: mypy --strict src/ 零错误
  - [ ] AC-T049-6: pytest 可正常运行（允许因后续任务未完成而部分测试缺失，但无 import 错误）
- **deliverables**:
  - [ ] 删除 7 个源文件 + 7 个测试文件
  - [ ] 更新 `src/intellisource/llm/processors/__init__.py`
- **context_load**:
  - T-048 deliverables（确认原子工具已就位）

---

### T-050: Agent工具注册增强

- **目标**: 在 AgentToolRegistry 中注册 T-048 的 10 个原子工具 + 新增 llm_complete 元工具
- **模块**: M-006
- **接口**: internal
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-T050-1: `register_atomic_tools()` 注册全部 10 个原子工具
  - [ ] AC-T050-2: 每个工具有 name/description/parameters(JSON Schema)/execute callable
  - [ ] AC-T050-3: `llm_complete` 元工具注册，参数: {call_type: str, prompt_vars: dict}
  - [ ] AC-T050-4: `list_tools()` 返回包含原子工具 + llm_complete + 现有高级工具
  - [ ] AC-T050-5: `filter(allowed=..., denied=...)` 对新工具正常工作
- **deliverables**:
  - [ ] `src/intellisource/agent/tools.py` -- 更新
  - [ ] `tests/unit/agent/test_tools.py` -- 更新
- **context_load**:
  - src/intellisource/agent/tools.py (现有 AgentToolRegistry)
  - T-048 deliverables

---

### T-051: PromptBuilder与Token截断

- **目标**: 创建统一提示词组装器（借鉴 OpenCode），支持模板加载、变量替换、内容 token 截断；增强 LLMGateway 自动截断能力
- **模块**: M-005
- **接口**: internal
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-T051-1: `PromptBuilder(call_type, model)` 从 llm/prompts/ 目录加载对应 .txt 模板
  - [ ] AC-T051-2: `add_content(content, max_tokens)` 超限时截断（保留前40%+后10%，中间 `[...已截断 N 字符...]`）
  - [ ] AC-T051-3: `add_schema(schema)` 将 JSON Schema 序列化为输出约束指令
  - [ ] AC-T051-4: `build_messages()` 返回 `[{role: "system", content: ...}, {role: "user", content: ...}]`
  - [ ] AC-T051-5: `build()` 产出与现有 `load_prompt()` 等价的纯字符串（兼容旧调用方式）
  - [ ] AC-T051-6: `LLMGateway.complete()` 新增可选 `max_input_tokens` 参数
  - [ ] AC-T051-7: prompt 超过模型上下文窗口 80% 时自动截断并 log warning
  - [ ] AC-T051-8: token 估算使用现有 `estimate_tokens()` 方法
- **deliverables**:
  - [ ] `src/intellisource/llm/prompt_builder.py` -- PromptBuilder 类
  - [ ] `src/intellisource/llm/gateway.py` -- 截断增强
  - [ ] `tests/unit/llm/test_prompt_builder.py` -- PromptBuilder 测试
- **context_load**:
  - src/intellisource/llm/prompts/**init**.py (现有 load_prompt)
  - src/intellisource/llm/gateway.py (现有 LLMGateway)
  - docs/research/prompt-management-analysis.md §3.2, §3.5

---

### T-052: LLM调用结果缓存

- **目标**: 实现 Redis LLM 结果缓存，减少重复 LLM 调用（借鉴 OpenCode）
- **模块**: M-005
- **接口**: internal
- **复杂度**: M
- **tdd_acceptance**:
  - [ ] AC-T052-1: cache key 格式: `llm:cache:{call_type}:{prompt_version}:{fingerprint}`
  - [ ] AC-T052-2: TTL 默认 24h，可配置
  - [ ] AC-T052-3: 仅缓存 status=success 的 LLMResult
  - [ ] AC-T052-4: 缓存命中时 LLMCallLog 记录 status=cached, input_tokens=0
  - [ ] AC-T052-5: `invalidate(call_type, prompt_version)` 批量失效
  - [ ] AC-T052-6: LLMGateway 在 cache=None 时正常工作（无 cache 降级）
  - [ ] AC-T052-7: `get_or_call()` 返回 (result, was_cached) 元组
- **deliverables**:
  - [ ] `src/intellisource/llm/cache.py` -- LLMCache 类
  - [ ] `src/intellisource/llm/gateway.py` -- 可选 cache 集成
  - [ ] `tests/unit/llm/test_cache.py` -- 缓存测试
- **context_load**:
  - docs/research/prompt-management-analysis.md §3.3
  - src/intellisource/llm/gateway.py

---

### T-053: 模型参数配置增强

- **目标**: 支持按模型 ID 配置默认参数（temperature/max_tokens/context_window），LLMGateway 自动应用
- **模块**: M-005
- **接口**: internal
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-T053-1: `ModelProfile` dataclass 含 temperature/max_tokens/context_window/prompt_style
  - [ ] AC-T053-2: `ModelRoutingConfig.get_profile(model)` 返回 ModelProfile 或 None
  - [ ] AC-T053-3: LLMGateway 在无显式 temperature 时使用 profile 默认值
  - [ ] AC-T053-4: LLMGateway 在无显式 max_tokens 时使用 profile 默认值
  - [ ] AC-T053-5: 未知模型 fallback 到 gateway 内置默认值
- **deliverables**:
  - [ ] `src/intellisource/llm/model_config.py` -- ModelProfile + get_profile()
  - [ ] `config/llm_models.example.yaml` -- profiles 区段
  - [ ] `src/intellisource/llm/gateway.py` -- profile 默认值集成
  - [ ] `tests/unit/llm/test_model_config.py` -- 更新
- **context_load**:
  - docs/research/prompt-management-analysis.md §3.4
  - src/intellisource/llm/model_config.py

---

### T-054: Agent处理编排引擎

- **目标**: 增强 AgentRunner 成为 LLM 处理的主编排点。Agent 通过 llm_complete 元工具按需调用 LLM，根据管道配置和编排提示词决定工作流
- **模块**: M-006
- **接口**: internal
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-T054-1: `run_flexible()` 接受 system_prompt 参数（从 PipelineConfig 加载）
  - [ ] AC-T054-2: 工具调用结果正确序列化回 LLM 对话上下文
  - [ ] AC-T054-3: Agent 可通过 llm_complete 工具发起 LLM 处理（提取/去重/聚类/摘要/打标/优化）
  - [ ] AC-T054-4: LLM 失败时 Agent 回退到对应原子工具
  - [ ] AC-T054-5: max_steps 限制仍然生效
  - [ ] AC-T054-6: content_process.txt 提示词覆盖提取→去重→聚类→打标→摘要完整工作流
  - [ ] AC-T054-7: push_optimize.txt 提示词覆盖推送优化工作流
- **deliverables**:
  - [ ] `src/intellisource/agent/runner.py` -- run_flexible() 增强
  - [ ] `src/intellisource/agent/pipeline.py` -- PipelineConfig 新增 system_prompt
  - [ ] `src/intellisource/agent/prompts/content_process.txt` -- 内容处理编排提示词
  - [ ] `src/intellisource/agent/prompts/push_optimize.txt` -- 推送优化编排提示词
  - [ ] `config/pipelines/content-process.yaml` -- 内容处理管道
  - [ ] `config/pipelines/push-optimize.yaml` -- 推送优化管道
  - [ ] `tests/unit/agent/test_runner.py` -- 更新
- **context_load**:
  - src/intellisource/agent/runner.py
  - src/intellisource/agent/pipeline.py
  - src/intellisource/agent/prompts/base.txt

---

### T-055: 管道配置更新

- **目标**: 更新现有管道 YAML 配置，strict 模式使用原子工具名称，验证 system_prompt 字段解析
- **模块**: M-006
- **接口**: internal
- **复杂度**: S
- **tdd_acceptance**:
  - [ ] AC-T055-1: scheduled-collect.yaml tools_allowed 更新为原子工具名称
  - [ ] AC-T055-2: instant-search.yaml 包含相关原子工具
  - [ ] AC-T055-3: PipelineConfig 解析 system_prompt 字段（可选，默认 None）
  - [ ] AC-T055-4: 现有管道配置测试通过
- **deliverables**:
  - [ ] `config/pipelines/scheduled-collect.yaml` -- 更新
  - [ ] `config/pipelines/manual-collect.yaml` -- 更新
  - [ ] `config/pipelines/instant-search.yaml` -- 更新
  - [ ] `tests/unit/agent/test_pipeline.py` -- 更新
- **context_load**:
  - config/pipelines/*.yaml
  - src/intellisource/agent/pipeline.py

---

### T-056: 集成测试与全量回归

- **目标**: 编写 Agent 编排集成测试，验证 6 个处理工作流通过 Agent 正确执行；运行全量 pytest + mypy 确认无残留错误
- **模块**: 全模块
- **接口**: internal
- **复杂度**: L
- **tdd_acceptance**:
  - [ ] AC-T056-1: 6 个工作流（提取/去重/聚类/摘要/打标/推送优化）通过 Agent 编排测试覆盖
  - [ ] AC-T056-2: flexible 模式: Agent 正确调用原子工具 + llm_complete
  - [ ] AC-T056-3: strict 模式: 仅原子工具，零 LLM 调用
  - [ ] AC-T056-4: 全量 `pytest` 通过（无 import 错误、无残留引用）
  - [ ] AC-T056-5: `mypy --strict src/` 零错误
- **deliverables**:
  - [ ] `tests/unit/agent/test_orchestration.py` -- Agent 编排集成测试
  - [ ] 全量 pytest + mypy 通过报告
- **context_load**:
  - 所有 T-048 ~ T-055 deliverables
