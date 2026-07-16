# Skill 执行回执验证记录

验证日期：2026-07-15

## 目的

验证研究设计 Agent 的 Skill 调用不是模型在最终文本中自行声明，而是由 OpenCode 运行时插件在 `skill` 工具完成后签名记录，并由后端在项目工作流推进前验签。

## 实现链路

```text
OpenCode skill 工具完成
  -> medical-skill-receipts 插件生成 HMAC 回执
  -> 受限会话日志持久化
  -> 创建项目时插件注入 OpenCode session id
  -> 后端绑定 workflow_run_id 并验签入库
  -> 蓝图/内容/样本量/随机化门禁检查必需回执
  -> 导出工作包显示 Verified Skill Execution Receipts
```

## 自动化验证

- 插件可为真实 Skill 工具调用生成签名回执。
- 回执跨 OpenCode CLI `--continue` 重启后仍可绑定。
- 多个 Skill 并发完成时，按会话串行写入，不丢失回执。
- 插件可在创建项目工具执行前注入当前 OpenCode session id。
- 后端拒绝缺失必需回执或签名被篡改的回执。
- 后端测试结果：`23 passed`。

## 真实 OpenCode 验证

使用 `study-design-agent` 和 `gpt-5.4` 执行脱敏的“肺结节 AI 辅助 CT 诊断准确性研究”案例。

- 项目 ID：`14`
- 工作流 Run ID：`1efc0264640b4a8e845b40ccf20af2f2`
- 已成功推进：项目创建、`STARD` 蓝图生成
- 已入库并验签的 Skill 回执：`6`
- 已验证 Skill：
  - `phi-prompt-guard`
  - `clinic-research-design`
  - `inclusion-criteria-gen`
  - `research-proposal-generator`
  - `biomed-outline-generator`
  - `method-writing`

本次运行中，STARD 蓝图门禁在读取已验签回执后正常放行。`sample-size-basic` 已在后续步骤被实际调用；它会在下一次 MCP 工作流推进时同步入库，并作为样本量计算门禁证据。

## 部署要求

部署人员需要在启动 OpenCode 和 MCP 后端前，向同一进程环境设置高强度随机密钥：

```bash
export LRA_SKILL_RECEIPT_KEY='replace-with-a-high-entropy-secret'
```

密钥不可提交到仓库、不可出现在 Agent 提示词、不可提供给模型。该机制用于证明本地 OpenCode 运行时真实执行过指定 Skill，不替代生产环境的统一身份认证、集中审计和密钥托管。
