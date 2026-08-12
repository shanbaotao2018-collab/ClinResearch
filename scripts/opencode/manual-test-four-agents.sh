#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="${1:-help}"
REVIEW_PROJECT_ID="${REVIEW_PROJECT_ID:-5}"
RECEIPT_KEY_FILE="${LRA_SKILL_RECEIPT_KEY_FILE:-$ROOT_DIR/runtime/.skill-receipt-key}"

cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
医疗科研四 Agent 手工测试脚本

用法:
  bash scripts/opencode/manual-test-four-agents.sh check
  bash scripts/opencode/manual-test-four-agents.sh study
  bash scripts/opencode/manual-test-four-agents.sh literature
  REVIEW_PROJECT_ID=5 bash scripts/opencode/manual-test-four-agents.sh evidence
  REVIEW_PROJECT_ID=5 bash scripts/opencode/manual-test-four-agents.sh writing

脚本会首次运行时自动生成本地 Skill 回执密钥，并在后续测试中复用：
  $ROOT_DIR/runtime/.skill-receipt-key

说明:
  literature 会创建或推进一个新的文献项目，请从 Agent 输出中记录 project_id。
  evidence 和 writing 默认复用已经完成筛选和证据抽取的项目 #5。
  如测试自己的项目，请通过 REVIEW_PROJECT_ID 传入项目编号。
EOF
}

require_runtime() {
  if ! command -v opencode >/dev/null 2>&1; then
    echo "未找到 opencode，请先安装并确保它在 PATH 中。" >&2
    exit 1
  fi
  if [[ -z "${LRA_SKILL_RECEIPT_KEY:-}" ]]; then
    if [[ ! -s "$RECEIPT_KEY_FILE" ]]; then
      mkdir -p "$(dirname "$RECEIPT_KEY_FILE")"
      (umask 077 && openssl rand -hex 32 > "$RECEIPT_KEY_FILE")
    fi
    export LRA_SKILL_RECEIPT_KEY="$(<"$RECEIPT_KEY_FILE")"
  fi
  if [[ -z "${LRA_SKILL_RECEIPT_KEY:-}" ]]; then
    echo "无法读取本地 Skill 回执密钥: $RECEIPT_KEY_FILE" >&2
    exit 1
  fi
}

run_agent() {
  local agent="$1"
  shift
  echo
  echo "===== 开始测试: ${agent} ====="
  opencode run --agent "$agent" "$*"
  echo "===== 测试结束: ${agent} ====="
}

case "$MODE" in
  help|-h|--help)
    usage
    ;;

  check)
    echo "===== OpenCode Agent 检查 ====="
    expected_agents=(
      "study-design"
      "literature-review"
      "evidence-extraction"
      "research-writing"
      "search"
      "screening"
    )
    for agent in "${expected_agents[@]}"; do
      if [[ -f "$ROOT_DIR/.opencode/agents/$agent.md" ]]; then
        if [[ "$agent" == "search" || "$agent" == "screening" ]]; then
          echo "**${agent}** (subagent)"
        else
          echo "**${agent}** (primary)"
        fi
      else
        echo "[缺失] $agent -> $ROOT_DIR/.opencode/agents/$agent.md"
      fi
    done
    echo
    echo "===== MCP 检查 ====="
    opencode mcp list 2>/dev/null | rg 'literature_review|connected'
    ;;

  study)
    require_runtime
    run_agent "study-design" \
      "请使用 testdata/mvp-four-agent/05-study-design-internal-approval-input.json 的假设性高血压出院随访研究案例，完成临床科研方案设计 MVP。调用规定 Skills 和 MCP 工具，输出 PICO、研究类型、纳排标准、主要结局、样本量假设和随机化方案。不要生成实际受试者分配表，不提供临床决策建议。"
    ;;

  literature)
    require_runtime
    run_agent "literature-review" \
      "请使用 testdata/mvp-four-agent/02-literature-review-input.json 的历史性公开文献案例，创建一个新的文献项目。真实调用 PubMed 和 Europe PMC，生成检索式，导入指定的两篇 COVID-19 羟氯喹 RCT，执行去重、标题摘要筛选、PRISMA 计数并导出项目包。输出新建 project_id。这个案例只用于公开文献方法学测试，不构成临床建议。"
    ;;

  evidence)
    require_runtime
    run_agent "evidence-extraction" \
      "请对已经完成筛选的 review 项目 #${REVIEW_PROJECT_ID} 执行 testdata/mvp-four-agent/03-evidence-extraction-input.json 的完整证据抽取案例。对纳入研究完成摘要级证据、撤稿核查、受控公开全文获取、基线和二分类结局抽取、RoB 2、RR 随机效应 Meta 和森林图。完成后进入系统评价内部人工确认流程，不要自行确认、导出或给出临床用药建议。"
    ;;

  writing)
    require_runtime
    run_agent "research-writing" \
      "请使用 review 项目 #${REVIEW_PROJECT_ID} 中已保存的证据，执行 testdata/mvp-four-agent/04-research-writing-input.json 的 discussion 写作案例。先读取研究写作来源，只使用已保存事实；调用 biomed-outline-generator、method-writing、discussion-section-architect，保存版本化草稿并进入科研写作内部人工确认流程。不得编造引用、效应量或临床建议。"
    ;;

  *)
    echo "未知测试模式: $MODE" >&2
    usage >&2
    exit 2
    ;;
esac
