#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/apps/literature-review-agent/backend"
PACKAGE_DIR="$ROOT_DIR/packages/clinresearch-opencode-global"
BACKEND_URL="http://127.0.0.1:8010"
SKIP_DESKTOP_BUILD=false
OPEN_APP=true
SKIP_MODEL_CHECK=false

usage() {
  cat <<'EOF'
Usage: bash scripts/install-fresh-mac.sh [options]

Installs ClinResearch from a fresh source checkout. OpenCode does not need to
be installed separately because its branded source is bundled in this repo.

Options:
  --backend-url URL       Default: http://127.0.0.1:8010
  --skip-desktop-build    Install and verify backend/Agents only (CI use).
  --skip-model-check      Allow installation without a SenseNova API key.
  --no-open               Do not open the desktop app after installation.
  -h, --help              Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-url) BACKEND_URL="${2:-}"; shift 2 ;;
    --skip-desktop-build) SKIP_DESKTOP_BUILD=true; shift ;;
    --skip-model-check) SKIP_MODEL_CHECK=true; shift ;;
    --no-open) OPEN_APP=false; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer currently supports macOS. Windows packaging remains a separate release target." >&2
  exit 1
fi

for command in python3 curl openssl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing prerequisite: $command" >&2
    exit 1
  fi
done

BACKEND_ENDPOINT="$(python3 - "$BACKEND_URL" <<'PY'
import sys
from urllib.parse import urlparse

value = urlparse(sys.argv[1])
if value.scheme != "http" or value.hostname not in {"127.0.0.1", "localhost"}:
    raise SystemExit("--backend-url must be a local HTTP URL such as http://127.0.0.1:8010")
if value.path not in {"", "/"} or value.params or value.query or value.fragment:
    raise SystemExit("--backend-url must not include a path, query, or fragment")
print(value.hostname, value.port or 80)
PY
)"
read -r BACKEND_HOST BACKEND_PORT <<<"$BACKEND_ENDPOINT"

python3 - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit("Python 3.12 or later is required.")
PY

if [[ "$SKIP_DESKTOP_BUILD" != true ]] && ! command -v bun >/dev/null 2>&1; then
  echo "Bun is required to build the bundled desktop client." >&2
  echo "Install it from https://bun.sh/docs/installation, then rerun this command." >&2
  exit 1
fi

if [[ "$SKIP_DESKTOP_BUILD" != true ]]; then
  REQUIRED_BUN_VERSION="1.3.14"
  CURRENT_BUN_VERSION="$(bun --version)"
  if [[ "$(printf '%s\n%s\n' "$REQUIRED_BUN_VERSION" "$CURRENT_BUN_VERSION" | sort -V | head -1)" != "$REQUIRED_BUN_VERSION" ]]; then
    echo "Bun $REQUIRED_BUN_VERSION or later is required; found $CURRENT_BUN_VERSION." >&2
    exit 1
  fi
fi

for required in \
  "$ROOT_DIR/vendor/opencode-bundled/package.json" \
  "$ROOT_DIR/vendor/opencode-bundled/bun.lock" \
  "$ROOT_DIR/vendor/opencode-bundled/packages/desktop/package.json" \
  "$PACKAGE_DIR/manifest.json" \
  "$BACKEND_DIR/pyproject.toml"; do
  if [[ ! -f "$required" ]]; then
    echo "The source checkout is incomplete; missing: $required" >&2
    echo "Clone the complete ClinResearch repository and retry." >&2
    exit 1
  fi
done

MODEL_ENV_FILE="$HOME/.config/opencode/clinresearch.env"
if [[ -z "${SENSENOVA_API_KEY:-}" && -s "$MODEL_ENV_FILE" ]]; then
  SENSENOVA_API_KEY="$(sed -n 's/^SENSENOVA_API_KEY=//p' "$MODEL_ENV_FILE" | head -1)"
  export SENSENOVA_API_KEY
fi
if [[ -z "${SENSENOVA_API_KEY:-}" && ! -s "$MODEL_ENV_FILE" && "$SKIP_MODEL_CHECK" != true ]]; then
  if [[ ! -t 0 ]]; then
    echo "SENSENOVA_API_KEY is required for a non-interactive fresh installation." >&2
    exit 1
  fi
  read -r -s -p "SenseNova API key (input hidden): " SENSENOVA_API_KEY
  echo
  export SENSENOVA_API_KEY
fi

echo "[1/5] Preparing the Python backend environment..."
if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  python3 -m venv "$BACKEND_DIR/.venv"
fi
"$BACKEND_DIR/.venv/bin/python" -m pip install --upgrade pip
"$BACKEND_DIR/.venv/bin/python" -m pip install -e "$BACKEND_DIR"

echo "[2/5] Verifying the bundled Agent and Skill payload..."
python3 "$ROOT_DIR/scripts/opencode/sync-global-package.py"

echo "[3/5] Installing the research capability package..."
install_args=(--backend-url "$BACKEND_URL")
if [[ -f "$HOME/.config/opencode/clinresearch-global-install.json" ]]; then
  install_args+=(--upgrade)
fi
if [[ "$SKIP_MODEL_CHECK" == true ]]; then
  install_args+=(--skip-model-config)
fi
bash "$PACKAGE_DIR/install.sh" "${install_args[@]}"

echo "[4/5] Starting and validating the unified backend..."
bash "$ROOT_DIR/scripts/start-research-backend.sh" \
  --literature-access-mode client_online \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" \
  --daemon

for _ in {1..15}; do
  if curl --fail --silent --max-time 2 "$BACKEND_URL/health" >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error --max-time 3 "$BACKEND_URL/health" >/dev/null

echo "[5/5] Installing the bundled ClinResearch desktop client..."
if [[ "$SKIP_DESKTOP_BUILD" == true ]]; then
  echo "Desktop build skipped by request."
else
  desktop_args=(--install)
  if [[ "$OPEN_APP" != true ]]; then
    desktop_args+=(--no-open)
  fi
  bash "$ROOT_DIR/scripts/release-desktop-mac.sh" "${desktop_args[@]}"
fi

verify_args=(--backend-url "$BACKEND_URL")
if [[ "$SKIP_MODEL_CHECK" == true ]]; then
  verify_args+=(--skip-model-check)
fi
bash "$ROOT_DIR/scripts/verify-installation.sh" "${verify_args[@]}"
echo
echo "ClinResearch fresh installation completed successfully."
if [[ "$SKIP_DESKTOP_BUILD" != true ]]; then
  echo "Application: /Applications/临床科研智能体工作台.app"
fi
echo "Backend: $BACKEND_URL"
