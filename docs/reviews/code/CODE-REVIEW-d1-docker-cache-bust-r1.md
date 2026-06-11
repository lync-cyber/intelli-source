---
id: "code-review-d1-docker-cache-bust-r1"
doc_type: code-review
author: reviewer
status: approved
deps: ["d1-docker-cache-bust"]
---

# CODE-REVIEW: d1-docker-cache-bust r1

**Layer 1**: PASS (exit 0, ruff check + format clean)
**Layer 2**: AI 语义审查完整执行

**Verdict**: approved_with_notes

---

## 审查范围

分支 `fix/d1-docker-cache-bust`（对比基线 main HEAD 9c1553c）：

- `src/intellisource/cli/commands/stack.py`
- `tests/unit/cli/test_stack.py`（新增）
- `tests/unit/cli/test_main.py`（存量断言更新）
- `docker/Dockerfile`
- `docker/docker-compose.yml`
- `Makefile`
- `docs/deploy-spec/deploy-spec-intellisource-v1.md`
- `docs/deploy/PRE-DEPLOY-WALKTHROUGH.md`

---

## 重点核查结论

### 1. Dockerfile cache-bust 机制正确性

`ARG GIT_SHA=unknown` + `LABEL org.opencontainers.image.revision=$GIT_SHA` 放在 `COPY src/` 之前，位置正确。

技术路径：`LABEL` 指令将 ARG 值写入层内容 → GIT_SHA 变化时 LABEL 层 cache key 变化 → cache miss → 后续 COPY src/、COPY config/、COPY alembic/ 全部失效重跑。

上方依赖层（`COPY --from=builder /app/.venv`、`COPY pyproject.toml`）不受影响，保持缓存。机制静态正确。

### 2. compose build.args 接线

`migrate`、`api`、`worker`、`beat` 四个应用服务全部加了 `args: GIT_SHA: ${GIT_SHA:-unknown}`。`db`、`redis`、`embedding`、`mailhog`、`prometheus` 不使用该 Dockerfile，无需添加。覆盖完整，无遗漏。

### 3. stack.py 逻辑

- `_git_sha()` 捕获 `FileNotFoundError`（git 不在 PATH），正常兜底返回 `"unknown"`。
- `rebuild` 分支（`build --no-cache` → `up -d --wait`）与正常分支（`up -d --wait --build`）均透传相同 `env`，GIT_SHA 注入一致。
- `down`/`migrate`/`logs`/`ps` 仍调用 `_run_compose` 且 `env=None`，`subprocess.run(..., env=None)` 语义为继承父进程环境，与改前行为等价，无回归。

### 4. 测试质量

`test_stack.py` 新增 9 个用例，覆盖 `_git_sha` 三路（成功 / 非零返回码 / FileNotFoundError）、normal up 三项（argv 含 up/--build/-d/--wait / env 含 GIT_SHA / shell=False）、rebuild 三项（build→up 顺序 / 两次调用都带 GIT_SHA / -r 短标志）。

断言绑定真实可观测属性（argv 内容、kwargs 键值、call_count、call_args_list 顺序），无弱断言，无假绿。mock 忠实使用 `CompletedProcess` 形状。

`test_main.py` 的存量测试 `test_up_runs_compose_up_detached` 将 `argv[-3:] == ["up", "-d", "--wait"]` 改为成员检查（`assert "up" in argv` 等）。改法合理——因现在 `--build` 也加入了 argv 且调用顺序含 git 内部调用，精确位置断言脆弱；成员断言保持语义等价且更稳健。

---

## 问题列表

### [R-001] MEDIUM: make rebuild 行为与 intellisource up --rebuild 不等价，文档暗示等价

- **category**: consistency
- **root_cause**: self-caused
- **描述**: `Makefile` 的 `rebuild` 目标仅执行 `$(COMPOSE) build --no-cache`，不执行 `up`。而 `intellisource up --rebuild` 先 `build --no-cache`、再 `up -d --wait`。`docs/deploy-spec/deploy-spec-intellisource-v1.md` §1.2 注意栏将两者并列写为 "dirty-tree 迭代（sha 未变但 src 已改）使用 `intellisource up --rebuild` / `make rebuild`"，暗示等价。用户使用 `make rebuild` 后容器不会自动起栈，需额外执行 `make up`，与文档描述不符。
- **建议**: 将 `make rebuild` 目标改为 `build --no-cache && $(COMPOSE) up -d --build`；或在文档中明确说明 `make rebuild` 只重建镜像，需后跟 `make up`，与 `intellisource up --rebuild`（一步完成重建+起栈）不同。

---

### [R-002] LOW: PRE-DEPLOY-WALKTHROUGH §0.2 截面内跨引用因新增节而漂移

