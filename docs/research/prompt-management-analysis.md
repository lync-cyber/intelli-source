# IntelliSource 提示词管理分析报告

> 对比分析对象: OpenCode (github.com/sst/opencode)
> 分析范围: src/、docs/、config/ 目录（排除 .claude 目录）
> 日期: 2026-04-03

## 1. IntelliSource 当前设计评估

### 1.1 架构概述

IntelliSource 采用 **分布式处理器模式 (Distributed Processor Model)** 管理提示词:

| 组件 | 位置 | 职责 |
|------|------|------|
| LLMGateway | `src/intellisource/llm/gateway.py` | 统一 litellm 调用接口，屏蔽提供商差异 |
| SchemaEnforcer | `src/intellisource/llm/gateway.py` | JSON Schema 输出格式强制校验 |
| 各 LLM Processor | `src/intellisource/llm/processors/*.py` | 每个处理器内嵌自己的 prompt |
| JSON Schemas | `src/intellisource/llm/schemas/` | 结构化输入输出契约 |

**核心设计决策**: 提示词分散在各处理器类内部，没有集中式的 prompt 模板库。每个处理器（Extractor、SemanticDedup、Clusterer、Summarizer、Tagger、SentimentAnalyzer、ContentFilter、PushOptimizer）独立管理自己的 system prompt 和 user prompt 组装逻辑。

### 1.2 现有设计的优点

1. **职责内聚**: 每个处理器自包含 prompt + schema + 降级逻辑，修改一个处理器不影响其他
2. **Gateway 抽象**: litellm 封装提供了统一的 provider/model 切换能力
3. **全链路可观测**: LLMCallLog (E-007) 记录每次调用的 tokens/latency/status
4. **降级优先设计**: 每个 LLM 处理器都有对应的传统算法降级路径
5. **成本追踪**: CostTracker 按 model/call_type 维度统计
6. **优先级队列**: 用户交互请求与后台处理隔离

### 1.3 现有设计的不足

| 问题 | 严重等级 | 影响 |
|------|---------|------|
| 无集中式 Prompt 版本管理 | MEDIUM | prompt 散落各 processor 中，难以审计变更历史、A/B 测试 |
| 缺少 Prompt 缓存机制 | HIGH | 相同类型任务重复构建 prompt，浪费 token 和延迟 |
| 无模型特化适配 | MEDIUM | 不同 LLM 提供商对 prompt 格式有不同偏好，统一 prompt 不一定最优 |
| 缺少上下文窗口管理 | HIGH | 无 token 计数和截断策略，大内容输入可能超出模型限制 |
| 缺少 Prompt 模板化机制 | LOW | 硬编码 prompt 字符串，调整需改代码 |
| 无 Few-shot 支持 | LOW | 缺少示例管理，某些任务（如提取、分类）质量可能不够 |
| LLM 调用结果缓存仅设计未实现 | MEDIUM | arch§5.1 提到 Redis 缓存 24h 方案，但无具体实现设计 |

---

## 2. OpenCode 提示词管理方案分析

OpenCode 是一个 TypeScript 编写的 AI 编程助手 CLI 工具，其提示词管理相当成熟。

### 2.1 多层级 System Prompt 组装

OpenCode 的 prompt 由多个独立层级组合，在 `session/prompt.ts:1501-1507` 处完成最终拼装:

```typescript
const system = [...env, ...(skills ? [skills] : []), ...instructions]
```

层级分解:

| 层级 | 来源 | 说明 |
|------|------|------|
| **Provider Prompt** | `session/prompt/*.txt` | 按模型 ID 匹配最优 prompt 模板 |
| **Environment** | `session/system.ts` | 运行时环境信息（目录、平台、日期等） |
| **Skills** | `session/system.ts` | 可用 skill 的描述，按 agent 权限过滤 |
| **Instructions** | `session/instruction.ts` | 用户项目级指令（AGENTS.md、CLAUDE.md 等） |
| **Reminders** | `session/prompt.ts` | 上下文内注入的 system-reminder 标签 |

### 2.2 模型特化 Prompt (Provider-Specific Prompts)

**这是 OpenCode 最值得借鉴的设计之一。**

`session/system.ts` 中根据 model ID 匹配不同的 prompt 文件:

```typescript
export function provider(model: Provider.Model) {
  if (model.api.id.includes("gpt-4") || model.api.id.includes("o1") || model.api.id.includes("o3"))
    return [PROMPT_BEAST]     // 激进自主模式
  if (model.api.id.includes("gemini-")) return [PROMPT_GEMINI]  // Gemini 专用
  if (model.api.id.includes("claude")) return [PROMPT_ANTHROPIC] // Claude 专用
  return [PROMPT_DEFAULT]     // 通用默认
}
```

每个模型有不同的 prompt 风格:

- **Anthropic (Claude)**: 结构化指令，强调 TodoWrite、Task 工具使用
- **Beast (GPT-4/o1/o3)**: 极度自主模式，强调"不要停下来直到问题完全解决"
- **Gemini**: 注重代码规范遵循，明确路径构建规则
- **Default**: 简洁通用指令

