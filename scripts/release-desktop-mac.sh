#!/usr/bin/env bash
set -euo pipefail

# Build the branded production desktop app deterministically. The local model
# snapshot prevents a transient models.dev certificate/network failure from
# changing the release result.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/vendor/opencode-desktop-source/packages/desktop"
MODELS_SNAPSHOT="$ROOT_DIR/vendor/opencode-desktop-source/packages/opencode/test/tool/fixtures/models-api.json"
SOURCE_APP="$DESKTOP_DIR/dist/mac-arm64/临床科研智能体工作台.app"
TARGET_APP="/Applications/临床科研智能体工作台.app"
BACKEND_HEALTH_URL="http://127.0.0.1:8010/health"
INSTALL=false
OPEN_APP=true

usage() {
  cat <<'EOF'
Usage: bash scripts/release-desktop-mac.sh [--install] [--no-open]

Builds the production macOS desktop application with the ClinResearch name and icon.
  --install  Back up the installed application and replace it with this build.
  --no-open  Do not open the application after a successful installation.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=true ;;
    --no-open) OPEN_APP=false ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ! -f "$MODELS_SNAPSHOT" ]]; then
  echo "Missing local model snapshot: $MODELS_SNAPSHOT" >&2
  exit 1
fi

export OPENCODE_CHANNEL=prod
export MODELS_DEV_API_JSON="$MODELS_SNAPSHOT"

pushd "$DESKTOP_DIR" >/dev/null
bun run build
bun run package:mac
popd >/dev/null

if [[ ! -d "$SOURCE_APP" ]]; then
  echo "Expected production app was not created: $SOURCE_APP" >&2
  exit 1
fi

if ! plutil -p "$SOURCE_APP/Contents/Info.plist" | rg -q '"CFBundleDisplayName" => "临床科研智能体工作台"'; then
  echo "Release validation failed: incorrect display name." >&2
  exit 1
fi

if ! rg -a -q '多源证据抽取分析' "$SOURCE_APP/Contents/Resources/app.asar"; then
  echo "Release validation failed: updated evidence agent name is missing." >&2
  exit 1
fi

EXPECTED_ICON="$DESKTOP_DIR/icons/prod/icon.icns"
if [[ "$(shasum -a 256 "$SOURCE_APP/Contents/Resources/icon.icns" | awk '{print $1}')" != "$(shasum -a 256 "$EXPECTED_ICON" | awk '{print $1}')" ]]; then
  echo "Release validation failed: production icon does not match." >&2
  exit 1
fi

echo "Build validated: $SOURCE_APP"
echo "Release archives:"
find "$DESKTOP_DIR/dist" -maxdepth 1 -type f \
  \( -name 'clinical-research-agent-workbench-*-mac-arm64.dmg' -o -name 'clinical-research-agent-workbench-*-mac-arm64.zip' \) \
  -print | sort

if [[ "$INSTALL" != true ]]; then
  exit 0
fi

osascript -e 'tell application "临床科研智能体工作台" to quit' || true
osascript -e 'tell application "OpenCode Dev" to quit' || true
sleep 2

if [[ -d "$TARGET_APP" ]]; then
  backup="$TARGET_APP.backup-$(date +%Y%m%d-%H%M%S)"
  mv "$TARGET_APP" "$backup"
  echo "Backed up previous app to: $backup"
fi

ditto "$SOURCE_APP" "$TARGET_APP"
echo "Installed: $TARGET_APP"

# Remote MCP tools are discovered when a new desktop session is initialized.
# Start the local backend before opening the app so the first session does not
# begin with only desktop-local tools.
echo "Ensuring ClinResearch backend is healthy before opening the app..."
bash "$ROOT_DIR/scripts/start-research-backend.sh" \
  --literature-access-mode client_online --daemon
for _ in {1..10}; do
  if curl --fail --silent --max-time 2 "$BACKEND_HEALTH_URL" >/dev/null; then
    echo "Backend verified: $BACKEND_HEALTH_URL"
    break
  fi
  sleep 1
done
if ! curl --fail --silent --max-time 2 "$BACKEND_HEALTH_URL" >/dev/null; then
  echo "Installation completed, but the local backend is unavailable: $BACKEND_HEALTH_URL" >&2
  echo "Start it manually with: bash scripts/start-research-backend.sh --literature-access-mode client_online --daemon" >&2
  exit 1
fi

if [[ "$OPEN_APP" == true ]]; then
  open -n "$TARGET_APP"
fi
