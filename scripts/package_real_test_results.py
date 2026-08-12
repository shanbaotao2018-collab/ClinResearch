"""Create a safe, indexed evidence package for the local V0.1 self-test record."""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from datetime import date
from pathlib import Path


ROOT = Path("/Users/shanbaotao/Documents/agent 2")
DELIVERABLES = ROOT / "deliverables"
PACKAGE = DELIVERABLES / "佐证材料4-本地真实测试结果包-2026-07-22"
ARCHIVE = DELIVERABLES / "佐证材料4-本地真实测试结果包-2026-07-22.zip"


def write_text(relative_path: str, text: str) -> None:
    destination = PACKAGE / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def copy_file(source_relative: str, destination_relative: str) -> None:
    source = ROOT / source_relative
    destination = PACKAGE / destination_relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def run_and_log(command: list[str], cwd: Path, destination: str) -> tuple[int, str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    log = "$ " + " ".join(command) + "\n\n" + result.stdout + result.stderr
    log += f"\n[exit_code={result.returncode}]\n"
    write_text(destination, log)
    return result.returncode, log


def receipt_summary(source_name: str, label: str) -> dict:
    source = ROOT / "runtime/skill-receipts" / source_name
    data = json.loads(source.read_text(encoding="utf-8"))
    receipts = data.get("receipts", [])
    skills = sorted({item["skill_name"] for item in receipts})
    return {
        "label": label,
        "workflow_run_id": data.get("workflow_run_id"),
        "subject": {
            "study_design_project_id": data.get("study_design_project_id"),
            "workflow_type": data.get("workflow_type"),
            "subject_type": data.get("subject_type"),
            "subject_id": data.get("subject_id"),
        },
        "receipt_entry_count": len(receipts),
        "distinct_skill_count": len(skills),
        "distinct_skill_names": skills,
        "redaction_note": "已移除 receipt_id、OpenCode session id、HMAC signature 和执行时间戳。",
    }


def main() -> None:
    PACKAGE.mkdir(parents=True, exist_ok=True)
    (PACKAGE / "10-可复现测试输入").mkdir(parents=True, exist_ok=True)
    legacy_manual_plan = PACKAGE / "11-四Agent原生确认手工测试方案.md"
    if legacy_manual_plan.exists():
        legacy_manual_plan.unlink()

    pytest_code, _ = run_and_log(
        [".venv/bin/python", "-m", "pytest", "-q"],
        ROOT / "apps/literature-review-agent/backend",
        "01-后端自动化测试结果-2026-07-22.txt",
    )
    contract_code, _ = run_and_log(
        ["node", "scripts/opencode/test-agent-skill-contract.mjs"],
        ROOT,
        "02-Agent-Skill合同检查结果-2026-07-22.txt",
    )
    frontend_code, _ = run_and_log(
        ["npm", "run", "build"],
        ROOT / "apps/research-workbench-frontend",
        "03-BS工作台生产构建结果-2026-07-22.txt",
    )
    if any(code != 0 for code in (pytest_code, contract_code, frontend_code)):
        raise SystemExit("One or more current verification commands failed; package was not finalized.")

    for source, destination in [
        ("docs/three-real-agent-runs-2026-07-16.md", "04-研究设计Agent真实运行记录.md"),
        ("docs/case-ai-dr-diagnostic-accuracy-mvp-output.md", "05-文献检索综述Agent真实运行记录.md"),
        ("docs/mvp-evidence-extraction-acceptance-2026-07-20.md", "06-证据抽取系统评价Agent验收记录.md"),
        ("docs/two-research-writing-agent-runs-2026-07-16.md", "07-科研写作Agent真实运行记录.md"),
        ("testdata/mvp-four-agent/README.md", "10-可复现测试输入/README.md"),
        ("testdata/mvp-four-agent/01-study-design-input.json", "10-可复现测试输入/01-study-design-input.json"),
        ("testdata/mvp-four-agent/02-literature-review-input.json", "10-可复现测试输入/02-literature-review-input.json"),
        ("testdata/mvp-four-agent/03-evidence-extraction-input.json", "10-可复现测试输入/03-evidence-extraction-input.json"),
        ("testdata/mvp-four-agent/04-research-writing-input.json", "10-可复现测试输入/04-research-writing-input.json"),
        ("testdata/mvp-four-agent/05-study-design-internal-approval-input.json", "10-可复现测试输入/05-study-design-internal-approval-input.json"),
        ("deliverables/佐证材料4-临研智策V0.1本地真实案例自测记录.docx", "佐证材料4-临研智策V0.1本地真实案例自测记录.docx"),
    ]:
        copy_file(source, destination)

    write_text(
        "11-四Agent原生确认手工测试步骤摘要-脱敏.md",
        """# 四 Agent 原生确认手工测试步骤摘要（脱敏）

完整开发版手工测试方案位于本地 `docs/manual-test-plan-native-approval.md`，不随结果包发送，因为其中包含本机演示环境变量示例。本摘要保留可复现流程，不包含任何密钥、审批摘要或实际随机分配数据。

1. 由授权操作者在本地启动后端并配置运行环境；审批密钥只存在于本地进程环境。
2. 在仓库根目录启动 OpenCode，运行 `bash scripts/opencode/manual-test-four-agents.sh check`，确认 4 个主 Agent、2 个子 Agent 与 MCP 连接可见。
3. 使用 `10-可复现测试输入/05-study-design-internal-approval-input.json` 运行研究设计 Agent；在 OpenCode 原生 Allow/Deny 中分别验证拒绝与允许。拒绝后不得生成随机化表或导出；允许后只导出脱敏方案包，实际分配序列仍保持受保护且对 Agent 不可见。
4. 使用 `10-可复现测试输入/02-literature-review-input.json` 运行文献检索综述 Agent，核验 PubMed/Europe PMC 检索、项目、题录、去重、筛选与 PRISMA 记录。
5. 对已完成筛选的项目运行证据抽取 Agent，核验公开全文来源、结构化字段、RoB 2、二分类 Meta 和系统评价 Allow/Deny 门禁。
6. 使用已保存研究设计或证据来源运行科研写作 Agent，核验 source_manifest、limitations、unresolved_items、版本化草稿和写作导出门禁。

所有医学结果须由研究者、统计师或相应专家复核；本步骤仅验证工具链行为。
""",
    )

    summaries = [
        receipt_summary("602700a20b6644b9b535cc8809141173.json", "研究设计：SGLT2 与心衰住院风险务实 RCT"),
        receipt_summary("309696a67b304e42844015db8a8cae58.json", "研究设计：AI 辅助 CT 肺结节诊断准确性"),
        receipt_summary("b61465e053264fb3a0853c986f47dfd3.json", "科研写作：SGLT2 研究方案初稿"),
        receipt_summary("58521eb3b1344fe48d93451f957f5e87.json", "科研写作：AI 辅助 CT 标书初稿"),
    ]
    write_text("08-Skill执行回执汇总-脱敏.json", json.dumps(summaries, ensure_ascii=False, indent=2) + "\n")

    result = json.loads((ROOT / "runtime/mvp-real-case-20260720/toolchain-validation-result.json").read_text(encoding="utf-8"))
    meta = result["meta_result"]
    toolchain_summary = {
        "case": "公开全文二分类 Meta 工具链验证",
        "project_id": result["project_id"],
        "workflow_run_id": result["workflow_run_id"],
        "full_text_document_count": len(result["document_ids"]),
        "evidence_detail_count": len(result["detail_ids"]),
        "bias_assessment_count": len(result["assessment_ids"]),
        "meta_analysis_id": result["meta_analysis_id"],
        "meta_result": {
            "effect_measure": meta["effect_measure"],
            "model": meta["model_label"],
            "outcome_label": meta["outcome_label"],
            "pooled_estimate": meta["pooled_estimate"],
            "pooled_ci_lower": meta["pooled_ci_lower"],
            "pooled_ci_upper": meta["pooled_ci_upper"],
            "i_squared": meta["i_squared"],
            "study_count": meta["study_count"],
            "studies": [
                {
                    "title": study["title"],
                    "intervention_events": study["intervention_events"],
                    "intervention_total": study["intervention_total"],
                    "comparator_events": study["comparator_events"],
                    "comparator_total": study["comparator_total"],
                    "timepoint": study["timepoint"],
                }
                for study in meta["studies"]
            ],
        },
        "approval_snapshot": "该 JSON 捕获于提交系统评价审批后、演示授权前；最终 approved 与导出状态见 06-证据抽取系统评价Agent验收记录.md。",
        "redaction_note": "已移除审批 scope digest、原始审批人/时间和其他运行时字段。结果仅用于工具链验证，不构成临床结论。",
    }
    write_text("09-证据抽取工具链实际结果-脱敏.json", json.dumps(toolchain_summary, ensure_ascii=False, indent=2) + "\n")

    index = f"""# 临研智策 V0.1 本地真实测试结果包

生成日期：{date.today().isoformat()}

## 目的

本结果包为《佐证材料4-临研智策V0.1本地真实案例自测记录.docx》提供可核验的本地证据。内容同时包含当次重新执行的自动化测试日志、历史真实运行记录、脱敏 Skill 回执汇总、实际工具链结果与可复现输入。

## 目录与索引

| 文件/目录 | 内容 | 对应自测记录 |
| --- | --- | --- |
| `01-后端自动化测试结果-2026-07-22.txt` | 当次后端 `pytest -q` 原始输出，39 passed。 | 第二节 |
| `02-Agent-Skill合同检查结果-2026-07-22.txt` | 当次 Agent/Skill/MCP 绑定合同检查输出。 | 第二节 |
| `03-BS工作台生产构建结果-2026-07-22.txt` | 当次 React/TypeScript/Vite 生产构建输出。 | 第二节 |
| `04-研究设计Agent真实运行记录.md` | 三个研究设计真实运行及一次 Skill 门禁阻断记录。 | 案例 1-3 |
| `05-文献检索综述Agent真实运行记录.md` | 真实 PubMed/Europe PMC 检索与项目闭环记录。 | 案例 4 |
| `06-证据抽取系统评价Agent验收记录.md` | 公开全文、RoB 2、二分类 Meta 与审批验收记录。 | 案例 5 |
| `07-科研写作Agent真实运行记录.md` | 方案/标书草稿、来源清单与审批导出记录。 | 案例 6 |
| `08-Skill执行回执汇总-脱敏.json` | 真实工作流的已执行 Skill 名称和数量汇总。 | 第三节与第六节 |
| `09-证据抽取工具链实际结果-脱敏.json` | 真实公开全文验证的字段、事件数与 Meta 工具输出摘要。 | 案例 5 |
| `10-可复现测试输入/` | 四 Agent 的脱敏/公开可复现输入。 | 第四节 |
| `11-四Agent原生确认手工测试步骤摘要-脱敏.md` | 不含密钥的 OpenCode 原生 Allow/Deny 人工确认步骤摘要。 | 第四节 |
| `佐证材料4-临研智策V0.1本地真实案例自测记录.docx` | 本结果包对应的正式 Word 自测记录。 | 全文 |

## 安全说明

本包不包含模型 API Key、审批 Key、Skill 回执签名、OpenCode session id、审批 scope digest、RCT 实际随机分配序列、患者身份信息、非公开全文或数据库文件。所有医学案例均为公开发表历史文献或脱敏/聚合的演示性研究假设；不构成临床建议或科研定稿。
"""
    write_text("00-结果包索引.md", index)

    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(PACKAGE.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(PACKAGE.parent))
    print(PACKAGE)
    print(ARCHIVE)


if __name__ == "__main__":
    main()