- **category**: consistency
- **root_cause**: self-caused
- **描述**: 新增 §0.2"起栈方式说明"后，原 §0.2"环境变量"升为 §0.3，原 §0.3~0.5 依次升号。`PRE-DEPLOY-WALKTHROUGH.md` 第 183 行（历史签字注记）中 `§0.2 矛盾` 原意指"环境变量"节，现已指向新的"起栈方式说明"节，语义错位。
- **建议**: 将第 183 行的 `§0.2` 更新为 `§0.3`，或将引用改为节标题锚点以避免未来漂移。

---

### [R-003] LOW: _git_sha() 仅捕获 FileNotFoundError，OSError 子类（如 PermissionError）未兜底

- **category**: error-handling
- **root_cause**: self-caused
- **描述**: `_git_sha()` 仅捕获 `FileNotFoundError`（git 不在 PATH 的情况）。`subprocess.run` 在部分系统环境下可能抛出 `PermissionError`（执行位未设、SELinux 拒绝等）或其他 `OSError` 子类，这些异常会从 `_git_sha()` 传播到 `up()`，导致 CLI 崩溃而非优雅降级到 `"unknown"`。
- **建议**: 将 `except FileNotFoundError` 扩展为 `except OSError`，覆盖 `PermissionError` 等 `OSError` 子类；或在 `except` 块中同时处理 `OSError`。测试也相应补充 `PermissionError` 用例。

---

### [R-004] LOW: deploy-spec §1.2 注意栏对 cache-bust 机制的描述偏向实现角度，ARG 作用表述不精确

- **category**: convention
- **root_cause**: self-caused
- **描述**: 注意栏写 "`--build-arg GIT_SHA` 使 `COPY src/` 层在 sha 变化时强制失效"。技术上，失效的直接触发者是 `LABEL org.opencontainers.image.revision=$GIT_SHA` 层（消费了 ARG 值），而非 ARG 本身。ARG 单独不产生层，必须被后续指令引用才参与 cache key 计算。描述虽不影响用户操作，但对需要排查 BuildKit 缓存问题的 devops 有误导风险。
- **建议**: 改为"`--build-arg GIT_SHA` 通过 LABEL 指令将 sha 写入镜像层，在 sha 变化时使该层及后续 `COPY src/` 失效"，或类似措辞。

---

## 三态判定

无 CRITICAL，无 HIGH；存在 MEDIUM 1 项（R-001）、LOW 3 项（R-002、R-003、R-004）。

**verdict: approved_with_notes**

---

## 附：各审查维度摘要

| 维度 | 结论 |
|------|------|
| Dockerfile cache-bust 机制正确性 | 正确。ARG+LABEL 位置合理，依赖层缓存保持，COPY src/ 层失效路径正确。 |
| compose build.args 接线完整性 | 完整。四个应用服务全部覆盖，非应用服务无需覆盖。 |
| stack.py 逻辑（_git_sha / up / _run_compose） | 正确。失败兜底完备（FileNotFoundError），env 注入一致，非 up 命令无回归。 |
| 测试质量（test_stack.py + test_main.py 更新） | 合格。断言有效，mock 形状忠实，rebuild 顺序断言真实覆盖，三路失败路径全测。 |
| 回归面（_run_compose 签名变更） | 无回归。env=None 语义等价于不传 env；down/migrate/logs/ps 调用方不受影响。 |
| COMMON-RULES 规约合规（变更叙事/PR引用残留） | 新增代码/配置/新增文档节均无违规。Dockerfile 注释符合"非显然 WHY"场景。 |

---

## Inline-Fix 闭环记录

verdict `approved_with_notes`，R-001~R-004 由 orchestrator 主线程逐条 inline 修复（均为表述/健壮性微调，非设计变更），修复后 ruff check + mypy --strict + 全量 unit（含 9 个 test_stack 用例）复跑绿。

| 编号 | severity | 修复内容 | closed-by |
|------|----------|----------|-----------|
| R-001 | MEDIUM | deploy-spec §1.2 明确 `make rebuild` 仅 `--no-cache` 重建镜像（需随后 `make up`），与 `intellisource up --rebuild`（重建后自动起栈）区分 | orchestrator |
| R-002 | LOW | PRE-DEPLOY-WALKTHROUGH 历史签字注记 `§0.2` → `§0.3`（修正插节后的引用漂移，签字语义不变） | orchestrator |
| R-003 | LOW | `stack.py:_git_sha()` `except FileNotFoundError` → `except OSError`（兼顾 PermissionError 等 OSError 子类，优雅降级 "unknown"） | orchestrator |
| R-004 | LOW | deploy-spec §1.2 措辞订正：缓存失效触发者是消费 `ARG GIT_SHA` 的 `LABEL` 层，非 ARG 本身 | orchestrator |
