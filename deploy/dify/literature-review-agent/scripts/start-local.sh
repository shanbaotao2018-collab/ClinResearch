#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../../.." && pwd)"
CONFIG_SOURCE="$ROOT_DIR/deploy/dify/literature-review-agent/config/dify.local.env"
BASE_ENV_SOURCE="$ROOT_DIR/vendor/dify/docker/.env.example"
CONFIG_TARGET="$ROOT_DIR/vendor/dify/docker/.env"

if [ ! -f "$CONFIG_SOURCE" ]; then
  printf '[start-local] missing config: %s\n' "$CONFIG_SOURCE" >&2
  exit 1
fi

if [ ! -f "$BASE_ENV_SOURCE" ]; then
  printf '[start-local] missing base env: %s\n' "$BASE_ENV_SOURCE" >&2
  exit 1
fi

BASE_ENV_SOURCE="$BASE_ENV_SOURCE" CONFIG_SOURCE="$CONFIG_SOURCE" CONFIG_TARGET="$CONFIG_TARGET" python3 - <<'PY'
import os
from pathlib import Path

base_path = Path(os.environ["BASE_ENV_SOURCE"])
override_path = Path(os.environ["CONFIG_SOURCE"])
target_path = Path(os.environ["CONFIG_TARGET"])

base_lines = base_path.read_text(encoding="utf-8").splitlines()
override_lines = override_path.read_text(encoding="utf-8").splitlines()

overrides = {}
for line in override_lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    overrides[key] = value

written_keys = set()
result_lines = []
for line in base_lines:
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and "=" in line:
        key, _ = line.split("=", 1)
        if key in overrides:
            result_lines.append(f"{key}={overrides[key]}")
            written_keys.add(key)
            continue
    result_lines.append(line)

for key, value in overrides.items():
    if key not in written_keys:
        result_lines.append(f"{key}={value}")

target_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")
PY

printf '[start-local] rendered %s from .env.example + local overrides\n' "$CONFIG_TARGET"

(
  cd "$ROOT_DIR/vendor/dify/docker"
  docker-compose up -d
)

printf '[start-local] Dify is starting on http://localhost:18080\n'
printf '[start-local] run bootstrap after backend is healthy:\n'
printf '  deploy/dify/literature-review-agent/scripts/bootstrap-dify.sh\n'
