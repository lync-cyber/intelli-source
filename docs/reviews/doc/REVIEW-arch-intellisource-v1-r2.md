# REVIEW: arch-intellisource-v1 (r2)
<!-- date: 2026-04-02 | reviewer: reviewer | doc_id: arch-intellisource-v1 -->
<!-- scope: main + modules + api + data volumes -->
<!-- upstream: prd-intellisource-v1 (approved) -->
<!-- previous: REVIEW-arch-intellisource-v1-r1 -->

## Layer 1 结果
- **主卷** (arch-intellisource-v1.md): PASS
- **模块分卷** (arch-intellisource-v1-modules.md): PASS
- **接口分卷** (arch-intellisource-v1-api.md): PASS (2 WARN: 行数超阈值 862 行; ID 编号不连续缺少 M-002/M-003/M-004)
- **数据分卷** (arch-intellisource-v1-data.md): PASS

Layer 1 WARN 说明: 与 r1 一致，API 分卷 ID 不连续警告为误报（分卷 ID 前缀为 API-xxx，M-xxx 属于模块分卷）。行数从 641 增至 862，因新增 8 个 API 定义（API-022 至 API-029），体量合理。

## r1 问题修复验证

| r1 编号 | 等级 | 问题 | 修复状态 | 验证说明 |
|---------|------|------|---------|---------|
| R-001 | HIGH | 订阅规则缺少管理 API | 已修复 | 新增 API-022(列表)、API-023(创建)、API-024(更新)、API-025(删除)，路径 `/api/v1/subscriptions`，归属 M-007，主卷交叉引用表已同步 |
| R-002 | HIGH | ChatMessage ER 图不一致 | 已修复 | ER 图已移除 ChatMessage 独立实体，NAV 块明确标注"不含 ChatMessage 独立实体"，E-011 context 字段说明内嵌存储对话消息历史 |
| R-003 | HIGH | API-005 路径遍历安全风险 | 已修复 | `file_path` 参数已替换为 `config_name`（仅文件名，白名单校验），desc 明确说明防路径遍历；arch#5.2 新增输入校验策略小节 |
| R-004 | MEDIUM | 工作流缺少查询/更新/删除 API | 已修复 | 新增 API-026(列表)、API-027(详情)、API-028(更新)、API-029(删除)，归属 M-006，主卷交叉引用表已同步 |
| R-005 | MEDIUM | API-003 PUT 改 PATCH | 已修复 | 方法已改为 PATCH，标题更新为"更新信源（部分更新）" |
| R-006 | MEDIUM | 向量维度 ASSUMPTION 标注 | 已修复 | E-004 embedding 字段已添加 [ASSUMPTION] 标注，说明默认 1536 维度、配置管理方式及迁移方案；E-005 centroid 同步标注 |
| R-007 | MEDIUM | zhparser 中文分词扩展 | 已修复 | 主卷 1.4 技术栈表新增 zhparser 行，含 Docker 部署说明和 GitHub 链接 |
| R-008 | MEDIUM | 健康检查 status 值 | 已修复 | API-018 status 枚举已改为 `"healthy \| degraded \| unhealthy"` |

**r1 修复结论**: 3 个 HIGH 和 5 个 MEDIUM 问题全部修复，修复质量合格。

## Layer 2 审查结果

对修订后文档进行全面复查，包括新增内容和原有内容的一致性验证。

### [R-001] LOW: r1 LOW 级别建议未处理（API 层速率限制 + 数据清理策略一致性）
- **category**: completeness
- **root_cause**: reviewer-calibration
- **描述**: r1 报告中 R-009（API 层速率限制）和 R-010（数据清理策略一致性）两个 LOW 级别建议在本轮修订中未处理。考虑到 r1 仅要求修复 HIGH/MEDIUM 问题，LOW 级别不修复符合流程规范。此处仅作记录以便后续参考。
- **建议**: 可在 dev-plan 阶段将 API 层速率限制和数据清理策略统一纳入技术债务 backlog。

## 审查摘要

| 等级 | 数量 |
|------|------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 0 |
| LOW | 1 |

**总体评价**: 修订后的架构文档质量良好。所有 r1 提出的 3 个 HIGH 和 5 个 MEDIUM 问题均已妥善修复。新增的订阅规则 CRUD API（API-022 至 API-025）和工作流 CRUD API（API-026 至 API-029）定义完整、格式规范，与模块分卷和主卷交叉引用表保持一致。安全修复（API-005 路径遍历防护、5.2 输入校验策略）设计合理。数据模型修订（ChatMessage 移除、ASSUMPTION 标注）清晰准确。修订过程未引入新的 CRITICAL/HIGH/MEDIUM 问题。

## 结论

**approved**
