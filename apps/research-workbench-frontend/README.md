# 临床科研智能体工作台前端

这是四 Agent 临床科研智能体工作台的 P0 只读浏览器界面。它从 FastAPI 聚合接口读取本地 SQLite 中已经保存的研究设计、文献综述、证据抽取和科研写作结果。

## 本地启动

终端 A：启动后端。若 `8010` 已有旧服务，先停止旧进程再重新执行，使它加载本轮新增的 `/workbench/*` 接口。

```bash
cd "/Users/shanbaotao/Documents/agent 2/apps/literature-review-agent/backend"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
```

终端 B：启动前端。

```bash
cd "/Users/shanbaotao/Documents/agent 2/apps/research-workbench-frontend"
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器访问 `http://127.0.0.1:5173`。

## 当前能力

- 总览当前保存的研究设计、文献综述、证据工作流、科研写作草稿和待审批事项。
- 查看研究设计的 PICO、纳排标准、样本量、随机化计划、审批、审计与 Skill 回执。
- 查看文献项目的检索式、题录、PRISMA、证据抽取、偏倚评价、Meta 分析、写作草稿和审计。
- 查看科研写作草稿的来源清单、结构、局限性、未解决项、审批与 Skill 回执。
- 随机分配种子和实际分配序列不会返回给网页。

## P0 边界

该版本是只读工作台。网页发起 Agent、角色登录和网页审批将在后续 P1/P2 实施；当前 Agent 执行和审批流程仍由 OpenCode/MCP 承担。
