---
id: code-scan-deploy-ux-20260617-r1
doc_type: code-review
author: reviewer
status: draft
deps: [backlog-intellisource-v1, pre-deploy-walkthrough-v1]
---

# IntelliSource 分发/部署机制 新手友好度评估 (CODE-SCAN-deploy-ux-20260617-r1)

> 范围：仅评审「部署 / 订阅 / 推送 / 模板」四单元相关产物的**新手自助友好度**与机制健壮性；不扩散到无关模块。
> 视角：①新手用户（只读 README，目标走通"部署→订阅→第一条推送→自定义模板"全链路）；②DevOps/框架评审者（健壮性、可发现性、可调试性）。
> 方法：实走 README quickstart 与 PRE-DEPLOY-WALKTHROUGH 关键步骤 + 四单元源码 path:line 取证；结论分 `[已具备]` / `[缺口]` / `[风险]`。最高两项 `G-001` / `G-007` 已二次复核源码确认。
> 处置（用户 2026-06-17 决策）：立 backlog（`B-072`~`B-077`）+ 固化本报告；暂不改代码。各单元修复方向已折入对应 backlog 条目。

---

## 1. 结论摘要

**整体定性：本地部署"骨架友好、暗坑遍布"；远端部署"应用层成熟、主机层空白"。** 新手能凭 README 把栈跑起来，但很难自助走通"订阅→收到第一条推送→自定义模板"全链路，且多数失败是**静默**的。

核心依据：

1. **[新手][已具备]** 冷启动主路径 `uv sync → init → up → doctor` 设计良好：`init` 幂等、自动生成强口令（`src/intellisource/cli/commands/init.py:223-284`）、播种模板、给 Next steps；`doctor --check-api` 带 5 次重试自愈（`src/intellisource/cli/commands/doctor.py:143-194`）。冷启动隐含前置只有 Docker Desktop + uv 两个，README 首行已点名（`README.md:7`）。
2. **[新手][风险]** TTFV（到第一条推送）卡点密集：`match_rules` 零校验 + 未知键静默忽略（`src/intellisource/config/subscription_validator.py` 不校验 match_rules；`src/intellisource/distributor/matcher.py:36-42`），写错规则后订阅 active 却永不触发，无告警、无诊断命令。
3. **[DevOps][CRITICAL]** 失败推送完全无法审计追溯：`/push-records` 实际只含 `status=sent` 行（`src/intellisource/distributor/facade.py:234,364` + `src/intellisource/composition/builders.py:65-75` 不注入 push_repo）。
4. **[新手][缺口]** 自定义模板落地路径断裂：CLI `template` 子命令操作 DB 模板，与 README 主推的 `config/templates/` 文件覆盖完全脱节（`src/intellisource/cli/commands/template.py` 全程不碰 `config/templates/`），且可用 Jinja 变量零用户文档（仅存在于 `src/intellisource/distributor/templates/schemas.py:16-41`）。
5. **[DevOps][缺口]** 远端"主机就绪"层零覆盖：deploy-spec 对发布/回滚/监控/迁移覆盖充分且 approved，但 reverse proxy / TLS / 域名 / systemd / 防火墙 / 入站 webhook 公网可达性全无指引，全文命令一律 `localhost`。

可证伪判据小结：冷启动隐含前置 = 2（已点名）；TTFV 卡点数 ≥ 3（match_rules 静默 / 渠道软禁用半静默 / SMTP 默认错配）；配置可发现性 = render_mode/quiet_hours 可发现，模板变量 + match_rules 操作符不可发现；失败可调试性 = 弱。

---

## 2. 现状映射表（4 单元 × 现状 / 友好度 / 缺口）

| 单元 | 现状（关键证据） | 友好度 | 主要缺口 |
|------|------------------|--------|---------|
| ① 本地+远端部署 | `init` 幂等播种 + 强口令（`init.py:223-284,287-422`）；`stack.py` 跨平台封装 compose + GIT_SHA busting（`stack.py:65-83`）；`doctor --check-api`（`doctor.py:143-194`）；7 容器栈依赖编排健全（`docker/docker-compose.yml:87-95`）；deploy-spec prod/回滚/监控 approved | 本地高 / 远端中-低 | 无 Docker/daemon/.env 预检；远端主机就绪空白；无置备脚本；embedding 冷启 20min 无进度（`docker-compose.yml:181`） |
| ② 个性化订阅 | YAML SSOT + DB 双层，reload 全量同步（YAML 缺失→PAUSE，`storage/repositories/subscription.py:153-155`）；versions/rollback/diff 齐全有文档（`README.md:43-59`）；render_mode 降级提示（`cli/commands/subscription.py:80-105`） | 机制中 / 写规则低 | match_rules/frequency/quiet_hours/timezone 零校验且静默失败；无匹配诊断命令；match_rules 语义无用户文档 |
| ③ 推送通道 | 三渠道 from_env 缺凭据即报错带变量名；软禁用非完全静默（启动 warn + `/health.missing_config` + `/channels`）；facade 失败隔离 + `pushes_total` 指标 | 配置中 / 排障低 | 失败推送不落库（审计死列）；token 真实 errmsg 被吞成 network_error；SMTP 587+tls=true 默认错配；凭据获取步骤无文档；"配了却没收到"半静默 |
| ④ 模板设计 | 5 内置模板 + user>builtin 文件覆盖（`distributor/templates/render.py:29`）；render_mode 三档降级稳健可追溯（`distributor/templates/digest.py:130-147`）；DB 模板 CRUD + sandbox + 422 校验 | 发现中 / 自写极低 | CLI(DB) 与文件覆盖(config/templates) 两套机制脱节；可用变量零文档；文件名拼错静默回落 builtin；无 preview/validate；render_mode 选择无文档 |

