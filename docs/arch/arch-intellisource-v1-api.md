# Architecture 分卷 -- 接口契约: IntelliSource
<!-- required_sections: ["## 3. 接口契约"] -->
<!-- volume_type: api -->
<!-- id: arch-intellisource-v1-api | author: architect | status: approved -->
<!-- deps: prd-intellisource-v1 | consumers: tech-lead, developer, devops -->
<!-- volume: api | split-from: arch-intellisource-v1 -->

[NAV]

- §3 接口契约 → API-001..API-032
[/NAV]

## 3. 接口契约

> 通用约定:
>
> - 基础路径: `/api/v1`
> - 认证: 所有接口（除 Webhook 回调和健康检查外）需在请求头携带 `X-API-Key`
> - Webhook 回调接口使用平台签名验证
> - 分页: 列表接口统一使用游标分页，参数 `cursor`（可选）和 `limit`（默认 20，最大 100）
> - 错误响应统一格式见 arch#§5.3

### API-001: 获取信源列表

```yaml
path: /api/v1/sources
method: GET
module: M-001
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  query:
    cursor: { type: string, required: false, desc: "分页游标" }
    limit: { type: integer, required: false, desc: "每页数量，默认 20，最大 100" }
    type: { type: string, required: false, desc: "信源类型过滤: rss | api | web" }
    tag: { type: string, required: false, desc: "学科标签过滤" }
    status: { type: string, required: false, desc: "状态过滤: active | paused | error" }
response:
  200:
    schema: "SourceListResponse"
    body:
      items: { type: "array[Source]", desc: "信源列表" }
      next_cursor: { type: "string | null", desc: "下一页游标" }
      has_more: { type: boolean, desc: "是否有更多数据" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-002: 创建信源

```yaml
path: /api/v1/sources
method: POST
module: M-001
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  body:
    name: { type: string, required: true, desc: "信源名称" }
    type: { type: string, required: true, desc: "信源类型: rss | api | web" }
    url: { type: string, required: true, desc: "信源 URL" }
    tags: { type: "array[string]", required: false, desc: "学科标签列表" }
    schedule:
      interval: { type: integer, required: false, desc: "采集间隔（秒），默认 3600" }
      adaptive: { type: boolean, required: false, desc: "是否启用自适应频率，默认 true" }
    proxy: { type: string, required: false, desc: "HTTP 代理地址" }
    rate_limit:
      qps: { type: number, required: false, desc: "每秒请求数限制" }
      concurrency: { type: integer, required: false, desc: "并发请求数限制" }
    metadata: { type: object, required: false, desc: "自定义扩展字段" }
