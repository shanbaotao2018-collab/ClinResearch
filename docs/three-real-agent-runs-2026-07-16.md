# 三个真实 Agent 运行记录

运行日期：2026-07-16

运行方式：`gpt-5.4` 通过 OpenCode `study-design-agent` 实际调用项目级 Skills 和本地 MCP。启用了 `LRA_SKILL_RECEIPT_KEY`，后端仅接受带签名的 Skill 执行回执。

## 案例 1：SGLT2 与心衰住院风险务实 RCT

- 项目 ID：`15`
- 工作流 Run ID：`602700a20b6644b9b535cc8809141173`
- 研究类型：`efficacy`
- 规范：`SPIRIT/CONSORT`
- 最终状态：`exported`
- 签名 Skill 回执：`8`
  - `phi-prompt-guard`
  - `clinic-research-design`
  - `inclusion-criteria-gen`
  - `research-proposal-generator`
  - `biomed-outline-generator`
  - `method-writing`
  - `sample-size-basic`
  - `randomization-gen`
- 基础样本量：两组率比较，总样本量 `712`
- 外部审批：`approved`
- 随机化：审批后生成受控随机表；Agent 返回 `allocation_visible_to_agent=false`，导出物未包含分配序列。

## 案例 2：AI 辅助 CT 肺结节诊断准确性研究

- 项目 ID：`16`
- 工作流 Run ID：`309696a67b304e42844015db8a8cae58`
- 研究类型：`diagnostic`
- 规范：`STARD`
- 最终状态：`exported`
- 签名 Skill 回执：`7`
  - `phi-prompt-guard`
  - `clinic-research-design`
  - `inclusion-criteria-gen`
  - `research-proposal-generator`
  - `biomed-outline-generator`
  - `method-writing`
  - `sample-size-basic`
- 外部审批：`approved`
- 随机化：不适用；导出工作包未产生随机化内容。

## 案例 3：衰弱评估预测心衰患者再入院的预后队列研究

- 项目 ID：`20`
- 工作流 Run ID：`95586d56088842c5aa1b3ed4556c3d20`
- 研究类型：`prognosis`
- 目标规范：`TRIPOD`
- 当前状态：`content_drafted`
- 已签名 Skill 回执：`6`
  - `phi-prompt-guard`
  - `clinic-research-design`
  - `inclusion-criteria-gen`
  - `research-proposal-generator`
  - `biomed-outline-generator`
  - `method-writing`
- 失败点：没有获取到 `sample-size-basic` 的真实执行回执。
- 系统行为：后端拒绝样本量计算，错误为“Verified OpenCode Skill receipts are required before sample_size: sample-size-basic.”
- 结论：该案例没有被伪造为完成；Skill 门禁按预期阻断了后续审批和导出。

## 总结

三种研究类型都实际进入了 OpenCode Agent、Skills、签名回执和 MCP 项目工作流。两条案例完成到可导出的闭环；第三条案例证明了当必需 Skill 未真实执行时，系统会停止而不是让模型用提示词绕过规则。
