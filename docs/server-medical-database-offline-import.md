# 服务器无法访问医学数据库时的文献导入方案

## 适用场景

服务器可以访问模型服务，但不能直接访问 PubMed、Europe PMC 等医学数据库时，文献综述 Agent 采用“离线题录导入兜底”：

1. 在可访问医学数据库的环境中检索文献。
2. 导出原始题录，并按离线证据包规范保留原始 PDF / HTML / XML 全文和校验和。
3. 将整个离线证据包放入服务器指定目录。
4. 由 OpenCode Agent 发现并导入证据包题录；筛选后再由证据抽取 Agent 解析同包原始全文。
5. 后续继续执行去重、筛选、PRISMA、证据抽取和科研写作流程。

## 配置

后端启动时指定文献访问模式：

```bash
bash scripts/start-research-backend.sh --literature-access-mode offline
```

三种模式如下：

- `online`：允许实时访问 PubMed、Europe PMC；网络错误直接报告。
- `offline`：禁止所有实时医学数据库请求，只允许题录文件导入。
- `auto`：先尝试实时访问；某个数据库不可达时，返回离线题录导入指引，Agent 不应重复请求该来源。

OpenCode 通过后端内置的 `/mcp/` 端点访问同一个服务，因此不再单独设置模式。后端启动成功后再启动 OpenCode：

```bash
bash scripts/opencode/start-literature-review-agent.sh
```

离线题录目录可通过以下配置覆盖：

```bash
export LRA_LITERATURE_IMPORT_DIR="/data/clinresearch/literature-imports"
export LRA_OFFLINE_EVIDENCE_PACKAGE_DIR="/data/clinresearch/offline-evidence-packages"
```

如果不配置，默认使用仓库内：

```text
runtime/literature-imports
runtime/offline-evidence-packages
```

出于安全考虑，文件导入工具只允许读取该目录下的文件。

## OpenCode / MCP 工具

优先使用完整离线证据包：

```text
list_offline_evidence_packages
import_offline_evidence_package
ingest_offline_package_full_text
```

包格式与原始全文解析说明见 [离线原始证据包规范](offline-evidence-package-spec.md)。

新增工具：

```text
import_citations_file_to_project
```

参数：

```json
{
  "project_id": 1,
  "file_path": "heart-failure-discharge-citations.json",
  "source": "offline_pubmed_export",
  "file_format": "json"
}
```

说明：

- `project_id`：本地文献综述项目 ID。
- `file_path`：题录文件路径。可以是导入目录下的相对路径。
- `source`：导入来源标记，例如 `offline_pubmed_export`、`offline_ris_export`。
- `file_format`：可选。为空时按扩展名推断。

## HTTP API

新增接口：

```http
POST /projects/{project_id}/citations/import-file
```

请求示例：

```json
{
  "file_path": "heart-failure-discharge-citations.json",
  "source": "offline_pubmed_export",
  "file_format": "json"
}
```

返回示例：

```json
{
  "project_id": 1,
  "source": "offline_pubmed_export",
  "file_path": "heart-failure-discharge-citations.json",
  "parsed_count": 3,
  "imported_count": 3
}
```

## 推荐操作流程

1. 管理员或科研秘书在可访问数据库的电脑上完成 PubMed / Europe PMC / 知网 / 万方检索。
2. 导出题录文件，优先使用 `RIS` 或 `NBIB`。
3. 上传到服务器的 `LRA_LITERATURE_IMPORT_DIR`。
4. 文献综述 Agent 创建项目、生成检索式，并说明当前采用离线题录来源。
5. 优先调用 `list_offline_evidence_packages` 和 `import_offline_evidence_package` 导入题录；只有题录文件时再调用 `import_citations_file_to_project`。
6. Agent 调用 `deduplicate_project_citations` 去重。
7. 研究者确认纳排标准后，Agent 提交筛选建议并生成 PRISMA 计数。

## 边界

- 离线导入只能证明“题录已导入”，不能证明数据库实时检索已完成。
- 题录文件的真实性、检索日期、数据库来源需要人工或内网文献网关提供。
- Agent 不应伪造 PMID、DOI、检索时间或数据库命中数。
- 如果需要全文抽取，仍需提供开放获取全文、PDF / HTML / XML 原文或人工上传全文摘录。

## 样例文件

本地演示样例：

```text
testdata/offline-literature-import/heart-failure-discharge-citations.json
```
