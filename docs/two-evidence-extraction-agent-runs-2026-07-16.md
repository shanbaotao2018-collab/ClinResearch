# 文献筛选与证据提取 Agent：两组真实运行记录

## 验证口径

两组运行均由 OpenCode 的 `evidence-extraction-agent` 调用实际 Skill 与 MCP 工具完成。证据字段只使用本地项目已保存的题录和摘要；导出表中的缺失信息保留为 `not_reported` 或 `missing_fields`，没有补造全文结果。

Skill 回执使用本地 `LRA_SKILL_RECEIPT_KEY` 的 HMAC 签名，由后端在保存提取、撤稿核查和导出前验证。

## 案例 1：AI 辅助眼底影像筛查糖尿病视网膜病变

| 项目 | 记录 |
| --- | --- |
| 本地文献项目 | `1` |
| 工作流运行 | `1793a63fcae448299e5a0431047c5f28` |
| 已纳入并提取文献 | 2 篇 |
| 已保存安全核查 | 2 条 |
| 最终状态 | 已导出 Markdown 证据表 |
| 已验证 Skills | `clinical-study-info-extractor`、`methodology-extractor`、`retraction-watcher` |

实际工具链：`start_evidence_extraction_workflow` -> `save_evidence_extractions` -> `check_project_retractions` -> `export_evidence_table`。

提取结果包括诊断准确性研究设计、研究对象、AI 算法/比较标准、结局与方法摘要。没有出现在摘要中的样本量、敏感度、特异度、置信区间等字段被标记为缺失，而非推断填写。

安全核查结果为 `unavailable`：该本地题录并非可用的 PubMed 数字 PMID 记录，因而系统没有把“无法核查”伪装成“未发现撤稿”。需要研究者用 DOI/期刊页面或其他合规数据源继续核对。

## 案例 2：达格列净与 2 型糖尿病心血管结局

| 项目 | 记录 |
| --- | --- |
| 本地文献项目 | `2` |
| 工作流运行 | `5aa6357c7ba94d0bb17021b61ed465a7` |
| 已纳入并提取文献 | 1 篇 |
| 已保存安全核查 | 1 条 |
| 最终状态 | 已导出 Markdown 证据表 |
| 已验证 Skills | `clinical-study-info-extractor`、`methodology-extractor`、`retraction-watcher` |

实际工具链：`start_evidence_extraction_workflow` -> `save_evidence_extractions` -> `check_project_retractions` -> `export_evidence_table`。

该条记录被标注为“随机、安慰剂对照 III 期试验的事后分析”；摘要明确支持的内容写入研究设计、目标人群、干预、对照、复合心血管结局和方法概述。精确风险比、95% CI、随访时间和分层结果未在当前摘要依据中确认，因此进入 `missing_fields`。

安全核查同样返回 `unavailable`，原因是本地记录没有可用于自动 PubMed 公告类型查询的 PubMed 数字 PMID。该结果正确保留了人工核查要求。

## 回执核验

数据库 `agentskillexecutionreceipt` 中，两个工作流各包含上述三个必需 Skill 的 HMAC 已验证回执；`agentworkflowevent` 中均有启动、提取保存、安全核查和导出事件。

本次验证证明了：没有真实 Skill 回执时，后端会拒绝保存提取或导出；有回执后，Agent 才能完成对应 MCP 操作。

## 限制

- 当前 MVP 只处理题录、摘要和用户提供的全文摘录，不自动获取或解析受版权限制的全文 PDF。
- PubMed 公告类型查询是“检查时状态”，不构成永久撤稿安全保证。
- 所有证据行仍需研究者逐篇核对全文和最终纳排决定。
