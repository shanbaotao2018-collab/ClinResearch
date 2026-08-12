# Literature Review Agent Backend

## Run

```bash
# Default: persistent macOS launchd service. It stays alive after the terminal closes.
bash ../../../scripts/start-research-backend.sh --literature-access-mode client_online

# Status, logs, and debugging options.
bash ../../../scripts/start-research-backend.sh --status
bash ../../../scripts/start-research-backend.sh --foreground --literature-access-mode client_online
bash ../../../scripts/start-research-backend.sh --stop
```

`--literature-access-mode` supports `online`, `client_online`, `offline`, and `auto`:

- `online`: PubMed and Europe PMC live retrieval is enabled.
- `client_online`: the desktop-local `literature_client` MCP retrieves public
  PubMed/Europe PMC data; this backend stores projects and audit records only.
- `offline`: live retrieval is blocked and the workflow uses local citation-file import.
- `auto`: live retrieval is attempted; an unreachable source returns an offline-import instruction.

The MCP endpoint is hosted by this same backend at `/mcp/`, so the access mode is
configured once here. After the backend is running, start the interactive
literature-review Agent:

```bash
bash scripts/opencode/start-literature-review-agent.sh
```
