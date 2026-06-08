# 配置地图（改任何东西前先看这张表）

IntelliSource 里"配置型"的东西分**三类**，物理上分别住在不同位置——别指望它们都在一个文件夹。先认清这三类，后面就不会找错地方。

| 类别 | 是什么 | 在哪 | 谁来改 |
|------|--------|------|--------|
| **A. 用户运行时配置** | 信源 / 订阅 / LLM 路由 / 密钥 | `config/`、`docker/.env` | **你（部署者）** |
| **B. 随代码发布的内置资源** | LLM 提示词 / 主题包 / 内置 digest 模板 | `src/intellisource/**/` | 开发者 |
| **C. 配置加载代码** | Pydantic 模型 / 校验器 / loader | `src/intellisource/config/` | 开发者 |

> ⚠️ `config/`（A 类，你改）和 `src/intellisource/config/`（C 类，纯 Python 代码）**同名但完全不同**。你日常只需要动 `config/` 和 `docker/.env`。

---

## A. 我（用户）要改的运行时配置

都在本目录 `config/` 和 `docker/.env`。改完后大多需要 `reload` 或重启进程生效。

| 我想改… | 改这个 | 改完怎么生效 |
|---------|--------|--------------|
| 内容从哪来（RSS/API/网页） | `config/sources/*.yaml` | `intellisource source diff` 预览 → `reload` |
| 推给谁 / 走哪个渠道 | `config/subscriptions/*.yaml` | `intellisource subscriptions reload` |
| 用哪个大模型、各任务的路由 | `config/llm_models.yaml` | 重启 api / worker 进程 |
| 密钥 / 数据库 / Redis / 渠道凭据 | `docker/.env` | 重启栈 |
| 采集→处理→分发的编排 | `config/pipelines/*.yaml` | `reload` |
| digest 排版样式（覆盖内置模板） | `config/templates/` | `reload` |

### 本目录结构

```
config/
├── README.md          # 你正在看的这张地图
├── examples/          # 所有 *.example.yaml 模板集中处（只读样例，照着抄）
├── schema/            # JSON Schema（llm_models / sources / subscriptions / pipeline；编辑器据 modeline 补全/校验）
├── llm_models.yaml    # [gitignore] 实际生效的 LLM 路由；intellisource init 从 examples 播种
├── sources/           # [*.yaml gitignore] 你的信源定义（复制 examples/sources.example.yaml 进来）
├── subscriptions/     # [*.yaml gitignore] 你的订阅定义
├── pipelines/         # 管线定义（随仓库提交，可直接改）
└── templates/         # 用户自定义 digest 模板，覆盖 B 类内置模板
```

> 四类配置（`llm_models` / `sources` / `subscriptions` / `pipelines`）的样例与文件顶部都带 `# yaml-language-server: $schema=…` modeline，支持的编辑器（VS Code + YAML 插件等）据此即时补全字段、校验拼写与取值范围（如 source 的 `type` 只能 rss/api/web、profile 的 `temperature` 必须 0~2）。`intellisource doctor` 也会在加载时做一次完整校验。
>
> `config/schema/*.json` 全部由 `uv run python scripts/gen_config_schemas.py` 从 `src/intellisource/config/` 的 Pydantic 模型 / 常量生成；改了模型就重跑该脚本（`tests/unit/config/test_config_schemas.py` 会在漂移时报错）。

### 命名约定（一句话记住）

- **集合型**（信源 / 订阅，可有多个文件）→ 一个**目录**：`config/sources/`、`config/subscriptions/`，实际文件 gitignore，只追踪样例。
- **单例型**（LLM 路由，只有一份）→ 一个**扁平文件**：`config/llm_models.yaml`。
- **所有样例模板**统一放 `config/examples/`，文件名 `*.example.yaml`，照着复制即可。
- **管线**（`config/pipelines/`）随仓库提交、可直接编辑，没有 `.example` 中间层。

### 配置生效模型（SSOT + 运行时 DB 双层）

YAML 是事实来源（SSOT）：编辑 `config/**/*.yaml` 后 `reload` 生效并记录版本快照。API/CLI 的热编辑是临时态，下次 `reload` 会被 YAML 覆盖。回滚 / 版本 / diff 命令见仓库根 `README.md §配置管理`。

---

## B. 开发者维护的内置资源（普通用户别动）

这些是**随代码发布**的资源，用 `Path(__file__).parent` 相对包路径加载、打进 Docker 镜像，所以**必须**待在 `src/` 里、不能搬进 `config/`。

| 这是… | 在哪 | 用户怎么覆盖 |
|-------|------|--------------|
| LLM 任务提示词（`*.prompt.md`，含防注入片段 `_fragments/`；目录索引见 [`llm/prompts/README.md`](../src/intellisource/llm/prompts/README.md)） | `src/intellisource/llm/prompts/` | 改源码 / style 变体 |
| 内置主题包（AI / 生物医学 / CS …） | `src/intellisource/topic/builtin/` | — |
| 内置 digest 模板（`*.j2`） | `src/intellisource/distributor/templates/builtin/` | 在 `config/templates/` 放同名覆盖 |

> 注：`config/pipelines/*.yaml` 里的 `system_prompt` 是**单条管线 agent 的专属人设**（属 A 类，你可改）；和 B 类 `llm/prompts/` 里**跨管线复用的任务提示词**是两回事，别混。

---

## C. 配置加载代码

`src/intellisource/config/` 是 Pydantic 模型 + 校验器 + loader（`loader.py` / `validator.py` / `*_models.py` / `llm_schema.py`），**是代码不是配置**。环境变量的唯一事实来源是 `src/intellisource/core/settings.py` 的 `Settings` 类（全部 `IS_*` 前缀）。
