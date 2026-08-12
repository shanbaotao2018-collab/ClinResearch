# 统一后端离线模式手工验证

> 历史说明：本手册中的 `*-v1` 小样本包每包只有 2 篇，保留用于回归测试。参赛和四 Agent 全流程演示请改用 [全文预验证四 Agent 演示案例（V2）](fulltext-verified-demo-cases-v2.md) 中的三个 9 篇全文包。

## 目标与范围

本手册验证临床科研智能体工作台在没有 PubMed、Europe PMC 等医学数据库实时访问能力时，仍可用本地保存的**原始题录和开放获取全文 XML**完成可审计的科研工作流。

本轮覆盖三套离线证据包和四个主 Agent：

| 验证案例 | 离线证据包 | 研究主题 | 主要验证 Agent | 闭环产物 |
|---|---|---|---|---|
| A | `hf-transition-care-v1` | 药师主导心衰出院过渡管理 | `literature-review` | 综述项目、检索策略、筛选建议、PRISMA、review bundle |
| B | `ai-diabetic-retinopathy-v1` | AI 眼底影像筛查糖尿病视网膜病变 | `evidence-extraction` | 综述项目、全文证据表、诊断研究初步质量评价、systematic evidence bundle |
| C | `frailty-hf-readmission-v1` | 衰弱评估预测心衰再入院 | `study-design`、`research-writing` | 综述项目、队列研究设计草案、研究方案写作草稿与导出包 |

离线包的职责仅是替代在线数据库的**检索资料来源**。因此每套包都必须先由 `literature-review` 创建并导入本地综述项目；后续 Agent 只消费已保存的项目事实、筛选结果和证据记录，不能绕过项目记录直接把离线原始文件当作结论。

所有案例仅用于公开文献的软件方法学演示，不包含患者身份信息，不构成诊疗建议、伦理审批、注册方案或可直接投稿的科研结论。

## 1. 启动前检查

### 1.1 确认统一后端为离线模式

先检查 `8010` 是否已运行：

```bash
curl -fsS http://127.0.0.1:8010/health | jq
```

预期关键字段：

```json
{
  "status": "ok",
  "literature_access": {
    "mode": "offline",
    "live_database_requests_enabled": false
  }
}
```

如果连接失败，才在新的终端启动后端：

```bash
cd "/Users/shanbaotao/Documents/agent 2"
bash scripts/start-research-backend.sh --literature-access-mode offline
```

不要在 `8010` 已被占用时重复启动第二个后端。访问模式只在后端启动时设置一次；OpenCode 不再单独设置 `offline`。

### 1.2 确认 OpenCode 已连接统一 MCP

```bash
cd "/Users/shanbaotao/Documents/agent 2"
opencode mcp list
```

预期：

```text
literature_review  connected
http://127.0.0.1:8010/mcp/
```

查看后端发现的离线包：

```bash
curl -fsS http://127.0.0.1:8010/offline-evidence-packages | jq
```

预期包含：

```text
hf-transition-care-v1
ai-diabetic-retinopathy-v1
frailty-hf-readmission-v1
```

### 1.3 选择 Agent 的方式

推荐从 Web 版启动，便于使用输入框左下角的 Agent 下拉框：

```bash
cd "/Users/shanbaotao/Documents/agent 2"
opencode web --port 4096 --hostname 127.0.0.1
```

在浏览器打开 `http://127.0.0.1:4096` 后，从下拉框选择对应 Agent。也可以在桌面端输入 `/literature-review`、`/study-design`、`/evidence-extraction` 或 `/research-writing` 选择主 Agent。

## 2. 共通执行与记录规则

1. 三个案例均创建新的项目，不能复用历史 `project_id`。
2. Prompt 应保持自然语言表达，不指定 `offline`、离线包名称或 MCP 工具名；系统应根据后端状态自动选择本地资料。
3. 文献综述 Agent 展示筛选建议后必须停下，等研究者明确确认，才可保存纳入/排除决定。
4. 证据抽取、研究设计和科研写作的权限弹窗必须由操作者在 OpenCode 中选择 `Allow` 或 `Deny`；不要提供或输入后端审批密钥。
5. 每步记录 `project_id`、`workflow.run_id`（若输出）、实际 `citation_id`、`Skills Applied`、权限确认结果和导出文件位置。
6. 通过离线模式的核心证据是：后端状态为 `offline`，工具回执显示本地来源，且整个过程没有 `search_pubmed`、`search_europepmc` 或在线全文获取调用。

## 3. 案例 A：药师主导心衰出院过渡管理

### 3.1 文献综述与筛选建议

在 Agent 下拉框选择 `Literature-Review`，输入：

```text
请从零开始创建一个文献综述项目，研究问题是：药师主导的心衰患者出院过渡管理，相较常规出院管理，是否改善再入院或临床结局？

请完成 PICO、检索策略草案、资料获取、去重和标题摘要筛选建议；在保存任何纳入或排除决定前，请先向我展示建议并等待确认。仅用于公开文献的软件方法学演示，不提供临床建议。
```

如 Agent 询问匹配资料，正常回答：

