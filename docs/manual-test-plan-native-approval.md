# 四 Agent 原生审批手工测试方案

本轮重点验证 OpenCode 原生内部人工确认，而不是手工调用 REST。测试使用公开历史文献和脱敏/聚合假设数据，不形成临床建议。

研究设计 Agent 已将“创建审批申请”和“批准申请”封装为一次 `finalize_study_design` 调用。用户只需要在 OpenCode 中选择一次 Allow/Deny；允许后后端会记录审批范围 Digest、审批人和项目状态，不需要研究设计审批密钥。

## 0. 启动两个终端

终端 A 启动后端。研究设计 Agent 的默认原生确认不需要审批密钥；下面两组密钥仅用于证据抽取和科研写作 Agent 的本机演示：

```bash
cd "/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend"
export LRA_SYSTEMATIC_EVIDENCE_APPROVAL_KEY="local-demo-evidence-key"
export LRA_RESEARCH_WRITING_APPROVAL_KEY="local-demo-writing-key"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
```

如果提示 `address already in use`，说明已有 8010 服务。不要直接启动第二个服务；先确认占用进程使用的是当前所需配置，必要时重启旧进程后再继续。

终端 B 启动 OpenCode。测试脚本会自动生成并复用本地 Skill 回执密钥：

```bash
cd "/Users/shanbaotao/Documents/agent 2"
export LRA_SYSTEMATIC_EVIDENCE_APPROVAL_KEY="local-demo-evidence-key"
export LRA_RESEARCH_WRITING_APPROVAL_KEY="local-demo-writing-key"
bash scripts/opencode/manual-test-four-agents.sh check
```

预期看到 4 个主 Agent、2 个子 Agent 和 `literature_review connected`。

> 注意：`opencode run` 是非交互模式。遇到 `ask` 权限时，它会自动拒绝工具调用，用于验证“未确认不能执行”的安全门禁；要验证并实际选择 Allow，必须使用下面的交互式 `opencode --agent ...` 命令。

## 1. 研究设计 Agent

在终端 B 执行：

```bash
opencode --agent study-design
```

粘贴：

```text
请读取并使用 testdata/mvp-four-agent/05-study-design-internal-approval-input.json，从零开始完成这个全新的研究设计案例。创建新的 study-design 项目，不要复用历史项目；完成研究设计、PICO、纳排标准、结局、两组比例样本量和随机化方案。所有参数是演示假设，不包含患者身份信息。
```

预期流程：

1. Agent 创建全新的 study-design 项目并保存方案。
2. Agent 调用一次 `literature_review_finalize_study_design`。
3. OpenCode 弹出一次权限确认，显示 Allow/Deny。
4. 选择 Deny，确认项目不会变为 `approved`，不会生成随机分配表，也不会导出方案包。
5. 重新启动一个新的确认调用并选择 Allow，确认审批状态变为 `approved`，并完成随机化和方案包导出。

查看状态：

```bash
bash scripts/opencode/approve-workflow.sh status study <project_id>
```

重点检查纳排标准、样本量参数、随机化方案和 Digest 是否与确认前一致。拒绝时重点检查没有随机化文件和导出包；允许后检查分配序列对 Agent 保持隐藏。

### 查看已成功导出的研究设计方案

当状态已经是 `approved` 且方案已导出时，最直观的方式是在同一个 OpenCode 会话中输入下面的话。将占位符替换为本次运行输出的项目 ID 与工作流运行 ID：

```text
请读取已完成的 study-design 项目 #<project_id>，workflow run id 为 <workflow_run_id>。调用 export_study_design_bundle，以 Markdown 展示完整脱敏研究方案包：研究问题、PICO、纳排标准、结局、样本量、随机化计划、审批状态、Skill 回执和审计记录。不要展示实际随机分配序列。
```

OpenCode 会展示可读的 Markdown 方案包。导出包只显示随机化计划和“已生成”的受控状态，不会显示受试者实际分配序列。

也可以在终端分别查看审批状态和本次工作流的审计事件：

