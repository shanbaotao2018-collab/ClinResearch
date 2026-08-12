# 全新电脑从零部署

## 交付范围

本仓库已包含二开的 OpenCode 桌面源码，不要求目标电脑预装 OpenCode。默认安装结果包括：

1. 临床科研智能体工作台 macOS 应用；
2. 研究设计、文献检索与综述、多源证据抽取分析、科研写作四个主 Agent；
3. search、screening 两个子 Agent和 30 个精选医学 Skills；
4. 本地 PubMed 检索及开放全文预检连接器；
5. FastAPI/MCP 后端、SQLite 项目存储、审计与 Skill 执行回执；
6. `data/offline-evidence-packages/` 中可复现的离线演示题录包。

## 前置条件

- macOS Apple Silicon 或 Intel；
- Python 3.12 或更高版本；
- Bun 1.3.14 或更高版本；
- Git、curl、OpenSSL；
- 能访问模型接口和首次安装依赖所需的网络。

## 一键安装

```bash
git clone https://github.com/shanbaotao2018-collab/ClinResearch.git
cd ClinResearch
bash scripts/install-fresh-mac.sh
```

如果本机 `8010` 端口已被其他服务占用，可让能力包和后端统一使用另一个本地端口：

```bash
bash scripts/install-fresh-mac.sh --backend-url http://127.0.0.1:18010
```

模型密钥不会写入仓库。安装脚本会隐蔽读取并保存到
`~/.config/opencode/clinresearch.env`，文件权限为 `600`。也可以通过环境变量提供：

```bash
export SENSENOVA_API_KEY="your-key"
bash scripts/install-fresh-mac.sh
```

升级或普通卸载默认保留该凭证文件与 Skill 回执密钥，避免版本更新破坏已有配置；只有显式执行
`bash packages/clinresearch-opencode-global/uninstall.sh --remove-secrets` 才会同时清除它们。

## 安装位置

| 组件 | 位置 |
|---|---|
| 桌面应用 | `/Applications/临床科研智能体工作台.app` |
| Agent 与 OpenCode 配置 | `~/.config/opencode/` |
| Skills | `~/.agents/skills/` |
| 后端 Python 环境 | `apps/literature-review-agent/backend/.venv/` |
| 后端日志 | `runtime/research-backend/` |
| 后端项目数据库 | `apps/literature-review-agent/backend/literature_review_agent.db` |

## 验证与运维

```bash
bash scripts/verify-installation.sh
bash scripts/start-research-backend.sh --status
bash scripts/start-research-backend.sh --stop
bash scripts/start-research-backend.sh --literature-access-mode client_online --daemon
```

若只验证后端和能力包，不构建桌面端：

```bash
bash scripts/install-fresh-mac.sh --skip-desktop-build --no-open
```

## 重新构建桌面端

```bash
bash scripts/release-desktop-mac.sh --install
```

该命令使用 `vendor/opencode-bundled/bun.lock` 恢复依赖，并验证应用名称、Agent 中文名称和
图标哈希。OpenCode 官方源码及 ClinResearch 修改都在仓库内，不再依赖本机的外部 OpenCode
源码目录。

## 已知边界

- 当前经过端到端验证的是 macOS 版本；
- Windows 的 Electron 构建入口已经随 OpenCode 源码纳入，但安装包、签名和 Windows 服务
  管理脚本仍需在 Windows CI/真机上完成验证；
- 首次构建桌面端需要下载 Bun 依赖和 Electron 运行时，后续可使用构建缓存。

## 仓库自动验证（可选）

仓库提供 `docs/ci/clinresearch-ci.yml` 模板。仓库管理员使用具备 GitHub
`workflow` 权限的凭证将它复制到 `.github/workflows/ci.yml` 并提交后，每次推送或提交
Pull Request 会分别验证：

- FastAPI 后端测试、Agent/Skill 契约和可复现能力包；
- macOS 环境下恢复内置 OpenCode 的锁定依赖；
- 桌面端 TypeScript 类型检查和发布契约测试。

因此，内置 OpenCode 源码、四个 Agent、Skills 与后端不再依赖开发机上的历史安装目录。
