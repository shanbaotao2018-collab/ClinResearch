# 临床科研智能体工作台

临床科研智能体工作台是一套面向医院科研人员的混合式科研 Agent 产品，围绕一个科研问题
串联四个可追溯闭环：研究设计、文献检索与综述、多源证据抽取分析、科研写作。

本仓库是自包含交付仓库，包含：

- `vendor/opencode-bundled/`：基于 OpenCode 二开的完整桌面端源码；
- `packages/clinresearch-opencode-global/`：四个主 Agent、两个子 Agent、30 个精选医学 Skills；
- `apps/literature-review-agent/backend/`：统一 FastAPI、MCP、项目持久化和审计后端；
- 桌面本地 PubMed 检索与开放全文预检连接器；
- macOS 一键安装、构建、验证与卸载脚本。

新电脑不需要预装 OpenCode。当前可验证交付目标为 macOS，要求 Python 3.12+、Bun 1.3.14+
和 Git。Windows 桌面源码具备 Electron 构建基础，但尚未作为本版本的已验证安装包交付。

## 新电脑安装

```bash
git clone https://github.com/shanbaotao2018-collab/ClinResearch.git
cd ClinResearch
bash scripts/install-fresh-mac.sh
```

安装脚本会隐蔽询问 SenseNova API Key，也可提前设置：

```bash
export SENSENOVA_API_KEY="your-key"
bash scripts/install-fresh-mac.sh
```

完整说明见 [新电脑部署指南](docs/fresh-machine-deployment.md)。

## 验证

```bash
bash scripts/verify-installation.sh
bash scripts/start-research-backend.sh --status
```

## 安全边界

- 不提交模型密钥、患者身份信息、运行数据库和 Skill 回执；
- 不生成虚构题录、PMID、DOI、效应量或临床结论；
- 摘要级、全文级、推断性结果必须明确区分；
- 关键筛选、研究设计定稿、系统评价和写作导出保留人工确认与审计。

第三方来源与许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
