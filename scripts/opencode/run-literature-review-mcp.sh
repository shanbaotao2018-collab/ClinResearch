#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/apps/literature-review-agent/backend"
PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python virtualenv not found: $PYTHON_BIN" >&2
  echo "Please create the backend virtualenv and install dependencies first." >&2
  exit 1
fi

cd "$BACKEND_DIR"
exec "$PYTHON_BIN" -m app.mcp_server
