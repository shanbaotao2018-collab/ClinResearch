#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

BACKEND_URL="${LRA_BACKEND_URL:-http://127.0.0.1:8010}"

if [[ "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/opencode/start-literature-review-agent.sh

Starts interactive OpenCode with the literature-review Agent connected to the
already-running unified backend MCP endpoint. Start the backend first with its
chosen literature-access mode; OpenCode no longer accepts a separate mode.
EOF
  exit 0
fi

if [[ $# -gt 0 ]]; then
  echo "Usage: bash scripts/opencode/start-literature-review-agent.sh" >&2
  exit 2
fi

if ! command -v opencode >/dev/null 2>&1; then
  echo "OpenCode is not installed or is not on PATH." >&2
  exit 1
fi

cd "$ROOT_DIR"
if ! curl --fail --silent --show-error "$BACKEND_URL/health" >/dev/null; then
  echo "Unified backend is unavailable at $BACKEND_URL. Start it first, for example:" >&2
  echo "  bash scripts/start-research-backend.sh --literature-access-mode offline" >&2
  exit 1
fi
exec opencode --agent literature-review
