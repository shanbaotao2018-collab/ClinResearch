# 三套离线闭环案例材料

## 目的

本材料包用于在无法访问 PubMed、Europe PMC 的服务器上，演示四个 Agent 的离线闭环：研究设计、文献检索与综述、证据抽取与系统评价、科研写作。它只替代外网资料获取环节；去重、筛选、PRISMA、全文解析、证据抽取和写作仍走同一套后端与 MCP 工作流。

每包固定包含 9 条真实公开题录及其开放获取原始全文 XML，适合验证流程、字段映射、全文抽取、偏倚风险评价和可审计性；它们是演示用的预检索集，不替代正式系统评价的完整检索。

## 已下载的原始材料

| 离线包 | 对应研究类型 | 题录与全文 | 覆盖的 Agent 环节 |
|---|---|---|---|
| `hf-remote-follow-up-v2` | 疗效 / RCT | 9 篇心衰出院后电话、远程医疗或短信随访研究；原始 NBIB + Europe PMC 全文 XML | 研究设计（RCT）、文献综述、全文证据抽取、RoB 2、按结局可比性选择性 Meta、科研写作 |
| `hf-home-rehabilitation-v2` | 疗效 / RCT | 9 篇心衰居家、远程或早期心脏康复研究；原始 NBIB + Europe PMC 全文 XML | 研究设计（RCT）、文献综述、全文证据抽取、RoB 2、功能与再入院结局整理、科研写作 |
| `pharmacist-medication-reconciliation-v2` | 药学服务 / 混合设计 | 9 篇药师用药核对、出院衔接或再入院结局研究；原始 NBIB + Europe PMC 全文 XML | 研究设计（实施/真实世界）、文献综述、全文证据抽取、RoB 2 或 NOS、异质性证据叙述、科研写作 |

本版本附带的去标识化演示离线包位于 `data/offline-evidence-packages/`，随仓库版本控制，
用于在新电脑或隔离网络中复现实验。新增的真实业务材料、授权受限全文和运行数据不得直接
提交，应通过 `LRA_OFFLINE_EVIDENCE_PACKAGE_DIR` 指向受控目录。

## 材料组成与来源

每个包都包含：

1. `citations.nbib`：通过 NCBI E-utilities 从 PubMed 导出的原始 MEDLINE/NBIB 题录。
2. `fulltext/*.xml`：从 Europe PMC `fullTextXML` 接口获取的原始开放获取全文。
3. `manifest.json`：记录检索式、下载日期、来源 URL、题录映射和每个文件的 SHA-256。

所有文件导入前均校验 SHA-256；校验失败、路径越界或题录映射不唯一时系统拒绝处理。

## 离线运行步骤

1. 在可联网的构建机生成或更新材料：

```bash
apps/literature-review-agent/backend/.venv/bin/python \
  scripts/build-offline-evidence-packages.py \
  --output-dir data/offline-evidence-packages
```

2. 将整个 `data/offline-evidence-packages/` 目录安全传输至目标服务器，例如 `/data/clinresearch/offline-evidence-packages/`。
3. 启动统一后端时指定 `offline` 模式，并设置离线包目录。MCP 已挂载在同一后端的 `/mcp/`，无需再单独启动或配置模式：

```bash
export LRA_OFFLINE_EVIDENCE_PACKAGE_DIR="/data/clinresearch/offline-evidence-packages"
bash scripts/start-research-backend.sh --literature-access-mode offline
bash scripts/opencode/start-literature-review-agent.sh
```

4. `literature-review` 调用 `list_offline_evidence_packages`，选择并导入一个包。每包先以 9 篇为演示上限运行，防止首次演示被大规模全文解析或模型限流干扰。
5. 正常完成去重、标题摘要筛选和人工确认。`evidence-extraction-agent` 仅对已纳入的文献调用 `ingest_offline_package_full_text`。
6. 在已保存的研究设计和证据记录基础上，`research-writing-agent` 生成带来源清单与待确认项的草稿。

## 边界

- 案例中的研究参数、筛选与质量评价均须由研究者确认；系统不会将模型建议当作最终科研结论。
- 仅应分发开放获取或机构已获授权的原文，并保留来源与许可核查记录。
- 如需扩充到正式系统评价，应由科研人员在可访问的数据库环境中按批准后的检索式补全检索集，再重新生成包。异质性较高的包不应为了演示而强行做 Meta 分析。
