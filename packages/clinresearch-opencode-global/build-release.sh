#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${1:-$ROOT_DIR/dist}"

exec python3 "$ROOT_DIR/scripts/build_release.py" --output-dir "$OUTPUT_DIR"
