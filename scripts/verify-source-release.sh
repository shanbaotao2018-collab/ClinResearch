#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() {
  echo "Source release check failed: $*" >&2
  exit 1
}

if git ls-files -s | awk '$1 == "160000" { print $4 }' | grep -q .; then
  git ls-files -s | awk '$1 == "160000" { print "- " $4 }' >&2
  fail "Gitlink entries are not allowed; a fresh clone must contain all required source files."
fi

for required in \
  vendor/opencode-bundled/package.json \
  vendor/opencode-bundled/bun.lock \
  vendor/opencode-bundled/LICENSE \
  vendor/opencode-bundled/CLINRESEARCH_UPSTREAM.md \
  vendor/opencode-bundled/packages/opencode/script/build-node.ts \
  vendor/opencode-bundled/packages/desktop/resources/clinresearch-client-retrieval.mjs \
  vendor/opencode-bundled/packages/app/src/assets/help/introducing-tabs.mp4 \
  data/offline-evidence-packages/hf-transition-care-v1/manifest.json \
  packages/clinresearch-opencode-global/manifest.json \
  apps/literature-review-agent/backend/pyproject.toml; do
  [[ -f "$required" ]] || fail "missing required file: $required"
done

bundled_file_count="$(git ls-files vendor/opencode-bundled | wc -l | tr -d ' ')"
if (( bundled_file_count < 6300 )); then
  fail "bundled OpenCode source is incomplete: only $bundled_file_count tracked files"
fi

if git ls-files | grep -E '(^|/)(runtime|tmp|dist|out)/|\.sqlite3?$|\.db$|\.pyc$|__pycache__' >/dev/null; then
  git ls-files | grep -E '(^|/)(runtime|tmp|dist|out)/|\.sqlite3?$|\.db$|\.pyc$|__pycache__' >&2
  fail "runtime or build artifacts are tracked"
fi

python3 scripts/opencode/sync-global-package.py
python3 -m json.tool opencode.json >/dev/null
python3 -m json.tool packages/clinresearch-opencode-global/manifest.json >/dev/null

if rg -n --hidden \
  --glob '!vendor/**' \
  --glob '!testdata/**' \
  --glob '!deliverables/**' \
  --glob '!docs/evidence/**' \
  --glob '!scripts/verify-source-release.sh' \
  'sk-[A-Za-z0-9_-]{20,}' .; then
  fail "a credential-like token is present in tracked product source"
fi

echo "Source release verified: self-contained source, canonical package payload, and repository hygiene checks passed."