---

## 3. 缺口清单（按 severity 排序）

### [G-001] CRITICAL — 失败推送从不落库
- **category**: error-handling ｜ **视角**: DevOps / 新手 ｜ **关联**: `B-072`
- **描述**: `facade.py:204,226` 失败路径仅 `_record_push_outcome`（指标）后 `continue`；DB 落库 `_record_push`（`facade.py:234`）只在成功路径调用、`status` 硬编码 `"sent"`（`:364`）；`builders.py:65-75` 构造渠道时不注入 `push_repo`，致 `distributor/base.py:144` 的失败落库分支永不触发。`PushRecord.error_message/retry_count/status=failed`（`storage/models.py:486-488`）成为死列。
- **对新手的影响**: "配了却没收到"时审计端点查不到失败记录，只能翻容器日志。
- **建议**: `build_distributor_facade` 给 from_env 注入 push_repo（单点改动）；失败路径补 `_record_push(status="failed", error_message=...)`，复用已存在的 `base.py:197-204` 逻辑。

### [G-002] HIGH — match_rules 零校验 + 静默不匹配
- **category**: error-handling ｜ **视角**: 新手 ｜ **关联**: `B-073`
- **描述**: validator 不校验 match_rules；`matcher.py:36-42` 用 `rules.get(...)`，键拼错被忽略；全空 match_rules → `_matches` 直接 `return False`（`matcher.py:42`），订阅 active 却永不推送。
- **对新手的影响**: 写错一个键，订阅"假活"，永远收不到第一条推送且无从查，直接打断 TTFV。
- **建议（决策 A）**: reload 时对"未知键 / 无任何有效匹配维度"WARN（不阻断）；可选 `intellisource subscriptions test-match <id>` dry-run。

### [G-003] HIGH — frequency/quiet_hours/timezone 静默错配
- **category**: error-handling ｜ **视角**: 新手 ｜ **关联**: `B-073`
- **描述**: `frequency` 为自由 str 无枚举（`config/subscription_models.py:19`），写 `daly` 不报错；`distributor/frequency.py:59` `interval=None → return True` 被当 realtime 狂推。`quiet_hours`/`timezone` 仅运行期暴露（`frequency.py:99-103` 无效时区静默回退 UTC）。
- **对新手的影响**: 频率/静默时段配错后行为与预期相反，加载期无报错。
- **建议**: model/validator 收敛 frequency 到已存在的 `FREQUENCY_OPTIONS`（`frequency.py:19-24`）；加载期校验 quiet_hours 的 `HH:MM` 与 timezone 有效性。

### [G-004] HIGH — 自定义模板可用变量零用户文档
- **category**: docs / usability ｜ **视角**: 新手 ｜ **关联**: `B-075`
- **描述**: 渲染唯一注入 `bundle`（`distributor/templates/render.py:39`），字段仅存在于 `schemas.py:16-41`；`config/templates/README.md`（9 行）只说"放同名文件"，不提任何字段。
- **对新手的影响**: 想写覆盖 j2 必须逆向读源码，是落地自定义模板的最大卡点。
- **建议（决策 A）**: `config/templates/README.md` 补 bundle 字段表 + 端到端覆盖示例（挑名→查变量→写 j2→reload→验证）。

### [G-005] HIGH — 模板两套机制脱节 + 拼错静默回落
- **category**: consistency / usability ｜ **视角**: 新手 ｜ **关联**: `B-075`
- **描述**: README 主推 `config/templates/*.j2` 文件覆盖（机制 A，`render.py:21,29`），而 CLI `template list/add/rm`（`cli/commands/template.py`）只操作 DB `templates` 表（机制 B），file override 永不出现在 list、无法 preview/validate；文件名拼错（kebab/snake 混淆）→ FileSystemLoader 静默回落 builtin，无告警。
- **对新手的影响**: 不知道该放文件还是敲命令；放了文件无法确认是否被识别。
- **建议（决策 A）**: 文档明确两套机制分工（文件覆盖为主）；CLI `template list` 增列扫描 `config/templates/` 的 file override + 加 `template validate`/`preview`。

