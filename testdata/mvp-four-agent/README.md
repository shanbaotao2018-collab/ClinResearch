# 四 Agent MVP 测试数据包

本目录提供一轮可重复执行的医疗科研 Agent MVP 验收输入。测试数据不包含患者身份信息：研究设计参数均为模拟的聚合假设；文献数据仅引用公开发表的历史性研究。

## 执行顺序

1. 使用 `01-study-design-input.json` 运行 `study-design`，独立验证研究设计闭环。
2. 使用 `02-literature-review-input.json` 运行 `literature-review`，创建新的文献项目、检索、导入、去重和筛选。
3. 将步骤 2 创建的 `project_id` 写入 `03-evidence-extraction-input.json` 的运行时参数，运行 `evidence-extraction`。
4. 在步骤 3 完成摘要级与全文级证据记录后，将同一 `project_id` 写入 `04-research-writing-input.json`，运行 `research-writing`。

每个 Agent 都应停在自身的“请求外部审批”节点。为演示完整导出链路，可以由本地授权演示操作者调用受保护审批端点；该行为只代表 MVP 演示审批，不代表伦理、统计或学术审批。

## 安全边界

- 羟氯喹和 COVID-19 案例仅用于验证公开文献检索、全文抽取和统计工具链，不构成诊疗或用药建议。
- 不得把结构化抽取、RoB 2 初评、Meta 结果或写作草稿表述为临床结论或可直接投稿的终稿。
- 每一个 Agent 必须实际调用其定义的 Skills 和 MCP 工具；签名执行回执是后端持久化和导出的前置条件。
