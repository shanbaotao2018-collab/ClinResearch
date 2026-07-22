# 医疗科研 Agent 建设目标

## 1. 建设范围

本项目只建设能够由 `medical-research-skills` 现有能力真实支撑的医疗科研 Agent。目标是把成熟的科研方法类 Skills、可审计的 MCP 工具和项目记录组合为“小切口、可闭环、可复用”的科研工作台能力。

本项目不以通用大模型提示词替代专业方法，也不为了覆盖更多方向而承诺当前 Skill 库不具备的能力。

### 不纳入当前范围

- EMR 病历数据智能体：现有 Skill 库不包含医院 EMR/FHIR 对接、中文病历 NLP、脱敏、ICD 编码、病例队列筛选和科研数据集导出能力。
- 医学统计绘图智能体：现有 Skill 库仅覆盖基础样本量估算，不覆盖 Cox、LASSO、PSM、ROC、复杂生存分析、期刊级绘图等完整统计分析能力。
- 临床诊断、治疗建议和最终临床决策。

## 2. 对外 Agent 目标

### 2.1 临床科研选题与研究设计 Agent

**解决的问题：** 将一个临床科研想法转化为可供科研人员和专家审阅的研究设计初稿。

**主要闭环：** 研究目标澄清 -> PICO -> 研究类型与报告规范 -> 纳入排除标准 -> 结局、创新性与可行性 -> 方案大纲与方法初稿 -> 基础样本量 -> RCT 随机化方案 -> 人工审批 -> 导出。

**复用 Skills：**

- `phi-prompt-guard`
- `clinic-research-design`
- `inclusion-criteria-gen`
- `research-proposal-generator`
- `biomed-outline-generator`
- `method-writing`
- `sample-size-basic`
- `randomization-gen`

**当前状态：** 主闭环已完成。已具备项目记录、Skill 执行回执、样本量限制校验、人工审批和受控随机表生成机制。

### 2.2 文献检索与综述 Agent

**解决的问题：** 将研究问题转化为可复现的检索策略，检索中外医学数据库，形成可追溯的文献综述基础工作流。

**主要闭环：** 问题澄清 -> PICO -> 检索概念与布尔检索式 -> PubMed/Europe PMC 检索 -> 导入 -> 去重 -> 初筛建议 -> PRISMA 计数 -> 导出 -> 综述大纲。

**复用 Skills：**

- `pubmed-search-specialist`
- `pubmed-database`
- `reference-search`
- `literature-review`
- `systematic-review`
- `citation-chasing-mapping`

**当前状态：** 基础闭环已完成，使用真实 PubMed 和 Europe PMC 检索接口。检索策略和初筛仍需研究者确认后才能作为正式研究决策。

### 2.3 文献筛选与证据提取 Agent

**解决的问题：** 将候选文献转化为可审阅的纳排建议、研究特征与证据表，降低人工阅读和整理成本。

**主要闭环：** 导入候选文献 -> 标题/摘要初筛建议 -> 人工确认 -> 研究设计、样本、干预与结局字段提取 -> 方法学信息提取 -> 撤稿风险核查 -> 导出证据表。

**复用 Skills：**

- `systematic-review-screener`
- `literature-filtering`
- `clinical-study-info-extractor`
- `methodology-extractor`
- `retraction-watcher`

**当前状态：** 主闭环已完成。已具备标题/摘要初筛、结构化研究信息提取、PubMed 公告类型安全核查、证据表导出、Skill 回执与人工复核标记；第二阶段已支持研究者提供或开放获取的全文文本/PDF 解析结果入库、基线与二分类结局数据、RoB 2/NOS/QUADAS-2 结构化初评，以及二分类 RR/OR 的固定或 DerSimonian-Laird 随机效应 Meta 分析和 SVG 森林图。全文受限于合规来源，所有偏倚风险与合并结果仍必须人工复核。

### 2.4 科研写作与方案成稿 Agent

**解决的问题：** 基于已确认的研究设计或证据材料，生成结构化、可继续修改的科研写作初稿，而非替代专家作最终学术判断。

**主要闭环：** 接收已确认的研究问题/设计/证据 -> 生成写作大纲 -> 生成方法、讨论和研究方案草稿 -> 人工审阅与修改 -> 导出。

**复用 Skills：**

- `biomed-outline-generator`
- `method-writing`
- `discussion-section-architect`
- `research-proposal-generator`

**当前状态：** 主闭环已完成。已独立封装为对外 Agent，支持 `protocol`、`proposal`、`methods` 和 `discussion` 四类文稿；具备来源清单、版本化草稿、Skill 回执、外部人工审批和导出机制。

## 3. 内部编排原则

对外呈现四个业务 Agent；对内允许使用专业子 Agent 和 Skills，不将内部组件单独包装为产品。

```text
科研工作台主入口
  ├─ 临床科研选题与研究设计 Agent
  ├─ 文献检索与综述 Agent
  │    ├─ 检索策略子 Agent
  │    └─ 文献初筛子 Agent
  ├─ 文献筛选与证据提取 Agent
  └─ 科研写作与方案成稿 Agent
```

- `Skill` 负责提供专业方法、输入要求、流程规则和输出规范。
- `MCP Tool` 负责真实检索、计算、项目记录、导出与受控操作。
- `Agent` 负责编排多个 Skills 与 MCP Tools，管理状态、分支、人工确认点和最终结构化交付。
- 所有高风险或需要专业判断的结果必须标明“草稿/建议”，并保留人工确认点。

## 4. 当前开发优先级

1. 为四个 Agent 提供科研小白引导式入口：使用自然语言描述课题，逐步解释术语和需要用户确认的决策。
2. 在不扩大当前 Skill 能力边界的前提下，完善真实案例、运行回执、人工审批和演示材料。
3. 在用户提供或合规接入全文的前提下，补充全文结构化提取、偏倚风险评价和更丰富的引文安全数据源。

## 5. 对外表述

本项目建设的是基于 `medical-research-skills` 的医疗科研智能体工作台，聚焦临床研究设计、文献检索综述、证据筛选提取和科研写作成稿四个可复用闭环。系统不替代临床诊疗、统计专家、伦理审查或研究者的最终学术判断；其价值在于将科研方法规范、工具调用、过程留痕与人工确认组织为可执行流程。
