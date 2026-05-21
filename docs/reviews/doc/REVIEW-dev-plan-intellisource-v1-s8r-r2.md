---
id: "review-dev-plan-intellisource-v1-s8r-r2"
doc_type: review
author: reviewer
status: approved
deps: ["dev-plan-intellisource-v1-s8r"]
---

# REVIEW: dev-plan-intellisource-v1-s8r — r2

**被审文档**: `docs/dev-plan/dev-plan-intellisource-v1-s8r.md`（716 行，12 张任务卡 T-083~T-094）
**审查层次**: 增量验证（r1 修订对照 + 回归检查）
**审查日期**: 2026-05-21

---

## 1. r1 → r2 修订对照表

| r1 编号 | 修订点 | r2 verdict | 证据 |
|---------|--------|-----------|------|
| R-001 HIGH | T-088 `tdd_mode: light` → `standard` | **已修复** | 行 339：`tdd_mode: standard（预估 LOC ~140；跨 M-005/M-011 两个 arch 模块，触发跨模块升档规则）`；`tdd_refactor: skip`（接驳已有组件，无新设计模式，合理） |
| R-002 HIGH | T-093 AC-5 `re.search(timeout=)` → `regex.search(timeout=)` | **已修复** | 行 597 AC-5 正确使用 `regex.search(pattern, text, timeout=1.0)` 并捕获 `regex.TimeoutError`；行 607 deliverables 中 `pyproject.toml` 已追加 `regex` 依赖；行 610 测试文件 `test_redos_protection.py` 明确标注"调用 `regex.search` 路径" |
| R-006 MEDIUM-security | T-091 AC-7 yaml.safe_load 约束 | **已修复** | 行 503 新增 AC-7，覆盖三个禁用变体（`yaml.load()` 无 Loader、`yaml.full_load()`、`yaml.unsafe_load()`），提供 grep 验收命令 `grep -nE "yaml\.(load\|full_load\|unsafe_load)\(" src/intellisource/config/` |
| R-007 MEDIUM-security | T-090 PII 脱敏 + pii.py + test_pii_masking.py | **已修复** | AC-7（行 448）明确 subscription_id 仅存关联键；若存渠道级标识须 SHA-256 哈希；AC-8（行 449）定义 error_message PII 脱敏 helper 位于 `distributor/pii.py`，覆盖邮箱 `u***@domain` 和手机号前3后4格式；deliverables 包含 `pii.py` 和 `test_pii_masking.py` |
| R-008 MEDIUM-security | T-086 prompt injection 边界声明 | **已修复（方向①）** | risk 段行 270 明确三项：messages 由 AgentRunner/PromptBuilder 内部构造；注入防护责任归属 PromptBuilder 上游；若未来有调用方将用户输入直接拼入 messages 时需在该调用方层做长度上限和注入模式过滤，并指明不在 LLMGateway 层处理 |
| R-010 LOW | T-092 risk 段 "supersedes T-075" 对比叙事 | **已修复** | 全文 grep `supersedes` 零命中；T-092 risk 段行 570 改为独立性陈述：`本任务独立完整实现 Celery worker 初始化逻辑，无需依赖外部 P2 任务` |

---

## 2. 新发现问题

### [R-013] LOW: T-093 `pyproject.toml` 出现在 deliverables 但未列入 affected_files

- **category**: consistency
- **root_cause**: self-caused
- **描述**: T-093 deliverables（行 607）中明确列出 `pyproject.toml — 在 [project.dependencies] 中追加 regex`，但同一任务卡的 `affected_files`（行 612~622）未包含 `pyproject.toml`。两个字段应保持一致：deliverables 声明了交付物，affected_files 应列出所有会被写入的文件路径，供 sprint-review Layer 1 `deliverables_exist` 检查器和 `unplanned_files` 检查器使用。
- **建议**: 在 T-093 `affected_files` 列表末尾追加 `pyproject.toml`。

