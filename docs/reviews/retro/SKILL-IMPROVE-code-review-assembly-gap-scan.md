---
id: "skill-improve-code-review-assembly-gap-scan"
doc_type: skill-improve
author: reflector
status: draft
date: 2026-05-23
deps: ["retro-intellisource-v1-sprint-9"]
target_id: code-review
target_kind: skill
source_exp: EXP-005
---

# SKILL-IMPROVE: code-review — 装配缺口扫描强制化

## EXP-005: 装配缺口模式跨 sprint-8r→sprint-9 累计 5 次复发

**evidence**:
- CODE-REVIEW-T-088-r1.md R-007: lifespan 未注入 collectors
- CODE-REVIEW-T-092-r1.md N-001: build_celery_tasks 漏传 content_repository
- CODE-REVIEW-T-089-r1.md: tool_deps 未注入 + ToolDeps 未构建
- CODE-REVIEW-T-098-r1.md R-001: webhook_token + cs_messenger 4 状态项未装配
- CODE-REVIEW-T-100-r1.md R-001: Worker composition 未透传 celery_app

5 个案例共性：单元 / 集成测试通过仅因 fixture 直接 set 状态项，生产代码路径零装配；每次都靠 reviewer 主观 HIGH 抓出，测试套件无能力拦截回归。

---

## 改进 1: code-review Layer 1 增 `assembly-gap-scan` 检查器

### target_file
`.cataforge/skills/code-review/scripts/check_assembly_gap.py`（新建）+ `cataforge.skill.builtins.code_review.checker` 注册项

### target_section
§Step 1 — Layer 1 Lint脚本自动检查

### current_text
```
**调用约定（单一入口）**: Layer 1 一律通过 `cataforge skill run <skill-id> -- <args>` 触发，由框架解析 SKILL.md 元数据并派发到内置脚本或项目覆写脚本。

支持语言: JavaScript/TypeScript(ESLint+Prettier), Python(Ruff), C#(dotnet format), Go(golangci-lint), Rust(clippy)
工具不存在时自动跳过并WARN，不阻断检查流程。
```

### proposed_text
```
**调用约定（单一入口）**: Layer 1 一律通过 `cataforge skill run <skill-id> -- <args>` 触发，由框架解析 SKILL.md 元数据并派发到内置脚本或项目覆写脚本。

支持语言: JavaScript/TypeScript(ESLint+Prettier), Python(Ruff), C#(dotnet format), Go(golangci-lint), Rust(clippy)
工具不存在时自动跳过并WARN，不阻断检查流程。

**强制 assembly-gap-scan 检查器**（不可短路，所有 task_kind 强制运行）:

`check_assembly_gap.py` AST 扫描 src/ 全树：
1. 收集所有 `getattr(<obj>, "<attr>", <default>)` 读取点（典型：`getattr(request.app.state, "wechat_cs_messenger", None)`）
2. 收集所有依赖注入读取点（典型：`self._celery_app` 在 `__init__(..., celery_app=None)` 后的字段读取）
3. 全 src/ 搜对应的"装配赋值"位置：
   - `app.state.<attr> = ...` 在 composition.py / main.py
   - 构造器调用 `<Class>(<attr>=...)` 在 composition.py
4. 凡读取点存在但全 src/ 无对应装配赋值的 `<attr>` 标记为 `ASSEMBLY-GAP`
5. exit code 2 触发 code-review Layer 1 FAIL，强制进入修复

例外白名单（`.cataforge/skills/code-review/assembly-gap-allowlist.yaml`）：
- 显式标记为"运行时可空"的 attr（如 `app.state.config_watcher_task` — lifespan-only）
- 测试 fixture 内的 `app.state.<attr> = ...` 不计为装配（mock 路径）

### rationale
sprint-9 4/4 reviewer 截断使 Layer 2 manual review 不可靠；EXP-005 5 次复发证明 reviewer 主观经验抓 HIGH 不是稳态防御。机器扫描装配对称性是唯一可重复的拦截手段。reverse-test：故意 revert composition 装配语句，CI 必 fail。
```

---

## 改进 2: code-review Layer 2 增 "lifespan symmetry" 强制审查

### target_file
`.cataforge/skills/code-review/SKILL.md`

### target_section
§Step 2 Layer 2 AI语义审查 — `structure` 维度

### current_text
```
- 代码结构(structure): 模块组织、职责划分是否合理
```

### proposed_text
```
- 代码结构(structure): 模块组织、职责划分是否合理
  - **lifespan symmetry 子项**（强制）: 凡任务 deliverables 含 `composition.py` / `main.py` / `scheduler/boot.py` 改动，必须对照 `build_api_composition` vs `build_worker_composition` 装配对称性。任何在 API 路径装配但 Worker 路径漏装（或反之）的状态项标记为 HIGH `structure`，root_cause=self-caused。
  - 反证测试要求：装配缺口修复后必须新增反证测试，验证两路径都装配同名 state（参考 T-098 r2 `test_composition_wires_webhook_state.py` 与 T-100 r2 `test_worker_composition_facade_has_celery_app`）。
```

### rationale
T-098 R-001 (4 状态项 API 装配 / Worker 不需要) + T-100 R-001 (celery_app API 装配 / Worker 漏装) 两个 sprint-9 案例都是双路径不对称的子模式。明确该子项让 reviewer 有可操作 checklist 而非主观判断。

---

## 改进 3: tech-lead 任务卡 template 强制 `wiring_checklist` 字段

### target_file
`.cataforge/skills/task-decomp/templates/task-card.yaml`（或 dev-plan 模板）+ `.cataforge/agents/tech-lead/AGENT.md` §Output Contract

### target_section
§Task card fields

### current_text
```
- deliverables: [{file_path}, ...]
- affected_files: [...]
- tdd_acceptance: [AC-1, AC-2, ...]
- context_load: [doc_id#§N, ...]
- risk: ...
- mitigation: ...
```

### proposed_text
```
- deliverables: [{file_path}, ...]
- affected_files: [...]
- tdd_acceptance: [AC-1, AC-2, ...]
- context_load: [doc_id#§N, ...]
- risk: ...
- mitigation: ...
- wiring_checklist:                  # 强制字段，凡 deliverables 含 src/ 新增 `app.state.X` / 依赖注入字段时必填
    - state_attr: app.state.wechat_webhook_token
      source: composition._install_webhook_state()
      reader: api/routers/webhooks.py
      lifespan_test: tests/integration/test_composition_wires_webhook_state.py
    - ... 每个新增装配点一条
```

### rationale
EXP-005 5 次复发中 4 次的根因都是 implementer 实施时遗漏装配语句，tech-lead 任务卡只列 deliverables（源文件级别）不强制声明 wiring。`wiring_checklist` 把装配点提升为任务卡一等公民，让 implementer 必须 cross-check，让 reviewer 在 Layer 2 有明确清单可对照。

5 个 sprint-9 / sprint-8r 历史案例都可以反向验证：如果当时任务卡有 `wiring_checklist` 字段，每个案例都会在 tech-lead 拆任务时就显式列出装配点，implementer 漏装的可能性会降至零。
