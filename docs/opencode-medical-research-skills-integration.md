# OpenCode + medical-research-skills 一期集成说明

更新日期：2026-07-14

## 1. 目标

在当前仓库里启动一条新的科研智能体路线：

- `medical-research-skills` 作为上游科研技能库
- `OpenCode` 作为 agent 宿主和多 agent 编排层
- 当前一期只落地一个主能力：
  - `文献综述智能体`

这条路线不会替代现有 Dify MVP，而是并行推进：

- 现有 Dify MVP：固定流程型演示
- 新的 OpenCode 集成：多 agent、skills、MCP 的科研工作台骨架

## 2. 已经落地到仓库的文件

- 根目录 `AGENTS.md`
  - 项目级 OpenCode 规则文件
- `.opencode/agents/literature-review.md`
  - 主 agent
- `.opencode/agents/search-agent.md`
  - 检索策略和数据库子 agent
- `.opencode/agents/screening-agent.md`
  - 初筛建议子 agent
- `.agents/skills/README.md`
  - 项目级 skills 目录说明
- `scripts/opencode/sync-medical-research-skills.sh`
  - 从上游技能库同步一期精选 skills
- `vendor/medical-research-skills/`
  - 本地上游技能库快照

## 3. 当前架构

当前 OpenCode 路线推荐理解成 5 层：

1. `OpenCode`
   - 提供主 agent、subagent、skills、rules、task、question
2. `medical-research-skills`
   - 提供科研方法 skill
3. `Project AGENTS.md + .opencode/agents`
   - 提供本项目的流程、边界、结构化输出和任务路由
4. `项目级 .agents/skills`
   - 只保留当前一期要用的 skill 子集
5. `MCP / tools`
   - 现在已经补上第一批 PubMed、Europe PMC、元数据拉取、项目导出工具

## 4. 一期主 agent 定位

一期只做：

- `literature-review`

职责：

- 澄清研究问题
- 拆 PICO
- 调度检索策略与数据库建议
- 调度标题摘要初筛建议
- 汇总成结构化文献综述输出

不负责：

- 临床诊疗建议
- 最终纳排标准拍板
- 最终医学结论确认

当前它的定位已经从“通用科研对话 agent”收紧为：

- 固定结构文献综述流程器
- 本地项目状态推进器
- 最终结果结构化汇总器

## 5. 一期精选 skills

当前同步脚本会把下面这些 skill 从上游仓库复制到项目级 `.agents/skills/`：

- `pubmed-search-specialist`
- `pubmed-database`
- `reference-search`
- `literature-filtering`
- `systematic-review-screener`
- `clinical-study-info-extractor`
- `methodology-extractor`
- `citation-chasing-mapping`
- `retraction-watcher`
- `literature-review`
- `systematic-review`
- `biomed-outline-generator`
- `method-writing`
- `discussion-section-architect`

这批 skill 足够覆盖一期文献综述智能体的核心路径：

- 检索
- 初筛
- 结构化信息抽取
- 综述框架
- 写作骨架

## 6. 如何同步 skills

在仓库根目录执行：

```bash
bash scripts/opencode/sync-medical-research-skills.sh
```

执行后会把精选 skill 复制到：

```text
.agents/skills/
```

这是 OpenCode 支持的项目级 skill 发现路径之一。

## 7. OpenCode 官方兼容点

这套接法依赖这些官方能力：

- `AGENTS.md` 项目规则
- `.opencode/agents/*.md` 自定义 agent
- `.agents/skills/*/SKILL.md` 项目级 skills
- `permission.task` 控制主 agent 可调用哪些 subagent
- `question` 工具做人机确认
- `todowrite` 做复杂任务分步推进
- `mcp` 配置外部工具

## 8. 已经落地的 MCP tools

目前这版 OpenCode 路线除了 skills 之外，已经补上了一层本地 MCP server：

- `apps/literature-review-agent/backend/app/mcp_server.py`
- `apps/literature-review-agent/backend/app/services/project_workflow.py`
- `scripts/opencode/run-literature-review-mcp.sh`
- `opencode.json` 里的本地 `literature_review` MCP 配置

当前已经暴露 9 个工具。

### 8.1 工作流推进类工具

1. `create_review_project`
2. `generate_project_search_strategy`
3. `import_citations_to_project`
4. `deduplicate_project_citations`
5. `submit_screening_decisions`

### 8.2 检索与导出类工具

1. `search_pubmed`
2. `search_europepmc`
3. `fetch_paper_metadata`
4. `export_review_bundle`

这意味着现在不是只有“会思考的 agent”，而是已经有“能动手执行”的工具层。

## 9. 这 4 个工具分别做什么

### 9.1 `search_pubmed`

输入：

- `query`
- `limit`

输出：

- 标题
- PMID
- 摘要
- 年份
- DOI
- 作者
- 期刊

