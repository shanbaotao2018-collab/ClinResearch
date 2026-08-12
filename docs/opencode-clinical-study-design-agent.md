# OpenCode 临床科研方案设计智能体

## 定位

`study-design`（研究设计）是医学科研工作台的第一个方案设计闭环。它将自然语言科研想法沉淀为一个可追踪的本地项目；由当前 OpenCode 操作者完成内部人工确认后，才导出不含随机分配序列的研究方案工作包。

支持的研究类型：

- `diagnostic`：诊断准确性研究，使用 STARD 蓝图
- `efficacy`：疗效研究，使用 SPIRIT/CONSORT 蓝图
- `etiology`：病因研究，使用 STROBE 蓝图
- `prognosis`：预后研究，使用 TRIPOD 蓝图

它服务科研设计，不提供诊断、治疗建议、伦理审批结论或最终临床决策。

## 已封装 Skills

- `clinic-research-design`：研究类型、方案骨架与报告规范选择
- `inclusion-criteria-gen`：纳入与排除标准草案
- `research-proposal-generator`：课题方案与大纲
- `sample-size-basic`：基础样本量假设与边界
- `randomization-gen`：RCT 区组随机化
- `biomed-outline-generator`、`method-writing`：方案大纲与方法部分写作
- `phi-prompt-guard`：在进入模型和 MCP 前拦截明显的个人标识符

## MCP 工作流

1. `create_study_design_project`
2. `generate_study_design_blueprint`
3. `save_study_design_content`
4. `calculate_study_sample_size`
5. `save_rct_randomization_plan`，仅保存明确 RCT 的分组与区组计划
6. `finalize_study_design`：一次受权限保护的内部确认操作；OpenCode 显示原生 Allow/Deny，允许后创建确认范围、完成批准、生成受保护 RCT 分配表并导出方案包
7. `get_study_design_approval_status`：后续查看审批状态

样本量 MVP 只支持等比例分配的两组均值比较或两组率比较。它会保存 alpha、power、效应假设和结果；生存分析、集群试验、非劣效、多臂与自适应设计尚未开放。

## 在 OpenCode 中使用

从仓库根目录运行：

```bash
bash scripts/opencode/sync-medical-research-skills.sh
opencode --agent study-design
```

示例任务：

```text
请为心内科设计一项务实 RCT：在具有高心血管风险的 2 型糖尿病成人中，
SGLT2 抑制剂联合标准治疗是否可降低 12 个月内心衰住院风险？
科室预计每年有 300 例潜在合格病例。先生成完整方案草稿和两组率比较的样本量，
在我确认前不要导出最终工作包。
```

## 人工确认点

授权研究人员必须在 OpenCode 原生 Allow/Deny 确认框中确认以下内容后，Agent 才会导出工作包：

- 研究问题、研究类型与方案假设
- 纳入/排除标准和结局定义
- 样本量的效应假设、alpha、power 与适用范围
- RCT 的分组与区组大小

默认 OpenCode 工作流以 `finalize_study_design` 的原生 Allow/Deny 作为唯一人工确认门禁；允许后，后端直接写入审批人与审批范围的审计记录，不需要 `LRA_STUDY_DESIGN_APPROVAL_KEY`。MVP 在本机受限目录保存随机分配表并校验哈希；旧的受保护 REST 读取接口仍要求该密钥，只有授权试验运营人员可通过 `GET /study-design-projects/{id}/randomization-schedule` 读取。导出的 Markdown 只包含随机化计划和受控状态，不包含实际分配序列。

每次 MCP 调用均需携带项目创建时返回的 `workflow.run_id`，后端会记录操作及输入/输出摘要哈希，方便复核流程而不重复保存敏感内容。

## Skill 执行回执

`opencode.json` 已启用本地 `medical-skill-receipts` 插件。插件仅在 OpenCode 的 `skill` 工具真实执行完成后生成回执；回执使用 `LRA_SKILL_RECEIPT_KEY` 做 HMAC 签名，并先写入受限本地会话日志。创建项目后，插件将已签名回执绑定到该项目的 `workflow.run_id`。

后端启用同一个环境变量时，会在推进蓝图、方案内容、样本量和 RCT 随机化计划前验证必需回执。缺少回执或签名被篡改会阻断流程。导出工作包会增加 `Verified Skill Execution Receipts` 区段，列出实际执行的 Skill、执行时间和回执编号。

启动 OpenCode 前应由部署人员设置高强度随机密钥，且不要将其提交到仓库：

```bash
export LRA_SKILL_RECEIPT_KEY='replace-with-a-high-entropy-secret'
opencode --agent study-design
```

该机制证明 Skill 工具曾在指定 OpenCode 会话中真实运行；它不替代医院级身份认证、审计平台或密钥托管。
