# 科研写作与方案成稿 Agent：两组真实运行记录

## 验证口径

两组运行均由 OpenCode 的 `research-writing-agent` 读取已保存的研究设计来源、调用真实写作 Skills、保存版本化草稿、请求人工审批，并在受保护 REST 端点记录本地演示审批后由 Agent 导出。

`authorized_research_operator` 是本地演示中的授权操作员标识，不代表伦理审查、基金评审、统计审核或机构正式批准。

## 案例 1：SGLT2 抑制剂与心衰住院的研究方案初稿

| 项目 | 记录 |
| --- | --- |
| 来源研究设计项目 | `study_design #15` |
| 规范写作运行 | `b61465e053264fb3a0853c986f47dfd3` |
| 交付草稿 | `draft #4`，`protocol`，版本化草稿 |
| 最终状态 | `exported` |
| 本地演示审批 | `approved`，由 `authorized_research_operator` 记录 |
| 已验证 Skills | `biomed-outline-generator`、`method-writing`、`discussion-section-architect` |

实际工具链：`get_research_writing_source` -> `start_research_writing_workflow` -> `save_research_writing_draft` -> `request_research_writing_approval` -> 外部受保护审批端点 -> `get_research_writing_approval_status` -> `export_research_writing_bundle`。

草稿来源清单明确引用 `study_design #15`，并将统计分析计划、伦理审批、知情同意和数据治理列为待确认项。草稿没有报告未经来源支持的患者结果、效应量或文献结论。

## 案例 2：AI 辅助 CT 肺结节诊断准确性标书初稿

| 项目 | 记录 |
| --- | --- |
| 来源研究设计项目 | `study_design #16` |
| 规范写作运行 | `58521eb3b1344fe48d93451f957f5e87` |
| 交付草稿 | `draft #5`，`proposal`，版本 `1` |
| 最终状态 | `exported` |
| 本地演示审批 | `approved`，由 `authorized_research_operator` 记录 |
| 已验证 Skills | `biomed-outline-generator`、`method-writing`、`discussion-section-architect`、`research-proposal-generator` |

实际工具链：`get_research_writing_source` -> `start_research_writing_workflow` -> `save_research_writing_draft` -> `request_research_writing_approval` -> 外部受保护审批端点 -> `get_research_writing_approval_status` -> `export_research_writing_bundle`。

该案例走的是 `proposal` 分支，因此后端要求并验证 `research-proposal-generator` 回执；缺少该回执时，自动化测试和运行门禁都会拒绝保存草稿。草稿将参考标准、诊断阈值、样本量、统计分析、伦理与数据治理放入待确认事项，未虚构敏感度、特异度、预算或预实验结果。

## 回执与人工确认核验

两个写作运行的数据库回执均已记录 HMAC 签名、OpenCode 会话和执行时间。后端在保存草稿与导出前检查必需 Skills；审批请求仅能由 Agent 发起，批准只能通过带 `X-Research-Writing-Approval-Key` 的受保护 REST 端点完成。

这两组运行证明：Agent 负责写作编排，授权操作员负责最终放行，系统记录两者边界与完整来源链路。

## 限制

- 导出文稿是可审阅草稿，不是伦理批准、正式标书、投稿稿件或临床结论。
- 后续修改应创建新版本，并重新请求人工审批。
- 当前来源可为已保存研究设计或已完成证据表；不允许以没有来源清单的自由文本作为正式导出依据。