说明：

- 通过 PubMed ESearch + EFetch 拉真实数据
- 已在本地用真实查询验证过可返回结果

### 9.2 `search_europepmc`

输入：

- `query`
- `limit`

输出：

- Europe PMC 文献元数据

说明：

- 适合作为 PubMed 之外的补充来源
- 返回标题、摘要、作者、年份、DOI、PMCID、期刊等字段

### 9.3 `fetch_paper_metadata`

输入：

- PMID / DOI / Europe PMC id

输出：

- 结构化文献元数据

说明：

- 支持 `source=auto | pubmed | europe_pmc`
- 目前优先适配 PMID、DOI、外部 id 三类输入

### 9.4 `export_review_bundle`

输入：

- 当前综述结构化对象

输出：

- Markdown / JSON

当前实际已实现：

- `markdown`
- `json`

说明：

- 直接复用本地 SQLite 项目数据
- 会导出项目基本信息、PICO、检索策略、PRISMA 计数、候选文献、审计日志

## 10. 新补上的 5 个工作流工具分别做什么

### 10.1 `create_review_project`

作用：

- 为一个文献综述课题创建本地项目
- 保存研究问题、PICO、纳排标准草稿

输出：

- `project.id`
- `project.status`
- 项目基本字段

### 10.2 `generate_project_search_strategy`

作用：

- 基于项目中的研究问题与 PICO 字段生成 PubMed 检索式

输出：

- `query_text`
- `source`
- `version_number`
- `rationale`

### 10.3 `import_citations_to_project`

作用：

- 把检索得到的文献元数据写入项目文献池

输出：

- `imported_count`

### 10.4 `deduplicate_project_citations`

作用：

- 基于 DOI / external_id / title 对项目内文献去重

输出：

- `removed_count`

### 10.5 `submit_screening_decisions`

作用：

- 批量提交题录初筛决策
- 刷新 PRISMA 统计
- 推进项目筛选状态

输出：

- `submitted_count`
- `project_status`
- `identified_count`
- `deduplicated_count`
- `screened_count`
- `included_count`
- `excluded_count`

## 11. 一期推荐演示路径

建议一期演示这样跑：

1. 用户输入研究问题
2. `literature-review` 主 agent 调 `create_review_project`
3. 主 agent 拆 PICO 并回填项目字段
4. 主 agent 调 `generate_project_search_strategy`
5. 主 agent 调 `search-agent`
6. `search-agent` 产出检索式优化建议和数据库建议
7. 主 agent 调 `search_pubmed` / `search_europepmc`
8. 主 agent 调 `import_citations_to_project`
9. 主 agent 调 `deduplicate_project_citations`
10. 主 agent 调 `screening-agent`
11. `screening-agent` 对候选文献给出纳入/排除建议
12. 主 agent 调 `submit_screening_decisions`
13. 主 agent 调 `export_review_bundle`
14. 主 agent 汇总输出：
   - Research Question
   - PICO
   - Search Strategy Draft
   - Recommended Databases
   - Screening Suggestions
   - Evidence Summary
   - Key Controversies
   - Review Outline

## 12. 主 agent 的固定执行链已经如何落地

当前 `.opencode/agents/literature-review.md` 已经明确要求主 agent：

1. 先澄清问题
2. 再拆 PICO
3. 创建本地项目
4. 生成检索式
5. 调 `search-agent` 做检索优化
6. 调检索 MCP tools 跑真实检索
7. 入库、去重
8. 调 `screening-agent` 给出题录筛选建议
9. 提交筛选决策
10. 导出项目 bundle
11. 最后再做结构化总结

这意味着现在它不是“想到哪说到哪”，而是更接近一个固定 SOP 的执行器。

## 13. 固定输出模板

项目里已经新增：

- `docs/templates/literature-review-output-template.md`

它定义了主 agent 交付时的标准章节：

- Workflow Status
- Research Question
- PICO
- Search Strategy Draft
- Recommended Databases
- Retrieval Summary
- Screening Suggestions
- PRISMA Snapshot
- Evidence Summary
- Key Controversies
- Review Outline
- Next Steps

项目级 `AGENTS.md` 也已经要求优先遵守这份模板。

## 14. 现阶段怎么用

### 14.1 准备阶段

1. 确保仓库里已有：
   - `vendor/medical-research-skills/`
2. 运行同步脚本：

```bash
bash scripts/opencode/sync-medical-research-skills.sh
```

3. 配置一期默认模型。

项目根目录已经新增：

- `opencode.json`
  - 默认 provider: `model-port`
  - 默认模型: `model-port/gpt-5.4`
- `scripts/opencode/model-port.env.example`
  - 环境变量模板

推荐做法是把真实 API key 放进环境变量，而不是写进仓库文件：