### [G-006] HIGH — 远端"主机就绪"文档空白
- **category**: completeness / docs ｜ **视角**: DevOps ｜ **关联**: `B-074`
- **描述**: `docker/docker-compose.yml:75-76` 直接 `8000:8000` 暴露；deploy-spec 与 PRE-DEPLOY-WALKTHROUGH 全文 `localhost`，无 reverse proxy / TLS / 域名 / systemd / 防火墙 / 入站 webhook 公网可达性指引；仓库无置备脚本。
- **对新手的影响**: 无法据现有文档完成公网可访问的远端部署，回调类渠道在远端不可用。
- **建议（决策 B+C）**: 新增"远端部署主机就绪"文档（反代/TLS/防火墙/webhook 公网 URL）；提供置备脚本/远端 target；引入 prebuilt registry 镜像 + compose pull 模式（同解 G-013 回滚需重建 zhparser 依赖）。

### [G-007] MEDIUM — SMTP 587 + use_tls=true 默认错配
- **category**: error-handling ｜ **视角**: 新手 ｜ **关联**: `B-076`
- **描述**: `docker/.env.example:113-114` 默认 `IS_SMTP_PORT=587` + `IS_SMTP_USE_TLS=true` → aiosmtplib `use_tls=True`（隐式 TLS，对应 465）；587 标准走 STARTTLS。from_env 无端口↔TLS 一致性校验。
- **对新手的影响**: 按默认值配 Gmail/企业邮箱大概率握手失败，错误不直指端口/模式错配。
- **建议（决策 A）**: `.env.example` 默认改 587 + `use_tls=false`(STARTTLS) + 注释 465↔true / 587↔false；from_env 加端口-模式一致性 WARN。

### [G-008] MEDIUM — token 真实错误被吞为 network_error
- **category**: error-handling ｜ **视角**: DevOps ｜ **关联**: `B-076`
- **描述**: `_fetch_token` 抛带 errmsg 的异常（`distributor/channels/wechat.py:101` / `wework.py:182`），被 distribute 的 `except Exception` 统一替换为 `{"errmsg":"network_error"}`（`wechat.py:197-199` / `wework.py:138-140`）。
- **对新手的影响**: 无法区分"密钥错"与"网络抖动"。
- **建议**: 保留原始 errmsg 进 error 字段，区分 auth error 与 transport error。

### [G-009] MEDIUM — "配了却没收到"半静默
- **category**: usability ｜ **视角**: 新手 ｜ **关联**: `B-076`
- **描述**: 渠道软禁用后订阅匹配仍被 facade 计入 `skipped`（`facade.py:163-173`），distribute 整体仍返回 `{"status":"ok"}`（`facade.py:241-245`）。软禁用本身有 `/health.missing_config`+`/channels` 暴露但不主动推给用户。
- **对新手的影响**: 误以为推送成功，需主动查 health 才发现渠道被禁用。
- **建议**: distribute 返回体在 `skipped>0` 时附 disabled_channels 提示；doctor 默认提醒被软禁用的渠道。

### [G-010] MEDIUM — 冷启动无前置/缺文件预检
- **category**: error-handling ｜ **视角**: 新手 ｜ **关联**: `B-077`
- **描述**: `init`/`up` 均不检测 Docker daemon 是否运行、`.env` 是否存在（`stack.py:56-60` 只捕 FileNotFoundError=二进制缺失）；手动 copy `.env.example` 可绕过 init → 弱口令上线（占位非空，compose `:?` 不拦，`.env.example:18,27,36`）。
- **对新手的影响**: daemon 没开/没跑 init 时看到底层 compose 报错，不知先做什么。
- **建议**: `up` 前置检查 daemon 可达 + `.env` 存在，缺失时友好提示先启动 Docker / 先跑 init。

### [G-011] MEDIUM — doctor 误报与指引弱
- **category**: error-handling ｜ **视角**: DevOps ｜ **关联**: `B-076`
- **描述**: LLM key 检查只看非空（`doctor.py:100-104`），`.env.example:67-68` 的 `sk-...` 占位被判"已设"；DB/Redis/LLM "not set" 只报状态不给修复动作（`doctor.py:84,98,104`）；`env={**dotenv,**os.environ}`（`doctor.py:216`）使 shell 残留 `IS_*` 覆盖 `.env`。
- **对新手的影响**: doctor 通过但实际密钥无效/不一致，误导自检结论。
- **建议**: LLM key 增加占位值识别；"not set" 项附"跑 init 或填哪个变量"。

