# config/templates/ — 用户自定义 digest 模板（覆盖层）

把同名模板文件放进本目录即可**覆盖** `src/intellisource/distributor/templates/builtin/` 里的内置 digest 模板。这是自定义排版的**主推机制**（文件覆盖优先）。

- **优先级**：渲染器先查本目录（用户覆盖），未命中再用内置（`render.py` 的 loader 顺序 `[config/templates, builtin]`）。
- **生效**：`intellisource subscriptions reload`（或重启进程）。
- 默认为空——不放任何文件即全部使用内置模板。

> ⚠️ **两套机制别混**：本目录的**文件覆盖**与 CLI `intellisource template list/add/rm`（操作 DB `templates` 表）是**两条独立通路**。文件覆盖**不会**出现在 `template list` 里，DB 模板也不在本目录。新手默认用文件覆盖（本目录）即可。

---

## 文件命名

模板文件名为 `{name}.{fmt}.j2`，必须与要覆盖的内置模板**完全同名**：

- `{name}` 用 **kebab-case**（如 `daily-brief`，**不是** `daily_brief`）。内置 `*.j2` 全用 kebab；Python 模块名 `daily_brief.py` 的下划线是另一回事，别照搬到文件名。
- `{fmt}` ∈ `html` / `markdown` / `text` / `json`。
- ⚠️ **拼错文件名会静默回落内置模板，无任何告警**。放好覆盖文件后请验证输出确实变了（见下方端到端示例）。

### 内置模板 × 格式覆盖矩阵

| 模板 `{name}` | 提供的 `{fmt}` | 说明 |
|---------------|----------------|------|
| `daily-brief` | `html` / `markdown` / `text` | 日报 |
| `weekly-roundup` | `html` | 周报（仅 html） |
| `push-card` | `markdown` / `text` | 即时推送卡片（无 html） |
| `topic-deepdive` | `html` / `markdown` | 主题深读 |
| `json_feed` | `json` | 机器可读 feed；由 Python 直接返回 `bundle` 字典，**非 j2 渲染**，无需也无法用文件覆盖 |

> **缺失格式静默回落**：请求的 `{fmt}` 不在某模板的提供格式内时，渲染回落到该模板的 `default_format`（`templates/base.py`），不报错。例如向 `weekly-roundup` 要 `text` 会回落到 `html`。要新增一个内置未提供的格式，放一个对应的 `{name}.{fmt}.j2` 覆盖文件即可。

---

## 模板里能用的变量

渲染时**只注入一个变量 `bundle`**（类型 `DigestBundle`，定义见 `src/intellisource/distributor/templates/schemas.py`）。`*.html.j2` 自动 HTML 转义，其它格式不转义；环境是沙箱化的，模板无法访问 Python 内部。

### `bundle`（DigestBundle）

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | `str` | digest 标题 |
| `period_label` | `str \| None` | 周期标签（如 "2026-06-17"、"第 24 周"） |
| `intro` | `str \| None` | 开场白（`llm-assisted`/`llm-freeform` 模式可由 LLM 补写） |
| `top_picks` | `list[DigestItem]` | 头条精选 |
| `sections` | `list[DigestSection]` | 分栏内容 |
| `timeline` | `list[dict]` | 时间线条目，每项为 `{date, event}` 纯字典 |
| `outro` | `str \| None` | 结语 |
| `generated_at` | `datetime \| None` | 生成时间 |

### `DigestItem`（`top_picks[*]` 与 `section.items[*]`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | `str` | 条目标题 |
| `summary` | `str` | 摘要 |
| `body_text` | `str \| None` | 正文 |
| `key_points` | `list[str]` | 要点列表 |
| `why_it_matters` | `str \| None` | "为什么重要" |
| `tags` | `list[str]` | 标签 |
| `source_name` | `str \| None` | 信源名 |
| `source_url` | `str \| None` | 原文链接 |
| `published_at` | `datetime \| None` | 发布时间 |

### `DigestSection`（`sections[*]`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `heading` | `str` | 栏目标题 |
| `items` | `list[DigestItem]` | 栏目下条目 |

---

## 端到端示例：覆盖日报 markdown 排版

```jinja
{# config/templates/daily-brief.markdown.j2 #}
# {{ bundle.title }}
{% if bundle.period_label %}_{{ bundle.period_label }}_{% endif %}

{% if bundle.intro %}{{ bundle.intro }}{% endif %}

{% for item in bundle.top_picks %}
## ⭐ {{ item.title }}
{{ item.summary }}
{% if item.why_it_matters %}> 为什么重要：{{ item.why_it_matters }}{% endif %}
{% if item.source_url %}[原文]({{ item.source_url }}){% endif %}
{% endfor %}

{% for section in bundle.sections %}
## {{ section.heading }}
{% for item in section.items %}
- **{{ item.title }}** — {{ item.summary }}
{% endfor %}
{% endfor %}
```

落地步骤：

1. **挑名**：选要覆盖的内置模板 + 格式（如 `daily-brief` 的 `markdown`），文件名即 `daily-brief.markdown.j2`。
2. **查变量**：照上面的 `bundle` 字段表写 `{{ bundle.* }}`。
3. **写 j2**：放进本目录 `config/templates/`。
4. **生效**：`intellisource subscriptions reload`。
5. **验证**：触发一次该订阅的 digest，确认输出用了你的排版。**没生效大概率是文件名拼错**（kebab-case？格式后缀对不对？）——拼错会静默回落内置模板。

---

完整配置地图见 [`../README.md`](../README.md)；订阅匹配规则见仓库根 [`README.md` §订阅匹配规则](../../README.md)。
