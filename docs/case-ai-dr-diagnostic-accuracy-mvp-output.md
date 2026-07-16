# AI 糖尿病视网膜病变筛查：诊断准确性案例验证

## 课题

- **课题名称**：AI辅助眼底影像筛查糖尿病视网膜病变的诊断准确性文献综述
- **研究问题**：在糖尿病人群中，AI眼底影像筛查相对人工眼科医生判读或参考标准，对糖尿病视网膜病变的诊断准确性如何？
- **PICO**：
  - P（人群）：糖尿病患者
  - I（干预/检测）：AI眼底影像筛查
  - C（对照/参考）：人工眼科医生判读或金标准
  - O（结局）：敏感度、特异度、AUC
- **纳入标准**：原始诊断准确性研究；成人糖尿病患者；报告至少一项准确性指标。
- **排除标准**：综述、研究方案、非人群研究、无诊断准确性结局。

## 实际执行结果

| 环节 | 结果 |
| --- | --- |
| 创建项目 | 成功，`project_id = 2` |
| 检索策略 | 成功生成，并调用 `search-agent` 优化 |
| 数据库检索 | 已调用 PubMed 与 Europe PMC |
| 文献导入 | 3 篇真实候选研究 |
| 去重 | 移除 0 篇重复记录 |
| 初筛建议 | 已调用 `screening-agent` |
| 筛选决定 | 3 篇均暂定 `include` |
| 导出 | 成功，项目状态为 `exported` |

## 导入与筛选记录

| 本地 citation_id | 题名（缩略） | 初筛决定 | 原因摘要 |
| --- | --- | --- | --- |
| 1 | *Diagnostic Accuracy of Artificial Intelligence-based Automated Detection of Diabetic Retinopathy...* | `include` | 前瞻性诊断准确性研究，AI 与眼科医师参考标准比较，并报告 ROC/AUC。 |
| 2 | *Diagnostic performance of an artificial intelligence software for diabetic retinopathy organised screening...* | `include` | 原始筛查试点研究，AI 与盲法眼科专家参考标准比较。 |
| 3 | *Comparative assessment of diagnostic agreement between artificial intelligence and general practitioners...* | `include` | 500 名 2 型糖尿病患者，报告敏感度、特异度和总体准确率。 |

这些是题录/摘要层面的初筛结果，不等同于系统综述的最终纳入。进入正式证据综合前，仍需全文核验研究设计、参考标准和准确性数据。

## PRISMA 快照

```text
identified_count:       3
deduplicated_count:     3
screened_count:         3
included_count:         3
excluded_count:         0
full_text_assessed:     0
```

## 验证结论与边界

业务引擎的项目创建、检索、导入、去重、筛选、PRISMA 计数和导出均已验证。主智能体完成了前六个步骤；在提交筛选决定前，外部 `model-port/gpt-5.4` 的 OpenCode 长链路两次超时，因此最后两步通过同一后端 HTTP 接口完成，以验证工具契约与数据闭环。

这说明 MVP 的业务流程可用，但当前不应把外部模型连接稳定性视为已验收。后续应为模型调用增加重试/故障切换，并补齐全文获取、基线与效应指标提取、偏倚风险评价和综述写作能力。