### [G-012] LOW — match_rules 语义无用户文档
- **category**: docs ｜ **视角**: 新手 ｜ **关联**: `B-077`
- **描述**: AND/OR、大小写、keywords `+`/`!`/`/regex/`、source_names 强约束仅在 `matcher.py` 源码与内部 dev-plan；`config/examples/subscriptions.example.yaml` 只演示 tags，未演示 keywords/min_score/discipline_tags，quiet_hours 未注释时区归属与跨午夜。
- **对新手的影响**: 不知道高级匹配能力存在。
- **建议**: example.yaml 补全各匹配维度示例 + README 加 match_rules 语义小节。

### [G-013] LOW — 杂项摩擦
- **category**: completeness ｜ **视角**: DevOps / 新手 ｜ **关联**: `B-074` / `B-077`
- **描述**: embedding 冷启动 `start_period:1200s`（`docker-compose.yml:181`）无进度提示；`config/templates/README.md:3` 漏列内置 `json_feed`；j2 覆盖度不全（weekly-roundup 仅 html、push-card 无 html）→ 无对应 fmt 时静默回落 default_format（`distributor/templates/base.py:42-44`）；prebuilt registry 镜像未实现，远端回滚强依赖目标主机重建 zhparser。
- **对新手的影响**: 各为小摩擦，单独不阻断。
- **建议**: `up` 输出 embedding 首次拉模型等待提示；补 README json_feed；补缺失 j2 或文档说明回落（registry 镜像归 `B-074`）。

---

## 4. 改进优先级（项目 P 语义对齐）

> 项目 P 语义：P0=阻塞上线；P1=阻塞质量(可观测/合规)；P2=架构/功能完整性；P3=优化/规约。
> 注：本评估"新手自助"维度的阻塞性已折入各条 severity；映射到项目优先级后，因本地起栈不被硬阻断，无新增 P0。

| Backlog | 优先级 | 覆盖 G-IDs | 主题 |
|---------|--------|-----------|------|
| `B-072` | P1 | G-001 | 失败推送审计落库（消除死列） |
| `B-073` | P1 | G-002, G-003 | 订阅静默失配兜底（reload WARN，决策 A） |
| `B-074` | P2 | G-006, G-013(registry) | 远端主机就绪 + 置备脚本/target + registry 镜像（决策 B+C） |
| `B-075` | P2 | G-004, G-005 | 模板可发现性 + 变量文档 + CLI validate/preview（决策 A） |
| `B-076` | P2 | G-007, G-008, G-009, G-011 | 推送渠道排障可观测性（SMTP 默认改 A） |
| `B-077` | P3 | G-010, G-012, G-013(杂项) | 冷启动预检 + match_rules 语义文档 + 杂项 |

落地顺序建议：先做纯文档项（`B-074` 文档面 / `B-075` 文档面 / `B-077` / `B-076` 注释与指引）——零代码风险、覆盖最大盲区；再做单点校验/落库（`B-072` / `B-073` WARN / `B-076` 代码面 / `B-077` 预检）——复用既有逻辑、单文件改动；CLI 增强（`B-073` dry-run、`B-075` list/validate）作为中等成本后续。

---

## 5. 已决策的开放问题（用户 2026-06-17）

| 决策点 | 选择 | 落地去向 |
|--------|------|---------|
| 远端部署目标形态 | B+C — 置备脚本/远端 target + registry 镜像 | `B-074` |
| 订阅静默不触发兜底 | A — reload 时 WARN（不阻断） | `B-073` |
| 模板自定义主推机制 | A — 文件覆盖为主，CLI 增列 + validate/preview | `B-075` |
| SMTP 默认值取向 | A — 默认 587 + use_tls=false(STARTTLS) + 注释 | `B-076` |

---

## 6. 已具备（正面，避免回归时误删）

- 冷启动主路径 `init` 幂等 + 强口令 + Next steps；`doctor --check-api` 重试自愈。
- 订阅双层 SSOT、reload 全量同步语义、diff 预览、versions/rollback、render_mode 降级提示，文档与实现一致。
- 渠道缺凭据即报错带变量名；软禁用不崩溃可枚举（registry + `/channels`）；facade 单渠道失败隔离 + `pushes_total{channel,status}` 指标；token 缓存原子写 + TTL 下限。
- 模板 user>builtin 文件覆盖实现正确；render_mode 三档降级稳健可追溯落库；DB 模板 CRUD + sandbox + 422 校验；`template list` DB 不可达仍返回 builtin 不硬失败。
- deploy-spec 应用层（dev/staging/prod 矩阵、灰度发布、回滚 SOP、密钥注入、监控 SLO + 告警 SOP、发布检查清单）覆盖充分且 approved。