response:
  201:
    schema: "Source"
    body:
      id: { type: string, desc: "信源 ID" }
      name: { type: string, desc: "信源名称" }
      type: { type: string, desc: "信源类型" }
      status: { type: string, desc: "状态: active" }
      created_at: { type: datetime, desc: "创建时间" }
  400: { schema: "ErrorResponse", desc: "参数校验失败" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  409: { schema: "ErrorResponse", desc: "信源名称或 URL 已存在" }
```

### API-003: 更新信源（部分更新）

```yaml
path: /api/v1/sources/{id}
method: PATCH
module: M-001
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  path_params:
    id: { type: string, required: true, desc: "信源 ID" }
  body:
    name: { type: string, required: false, desc: "信源名称" }
    url: { type: string, required: false, desc: "信源 URL" }
    tags: { type: "array[string]", required: false, desc: "学科标签列表" }
    schedule:
      interval: { type: integer, required: false, desc: "采集间隔（秒）" }
      adaptive: { type: boolean, required: false, desc: "是否启用自适应频率" }
    proxy: { type: string, required: false, desc: "HTTP 代理地址" }
    rate_limit:
      qps: { type: number, required: false, desc: "每秒请求数限制" }
      concurrency: { type: integer, required: false, desc: "并发请求数限制" }
    status: { type: string, required: false, desc: "状态: active | paused" }
    metadata: { type: object, required: false, desc: "自定义扩展字段" }
response:
  200: { schema: "Source", desc: "更新后的信源对象" }
  400: { schema: "ErrorResponse", desc: "参数校验失败" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  404: { schema: "ErrorResponse", desc: "信源不存在" }
```

### API-004: 删除信源

```yaml
path: /api/v1/sources/{id}
method: DELETE
module: M-001
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  path_params:
    id: { type: string, required: true, desc: "信源 ID" }
response:
  204: { desc: "删除成功，无返回体" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  404: { schema: "ErrorResponse", desc: "信源不存在" }
```

### API-005: 重载配置

```yaml
path: /api/v1/sources/reload
method: POST
module: M-001
desc: "从预定义配置目录重新加载信源配置，实现热加载。仅从服务端预配置的配置目录加载，不接受外部路径参数（防止路径遍历攻击，见 arch#§5.2 输入校验策略）"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  body:
    config_name: { type: string, required: false, desc: "配置文件名（不含路径），限白名单内文件名，为空则加载默认配置" }
response:
  200:
    schema: "ReloadResponse"
    body:
      loaded_count: { type: integer, desc: "成功加载的信源数" }
      errors: { type: "array[ConfigError]", desc: "校验失败的条目列表" }
  400: { schema: "ErrorResponse", desc: "配置文件格式错误或文件名不在白名单内" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-006: 获取任务列表

```yaml
path: /api/v1/tasks
method: GET
module: M-006
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  query:
    cursor: { type: string, required: false, desc: "分页游标" }
    limit: { type: integer, required: false, desc: "每页数量，默认 20" }
    status: { type: string, required: false, desc: "状态过滤: pending | running | success | failed | paused" }
    type: { type: string, required: false, desc: "任务类型: collect | process | distribute | workflow" }
    source_id: { type: string, required: false, desc: "关联信源 ID 过滤" }
response:
  200:
    schema: "TaskListResponse"
    body:
      items: { type: "array[Task]", desc: "任务列表" }
      next_cursor: { type: "string | null", desc: "下一页游标" }
      has_more: { type: boolean, desc: "是否有更多数据" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-007: 触发采集任务

```yaml
path: /api/v1/tasks/collect
method: POST
module: M-006
desc: "手动触发一次采集任务"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  body:
    source_ids: { type: "array[string]", required: false, desc: "指定信源 ID 列表，为空则采集全部活跃信源" }
    priority: { type: string, required: false, desc: "优先级: low | normal | high，默认 normal" }
response:
  202:
    schema: "TaskTriggerResponse"
    body:
      task_chain_id: { type: string, desc: "任务链 ID" }
      tasks: { type: "array[TaskBrief]", desc: "创建的子任务摘要" }
      message: { type: string, desc: "提示信息" }
  400: { schema: "ErrorResponse", desc: "参数校验失败" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-008: 查询任务状态

```yaml
path: /api/v1/tasks/{id}
method: GET
module: M-006
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  path_params:
    id: { type: string, required: true, desc: "任务 ID 或任务链 ID" }
response:
  200:
    schema: "TaskDetail"
    body:
      id: { type: string, desc: "任务 ID" }
      type: { type: string, desc: "任务类型" }
      status: { type: string, desc: "任务状态" }
      progress: { type: object, desc: "进度信息（已完成/总数）" }
      started_at: { type: "datetime | null", desc: "开始时间" }
      finished_at: { type: "datetime | null", desc: "完成时间" }
      error: { type: "string | null", desc: "错误信息" }
      subtasks: { type: "array[TaskBrief] | null", desc: "子任务列表（仅任务链）" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  404: { schema: "ErrorResponse", desc: "任务不存在" }
```

### API-009: 暂停/恢复任务

```yaml
path: /api/v1/tasks/{id}
method: PATCH
module: M-006
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  path_params:
    id: { type: string, required: true, desc: "任务 ID" }
  body:
    action: { type: string, required: true, desc: "操作: pause | resume | cancel" }
response:
  200:
    schema: "TaskBrief"
    body:
      id: { type: string, desc: "任务 ID" }
      status: { type: string, desc: "更新后状态" }
      message: { type: string, desc: "操作结果说明" }
  400: { schema: "ErrorResponse", desc: "操作不允许（如已完成的任务不可暂停）" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  404: { schema: "ErrorResponse", desc: "任务不存在" }
```

### API-010: 创建工作流

```yaml
path: /api/v1/workflows
method: POST
module: M-006
desc: "定义自定义工作流（采集-处理-分发的灵活组合）"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  body:
    name: { type: string, required: true, desc: "工作流名称" }
    description: { type: string, required: false, desc: "工作流描述" }
    steps:
      type: "array[WorkflowStep]"
      required: true
      desc: "工作流步骤列表"
      items:
        step_type: { type: string, desc: "步骤类型: collect | process | distribute" }
        config: { type: object, desc: "步骤配置（信源/管道/渠道参数）" }
        on_failure: { type: string, desc: "失败策略: retry | skip | abort，默认 retry" }
    schedule: { type: string, required: false, desc: "Cron 表达式，为空则仅手动触发" }
response:
  201:
    schema: "Workflow"
    body:
      id: { type: string, desc: "工作流 ID" }
      name: { type: string, desc: "工作流名称" }
      steps_count: { type: integer, desc: "步骤数" }
      created_at: { type: datetime, desc: "创建时间" }
  400: { schema: "ErrorResponse", desc: "参数校验失败" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-011: 执行工作流

```yaml
path: /api/v1/workflows/{id}/run
method: POST
module: M-006
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  path_params:
    id: { type: string, required: true, desc: "工作流 ID" }
  body:
    override_params: { type: object, required: false, desc: "运行时参数覆盖" }
response:
  202:
    schema: "TaskTriggerResponse"
    body:
      task_chain_id: { type: string, desc: "任务链 ID" }
      workflow_id: { type: string, desc: "工作流 ID" }
      message: { type: string, desc: "提示信息" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  404: { schema: "ErrorResponse", desc: "工作流不存在" }
```

### API-012: 混合检索

```yaml
path: /api/v1/search
method: POST
module: M-008
desc: "关键词 + 向量语义混合检索"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  body:
    query: { type: string, required: true, desc: "检索查询文本" }
    tags: { type: "array[string]", required: false, desc: "标签过滤" }
    date_from: { type: datetime, required: false, desc: "起始时间过滤" }
    date_to: { type: datetime, required: false, desc: "结束时间过滤" }
    limit: { type: integer, required: false, desc: "返回数量，默认 10，最大 50" }
    search_mode: { type: string, required: false, desc: "检索模式: keyword | semantic | hybrid，默认 hybrid" }
response:
  200:
    schema: "SearchResponse"
    body:
      items:
        type: "array[SearchResult]"
        desc: "检索结果列表"
        item_fields:
          content_id: { type: string, desc: "内容 ID" }
          title: { type: string, desc: "标题" }
          snippet: { type: string, desc: "匹配片段" }
          score: { type: number, desc: "相关性得分" }
          source_name: { type: string, desc: "来源信源名称" }
          published_at: { type: datetime, desc: "发布时间" }
      total: { type: integer, desc: "匹配总数" }
      query_time_ms: { type: integer, desc: "查询耗时（毫秒）" }
  400: { schema: "ErrorResponse", desc: "参数校验失败" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-013: 即时问答

```yaml
path: /api/v1/search/chat
method: POST
module: M-008
desc: "基于 LLM 的即时问答检索，支持多轮对话。本接口为同步 REST 调用模式；消息渠道用户的异步检索流程通过 API-020/API-021 Webhook 接入，由 M-008 内部异步处理后回调返回结果（对应 AC-052）"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  body:
    message: { type: string, required: true, desc: "用户问题" }
    session_id: { type: string, required: false, desc: "会话 ID，为空则创建新会话" }
response:
  200:
    schema: "ChatResponse"
    body:
      session_id: { type: string, desc: "会话 ID" }
      answer: { type: string, desc: "LLM 生成的回答摘要" }
      sources:
        type: "array[SourceReference]"
        desc: "引用的内容来源"
        item_fields:
          content_id: { type: string, desc: "内容 ID" }
          title: { type: string, desc: "标题" }
          url: { type: string, desc: "原始 URL" }
      query_time_ms: { type: integer, desc: "查询耗时（毫秒）" }
  400: { schema: "ErrorResponse", desc: "参数校验失败" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-014: 获取内容列表

```yaml
path: /api/v1/contents
method: GET
module: M-009
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  query:
    cursor: { type: string, required: false, desc: "分页游标" }
    limit: { type: integer, required: false, desc: "每页数量，默认 20" }
    source_id: { type: string, required: false, desc: "信源 ID 过滤" }
    tag: { type: string, required: false, desc: "标签过滤" }
    cluster_id: { type: string, required: false, desc: "聚类 ID 过滤" }
    date_from: { type: datetime, required: false, desc: "起始时间过滤" }
    date_to: { type: datetime, required: false, desc: "结束时间过滤" }
response:
  200:
    schema: "ContentListResponse"
    body:
      items:
        type: "array[ContentBrief]"
        desc: "内容摘要列表"
        item_fields:
          id: { type: string, desc: "内容 ID" }
          title: { type: string, desc: "标题" }
          summary: { type: string, desc: "摘要" }
          tags: { type: "array[string]", desc: "标签列表" }
          sentiment: { type: string, desc: "情感倾向: positive | neutral | negative" }
          source_name: { type: string, desc: "来源名称" }
          published_at: { type: datetime, desc: "发布时间" }
      next_cursor: { type: "string | null", desc: "下一页游标" }
      has_more: { type: boolean, desc: "是否有更多数据" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-015: 获取内容详情

```yaml
path: /api/v1/contents/{id}
method: GET
module: M-009
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  path_params:
    id: { type: string, required: true, desc: "内容 ID" }
response:
  200:
    schema: "ContentDetail"
    body:
      id: { type: string, desc: "内容 ID" }
      title: { type: string, desc: "标题" }
      author: { type: "string | null", desc: "作者" }
      body_text: { type: string, desc: "正文内容" }
      summary: { type: "string | null", desc: "LLM 生成摘要" }
      tags: { type: "array[string]", desc: "标签列表" }
      sentiment: { type: "string | null", desc: "情感倾向" }
      fingerprint: { type: string, desc: "内容指纹" }
      source_url: { type: string, desc: "原始 URL" }
      source_name: { type: string, desc: "来源名称" }
      cluster_id: { type: "string | null", desc: "所属聚类 ID" }
      published_at: { type: datetime, desc: "发布时间" }
      collected_at: { type: datetime, desc: "采集时间" }
      processed_at: { type: "datetime | null", desc: "处理完成时间" }
      structured_data: { type: "object | null", desc: "LLM 结构化提取结果（对应 E-004.structured_data, AC-018）" }
      metadata: { type: object, desc: "扩展元数据" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  404: { schema: "ErrorResponse", desc: "内容不存在" }
```

### API-016: 获取聚类列表

```yaml
path: /api/v1/clusters
method: GET
module: M-009
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  query:
    cursor: { type: string, required: false, desc: "分页游标" }
    limit: { type: integer, required: false, desc: "每页数量，默认 20" }
    tag: { type: string, required: false, desc: "标签过滤" }
    date_from: { type: datetime, required: false, desc: "起始时间过滤" }
response:
  200:
    schema: "ClusterListResponse"
    body:
      items:
        type: "array[Cluster]"
        desc: "聚类列表"
        item_fields:
          id: { type: string, desc: "聚类 ID" }
          topic: { type: string, desc: "聚类主题" }
          content_count: { type: integer, desc: "包含内容数" }
          digest: { type: "string | null", desc: "综合简报摘要" }
          tags: { type: "array[string]", desc: "标签列表" }
          created_at: { type: datetime, desc: "创建时间" }
          updated_at: { type: datetime, desc: "最后更新时间" }
      next_cursor: { type: "string | null", desc: "下一页游标" }
      has_more: { type: boolean, desc: "是否有更多数据" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-017: LLM 用量统计

```yaml
path: /api/v1/llm/stats
method: GET
module: M-005
desc: "查询 LLM 调用统计数据"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  query:
    period: { type: string, required: false, desc: "统计周期: day | week | month，默认 day" }
    model: { type: string, required: false, desc: "模型名称过滤" }
    date_from: { type: datetime, required: false, desc: "起始时间" }
    date_to: { type: datetime, required: false, desc: "结束时间" }
response:
  200:
    schema: "LLMStatsResponse"
    body:
      period: { type: string, desc: "统计周期" }
      total_calls: { type: integer, desc: "总调用次数" }
      total_tokens: { type: integer, desc: "总 Token 消耗" }
      total_input_tokens: { type: integer, desc: "输入 Token" }
      total_output_tokens: { type: integer, desc: "输出 Token" }
      avg_latency_ms: { type: number, desc: "平均延迟（毫秒）" }
      by_model:
        type: "array[ModelStats]"
        desc: "按模型分组统计"
        item_fields:
          model: { type: string, desc: "模型名称" }
          calls: { type: integer, desc: "调用次数" }
          tokens: { type: integer, desc: "Token 消耗" }
          avg_latency_ms: { type: number, desc: "平均延迟" }
          error_rate: { type: number, desc: "错误率（0-1）" }
      by_date:
        type: "array[DateStats]"
        desc: "按日期分组统计"
        item_fields:
          date: { type: string, desc: "日期" }
          calls: { type: integer, desc: "调用次数" }
          tokens: { type: integer, desc: "Token 消耗" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-018: 系统健康检查

```yaml
path: /api/v1/health
method: GET
module: M-010
desc: "系统健康检查端点，无需认证"
request:
  headers: {}
response:
  200:
    schema: "HealthResponse"
    body:
      status: { type: string, desc: "healthy | degraded | unhealthy" }
      version: { type: string, desc: "系统版本号" }
      uptime_seconds: { type: integer, desc: "运行时间（秒）" }
      checks:
        type: "object"
        desc: "各组件健康状态"
        fields:
          database: { type: string, desc: "healthy | unhealthy" }
          redis: { type: string, desc: "healthy | unhealthy" }
          celery: { type: string, desc: "healthy | unhealthy" }
      timestamp: { type: datetime, desc: "检查时间" }
  503:
    schema: "HealthResponse"
    desc: "系统不健康（至少一个关键组件不可用）"
```

### API-019: 系统指标

```yaml
path: /api/v1/metrics
method: GET
module: M-010
desc: "Prometheus 格式指标端点"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
response:
  200:
    content_type: "text/plain"
    desc: "Prometheus 格式指标文本，包含: 采集成功率、延迟、队列长度、LLM Token 用量等"
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-020: 微信消息回调

```yaml
path: /api/v1/webhooks/wechat
method: POST
module: M-007
desc: "微信公众号消息/事件回调接口，使用微信签名验证"
request:
  headers:
    Content-Type: { type: string, required: true, desc: "text/xml 或 application/xml" }
  query:
    signature: { type: string, required: true, desc: "微信签名" }
    timestamp: { type: string, required: true, desc: "时间戳" }
    nonce: { type: string, required: true, desc: "随机数" }
    msg_signature: { type: string, required: false, desc: "消息体签名（加密模式）" }
  body:
    xml_payload: { type: "XML", required: true, desc: "微信消息 XML 体（含 MsgType/Content 等字段）" }
response:
  200:
    content_type: "text/xml"
    desc: "微信要求的 XML 响应（空字符串或回复消息）"
  403: { desc: "签名验证失败" }
```

### API-021: 企业微信消息回调

```yaml
path: /api/v1/webhooks/wework
method: POST
module: M-007
desc: "企业微信应用消息回调接口，使用企业微信签名验证"
request:
  headers:
    Content-Type: { type: string, required: true, desc: "text/xml 或 application/xml" }
  query:
    msg_signature: { type: string, required: true, desc: "消息体签名" }
    timestamp: { type: string, required: true, desc: "时间戳" }
    nonce: { type: string, required: true, desc: "随机数" }
  body:
    xml_payload: { type: "XML", required: true, desc: "企业微信消息 XML 体" }
response:
  200:
    content_type: "text/xml"
    desc: "企业微信要求的 XML 响应"
  403: { desc: "签名验证失败" }
```

### API-022: 获取订阅规则列表

```yaml
path: /api/v1/subscriptions
method: GET
module: M-007
desc: "获取订阅规则列表"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  query:
    cursor: { type: string, required: false, desc: "分页游标" }
    limit: { type: integer, required: false, desc: "每页数量，默认 20，最大 100" }
    channel: { type: string, required: false, desc: "渠道过滤: wechat | wework | email" }
    status: { type: string, required: false, desc: "状态过滤: active | paused" }
response:
  200:
    schema: "SubscriptionListResponse"
    body:
      items:
        type: "array[Subscription]"
        desc: "订阅规则列表"
        item_fields:
          id: { type: string, desc: "订阅 ID" }
          name: { type: string, desc: "订阅规则名称" }
          channel: { type: string, desc: "推送渠道" }
          frequency: { type: string, desc: "推送频率" }
          status: { type: string, desc: "订阅状态" }
          created_at: { type: datetime, desc: "创建时间" }
      next_cursor: { type: "string | null", desc: "下一页游标" }
      has_more: { type: boolean, desc: "是否有更多数据" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-023: 创建订阅规则

```yaml
path: /api/v1/subscriptions
method: POST
module: M-007
desc: "创建新的订阅规则"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  body:
    name: { type: string, required: true, desc: "订阅规则名称" }
    source_id: { type: string, required: false, desc: "关联信源 ID，为空则匹配全部信源" }
    channel: { type: string, required: true, desc: "推送渠道: wechat | wework | email" }
    channel_config: { type: object, required: true, desc: "渠道配置（OpenID/CorpID/邮箱地址等）" }
    match_rules:
      type: object
      required: true
      desc: "匹配规则"
      fields:
        keywords: { type: "array[string]", required: false, desc: "关键词列表" }
        tags: { type: "array[string]", required: false, desc: "标签列表" }
        sentiment: { type: "array[string]", required: false, desc: "情感倾向过滤: positive | neutral | negative" }
    frequency: { type: string, required: false, desc: "推送频率: realtime | hourly | daily | weekly，默认 realtime" }
    quiet_hours:
      type: object
      required: false
      desc: "免打扰时段"
      fields:
        start: { type: string, desc: "开始时间，如 22:00" }
        end: { type: string, desc: "结束时间，如 08:00" }
response:
  201:
    schema: "Subscription"
    body:
      id: { type: string, desc: "订阅 ID" }
      name: { type: string, desc: "订阅规则名称" }
      channel: { type: string, desc: "推送渠道" }
      status: { type: string, desc: "状态: active" }
      created_at: { type: datetime, desc: "创建时间" }
  400: { schema: "ErrorResponse", desc: "参数校验失败" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-024: 更新订阅规则

```yaml
path: /api/v1/subscriptions/{id}
method: PATCH
module: M-007
desc: "部分更新订阅规则"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  path_params:
    id: { type: string, required: true, desc: "订阅 ID" }
  body:
    name: { type: string, required: false, desc: "订阅规则名称" }
    source_id: { type: "string | null", required: false, desc: "关联信源 ID，null 表示匹配全部" }
    channel_config: { type: object, required: false, desc: "渠道配置" }
    match_rules: { type: object, required: false, desc: "匹配规则" }
    frequency: { type: string, required: false, desc: "推送频率" }
    quiet_hours: { type: "object | null", required: false, desc: "免打扰时段，null 表示取消" }
    status: { type: string, required: false, desc: "订阅状态: active | paused" }
response:
  200: { schema: "Subscription", desc: "更新后的订阅规则" }
  400: { schema: "ErrorResponse", desc: "参数校验失败" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  404: { schema: "ErrorResponse", desc: "订阅规则不存在" }
```

### API-025: 删除订阅规则

```yaml
path: /api/v1/subscriptions/{id}
method: DELETE
module: M-007
desc: "删除订阅规则"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  path_params:
    id: { type: string, required: true, desc: "订阅 ID" }
response:
  204: { desc: "删除成功，无返回体" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  404: { schema: "ErrorResponse", desc: "订阅规则不存在" }
```

### API-026: 获取工作流列表

```yaml
path: /api/v1/workflows
method: GET
module: M-006
desc: "获取工作流定义列表"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  query:
    cursor: { type: string, required: false, desc: "分页游标" }
    limit: { type: integer, required: false, desc: "每页数量，默认 20，最大 100" }
    status: { type: string, required: false, desc: "状态过滤: active | paused | archived" }
response:
  200:
    schema: "WorkflowListResponse"
    body:
      items:
        type: "array[WorkflowBrief]"
        desc: "工作流列表"
        item_fields:
          id: { type: string, desc: "工作流 ID" }
          name: { type: string, desc: "工作流名称" }
          steps_count: { type: integer, desc: "步骤数" }
          schedule_cron: { type: "string | null", desc: "定时表达式" }
          status: { type: string, desc: "工作流状态" }
          last_run_at: { type: "datetime | null", desc: "上次执行时间" }
          created_at: { type: datetime, desc: "创建时间" }
      next_cursor: { type: "string | null", desc: "下一页游标" }
      has_more: { type: boolean, desc: "是否有更多数据" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-027: 获取工作流详情

```yaml
path: /api/v1/workflows/{id}
method: GET
module: M-006
desc: "获取工作流定义详情"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  path_params:
    id: { type: string, required: true, desc: "工作流 ID" }
response:
  200:
    schema: "WorkflowDetail"
    body:
      id: { type: string, desc: "工作流 ID" }
      name: { type: string, desc: "工作流名称" }
      description: { type: "string | null", desc: "工作流描述" }
      steps: { type: "array[WorkflowStep]", desc: "步骤定义列表" }
      schedule_cron: { type: "string | null", desc: "定时表达式" }
      status: { type: string, desc: "工作流状态" }
      last_run_at: { type: "datetime | null", desc: "上次执行时间" }
      created_at: { type: datetime, desc: "创建时间" }
      updated_at: { type: datetime, desc: "更新时间" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  404: { schema: "ErrorResponse", desc: "工作流不存在" }
```

### API-028: 更新工作流

```yaml
path: /api/v1/workflows/{id}
method: PATCH
module: M-006
desc: "部分更新工作流定义"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  path_params:
    id: { type: string, required: true, desc: "工作流 ID" }
  body:
    name: { type: string, required: false, desc: "工作流名称" }
    description: { type: string, required: false, desc: "工作流描述" }
    steps: { type: "array[WorkflowStep]", required: false, desc: "步骤定义列表" }
    schedule: { type: "string | null", required: false, desc: "Cron 表达式，null 表示取消定时" }
    status: { type: string, required: false, desc: "状态: active | paused | archived" }
response:
  200: { schema: "WorkflowDetail", desc: "更新后的工作流" }
  400: { schema: "ErrorResponse", desc: "参数校验失败" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  404: { schema: "ErrorResponse", desc: "工作流不存在" }
```

### API-029: 删除工作流

```yaml
path: /api/v1/workflows/{id}
method: DELETE
module: M-006
desc: "删除工作流定义（关联的已执行任务链记录保留）"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  path_params:
    id: { type: string, required: true, desc: "工作流 ID" }
response:
  204: { desc: "删除成功，无返回体" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  404: { schema: "ErrorResponse", desc: "工作流不存在" }
```

### API-030: 删除单条内容

```yaml
path: /api/v1/contents/{id}
method: DELETE
module: M-009
desc: "删除单条内容及其关联的向量索引（对应 prd#§2 F-014 AC-066）"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  path_params:
    id: { type: string, required: true, desc: "内容 ID (UUID)" }
response:
  204: { desc: "删除成功，无返回体" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
  404: { schema: "ErrorResponse", desc: "内容不存在" }
```

### API-031: 批量删除内容

```yaml
path: /api/v1/contents/batch-delete
method: POST
module: M-009
desc: "批量删除内容及其关联的向量索引（对应 prd#§2 F-014 AC-066）"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
  body:
    ids: { type: "array[string]", required: true, desc: "待删除内容 ID 列表，最大 100 条" }
response:
  200:
    body:
      deleted_count: { type: integer, desc: "实际删除数量" }
      not_found_ids: { type: "array[string]", desc: "未找到的 ID 列表" }
  400: { schema: "ErrorResponse", desc: "参数校验失败（如 IDs 为空或超过 100 条）" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

### API-032: 存储统计查询

```yaml
path: /api/v1/storage/stats
method: GET
module: M-009
desc: "查询存储统计信息：文档总数、向量索引大小、数据库存储用量（对应 prd#§2 F-014 AC-067）"
request:
  headers:
    X-API-Key: { type: string, required: true, desc: "API 认证密钥" }
response:
  200:
    body:
      total_raw_contents: { type: integer, desc: "原始内容总数" }
      total_processed_contents: { type: integer, desc: "处理后内容总数" }
      total_vectors: { type: integer, desc: "向量索引条目数" }
      database_size_bytes: { type: integer, desc: "数据库总存储用量（字节）" }
      vector_index_size_bytes: { type: integer, desc: "向量索引存储用量（字节）" }
      oldest_content_at: { type: "datetime | null", desc: "最早内容时间" }
      newest_content_at: { type: "datetime | null", desc: "最新内容时间" }
  401: { schema: "ErrorResponse", desc: "认证失败" }
```

---

### 通用响应类型定义

#### ErrorResponse

```yaml
error:
  code: { type: string, desc: "错误码，格式 IS-{MOD}-{NNN}" }
  message: { type: string, desc: "用户可读错误信息" }
  detail: { type: "string | null", desc: "详细错误描述" }
  trace_id: { type: string, desc: "请求追踪 ID" }
```

#### Source

```yaml
id: { type: string, desc: "信源 ID (UUID)" }
name: { type: string, desc: "信源名称" }
type: { type: string, desc: "信源类型: rss | api | web" }
url: { type: string, desc: "信源 URL" }
tags: { type: "array[string]", desc: "学科标签" }
status: { type: string, desc: "状态: active | paused | error" }
schedule:
  interval: { type: integer, desc: "采集间隔（秒）" }
  adaptive: { type: boolean, desc: "是否自适应频率" }
  last_collected_at: { type: "datetime | null", desc: "上次采集时间" }
  next_collect_at: { type: "datetime | null", desc: "下次计划采集时间" }
proxy: { type: "string | null", desc: "HTTP 代理" }
rate_limit:
  qps: { type: "number | null", desc: "QPS 限制" }
  concurrency: { type: "integer | null", desc: "并发限制" }
metadata: { type: object, desc: "扩展元数据" }
created_at: { type: datetime, desc: "创建时间" }
updated_at: { type: datetime, desc: "更新时间" }
```

#### TaskBrief

```yaml
id: { type: string, desc: "任务 ID" }
type: { type: string, desc: "任务类型" }
status: { type: string, desc: "任务状态: pending | running | success | failed | paused | cancelled" }
created_at: { type: datetime, desc: "创建时间" }
```
