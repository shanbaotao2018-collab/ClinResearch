#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL="http://127.0.0.1:8010"
SKIP_MODEL_CHECK=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-url) BACKEND_URL="${2:-}"; shift 2 ;;
    --skip-model-check) SKIP_MODEL_CHECK=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

CONFIG_DIR="$HOME/.config/opencode"
SKILLS_DIR="$HOME/.agents/skills"

curl --fail --silent --show-error --max-time 3 "$BACKEND_URL/health" >/dev/null
python3 - "$CONFIG_DIR/opencode.json" "$BACKEND_URL" "$SKIP_MODEL_CHECK" <<'PY'
import json
import sys
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
backend = sys.argv[2].rstrip("/")
assert config["mcp"]["literature_review"]["url"] == f"{backend}/mcp/"
for name in ("literature-review", "study-design", "evidence-extraction", "research-writing"):
    assert (Path(sys.argv[1]).parent / "agents" / f"{name}.md").is_file(), name
if sys.argv[3] != "true":
    assert config.get("provider", {}).get("sensenova", {}).get("options", {}).get("apiKey") == "{env:SENSENOVA_API_KEY}"
PY

for skill in clinic-research-design literature-review clinical-study-info-extractor method-writing; do
  test -f "$SKILLS_DIR/$skill/SKILL.md"
done
test -s "$CONFIG_DIR/clinresearch-skill-receipt-key"

if [[ "$SKIP_MODEL_CHECK" == true ]]; then
  echo "Installation verified: backend, four primary Agents, and curated Skills are ready (model check skipped)."
else
  echo "Installation verified: backend, four primary Agents, model provider, and curated Skills are ready."
fi