```bash
cp scripts/opencode/model-port.env.example /tmp/model-port.env
# 编辑 /tmp/model-port.env，把真实 key 填进去
source /tmp/model-port.env
```

或者直接在当前 shell 中设置：

```bash
export MODEL_PORT_API_KEY="your-real-model-port-key"
```

模型服务可能出现短暂的 `Service Unavailable`。为避免交互界面长时间无反馈，项目将单次请求与流首包等待上限设为 90 秒；超时后请重新执行当前任务，而不是继续等待。可在运行前检查配置：

```bash
node scripts/opencode/test-model-port-config.mjs
```

该检查不会读取或输出 API key。

4. 安装后端依赖：

```bash
cd apps/literature-review-agent/backend
./.venv/bin/pip install -e .
cd /Users/shanbaotao/Documents/agent\ 2
```

### 14.2 OpenCode 启动阶段

从仓库根目录启动 OpenCode，让它自动发现：

- 根目录 `AGENTS.md`
- `.opencode/agents/*.md`
- `.agents/skills/*/SKILL.md`
- `opencode.json`

其中 `opencode.json` 里已经配置了本地 MCP：

- server name: `literature_review`
- launch command: `bash scripts/opencode/run-literature-review-mcp.sh`

### 14.3 使用方式

你可以直接切到主 agent：

- `literature-review`

例如：

```bash
opencode --agent literature-review
```

或者在主会话中让它自动路由到：

- `search-agent`
- `screening-agent`

如果 OpenCode 正常加载 MCP，你的 agent 就能直接调用这些工具：

- `literature_review_search_pubmed`
- `literature_review_search_europepmc`
- `literature_review_fetch_paper_metadata`
- `literature_review_export_review_bundle`

如果你想直接跑一句命令式验证，也可以：

```bash
opencode run --agent literature-review "帮我为 2 型糖尿病与 SGLT2 抑制剂心衰住院风险做一个文献综述检索计划"
```

### 11.4 当前模型配置说明

当前项目默认采用 OpenAI-compatible custom provider 配置：

- provider id: `model-port`
- base URL: `https://api.model-port.xyz/v1`
- model: `gpt-5.4`

这套配置对应 OpenCode 官方的 custom provider 方式：

- 使用 `@ai-sdk/openai-compatible`
- 通过 `options.baseURL` 指向外部兼容接口
- 通过 `options.apiKey` 读取环境变量

这样做的好处是：

1. 不把密钥写进仓库
2. 后面换模型或换代理地址时只需要改配置
3. 三个 agent 会自动继承默认模型，无需逐个重复配置

## 15. 当前本地验证结果

已经完成的验证：

1. 后端单测通过
   - `10 passed`
2. MCP 工具注册成功
   - `create_review_project`
   - `generate_project_search_strategy`
   - `import_citations_to_project`
   - `deduplicate_project_citations`
   - `submit_screening_decisions`
   - `search_pubmed`
   - `search_europepmc`
   - `fetch_paper_metadata`
   - `export_review_bundle`
3. 真实 PubMed 查询通过
   - 查询词：`SGLT2 inhibitors heart failure type 2 diabetes`
4. 本地 MCP 工作流基础闭环通过
   - 创建项目
   - 生成检索式
   - 导入文献
   - 去重
   - 提交筛选决策
5. 本地项目导出通过
   - 已生成 Markdown 结构化综述草稿
6. 主 agent / subagent 规则已升级为固定流程契约
7. 固定输出模板已落地

## 16. 距离最小工作台还差什么

加完这 5 个工具之后，最短闭环已经具备，但还没有完全达到“固定结构科研工作台”的最终感受。

还差的核心点：

1. 还没有跑出 2 到 3 个正式的真实医学演示案例包
2. 检索结果到筛选输入之间还缺自动字段映射与候选集选择逻辑
3. `Evidence Summary / Key Controversies / Review Outline` 还没有建立稳定的证据抽取流水线
4. 还没有前端工作台式的人机确认界面

## 17. 下一步最值得做的事

按优先级：

1. 用真实 `MODEL_PORT_API_KEY` 启动 OpenCode，确认 `gpt-5.4` 可选
2. 用真实课题跑 2 到 3 条文献综述样例
3. 增加 PDF 全文解析和结构化信息抽取
4. 做候选文献自动映射与筛选前整理
5. 根据样例再收缩或扩展 skill 白名单

## 18. 当前定位

这套集成当前最合适的定位是：

`OpenCode 驱动的医学文献综述智能体一期骨架`

它已经具备：

- 主 agent
- 子 agent
- skill 子集
- 项目规则
- 路由边界
- 默认外部模型配置
- 本地 MCP 工具层
- 可复用的项目导出能力
- 项目状态推进工具层

但还不算完整科研平台，后续还需要：

- 项目状态持久化
- 更强结构化导出
- 前端工作台
