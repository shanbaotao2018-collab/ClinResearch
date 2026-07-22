#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_URL="${LRA_BACKEND_URL:-http://127.0.0.1:8010}"
COMMAND="${1:-help}"

usage() {
  cat <<'EOF'
Approve a medical research workflow after human review.

Usage:
  bash scripts/opencode/approve-workflow.sh status study <project_id>
  bash scripts/opencode/approve-workflow.sh status evidence <project_id> <workflow_run_id>
  bash scripts/opencode/approve-workflow.sh status writing <draft_id>

  bash scripts/opencode/approve-workflow.sh approve study <project_id>
  bash scripts/opencode/approve-workflow.sh approve evidence <project_id> <workflow_run_id>
  bash scripts/opencode/approve-workflow.sh approve writing <draft_id>

Environment:
  LRA_BACKEND_URL   Backend URL, default http://127.0.0.1:8010
  LRA_APPROVED_BY   Approver name; otherwise the script asks interactively

The approval key is read from the corresponding environment variable when
available, or entered interactively without being displayed:
  LRA_STUDY_DESIGN_APPROVAL_KEY
  LRA_SYSTEMATIC_EVIDENCE_APPROVAL_KEY
  LRA_RESEARCH_WRITING_APPROVAL_KEY

The script never sends an approval request until the operator types APPROVE.
EOF
}

die() {
  echo "错误: $*" >&2
  exit 2
}

require_curl() {
  command -v curl >/dev/null 2>&1 || die "未找到 curl。"
}

print_json() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -m json.tool
  else
    cat
  fi
}

get_target() {
  local target="$1"
  case "$target" in
    study)
      [[ $# -eq 2 ]] || die "study 需要 project_id。"
      echo "/study-design-projects/$2/approval"
      ;;
    evidence)
      [[ $# -eq 3 ]] || die "evidence 需要 project_id 和 workflow_run_id。"
      echo "/projects/$2/systematic-evidence/$3/approval"
      ;;
    writing)
      [[ $# -eq 2 ]] || die "writing 需要 draft_id。"
      echo "/research-writing-drafts/$2/approval"
      ;;
    *)
      die "类型必须是 study、evidence 或 writing。"
      ;;
  esac
}

approval_key() {
  local target="$1"
  local key=""
  case "$target" in
    study) key="${LRA_STUDY_DESIGN_APPROVAL_KEY:-}" ;;
    evidence) key="${LRA_SYSTEMATIC_EVIDENCE_APPROVAL_KEY:-}" ;;
    writing) key="${LRA_RESEARCH_WRITING_APPROVAL_KEY:-}" ;;
  esac
  if [[ -z "$key" ]]; then
    read -r -s -p "请输入 ${target} 审批密钥（输入不会显示）: " key
    echo
  fi
  [[ -n "$key" ]] || die "审批密钥不能为空。"
  printf '%s' "$key"
}

approval_header() {
  case "$1" in
    study) echo "X-Study-Design-Approval-Key" ;;
    evidence) echo "X-Systematic-Evidence-Approval-Key" ;;
    writing) echo "X-Research-Writing-Approval-Key" ;;
  esac
}

status() {
  local target="$1"
  shift
  local path
  path="$(get_target "$target" "$@")"
  require_curl
  curl --fail-with-body --silent --show-error "$BACKEND_URL$path" | print_json
}

approve() {
  local target="$1"
  shift
  local path key header approver decision payload
  path="$(get_target "$target" "$@")"

  echo "将读取以下审批范围："
  status "$target" "$@"
  echo
  echo "请确认上面的完整范围已由当前 OpenCode 操作者审核。"
  read -r -p "确认无误请输入 APPROVE，其他输入取消: " decision
  [[ "$decision" == "APPROVE" ]] || { echo "已取消，未提交审批。"; return 0; }

  approver="${LRA_APPROVED_BY:-}"
  if [[ -z "$approver" ]]; then
    read -r -p "审批人姓名或工号: " approver
  fi
  [[ -n "$approver" ]] || die "审批人不能为空。"

  key="$(approval_key "$target")"
  header="$(approval_header "$target")"
  payload="$(python3 -c 'import json,sys; print(json.dumps({"approved_by": sys.argv[1]}, ensure_ascii=False))' "$approver")"

  echo "正在提交审批..."
  curl --fail-with-body --silent --show-error -X POST \
    "$BACKEND_URL$path" \
    -H "Content-Type: application/json" \
    -H "$header: $key" \
    -d "$payload" | print_json
  echo "审批已提交。"
}

case "$COMMAND" in
  help|-h|--help)
    usage
    ;;
  status)
    [[ $# -ge 3 ]] || { usage >&2; exit 2; }
    status "$2" "${@:3}"
    ;;
  approve)
    [[ $# -ge 3 ]] || { usage >&2; exit 2; }
    approve "$2" "${@:3}"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