---

### [R-014] LOW: T-090 `security_sensitive` 字段未随 PII 修订升为 `true`

- **category**: consistency
- **root_cause**: self-caused
- **描述**: r1 R-007 的修订在 T-090 中新增了 AC-7（接收方标识 SHA-256 哈希）和 AC-8（error_message PII 脱敏），新增了 `pii.py` 交付物。这些修订使 T-090 实质上成为一个安全敏感任务（处理 PII 字段的存储和脱敏），但任务卡的 `security_sensitive` 字段仍为 `false`。`security_sensitive: true` 会影响 tdd-engine 的审查档位：tdd-engine 在 code-review Layer 2 短路豁免中，security_sensitive=true 的任务不可被短路跳过（见 COMMON-RULES §CODE_REVIEW_L2_SKIP_LIGHT_MAX_AC）。
- **建议**: 将 T-090 的 `security_sensitive` 改为 `true`，与修订内容的实质安全影响保持一致。

---

## 3. 范围外 r1 项当前状态备注

以下 6 项按 orchestrator + 用户约定推迟至 sprint 执行阶段处理，r2 不计入 verdict，仅确认其在文档中仍原样存在（未被意外修复或意外破坏）：

| r1 编号 | 描述 | 当前状态 |
|---------|------|---------|
| R-003 MEDIUM | 依赖图缺少 T-083 → T-087 直接边 | **注意**: 此问题在 r2 审查时已发现 T-083 → T-087 边存在于行 44，与 r1 描述不符；r1 报告时该边不存在，r2 时已存在。推测 tech-lead 在修订过程中顺手补充了此边（未在修订清单中申报）。该边补充是正向修复，无负面影响，此处备注以供知悉。 |
| R-004 MEDIUM | T-093 AC-2 quiet_hours 边界语义模糊 | 仍存在，原文未变（行 594 括号内"刚好在边界"歧义未消除） |
| R-005 MEDIUM | B-12 双卡拆分边界未明确说明 | 仍存在 |
| R-009 MEDIUM | T-094 AC-6 基线 PASS 数未文档化 | 仍存在 |
| R-011 LOW | T-083 AC-4 bind=True 签名变化未说明 | 仍存在 |
| R-012 LOW | `expected_tool_budget` 仅 T-083 有，其余 11 卡缺失 | 仍存在 |

---

## 4. r2 verdict 严重等级统计

| 严重等级 | r1 数量 | r2 新发现 | r2 合计（新发现） |
|---------|---------|---------|----------------|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 2（已全部修复） | 0 | 0 |
| MEDIUM | 7（5 已修复，2 推迟） | 0 | 0 |
| LOW | 3（1 已修复，2 推迟） | 2（R-013、R-014） | 2 |

**r2 新问题**: 0 CRITICAL / 0 HIGH / 0 MEDIUM / 2 LOW

**verdict**: **approved_with_notes**

5 项约定修订全部到位（2 HIGH + 3 MEDIUM-security + 1 LOW），未引入新 CRITICAL 或 HIGH 问题。新发现 2 个 LOW 问题（R-013 affected_files 缺 pyproject.toml；R-014 security_sensitive 字段未随 PII 修订同步），不阻塞执行。

---

## 5. 结论

**可进入 tdd-engine 编排执行**。

建议在 T-093 和 T-090 执行前由 tech-lead 顺手修正 R-013 和 R-014（均为单字段修改，成本极低）。若不修正：

- R-013 不影响功能正确性，但 sprint-review Layer 1 的 `deliverables_exist` 检查器可能不会验证 `pyproject.toml` 是否实际更新，gold-plating 检查也会将 `pyproject.toml` 改动视为计划外变更；
- R-014 不影响功能正确性，但若 code-review 使用 Adaptive Review 降级（`--layer1-only`），T-090 的 PII 相关代码将跳过 Layer 2 安全维度审查，存在安全盲点。
