# 离线原始证据包规范 V1

## 目标

离线证据包只替代 PubMed、Europe PMC 等外部数据获取渠道。题录导入后，去重、筛选、PRISMA、全文解析、证据抽取、质量评价、Meta 分析和科研写作仍使用与在线模式相同的项目流程。

包内不得放入 AI 生成的筛选结论、效应量、偏倚风险结论或写作草稿。

## 目录

```text
data/offline-evidence-packages/
  hf-transition-care-v1/
    manifest.json
    citations.nbib
    fulltext/
      paper-001.pdf
      paper-002.xml
```

通过 `LRA_OFFLINE_EVIDENCE_PACKAGE_DIR` 配置根目录；默认目录为 `data/offline-evidence-packages`。

## manifest.json

```json
{
  "schema_version": 1,
  "package_id": "hf-transition-care-v1",
  "title": "心衰出院过渡管理离线证据包",
  "source": "offline_pubmed_export",
  "provenance": {
    "databases": [
      {
        "name": "PubMed",
        "searched_at": "2026-08-03",
        "query": "original search query",
        "exported_count": 20
      }
    ]
  },
  "citation_file": {
    "path": "citations.nbib",
    "format": "nbib",
    "sha256": "<file sha256>"
  },
  "documents": [
    {
      "path": "fulltext/paper-001.pdf",
      "content_type": "application/pdf",
      "sha256": "<file sha256>",
      "citation_match": {"doi": "10.xxxx/example"},
      "source_url": "https://publisher.example/article"
    },
    {
      "path": "fulltext/paper-002.html",
      "content_type": "text/html",
      "sha256": "<file sha256>",
      "citation_match": {"external_id": "12345678"}
    }
  ]
}
```

题录文件支持 `RIS`、`NBIB`、`CSV`、`JSON`。每个全文文件必须有 SHA-256 和唯一的 `citation_match`；匹配优先级为 DOI、外部标识、题名。HTML、XML、PDF 内容只会在证据抽取阶段读取，且仅允许已纳入文献入库。

## 运行顺序

1. 文献综述 Agent 调用 `list_offline_evidence_packages`。
2. 研究者确认使用的包后，Agent 调用 `import_offline_evidence_package`。
3. 按正常流程完成去重、标题摘要筛选、人工确认与 PRISMA。
4. 证据抽取 Agent 启动工作流、执行必要 Skills 后，调用 `ingest_offline_package_full_text`；该工具只解析已纳入文献，排除文献不会进入全文入库。
5. 系统校验文件完整性和题录映射，解析原始 PDF/HTML/XML，保存可审计的全文文本。
6. 后续质量评价、Meta、科研写作与在线模式一致。

## 安全与边界

- 服务器不会自动联网补全文；`offline` 模式下在线全文获取工具会被阻止。
- 包内应仅放置开放获取或已获机构授权的全文。
- 原始文件的路径不得越出离线包目录；校验和不一致的包不会导入。
- PDF 解析依赖后端的 `pypdf` 安装；扫描版 PDF 还需要后续接入本地 OCR，当前会明确报告提取文本不足。
