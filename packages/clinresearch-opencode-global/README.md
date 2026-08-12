# ClinResearch OpenCode Global Package

## What It Installs

- Four primary Agents: literature review, study design, evidence extraction, and research writing.
- Two supporting subagents: search planning and title/abstract screening.
- Four desktop-friendly slash commands: `/literature-review`, `/study-design`, `/evidence-extraction`, `/research-writing`.
- The curated `medical-research-skills` subset and signed Skill-receipt plugin.
- A remote `literature_review` MCP entry pointing to the supplied ClinResearch backend URL.

The literature-review Agent defaults to `formal_review`: it pages raw PubMed
and Europe PMC records into the project backend, deduplicates the full imported
set, then screens records in bounded batches. Ask for `quick_exploration` only
when a short curated candidate set is intended.

The package never stores model credentials. On a fresh installation it adds the
SenseNova OpenAI-compatible provider using the `SENSENOVA_API_KEY` environment
variable. Existing provider or model settings are preserved. Use
`--skip-model-config` when an organization manages its own model configuration.

## Prerequisites

1. Python `3.10` or later for install scripts.
2. A running ClinResearch unified backend. Its MCP endpoint is `<backend-url>/mcp/`.

The standalone package is also usable with upstream OpenCode 1.17.0 or later.
The complete ClinResearch repository includes and builds its own branded
OpenCode desktop client, so a separate OpenCode installation is not required.

## Install

From the extracted package directory:

```bash
bash install.sh --backend-url http://127.0.0.1:8010
```

If a prior manual or partial installation left Agent or Skill files behind, upgrade safely with:

```bash
bash install.sh --backend-url http://127.0.0.1:8010 --upgrade
```

`--upgrade` moves only conflicting Agent, command, plugin, and Skill files to a timestamped backup directory under `~/.config/opencode/` before installing the new version.

By default, this writes Agents, commands, plugin registration, and MCP settings to `~/.config/opencode/`, and Skills to `~/.agents/skills/`. Existing files are never overwritten. The existing global OpenCode JSON configuration is backed up before it is updated.

For a hospital server, point at the institution backend instead:

```bash
bash install.sh --backend-url http://clinresearch-backend.internal:8010
```

Restart the OpenCode desktop app after installation. In any workspace, type `/literature-review` followed by a research question.

## Validate

```bash
opencode agent list
opencode mcp list
```

Expected MCP endpoint:

```text
literature_review  connected
<backend-url>/mcp/
```

## Build A Release

From the source package directory:

```bash
bash build-release.sh
```

The script creates ZIP, tar.gz, and SHA-256 files in `dist/`.

Verify the generated archive from that directory:

```bash
cd dist
shasum -a 256 -c clinresearch-opencode-global-0.3.23.sha256
```

## Uninstall

```bash
bash uninstall.sh
```

默认卸载会保留本地模型凭证和 Skill 回执密钥，便于安全升级。若确定需要同时清除本地秘密：

```bash
bash uninstall.sh --remove-secrets
```

The uninstaller removes only files whose checksum still matches the installation manifest. Modified files are retained for manual review.

## Security Notes

- Do not place model API keys or approval keys in this package.
- The MCP backend owns online/offline policy, project data, approvals, and audit logs.
- Global installation makes agent definitions reusable; it does not deploy the backend or transfer offline evidence packages.
