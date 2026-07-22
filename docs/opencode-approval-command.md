# OpenCode 审批命令

`approve-workflow.sh` 是人工确认的本地入口。它不替代后端 REST 审批接口，而是把接口调用封装起来，降低手工测试和本机演示的操作复杂度。

## OpenCode 原生确认

四个主 Agent 使用的 OpenCode 配置已将以下三个工具设置为 `ask`：

- `literature_review_finalize_study_design`
- `literature_review_approve_study_design`
- `literature_review_approve_systematic_evidence`
- `literature_review_approve_research_writing`

研究设计默认使用 `literature_review_finalize_study_design`：它把申请、确认、随机化和导出封装为一次调用。OpenCode 会在工具真正执行前显示权限确认，用户选择 Allow 时才会继续，选择 Deny 时不会修改后端审批状态。旧的分步审批工具仍保留用于兼容历史项目。MCP 工具会由本地进程携带审批密钥调用后端校验接口；密钥不会进入工具参数或模型上下文。

使用 OpenCode 原生确认时，后端必须在启动时配置对应审批密钥。终端 `approve-workflow.sh` 是没有 OpenCode UI、或需要独立复核时的备用入口。

## 使用方式

先查看审批范围：

```bash
bash scripts/opencode/approve-workflow.sh status study 32
```

确认研究设计项目：

```bash
bash scripts/opencode/approve-workflow.sh approve study 32
```

确认系统评价证据：

```bash
bash scripts/opencode/approve-workflow.sh approve evidence 5 afd37ee79a57465aa2d27f028efee796
```

确认科研写作草稿：

```bash
bash scripts/opencode/approve-workflow.sh approve writing 9
```

每次审批命令都会先读取当前范围，操作者必须输入 `APPROVE`，再输入审批人姓名或工号。输入其他内容会取消操作。

## 为什么不直接让 Agent 审批

OpenCode 的模型可以提出确认问题，但模型收到“确认”文本后仍然属于 Agent 会话，不能作为独立授权主体。审批命令由本地操作者启动，使用后端配置的审批密钥，并通过三个不同的 HTTP Header 区分研究设计、系统评价和科研写作审批。

后端会再次校验当前 Digest。如果审批请求之后修改了纳排标准、样本量、随机化、全文抽取、偏倚评估、Meta 结果或写作草稿，Digest 会变化，原审批自动失效，必须重新请求审批。

审批密钥不写入 OpenCode 配置、不进入模型上下文，也不写入 Git。可以通过对应环境变量提供，也可以由脚本运行时隐式输入。