```bash
curl -fsS 'http://127.0.0.1:8010/study-design-projects/<project_id>/approval' | jq
curl -fsS 'http://127.0.0.1:8010/study-design-projects/<project_id>/workflow-runs/<workflow_run_id>/events' | jq
```

只有授权的试验运营人员才能通过受保护接口读取实际随机分配表；不要在 OpenCode、Agent 输出或普通导出包中查看或粘贴该序列。

## 2. 文献检索与综述 Agent

执行：

```bash
opencode --agent literature-review
```

粘贴：

```text
请使用 testdata/mvp-four-agent/02-literature-review-input.json 创建新的文献项目。真实调用 PubMed 和 Europe PMC，检索住院成人 COVID-19 患者羟氯喹与28天死亡相关研究，导入指定的两篇公开 RCT，完成去重、标题摘要筛选、PRISMA 计数和项目包导出。输出 project_id。仅用于历史公开文献方法学测试。
```

检查：

- 是否真实调用 PubMed/Europe PMC；
- 是否创建新的 `project_id`；
- 是否调用 `search` 和 `screening`；
- 是否保留本地 citation ID、筛选理由和 PRISMA 计数。

该 Agent 当前没有人工确认节点，重点验证检索、导入、去重和筛选闭环。

## 3. 证据抽取与系统评价 Agent

最小回归可复用已完成筛选的项目 `#5`：

```bash
opencode --agent evidence-extraction
```

粘贴：

```text
请对 review 项目 #5 执行完整全文证据抽取验收。只处理已纳入研究：获取受控公开全文，抽取基线和28天全因死亡二分类事件数，完成 RoB 2、RR 随机效应 Meta 和森林图。完成后进入系统评价内部人工确认，不要自行确认、导出或给出临床建议。
```

预期在最后看到权限确认：

`literature_review_approve_systematic_evidence`

选择 Allow 后检查：

```bash
bash scripts/opencode/approve-workflow.sh status evidence 5 <workflow_run_id>
```

重点检查全文来源、事件数、RoB 2 五个域、Meta 结果和 `scope_current=true`。

## 4. 科研写作 Agent

在证据抽取完成后执行：

```bash
opencode --agent research-writing
```

粘贴：

```text
请使用 review 项目 #5 中已经保存的证据生成 document_type=discussion 的历史性系统综述讨论草稿。先读取 research writing source，只使用已保存事实，调用 biomed-outline-generator、method-writing、discussion-section-architect，保存 source_manifest、limitations 和 unresolved_items，然后进入科研写作内部人工确认。
```

预期看到权限确认：

`literature_review_approve_research_writing`

选择 Allow 后检查：

```bash
bash scripts/opencode/approve-workflow.sh status writing <draft_id>
```

## 验收标准

| 检查项 | 通过标准 |
|---|---|
| 原生权限确认 | 审批工具执行前出现 Allow/Deny |
| 研究设计拒绝 | 选择 Deny 后项目不变为 `approved`，不生成随机化表和导出包 |
| 研究设计允许 | 选择 Allow 后状态变为 `approved`，并完成随机化和导出 |
| 证据/写作拒绝 | 选择 Deny 后对应审批保持 `pending`，不允许导出 |
| 证据/写作允许 | 选择 Allow 后对应审批变为 `approved`，才允许导出 |
| Digest | 内容发生变化时旧审批不能继续使用 |
| 密钥隔离 | 审批密钥不出现在模型消息和工具参数中 |
| 审计 | 记录审批人、时间、审批范围和 Digest |
| 导出门禁 | 未审批时导出被阻断，审批后才允许导出 |

如果研究设计没有弹出确认，先检查 Agent 是否调用了 `literature_review_finalize_study_design`。不要再期待它先调用 `request_study_design_approval` 再调用 `approve_study_design`。如果仍显示旧的 `generate_rct_randomization_schedule` 和 `export_study_design_bundle` 后续步骤，说明当前 OpenCode/MCP 会话未加载最新配置，需完全退出后重新启动。

如果证据抽取或科研写作没有弹出确认，再检查是否只调用了 `request_*_approval` 就停止；这两个 Agent 当前仍使用分步审批工具链。
