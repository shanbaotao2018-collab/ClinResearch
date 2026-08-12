# 发布与仓库整理规范

## 发布桌面端

不要直接执行 `bun run package:mac`。该命令只负责封装，可能使用旧的前端构建结果或默认 `dev` 图标。

统一使用：

```bash
bash scripts/release-desktop-mac.sh --install
```

该脚本固定执行以下步骤：

1. 设定 `OPENCODE_CHANNEL=prod`，使用定制应用名、图标和 `com.clinresearch.workbench` 数据目录。
2. 使用仓库内的模型清单快照，避免构建时依赖 `models.dev` 的网络和证书状态。
3. 先执行桌面前端构建，再执行 macOS 打包。
4. 校验产物的应用名、定制图标和“多源证据抽取分析”前端文案。
5. 使用 `--install` 时备份旧应用、替换 `/Applications/临床科研智能体工作台.app` 并启动新版本。

发布后的唯一演示入口是：

```text
/Applications/临床科研智能体工作台.app
```

不要同时打开 `OpenCode Dev.app`，否则可能看到不同数据目录或旧界面。

## 版本控制边界

应提交：

- `.opencode/agents/`、`.opencode/commands/`、`.opencode/plugins/` 中的 Agent 与编排定义。
- 后端 `app/`、测试、脚本和文档。
- `packages/clinresearch-opencode-global/` 中的安装包源文件，不含 `dist/` 档案。
- `vendor/opencode-bundled/` 中完整、可构建的 OpenCode 二开源码及上游版本记录。
- `LICENSES/` 和 `THIRD_PARTY_NOTICES.md` 中的第三方许可与来源说明。

不应提交：

- `.runtime/`、`.tmp/`、日志、Python 缓存和桌面端 `dist/`、`out/`。
- 本地 SQLite 数据库及其 WAL/JOURNAL 文件；它们是运行状态，不是源代码。
- 临时前端 bundle，例如 `new-session-*.js`。

## 提交前检查

```bash
python3 scripts/opencode/sync-global-package.py
bash scripts/verify-source-release.sh
git status --short
git diff --check
```

检查时应确认：没有 Git 子模块悬空引用，没有运行日志、数据库、构建文件或本机测试输出混入；
能力包与项目内 Agent/Skill 单一来源一致；桌面源码可从仓库内独立构建；Agent 文件的重命名以
“删除旧名 + 新增新名”成组提交；桌面端源码改动与发布脚本改动一同提交。
