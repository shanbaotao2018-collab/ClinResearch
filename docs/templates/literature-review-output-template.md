# Literature Review Fixed Output Template

更新日期：2026-07-14

这个模板用于 `literature-review` 主 agent 的标准交付格式。

## 1. Workflow Status

- `project_id`:
- `project_status`:
- `completed_steps`:
- `pending_steps`:

说明：

- 这里写真实项目推进状态
- 不能凭空编造
- 必须尽量来自 MCP tool 返回值或导出结果

## 2. Research Question

- 原始研究问题：
- 当前规范化问题：

## 3. PICO

- Population:
- Intervention:
- Comparator:
- Outcome:

## 4. Search Strategy Draft

- 初始检索式：
- 优化后检索式：
- 检索式说明：

## 5. Recommended Databases

- 主数据库：
- 补充数据库：
- 为什么这样选：

## 6. Retrieval Summary

- `databases_used`:
- `queries_run`:
- `records_retrieved`:
- `records_imported`:
- `duplicates_removed`:

## 7. Screening Suggestions

按表格输出，字段固定为：

| citation_id | title | decision | reason | confidence |
|---|---|---|---|---|

说明：

- `decision` 只允许：
  - `include`
  - `exclude`
  - `human_review`

## 8. PRISMA Snapshot

- Identified:
- After deduplication:
- Screened:
- Included:
- Excluded:

## 9. Evidence Summary

- 已验证证据：
- 初步模式判断：
- 当前证据缺口：

## 10. Key Controversies

- 争议点 1：
- 争议点 2：
- 争议点 3：

## 11. Review Outline

- 引言
- 方法
- 结果
- 讨论
- 局限性
- 结论

## 12. 下一步操作

仅展示后端 `get_workflow_next_actions` 返回的操作卡片：

| 操作 | 状态 | 原因 |
|---|---|---|
| `{{ action.label }}` | `{{ action.status }}` | `{{ action.reason }}` |

不得自行增加下一步、内部工具名、未验证文献或跨项目建议。当前 Agent
未完成闭环时，只展示继续当前 Agent 的动作；仅在闭环完成后展示下游
Agent 的交接动作。

## 13. 标注规范

每个关键结论尽量标记为以下三类之一：

- `verified`
- `inferred`
- `suggested`