### 2.3 上下文窗口管理 (Context Window Management)

OpenCode 有完整的上下文溢出和压缩机制:

#### 溢出检测 (`session/overflow.ts`)

```typescript
export function isOverflow(input) {
  const count = input.tokens.total || input.tokens.input + input.tokens.output + ...
  const reserved = input.cfg.compaction?.reserved ?? Math.min(COMPACTION_BUFFER, maxOutputTokens)
  const usable = input.model.limit.input
    ? input.model.limit.input - reserved
    : context - maxOutputTokens
  return count >= usable
}
```

#### 工具输出裁剪 (Tool Output Pruning)

- `PRUNE_MINIMUM = 20_000` tokens: 最小裁剪阈值
- `PRUNE_PROTECT = 40_000` tokens: 保护最近的工具调用结果
- 从旧到新逐步标记工具输出为 `compacted`，释放上下文空间

#### 对话压缩 (Compaction)

- 使用独立的 compaction agent 将历史对话总结为摘要
- 摘要模板包含: Goal、Context、Changes、Current State、Next Steps
- 支持自动触发和手动触发

### 2.4 指令文件层级解析 (Instruction Resolution)

`session/instruction.ts` 实现了分层指令加载:

1. **全局指令**: `~/.config/opencode/AGENTS.md` 或 `~/.claude/CLAUDE.md`
2. **项目根指令**: 项目根目录的 `AGENTS.md`/`CLAUDE.md`
3. **目录级指令**: 读取文件时，向上遍历目录树查找就近的指令文件
4. **远程指令**: 支持通过 URL 加载远程指令文件
5. **去重机制**: 使用 `claims` Map 跟踪已附加的指令，避免重复

### 2.5 工具输出截断 (Tool Output Truncation)

`tool/truncate.ts` — 当工具返回内容超长时:

- 自动截断到合理长度
- 将完整内容写入临时文件
- 返回截断内容 + 文件路径引用

---

## 3. 可借鉴的改进建议

以下建议按 **投入产出比** 排序（高优先 = 低复杂度 + 高收益）。

### 3.1 [推荐] Prompt 模板外置化

**问题**: prompt 硬编码在 processor 类中，修改需改代码。
**方案**: 将 prompt 模板抽取到独立文件，运行时加载。

```
src/intellisource/llm/
  prompts/
    extractor.txt          # 结构化提取 system prompt
    dedup.txt              # 语义去重 system prompt
    cluster.txt            # 聚类主题生成 prompt
    summarizer.txt         # 摘要生成 prompt
    tagger.txt             # 打标 prompt
    sentiment.txt          # 情感分析 prompt
    filter.txt             # 合规检查 prompt
    optimizer.txt           # 推送优化 prompt
```

**实现要点**:

- 使用 Python `importlib.resources` 或 `pathlib` 加载 `.txt` 文件
- 支持 `{content}`, `{schema}`, `{context}` 等占位符的简单模板替换
- prompt 文件变更无需重启服务（配合 ConfigWatcher 热加载）

**复杂度**: 低 | **收益**: prompt 版本可 git 追踪，非开发人员可调优

### 3.2 [推荐] 输入内容 Token 截断

**问题**: 长文本内容直接送入 LLM，可能超出上下文窗口或浪费 token。
**方案**: 在 LLMGateway 层增加 token 计数和智能截断。

```python
class LLMGateway:
    async def complete(self, *, messages, max_input_tokens=None, **kwargs):
        # 1. 估算当前 messages 的 token 数
        estimated = self._estimate_tokens(messages)
        model_limit = self._get_model_context_limit(kwargs.get("model"))

        # 2. 如超限，截断最长的 user message 内容
        if estimated > model_limit * 0.8:
            messages = self._truncate_messages(messages, target=model_limit * 0.7)

        return await litellm.acompletion(messages=messages, **kwargs)
```

**实现要点**:

- 使用 `tiktoken` 或 litellm 内置的 token 计数
- 截断策略: 保留首尾内容，中间用 `[... 内容已截断，共 N 字符 ...]` 替代
- 按模型配置不同的 context window 限制

**复杂度**: 低 | **收益**: 防止 API 报错，降低 token 成本

### 3.3 [推荐] LLM 调用结果缓存实现

**问题**: arch§5.1 已设计但未有具体实现规划。相同内容重复处理浪费资源。
**方案**: 基于内容指纹 + 处理类型的 Redis 缓存。

```python
class LLMCache:
    def cache_key(self, content_fingerprint: str, call_type: str, prompt_version: str) -> str:
        return f"llm:cache:{call_type}:{prompt_version}:{content_fingerprint}"

    async def get_or_call(self, fingerprint, call_type, prompt_ver, llm_fn):
        key = self.cache_key(fingerprint, call_type, prompt_ver)
        cached = await redis.get(key)
        if cached:
            return json.loads(cached)  # 命中缓存
        result = await llm_fn()
        await redis.setex(key, 86400, json.dumps(result))  # 缓存 24h
        return result
```