```text
请选择与药师主导心衰出院过渡管理最相关的本地资料继续。
```

记录：

- `review_project_id`
- 导入题录数、去重数与每条本地 `citation_id`
- 检索策略、筛选建议、PRISMA 初始计数
- `search`、`screening` 回执中的 `Skills Applied`

通过标准：成功导入本案例的 2 条题录；生成筛选建议但未自行写入最终决定；资料来源被标记为本地离线证据包。

### 3.2 人工确认并导出综述包

用上一步实际返回的编号替换占位符，在同一会话输入：

```text
我确认本次筛选：citation_id=<include_id> 纳入，理由为“与药师主导心衰出院过渡管理直接相关”；citation_id=<exclude_id> 排除，理由为“本次演示仅保留一篇纳入文献验证后续流程”。请保存决定，生成 PRISMA 计数并导出综述项目包。
```

通过标准：仅在明确确认后保存筛选决定；PRISMA 显示 `identified_count=2`、`included_count=1`、`excluded_count=1`；成功导出 review bundle。

## 4. 案例 B：AI 眼底影像筛查糖尿病视网膜病变

本案例验证诊断准确性研究的离线资料导入、全文证据抽取和 QUADAS-2 初步质量评价。

### 4.1 创建综述项目并确认纳入研究

选择 `Literature-Review`，输入：

```text
请从零开始创建文献综述项目，研究问题是：人工智能眼底影像筛查糖尿病视网膜病变的诊断准确性如何？

请完成 PICO 或诊断问题框架、检索策略草案、资料获取、去重和标题摘要筛选建议；不要替我保存最终筛选决定。仅用于公开文献的软件方法学演示，不提供诊疗建议。
```

待筛选建议出现后，记录 `review_project_id` 和两个真实 `citation_id`，再输入：

```text
我已核对筛选建议，确认这两篇与 AI 眼底影像筛查糖尿病视网膜病变诊断准确性直接相关的研究均纳入。请保存筛选决定，生成 PRISMA 计数并导出综述项目包。
```

通过标准：导入本案例的 2 条题录，两个决定均为 `include`，并已导出 review bundle。

### 4.2 离线全文证据抽取与系统评价

选择 `Evidence-Extraction-Agent`，输入并替换 `<review_project_id>`：

```text
请继续处理综述项目 #<review_project_id> 中已纳入的两篇研究。请基于已保存的公开全文完成证据抽取：研究设计、样本、索引检验、参考标准、敏感度/特异度等可获得结果、缺失字段与证据依据；完成诊断研究的初步 QUADAS-2 评价。不要编造缺失信息，也不要给出诊疗建议。
```

当 Agent 展示系统评价范围并要求确认时，在 OpenCode 原生权限框选择 `Allow`。如果仅想验证审批前状态，选择 `Deny` 并记录停止点。

通过标准：

- 只对已纳入的两篇研究处理本地全文，不使用在线全文获取。
- 证据表中每个字段标明 `metadata`、`abstract` 或 `full_text_excerpt` 依据；缺失项标为 `not_reported` 或列入 `missing_fields`。
- 输出 `diagnostic-study-quality-assessment-quadas` 等实际 Skills 回执。
- 每条研究均有文献安全检查与初步质量评价；确认成功后可导出 systematic evidence bundle。

## 5. 案例 C：衰弱评估预测心衰再入院

本案例验证预后问题的离线文献依据、观察性队列研究设计，以及受来源约束的科研写作草稿。

### 5.1 创建预后综述项目

选择 `Literature-Review`，输入：

```text
请从零开始创建一个文献综述项目，研究问题是：衰弱评估是否能够预测心力衰竭患者出院后的再入院风险？

请完成 PICO 或预后问题框架、检索策略草案、资料获取、去重和标题摘要筛选建议；在最终保存筛选决定前等待我的确认。仅用于公开文献的软件方法学演示。
```

确认建议后，输入：

```text
我确认这两篇与衰弱评估预测心衰再入院直接相关的研究均纳入。请保存筛选决定，生成 PRISMA 计数并导出综述项目包。
```

记录本案例 `review_project_id`、两个 `citation_id` 与导出位置。

### 5.2 设计本地预后队列研究

选择 `Study-Design-Agent`，输入：

```text
请为“衰弱评估预测心力衰竭患者出院后 90 天再入院风险”从零开始设计一项前瞻性观察性队列研究。研究对象为出院前完成衰弱评估的成人心衰患者；主要结局为 90 天全因再入院；预期可招募 600 人。请完成研究问题、PICO、纳排标准、结局、可行性与创新性、研究方案大纲，并说明样本量测算是否适用。所有内容均为演示假设，不包含患者身份信息。
```

本例不是 RCT，不应生成随机分配方案。若 Agent 请求内部确认，核对草案后在 OpenCode 原生权限框选择 `Allow`，以完成研究设计包导出。

通过标准：

