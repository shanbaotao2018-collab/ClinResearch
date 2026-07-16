#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../../.." && pwd)"
BASE_URL="${DIFY_BASE_URL:-http://localhost:18080}"
INIT_PASSWORD="${DIFY_INIT_PASSWORD:-dify-init-123456}"
ADMIN_EMAIL="${DIFY_ADMIN_EMAIL:-admin@example.com}"
ADMIN_NAME="${DIFY_ADMIN_NAME:-Local Admin}"
ADMIN_PASSWORD="${DIFY_ADMIN_PASSWORD:-Local123456}"

WORKFLOW_DIR="$ROOT_DIR/deploy/dify/literature-review-agent/workflows"
COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

log() {
  printf '[bootstrap-dify] %s\n' "$1"
}

wait_for_console() {
  local url="$BASE_URL/console/api/init"
  for _ in $(seq 1 90); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  log "Dify console is not ready at $url"
  return 1
}

json_field() {
  local json_payload="$1"
  local field_path="$2"
  python3 - "$json_payload" "$field_path" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
value = payload
for part in sys.argv[2].split("."):
    if not part:
        continue
    value = value[part]
if isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False))
else:
    print(value)
PY
}

post_json() {
  local url="$1"
  local data="$2"
  shift 2
  curl -fsS -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
    -H 'Content-Type: application/json' \
    "$@" \
    -X POST \
    "$url" \
    -d "$data"
}

import_workflow() {
  local yaml_file="$1"
  local csrf_token="$2"
  local import_payload
  local import_response
  local import_id
  local import_status

  import_payload="$(python3 - "$yaml_file" <<'PY'
import json
import pathlib
import sys

content = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
print(json.dumps({
    "mode": "yaml-content",
    "yaml_content": content,
}, ensure_ascii=False))
PY
)"

  import_response="$(post_json \
    "$BASE_URL/console/api/apps/imports" \
    "$import_payload" \
    -H "X-CSRF-Token: $csrf_token"
  )"

  import_status="$(json_field "$import_response" "status")"
  import_id="$(json_field "$import_response" "id")"

  if [ "$import_status" = "pending" ]; then
    log "Import for $(basename "$yaml_file") requires confirmation"
    post_json \
      "$BASE_URL/console/api/apps/imports/$import_id/confirm" \
      '{}' \
      -H "X-CSRF-Token: $csrf_token" >/dev/null
  fi

  log "Imported $(basename "$yaml_file")"
}

wait_for_console

init_status="$(curl -fsS "$BASE_URL/console/api/init")"
if [ "$(json_field "$init_status" "status")" != "finished" ]; then
  log "Validating init password"
  post_json \
    "$BASE_URL/console/api/init" \
    "{\"password\":\"$INIT_PASSWORD\"}" >/dev/null
fi

setup_status="$(curl -fsS "$BASE_URL/console/api/setup")"
if [ "$(json_field "$setup_status" "step")" != "finished" ]; then
  log "Creating local admin account"
  post_json \
    "$BASE_URL/console/api/setup" \
    "$(ADMIN_EMAIL="$ADMIN_EMAIL" ADMIN_NAME="$ADMIN_NAME" ADMIN_PASSWORD="$ADMIN_PASSWORD" python3 - <<'PY'
import json
import os
print(json.dumps({
    "email": os.environ["ADMIN_EMAIL"],
    "name": os.environ["ADMIN_NAME"],
    "password": os.environ["ADMIN_PASSWORD"],
    "language": "zh-Hans",
}, ensure_ascii=False))
PY
)" >/dev/null
fi

log "Logging into Dify console"
post_json \
  "$BASE_URL/console/api/login" \
  "$(ADMIN_EMAIL="$ADMIN_EMAIL" ADMIN_PASSWORD="$ADMIN_PASSWORD" python3 - <<'PY'
import base64
import json
import os
print(json.dumps({
    "email": os.environ["ADMIN_EMAIL"],
    "password": base64.b64encode(os.environ["ADMIN_PASSWORD"].encode("utf-8")).decode("utf-8"),
    "remember_me": True,
}, ensure_ascii=False))
PY
)" >/dev/null

csrf_token="$(awk '$6 == "csrf_token" { token = $7 } END { print token }' "$COOKIE_JAR")"
if [ -z "$csrf_token" ]; then
  log "Failed to extract csrf_token cookie"
  exit 1
fi

post_json \
  "$BASE_URL/console/api/workspaces/current" \
  '{}' \
  -H "X-CSRF-Token: $csrf_token" >/dev/null

import_workflow "$WORKFLOW_DIR/init-and-search.yml" "$csrf_token"
import_workflow "$WORKFLOW_DIR/screening-and-prisma.yml" "$csrf_token"

apps_response="$(curl -fsS -b "$COOKIE_JAR" -H "X-CSRF-Token: $csrf_token" "$BASE_URL/console/api/apps?page=1&limit=20")"
log "Available apps:"
python3 - "$apps_response" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
for item in payload.get("data", []):
    print(f"- {item.get('name')} ({item.get('mode')})")
PY