**关键细节**:

- cache key 包含 `prompt_version`，prompt 模板更新后自动失效
- 仅缓存 `status=success` 的结果
- 缓存命中记录到 LLMCallLog (`status=cached`)

**复杂度**: 中 | **收益**: 直接减少 LLM 调用次数和成本

### 3.4 [可选] 模型特化参数适配

**问题**: 同一个 prompt 对不同模型效果不同。
**方案**: 在 LLMGateway 配置中支持按模型微调参数。

```yaml
# config/llm_profiles.yaml
profiles:
  openai:
    gpt-4o:
      temperature: 0.3
      max_tokens: 2000
      prompt_style: "concise"  # 简洁指令风格
  anthropic:
    claude-sonnet:
      temperature: 0.2
      max_tokens: 4000
      prompt_style: "structured"  # 结构化指令风格
  zhipuai:
    glm-4:
      temperature: 0.5
      max_tokens: 2000
      prompt_style: "detailed"  # 详细指令风格
```

**注意**: 不需要像 OpenCode 那样为每个模型维护完整的不同 prompt 文件。IntelliSource 的 LLM 调用场景（提取、分类、摘要等）相对固定，只需按模型微调关键参数（temperature、max_tokens）即可。

**复杂度**: 低 | **收益**: 不同模型获得更优质量

### 3.5 [可选] Prompt 组装器 (Prompt Builder)

**问题**: 各处理器独立组装 messages，格式和逻辑重复。
**方案**: 提供统一的 Prompt Builder 工具类。

```python
class PromptBuilder:
    def __init__(self, call_type: str, model: str):
        self.call_type = call_type
        self.model = model
        self._system = self._load_template(call_type)
        self._user_parts = []

    def _load_template(self, call_type: str) -> str:
        """从 prompts/ 目录加载对应模板"""
        ...

    def add_content(self, content: str, max_tokens: int | None = None) -> "PromptBuilder":
        """添加内容，自动截断"""
        if max_tokens:
            content = self._truncate(content, max_tokens)
        self._user_parts.append(content)
        return self

    def add_schema(self, schema: dict) -> "PromptBuilder":
        """添加输出 schema 指令"""
        self._user_parts.append(f"按以下 JSON Schema 输出:\n{json.dumps(schema, ensure_ascii=False)}")
        return self

    def build(self) -> list[dict]:
        """构建最终的 messages 列表"""
        return [
            {"role": "system", "content": self._system},
            {"role": "user", "content": "\n\n".join(self._user_parts)},
        ]
```

处理器使用:

```python
class LLMExtractor(BaseProcessor):
    async def process(self, content: str, schema: dict):
        messages = (
            PromptBuilder("extractor", self.model)
            .add_content(content, max_tokens=3000)
            .add_schema(schema)
            .build()
        )
        return await self.gateway.complete(messages=messages)
```

**复杂度**: 中 | **收益**: 统一 prompt 组装逻辑，减少重复代码

### 3.6 [不推荐] 完整的对话压缩系统

OpenCode 的 Compaction 系统（对话总结 + 工具输出裁剪 + 溢出检测）非常精巧，但 **不适合 IntelliSource**:

- IntelliSource 的 LLM 调用主要是 **无状态的单轮处理**（提取、分类、摘要），不是多轮对话
- 唯一的多轮场景是即时问答 (ChatSession)，但上下文仅保留最近 5 轮，已有简单有效的控制
- 引入完整压缩系统增加的复杂度远超收益

---

## 4. 总结

### 设计合理性评估

IntelliSource 的提示词管理设计 **整体合理**，特别是 Gateway 抽象、降级优先、全链路可观测这三个设计决策质量较高。分布式处理器模式适合其场景——各处理器独立性强，不存在复杂的 prompt 组合需求。

### 主要改进优先级

| 优先级 | 改进项 | 复杂度 | 预期收益 |
|--------|--------|--------|---------|
| P0 | 输入内容 Token 截断 (§3.2) | 低 | 防止 API 错误，降低成本 |
| P0 | LLM 调用结果缓存 (§3.3) | 中 | 直接减少调用次数和成本 |
| P1 | Prompt 模板外置化 (§3.1) | 低 | 可维护性、可追踪性 |
| P2 | 模型特化参数适配 (§3.4) | 低 | 不同模型获得更优质量 |
| P2 | Prompt Builder (§3.5) | 中 | 减少重复代码 |
| — | 对话压缩系统 (§3.6) | 高 | 不推荐，场景不匹配 |

### 不建议引入的设计

- **多文件 provider-specific prompt**: IntelliSource 不是交互式编程助手，不需要为每个模型维护完整的不同 system prompt
- **分层指令解析**: 无需目录级指令文件层级，IntelliSource 是后端服务而非 CLI 工具
- **Tool Output Truncation**: IntelliSource 的处理器输出是结构化数据（JSON），不存在工具输出过长的问题
