# SGLT2-HHF Literature Review MVP Case

更新日期：2026-07-14

## 1. Workflow Status

- `project_id`: 2
- `project_status`: exported
- `completed_steps`:
  - clarified review question
  - structured PICO
  - created local review project
  - generated project search strategy
  - ran PubMed and Europe PMC retrieval passes
  - imported 5 candidate citations
  - deduplicated citations
  - submitted 5 screening decisions
  - exported review bundle
- `pending_steps`:
  - replace MVP candidate set with cleaner landmark original trials
  - add full-text extraction before treating this as a formal review output

## 2. Research Question

- 原始研究问题：
  - 在 2 型糖尿病成人患者中，SGLT2 抑制剂是否降低心力衰竭住院风险？
- 当前规范化问题：
  - In adults with type 2 diabetes mellitus, do SGLT2 inhibitors reduce the risk of hospitalization for heart failure compared with placebo, usual care, or non-SGLT2 therapies?

## 3. PICO

- Population:
  - Adults with type 2 diabetes mellitus
- Intervention:
  - SGLT2 inhibitors
- Comparator:
  - Placebo, usual care, or non-SGLT2 glucose-lowering therapy
- Outcome:
  - Hospitalization for heart failure or risk of heart failure hospitalization

## 4. Search Strategy Draft

- 初始检索式：

```text
("In adults with type 2 diabetes mellitus, do SGLT2 inhibitors reduce the risk of hospitalization for heart failure compared with placebo, usual care, or non-SGLT2 therapies?"[Title/Abstract]) AND ("Adults with type 2 diabetes mellitus"[Title/Abstract]) AND ("SGLT2 inhibitors"[Title/Abstract]) AND ("Hospitalization for heart failure or risk of heart failure hospitalization"[Title/Abstract])
```

- 优化后检索式：

```text
((\"Diabetes Mellitus, Type 2\"[Mesh] OR \"type 2 diabetes\"[tiab] OR T2DM[tiab]) AND (\"Sodium-Glucose Transporter 2 Inhibitors\"[Mesh] OR \"SGLT2 inhibitor*\"[tiab] OR \"sodium-glucose cotransporter 2 inhibitor*\"[tiab] OR gliflozin*[tiab] OR empagliflozin[tiab] OR dapagliflozin[tiab] OR canagliflozin[tiab] OR ertugliflozin[tiab] OR sotagliflozin[tiab]) AND (\"Heart Failure\"[Mesh] OR \"heart failure\"[tiab] OR \"cardiac failure\"[tiab] OR \"congestive heart failure\"[tiab]) AND (hospitalization[tiab] OR hospitalisation[tiab] OR \"hospital admission*\"[tiab] OR HHF[tiab] OR hHF[tiab]))
```

- 检索式说明：
  - `verified`: OpenCode 主 agent 已创建本地项目并生成工作版检索式。
  - `verified`: 检索子 agent 将表达式扩展为更适合 PubMed 的 MVP 工作版。
  - `suggested`: 正式系统综述前应再补药物别名、研究设计过滤与时间范围策略。

## 5. Recommended Databases

- 主数据库：
  - PubMed
- 补充数据库：
  - Europe PMC
- 为什么这样选：
  - `verified`: 这次案例实际调用了 PubMed 与 Europe PMC。
  - `inferred`: 对于当前 MVP，PubMed 足以完成核心演示，Europe PMC 适合作为补充与交叉核对。

## 6. Retrieval Summary

- `databases_used`:
  - PubMed
  - Europe PMC
- `queries_run`:
  - broad disease + intervention + outcome query
  - targeted trial-name queries for EMPA-REG OUTCOME, CANVAS, DECLARE-TIMI 58, VERTIS CV
- `records_retrieved`:
  - `verified`: 多轮检索已执行
  - `verified`: 5 篇题录被选中并导入本地项目
  - `note`: 本次命令行运行在最终汇总前中断，未保留每轮检索的完整返回条数
- `records_imported`:
  - 5
- `duplicates_removed`:
  - 0

## 7. Screening Suggestions

