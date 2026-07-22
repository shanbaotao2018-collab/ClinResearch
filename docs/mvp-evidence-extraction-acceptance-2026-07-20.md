# 证据抽取与系统评价 Agent MVP 验收记录

## 结论

证据抽取与系统评价 Agent 的 P0 后端闭环已完成并通过验收：公开全文入库、字段抽取、RoB 2 初评、二分类随机效应 Meta、范围锁定审批和最终证据包渲染均已用真实公开研究数据验证。

本记录是产品工具链验收，不是临床建议、系统评价定稿或论文结论。所有抽取、偏倚风险和 Meta 结果均须由研究者复核。

## 验收案例

- 项目：`4`，住院 COVID-19 成人患者中，羟氯喹相较常规治疗对 28 天全因死亡的影响。
- 工作流：`ee543310823d4642bc37d65fbdfaaeb9`。
- 公开全文 1：[RECOVERY trial: Effect of Hydroxychloroquine in Hospitalized Patients with Covid-19](https://pmc.ncbi.nlm.nih.gov/articles/PMC7556338/)（PMID `33031652`，DOI `10.1056/NEJMoa2022926`）。
- 公开全文 2：[WHO Solidarity trial: Repurposed Antiviral Drugs for Covid-19](https://pmc.ncbi.nlm.nih.gov/articles/PMC7727327/)（PMID `33264556`，DOI `10.1056/NEJMoa2023184`）。
- 已由研究者筛选为纳入研究；全文来源类型均为 `open_access_html`。

## 已验证流程

1. 使用 `fulltext-fetcher` 获取两篇 PMC 公开全文；公开 HTML 中的作者联系邮箱在入库前被替换为 `[redacted-public-contact-email]`，其余 PHI 检测仍启用。
2. 保存两条全文来源记录、两条基线与二分类结局记录、两条 RoB 2 初评记录；每个 RoB 2 域均保留 Methods 或 Results 章节定位。
3. 以 `28-day all-cause mortality`、RR、DerSimonian-Laird 随机效应模型运行 Meta 分析，并生成 SVG 森林图。
4. 请求系统评价审批后，未携带审批密钥的 REST 请求返回 `403`；本地演示授权后状态为 `approved` 且 `scope_current=true`。
5. 审批门禁通过后，最终证据包成功渲染：2 条全文证据行、1 次二分类 Meta 分析和相应限制说明。

## 结构化结果

| 研究 | 干预组死亡/总数 | 对照组死亡/总数 | 时间点 | 来源定位 |
| --- | --- | --- | --- | --- |
| RECOVERY | `421/1561` | `790/3155` | 28 days | Results > Primary Outcome |
| WHO Solidarity | `104/947` | `84/906` | 28 days | Results > Primary Outcome |

- 合并结果：RR `1.09`，95% CI `0.99`–`1.20`，I² `0.0%`，k=`2`。
- 这是由研究者录入并可回溯到公开全文的演示数据。两个研究的具体结局分析定义、可比性、风险偏倚与统计模型适用性仍须由方法学研究者确认，不能据此产生临床结论。
- 两篇研究的总体 RoB 2 初评均为 `some_concerns`，并非最终偏倚风险判定。

## OpenCode 验收状态

- Agent 定义、真实 Skill 名称、MCP 工具绑定和签名回执门禁均已通过自动化合约检查。
- 后端仅接受已签名的 OpenCode Skill 回执后执行对应 MCP 操作；RoB 2 与 QUADAS-2 使用 OpenCode 实际暴露的名称 `rct-bias-assessment-rob` 与 `diagnostic-study-quality-assessment-quadas`。
- 本次尝试调用外部 `gpt-5.4` 运行 `evidence-extraction-agent` 时，模型供应商因账户余额不足在预扣费阶段拒绝请求，未产生伪造回执或虚假的 Agent 执行记录。补充模型额度后，应按本案例再次运行 Agent 端到端验收。

## 自动化验证

在后端目录执行：

```bash
.venv/bin/python -m pytest -q
node ../../../scripts/opencode/test-agent-skill-contract.mjs
```

本次结果：`30 passed`，并通过 OpenCode Agent-Skill 合约检查。
