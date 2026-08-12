#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/apps/literature-review-agent/backend"
PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
ACCESS_MODE="auto"
HOST="127.0.0.1"
PORT="8010"
RUN_MODE="daemon"
LABEL="com.clinresearch.research-backend"
RUNTIME_DIR="$ROOT_DIR/runtime/research-backend"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/start-research-backend.sh [options]

Options:
  --literature-access-mode online|client_online|offline|auto
      online: allow PubMed and Europe PMC requests.
      client_online: keep project data on this backend; require the desktop-local MCP connector for database requests.
      offline: disable live database requests; use citation-file import only.
      auto: allow live requests and return an offline-import instruction when a source is unreachable.
  --host HOST       Default: 127.0.0.1
  --port PORT       Default: 8010
  --daemon          Start as a persistent macOS launchd service (default).
  --foreground      Run in the current terminal for debugging.
  --status          Show launchd and HTTP health status without starting.
  --stop            Stop the persistent launchd service.
  -h, --help        Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --literature-access-mode) ACCESS_MODE="${2:-}"; shift 2 ;;
    --host) HOST="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --daemon) RUN_MODE="daemon"; shift ;;
    --foreground) RUN_MODE="foreground"; shift ;;
    --status) RUN_MODE="status"; shift ;;
    --stop) RUN_MODE="stop"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$ACCESS_MODE" != "online" && "$ACCESS_MODE" != "client_online" && "$ACCESS_MODE" != "offline" && "$ACCESS_MODE" != "auto" ]]; then
  echo "Invalid --literature-access-mode: $ACCESS_MODE (use online, client_online, offline, or auto)" >&2
  exit 2
fi

health_url="http://${HOST}:${PORT}/health"

show_status() {
  local launch_state="not loaded"
  if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
    launch_state="loaded"
  fi
  printf 'ClinResearch backend launchd status: %s\n' "$launch_state"
  if curl --fail --silent --show-error --max-time 3 "$health_url" >/dev/null; then
    printf 'HTTP health: healthy (%s)\n' "$health_url"
    printf 'Logs: %s\n' "$RUNTIME_DIR"
    return 0
  fi
  printf 'HTTP health: unavailable (%s)\n' "$health_url"
  printf 'Logs: %s\n' "$RUNTIME_DIR"
  return 1
}

if [[ "$RUN_MODE" == "status" ]]; then
  show_status
  exit $?
fi

if [[ "$RUN_MODE" == "stop" ]]; then
  launchctl bootout "gui/$UID/$LABEL" >/dev/null 2>&1 || true
  rm -f "$PLIST_PATH"
  # launchctl returns before uvicorn has necessarily released the socket.
  # Wait briefly so a following start does not mistake the terminating process
  # for a healthy backend and then leave the service stopped.
  for _ in {1..10}; do
    if ! curl --fail --silent --max-time 1 "$health_url" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  echo "ClinResearch backend stopped."
  exit 0
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python virtualenv not found: $PYTHON_BIN" >&2
  exit 1
fi

GLOBAL_RECEIPT_KEY_FILE="$HOME/.config/opencode/clinresearch-skill-receipt-key"
RECEIPT_KEY_FILE="${LRA_SKILL_RECEIPT_KEY_FILE:-$GLOBAL_RECEIPT_KEY_FILE}"
# The desktop OpenCode receipt plugin writes signed journals here. Keep the
# backend on the same directory so workflow gates can verify the receipts.
export LRA_SKILL_RECEIPT_DIR="${LRA_SKILL_RECEIPT_DIR:-$HOME/.config/opencode/clinresearch-skill-receipts}"
if [[ ! -f "$RECEIPT_KEY_FILE" && -z "${LRA_SKILL_RECEIPT_KEY_FILE:-}" ]]; then
  RECEIPT_KEY_FILE="$ROOT_DIR/runtime/.skill-receipt-key"
fi
if [[ -z "${LRA_SKILL_RECEIPT_KEY:-}" && -f "$RECEIPT_KEY_FILE" ]]; then
  export LRA_SKILL_RECEIPT_KEY="$(<"$RECEIPT_KEY_FILE")"
fi
if [[ -z "${LRA_SKILL_RECEIPT_KEY:-}" ]]; then
  mkdir -p "$(dirname "$RECEIPT_KEY_FILE")"
  umask 077
  openssl rand -hex 32 > "$RECEIPT_KEY_FILE"
  export LRA_SKILL_RECEIPT_KEY="$(<"$RECEIPT_KEY_FILE")"
  echo "Generated local Skill receipt key: $RECEIPT_KEY_FILE"
fi

if [[ "$RUN_MODE" == "foreground" ]]; then
  export LRA_LITERATURE_ACCESS_MODE="$ACCESS_MODE"
  cd "$BACKEND_DIR"
  exec "$PYTHON_BIN" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
fi

if curl --fail --silent --max-time 2 "$health_url" >/dev/null; then
  echo "ClinResearch backend is already healthy at $health_url"
  exit 0
fi
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is occupied, but $health_url is not this backend. Stop the conflicting process before retrying." >&2
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
  exit 1
fi

mkdir -p "$RUNTIME_DIR" "$HOME/Library/LaunchAgents"
chmod 700 "$RUNTIME_DIR"

# launchd keeps the MCP/API backend alive after the terminal closes and restarts it after crashes.
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>app.main:app</string>
    <string>--host</string><string>$HOST</string>
    <string>--port</string><string>$PORT</string>
  </array>
  <key>WorkingDirectory</key><string>$BACKEND_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>LRA_LITERATURE_ACCESS_MODE</key><string>$ACCESS_MODE</string>
    <key>LRA_SKILL_RECEIPT_KEY</key><string>$LRA_SKILL_RECEIPT_KEY</string>
    <key>LRA_SKILL_RECEIPT_DIR</key><string>$LRA_SKILL_RECEIPT_DIR</string>
  </dict>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$RUNTIME_DIR/backend.out.log</string>
  <key>StandardErrorPath</key><string>$RUNTIME_DIR/backend.err.log</string>
</dict>
</plist>
EOF
chmod 600 "$PLIST_PATH"
plutil -lint "$PLIST_PATH" >/dev/null

launchctl bootout "gui/$UID/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$UID" "$PLIST_PATH"
launchctl kickstart -k "gui/$UID/$LABEL"

for _ in {1..12}; do
  if curl --fail --silent --max-time 2 "$health_url" >/dev/null; then
    echo "ClinResearch backend is running persistently at $health_url"
    echo "Logs: $RUNTIME_DIR/backend.out.log and $RUNTIME_DIR/backend.err.log"
    exit 0
  fi
  sleep 1
done

echo "Backend did not become healthy. Check: $RUNTIME_DIR/backend.err.log" >&2
exit 1