- 创建新的 `study_design_project_id`，并显示研究类型为观察性预后研究，而非 RCT。
- 展示所用 Skills、纳排标准、主要/次要结局、可行性和未解决假设。
- 明确说明 MVP 样本量工具仅支持两组比较；对本预后队列问题不得伪造两组率样本量或随机方案。
- 内部确认后导出 study-design bundle；输出中不出现分配序列。

### 5.3 建立科研案例关联

科研写作若同时引用研究设计和综述证据，必须先建立一个 `research_case` 作为两者的可审计关联记录。保持在 `Study-Design-Agent` 会话或新建会话中，输入并替换两个项目编号：

```text
请创建一个新的科研案例记录，主题为“衰弱评估预测心衰再入院”。请将已保存的研究设计项目 #<study_design_project_id> 与综述项目 #<review_project_id> 关联到该案例，并告诉我新建的科研案例编号及关联状态。
```

记录返回的 `research_case_id`。通过标准：该案例同时关联一个研究设计项目和一个综述项目；后续写作以该科研案例作为唯一工作流来源。

### 5.4 基于已保存来源起草科研写作草稿

选择 `Research-Writing-Agent`，输入并替换科研案例编号：

```text
请使用已保存的科研案例 #<research_case_id> 作为唯一工作流来源，起草一份“衰弱评估预测心衰再入院”的研究方案草稿。请给出标题、结构化大纲、方法学草稿、讨论框架、来源清单、局限性和待补充事项。不要把草稿表述为已获伦理批准、已注册或可直接提交的正式方案。
```

当 Agent 展示写作审批范围时，核对来源清单包含科研案例及其关联的研究设计、综述证据；确认无误后在 OpenCode 原生权限框选择 `Allow`，再由 Agent 导出写作包。

通过标准：

- `source_manifest` 同时记录科研案例、研究设计项目和综述/证据来源；不存在的结果、参考文献、伦理信息均列为待补充项。
- 输出 `biomed-outline-generator`、`method-writing`、`discussion-section-architect`，以及方案类型所需的 `research-proposal-generator` 回执。
- Agent 不把本地两篇题录夸大为完整证据综述，也不生成患者诊疗建议。
- 人工确认后生成 research-writing bundle。

## 6. 覆盖矩阵与最终验收

| 项目 | 案例 A | 案例 B | 案例 C | 总体验收 |
|---|---:|---:|---:|---|
| `hf-transition-care-v1` 被导入 | 是 |  |  |  |
| `ai-diabetic-retinopathy-v1` 被导入 |  | 是 |  |  |
| `frailty-hf-readmission-v1` 被导入 |  |  | 是 |  |
| `literature-review` 完成离线导入与人工筛选 | 是 | 是 | 是 | 3/3 |
| `evidence-extraction` 完成全文证据抽取 |  | 是 |  | 1/1 |
| `study-design` 完成预后研究设计 |  |  | 是 | 1/1 |
| `research-writing` 生成来源受限草稿 |  |  | 是 | 1/1 |
| 在线医学数据库调用 | 0 | 0 | 0 | 必须为 0 |
| 原生人工确认记录 | 可选 | 必须 | 必须 | 至少 2 次 Allow |

可用以下模板记录最终结果：

```text
后端模式：offline
MCP 地址：http://127.0.0.1:8010/mcp/

案例 A：hf-transition-care-v1
review_project_id：<id>
导入/去重/纳入/排除：2 / <n> / 1 / 1
review bundle：<path-or-id>

案例 B：ai-diabetic-retinopathy-v1
review_project_id：<id>
导入/纳入：2 / 2
evidence bundle：<path-or-id>
QUADAS-2：已生成 / 未生成（原因）

案例 C：frailty-hf-readmission-v1
review_project_id：<id>
study_design_project_id：<id>
research_case_id：<id>
research-writing bundle：<path-or-id>

四个 Agent：通过 / 未通过（说明原因）
三套离线包：通过 / 未通过（说明原因）
在线医学数据库调用：0 / 非 0（说明原因）
结论：统一后端离线闭环通过 / 未通过（说明原因）
```

## 7. 常见问题

| 现象 | 处理方式 |
|---|---|
| `8010 address already in use` | 不要再启动服务；执行第 1.1 节 `/health` 检查。 |
| `literature_review disconnected` | 确认后端仍运行，并执行 `opencode mcp list`；地址应为 `http://127.0.0.1:8010/mcp/`。 |
| Agent 尝试在线检索 | 检查 `/health` 中 `mode` 是否为 `offline`，停止当前会话，重启后端和 OpenCode 后重新开始案例。 |
| 找不到离线包 | 检查 `runtime/offline-evidence-packages/`；服务器部署时检查 `LRA_OFFLINE_EVIDENCE_PACKAGE_DIR`。 |
| 全文解析提示没有纳入文献 | 先完成对应案例的明确筛选确认；离线全文只处理 `include` 记录。 |
| 看不到 Agent 下拉框 | 使用 `opencode web` 打开 Web 版，或在桌面端使用四个项目斜杠命令。 |
| 无法导出证据或写作包 | 核对是否已完成来源项目、Skill 回执和 OpenCode 原生 Allow 确认；不能用后端审批密钥替代。 |
