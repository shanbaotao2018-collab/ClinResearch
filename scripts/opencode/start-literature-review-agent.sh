#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage:
  MODEL_PORT_API_KEY="..." bash scripts/opencode/start-literature-review-agent.sh

Starts interactive OpenCode with the local literature-review agent and MCP tools.
The model key is read only from MODEL_PORT_API_KEY and is never stored by this script.
EOF
  exit 0
fi

if [[ -z "${MODEL_PORT_API_KEY:-}" ]]; then
  echo "MODEL_PORT_API_KEY is required. Set it in your terminal, then run this script again." >&2
  exit 1
fi

if ! command -v opencode >/dev/null 2>&1; then
  echo "OpenCode is not installed or is not on PATH." >&2
  exit 1
fi

cd "$ROOT_DIR"
exec opencode --agent literature-review