| citation_id | title | decision | reason | confidence |
|---|---|---|---|---|
| 1 | Sodium-Glucose Cotransporter-2 (SGLT2) Inhibitors and Risk of Heart Failure Hospitalization in Type 2 Diabetes: A Systematic Review and Meta-Analysis of Randomized Controlled Trials. | exclude | Systematic review and meta-analysis, not an original core study for this MVP evidence set. | high |
| 2 | Effects of SGLT2 inhibition on incident heart failure in carriers of cardiomyopathy-associated genetic variants. | include | Secondary analysis of DECLARE-TIMI 58 directly addresses SGLT2 and heart failure hospitalization in type 2 diabetes. | medium |
| 3 | Heart failure outcomes captured by adverse event reporting in participants with type 2 diabetes and atherosclerotic cardiovascular disease: Observations from the VERTIS CV trial. | include | Trial-based heart failure outcome analysis in adults with type 2 diabetes and directly relevant HHF endpoint. | high |
| 4 | Cardiovascular and Renal Outcomes with Ertugliflozin by Baseline Use of Renin-Angiotensin-Aldosterone System Inhibitors or Diuretics, Including Mineralocorticoid Receptor Antagonist: Analyses from the VERTIS CV Trial. | include | Relevant VERTIS CV subgroup analysis reporting hospitalization for heart failure outcomes with ertugliflozin. | medium |
| 5 | PERsonalised Medicine for Intensification of Treatment (PERMIT) in type 2 diabetes mellitus: a target trial emulation from routine data. | exclude | Broad comparative effectiveness target trial emulation, not prioritized in the core trial-focused MVP set. | medium |

## 8. PRISMA Snapshot

- Identified:
  - 5
- After deduplication:
  - 5
- Screened:
  - 5
- Included:
  - 3
- Excluded:
  - 2

## 9. Evidence Summary

- 已验证证据：
  - `verified`: 本地项目已经完成从项目创建到筛选提交再到导出的完整最短闭环。
  - `verified`: 当前导入的 5 篇题录中，3 篇被纳入 MVP 证据集，2 篇被排除。
- 初步模式判断：
  - `inferred`: 当前纳入记录整体方向支持 SGLT2 抑制剂对心衰住院风险具有保护作用。
  - `inferred`: 但这批记录更偏向次级分析、结局分析和后续研究，不是最标准的 landmark 原始试验主报告集合。
- 当前证据缺口：
  - `verified`: 还没有把 EMPA-REG OUTCOME、CANVAS、DECLARE-TIMI 58 的主报告稳定纳入当前项目证据池。
  - `verified`: 目前仍然是标题摘要级筛选，没有全文级抽取与偏倚评估。

## 10. Key Controversies

- 争议点 1：
  - `inferred`: 当前 MVP 检索虽然完成闭环，但候选集质量仍受检索式和题录挑选策略影响，可能偏离“最经典主试验优先”的正式综述路径。
- 争议点 2：
  - `inferred`: 次级分析与真实世界研究能否进入核心证据集，取决于综述目标是“核心随机证据”还是“扩展临床证据”。
- 争议点 3：
  - `verified`: 仅基于标题摘要做初筛无法替代全文核验，尤其在结局定义、亚组分析和研究设计判断上容易保守或误判。

## 11. Review Outline

- 引言
  - T2DM 患者心衰负担与 SGLT2 抑制剂的心肾获益背景
- 方法
  - PICO、数据库、检索策略、MVP 初筛流程
- 结果
  - 候选文献筛选结果与 HHF 方向性证据
- 讨论
  - SGLT2 抑制剂可能的获益模式与当前证据组成局限
- 局限性
  - 题录集仍需经典原始试验补齐
  - 尚未进行全文抽取、NOS/Cochrane 评价
- 结论
  - 当前 MVP 结果支持继续向正式系统综述版本推进

## 12. Next Steps

- 下一步动作 1：
  - 重新定向检索，优先锁定 EMPA-REG OUTCOME、CANVAS、DECLARE-TIMI 58 主报告
- 下一步动作 2：
  - 增加全文解析与结构化信息抽取
- 下一步动作 3：
  - 在同一固定模板下再跑 2 个真实医学课题，形成演示案例包

## 13. 标注规范

- `verified`:
  - 来自本地项目数据库、MCP 工具返回值或已导出的 bundle
- `inferred`:
  - 来自题录级内容和当前证据集的谨慎判断
- `suggested`:
  - 用于后续工作流优化建议
