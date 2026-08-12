"""Authoritative, user-facing next actions for the four research Agents.

The model must not invent workflow routes.  This module translates persisted
project state into a small, ordered action list that is safe to render in both
OpenCode and the B/S workbench.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.models import (
    AgentWorkflowRun,
    Citation,
    CitationSafetyCheck,
    EvidenceExtraction,
    FullTextDocument,
    FullTextEvidenceDetail,
    Project,
    ProjectStatus,
    ResearchWritingApproval,
    ResearchWritingDraft,
    ScreeningDecision,
    StudyDesignApproval,
    StudyDesignProject,
    StudyDesignRandomizationPlan,
    StudyDesignRandomizationSchedule,
    StudyDesignStatus,
    SystematicEvidenceReviewApproval,
    BiasAssessment,
)


def _action(
    action_id: str,
    label: str,
    status: str,
    target_agent: str,
    reason: str,
    prompt: str,
) -> dict[str, str]:
    return {
        "action_id": action_id,
        "label": label,
        "status": status,
        "target_agent": target_agent,
        "reason": reason,
        "prompt": prompt,
    }


def _result(subject_type: str, subject_id: int, status: str, actions: list[dict[str, str]]):
    """Expose one main action and at most two supporting actions."""
    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "workflow_status": status,
        "actions": actions[:3],
        "rendering_rule": (
            "Only show these actions to the researcher. Do not add tool names, "
            "unverified citations, unsupported deliverables, or extra next steps."
        ),
    }


def _study_actions(session: Session, project_id: int) -> dict[str, Any]:
    project = session.get(StudyDesignProject, project_id)
    if not project:
        raise ValueError(f"Study-design project {project_id} not found.")
    approval = session.exec(select(StudyDesignApproval).where(
        StudyDesignApproval.study_design_project_id == project_id
    )).first()
    plan = session.exec(select(StudyDesignRandomizationPlan).where(
        StudyDesignRandomizationPlan.study_design_project_id == project_id
    )).first()
    schedule = session.exec(select(StudyDesignRandomizationSchedule).where(
        StudyDesignRandomizationSchedule.study_design_project_id == project_id
    )).first()

    if project.status == StudyDesignStatus.DRAFT:
        return _result("study_design", project_id, project.status, [_action(
            "complete_study_blueprint", "完善研究设计信息", "available", "study-design",
            "研究项目尚未生成设计蓝图。", f"继续研究设计项目 {project_id}，生成研究设计蓝图并保存草稿。",
        )])
    if project.status in {StudyDesignStatus.BLUEPRINT_READY, StudyDesignStatus.CONTENT_DRAFTED}:
        return _result("study_design", project_id, project.status, [_action(
            "complete_study_content", "完善纳排标准、结局与方案草稿", "available", "study-design",
            "研究设计尚未完成可确认的完整内容。", f"继续研究设计项目 {project_id}，补齐纳排标准、结局、可行性和方案草稿。",
        )])
    if project.status == StudyDesignStatus.SAMPLE_SIZE_READY and project.study_design.lower() == "rct" and not plan:
        return _result("study_design", project_id, project.status, [_action(
            "save_randomization_plan", "保存随机化计划", "available", "study-design",
            "这是 RCT，尚未保存随机化计划；此步骤不会生成或展示分配序列。",
            f"继续研究设计项目 {project_id}，保存随机化计划，不生成分配序列。",
        )])
    if project.status == StudyDesignStatus.SAMPLE_SIZE_READY:
        return _result("study_design", project_id, project.status, [_action(
            "request_study_confirmation", "确认研究设计假设", "requires_confirmation", "study-design",
            "研究设计与样本量假设已完成，需由研究者确认后才能导出方案包。",
            f"继续研究设计项目 {project_id}，展示方案与样本量假设并请求 OpenCode 原生确认。",
        )])
    if project.status == StudyDesignStatus.APPROVAL_PENDING:
        return _result("study_design", project_id, project.status, [_action(
            "confirm_study_design", "确认或退回研究设计", "requires_confirmation", "study-design",
            "样本量假设和随机化计划须由研究者在 OpenCode 中确认。",
            f"继续研究设计项目 {project_id}，展示确认范围并请求 OpenCode 原生确认；如拒绝则保留草稿供修改。",
        )])
    if project.status in {StudyDesignStatus.HUMAN_APPROVED, StudyDesignStatus.HUMAN_CONFIRMED, StudyDesignStatus.RANDOMIZATION_READY}:
        return _result("study_design", project_id, project.status, [_action(
            "complete_study_export", "完成方案包导出", "available", "study-design",
            "研究设计已确认，仍需在当前闭环完成受保护随机化与导出。",
            f"继续研究设计项目 {project_id}，完成已确认范围内的导出，不展示随机分配序列。",
        )])
    if project.status == StudyDesignStatus.EXPORTED:
        actions = [_action(
            "start_review_from_study", "进入文献检索与综述", "available", "literature-review",
            "研究设计已完成并导出，可用已确认 PICO 建立证据检索项目。",
            f"基于 study-design 项目 {project_id} 的已确认研究问题和 PICO，创建新的文献综述项目并开始检索。",
        )]
        if schedule is not None:
            actions.append(_action(
                "view_study_export", "查看或重新导出方案包", "available", "study-design",
                "已生成受保护方案包。", f"查看或重新导出研究设计项目 {project_id} 的方案包。",
            ))
        return _result("study_design", project_id, project.status, actions)
    return _result("study_design", project_id, project.status, [])


def _review_actions(session: Session, project_id: int) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if not project:
        raise ValueError(f"Review project {project_id} not found.")
    citations = session.exec(select(Citation).where(Citation.project_id == project_id)).all()
    active = [item for item in citations if not item.is_deduplicated]
    decisions = {item.citation_id for item in session.exec(
        select(ScreeningDecision).where(ScreeningDecision.project_id == project_id)
    ).all()}
    if project.status == ProjectStatus.DRAFT:
        return _result("review", project_id, project.status, [_action(
            "generate_search_strategy", "生成并确认检索策略", "available", "literature-review",
            "尚未生成项目检索策略。", f"继续文献综述项目 {project_id}，生成检索策略并说明检索范围。",
        )])
    if not citations:
        return _result("review", project_id, project.status, [_action(
            "retrieve_citations", "执行文献检索并导入题录", "available", "literature-review",
            "项目尚无候选题录。", f"继续文献综述项目 {project_id}，按当前部署的文献访问模式执行检索并导入原始题录。",
        )])
    if project.status in {ProjectStatus.SEARCH_EXECUTED, ProjectStatus.CITATIONS_DEDUPLICATED, ProjectStatus.SCREENING_IN_PROGRESS} and len(decisions) < len(active):
        return _result("review", project_id, project.status, [_action(
            "review_screening_suggestions", "查看并确认筛选建议", "requires_confirmation", "literature-review",
            "候选题录尚未形成经研究者确认的完整纳入/排除决定。",
            f"继续文献综述项目 {project_id}，展示标题摘要筛选建议，等待我确认或修改后再保存决定。",
        )])
    if project.status in {ProjectStatus.SCREENING_COMPLETED, ProjectStatus.PRISMA_GENERATED, ProjectStatus.EXPORTED}:
        return _result("review", project_id, project.status, [
            _action("start_evidence_extraction", "进入多源证据抽取分析", "available", "evidence-extraction",
                "筛选决定已保存，下一阶段是形成可核查证据表。",
                f"对文献综述项目 {project_id} 已纳入研究启动证据抽取；只使用已保存的题录、摘要和全文来源。"),
            _action("view_review_export", "查看或导出文献综述项目包", "available", "literature-review",
                "检索、去重与筛选记录可供追溯。", f"查看或导出文献综述项目 {project_id} 的项目包。"),
        ])
    return _result("review", project_id, project.status, [_action(
        "deduplicate_citations", "完成题录去重", "available", "literature-review",
        "题录已导入，尚未完成规范去重。", f"继续文献综述项目 {project_id}，完成题录去重后再进行筛选。",
    )])


def _evidence_actions(session: Session, project_id: int) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if not project:
        raise ValueError(f"Review project {project_id} not found.")
    included = {item.citation_id for item in session.exec(
        select(ScreeningDecision).where(
            ScreeningDecision.project_id == project_id,
            ScreeningDecision.decision == "include",
        )
    ).all()}
    if not included:
        return _result("evidence", project_id, "blocked", [_action(
            "return_to_screening", "返回文献综述完成筛选", "blocked", "literature-review",
            "没有已纳入且保存的研究，不能开始证据抽取。",
            f"继续文献综述项目 {project_id}，完成筛选确认后再进入证据抽取。",
        )])
    extractions = {item.citation_id for item in session.exec(select(EvidenceExtraction).where(EvidenceExtraction.project_id == project_id)).all()}
    safety = {item.citation_id for item in session.exec(select(CitationSafetyCheck).where(CitationSafetyCheck.project_id == project_id)).all()}
    run = session.exec(select(AgentWorkflowRun).where(
        AgentWorkflowRun.workflow_type == "evidence_extraction", AgentWorkflowRun.subject_type == "review", AgentWorkflowRun.subject_id == project_id
    ).order_by(AgentWorkflowRun.created_at.desc())).first()
    if run is None:
        return _result("evidence", project_id, "not_started", [_action(
            "start_evidence_workflow", "开始基础证据抽取", "available", "evidence-extraction",
            "已有纳入研究，尚未建立证据抽取工作流。", f"对文献综述项目 {project_id} 启动证据抽取工作流。",
        )])
    if not included.issubset(extractions):
        return _result("evidence", project_id, "extraction_in_progress", [_action(
            "complete_evidence_extraction", "补齐基础证据抽取", "available", "evidence-extraction",
            "部分纳入研究尚无来源限定的抽取记录。", f"继续证据抽取项目 {project_id}，补齐所有纳入研究的基础证据字段与缺失项。",
        )])
    if not included.issubset(safety):
        return _result("evidence", project_id, "safety_check_required", [_action(
            "complete_safety_check", "完成文献安全检查", "available", "evidence-extraction",
            "基础抽取已完成，但尚未完成所有纳入研究的撤稿/安全检查。", f"继续证据抽取项目 {project_id}，完成纳入研究的文献安全检查。",
        )])
    full_text = {
        item.citation_id
        for item in session.exec(select(FullTextDocument).where(
            FullTextDocument.project_id == project_id
        )).all()
    }
    details = {
        item.citation_id
        for item in session.exec(select(FullTextEvidenceDetail).where(
            FullTextEvidenceDetail.project_id == project_id
        )).all()
    }
    bias = {
        item.citation_id
        for item in session.exec(select(BiasAssessment).where(
            BiasAssessment.project_id == project_id
        )).all()
    }
    missing_full_text = sorted(included - full_text)
    missing_details = sorted(included - details)
    missing_bias = sorted(included - bias)
    available_full_text = included & full_text
    missing_available_details = sorted(available_full_text - details)
    missing_available_bias = sorted(available_full_text - bias)
    if missing_full_text:
        actions = []
        if missing_available_details or missing_available_bias:
            actions.append(_action(
                "complete_available_full_text_assessment", "完成已获取全文的证据评价", "available", "evidence-extraction",
                f"{len(available_full_text)}/{len(included)} 篇纳入研究已有全文；其中详细抽取缺失 "
                f"{missing_available_details}，偏倚风险评价缺失 {missing_available_bias}。",
                f"继续证据抽取项目 {project_id}，只对已有全文的 citation ID "
                f"{sorted(available_full_text)} 完成详细证据抽取、偏倚风险评价和适用的探索性 Meta 分析；"
                "不要因缺少其他研究全文而阻塞，也不要把它们作为科学排除。",
            ))
        elif available_full_text:
            actions.append(_action(
                "start_open_access_research_writing", "现在进入科研写作（部分证据综合）", "available", "research-writing",
                f"已完成 {len(available_full_text)}/{len(included)} 篇纳入研究的全文证据评价。"
                "可立即进入下一阶段；其余研究保留为全文覆盖缺口，不构成科学排除。",
                f"使用文献综述项目 {project_id} 已完成的基础证据表和已获取全文的详细评价开始科研写作；"
                "所有证据结论仅基于具备全文详情和偏倚风险评价的研究，并在文稿中明确标注“基于可获取全文的部分证据综合”。",
            ))
        actions.extend([
            _action(
                "export_partial_evidence_report", "查看或导出部分证据报告", "available", "evidence-extraction",
                "当前可导出摘要级证据表、已获取全文的初步抽取和明确全文缺口；不构成完整系统评价。",
                f"导出证据抽取项目 {project_id} 的部分证据报告，明确标注 partial_full_text_assessment 和全文缺口。",
            ),
            _action(
                "provide_missing_full_text", "可选：补充 PDF/全文后增量更新证据", "requires_input", "evidence-extraction",
                "这不是进入科研写作的前提。研究者如已合法获得 PDF 或全文，可随时补充以扩大证据覆盖范围并更新后续写作稿。",
                f"如需补充，为证据抽取项目 {project_id} 提供 citation ID {missing_full_text} 对应的合法 PDF 或全文；"
                "系统将作为研究者提供来源保存、补充全文级抽取和偏倚评价，并要求人工复核。",
            ),
        ])
        return _result("evidence", project_id, "partial_full_text_assessment", actions)
    if missing_details or missing_bias:
        return _result("evidence", project_id, "full_text_assessment_in_progress", [_action(
            "complete_full_text_assessment", "补齐全文证据抽取与偏倚风险评价", "available", "evidence-extraction",
            f"全部纳入研究已具备全文，但详细抽取缺失 {missing_details}，偏倚风险评价缺失 {missing_bias}。",
            f"继续证据抽取项目 {project_id}，仅补齐全文证据抽取和偏倚风险评价；完成前不申请正式系统评价。",
        )])
    approval = session.exec(select(SystematicEvidenceReviewApproval).where(
        SystematicEvidenceReviewApproval.project_id == project_id, SystematicEvidenceReviewApproval.workflow_run_id == run.run_id
    )).first()
    if approval and approval.status == "pending":
        return _result("evidence", project_id, "approval_pending", [_action(
            "confirm_systematic_evidence", "确认或退回系统评价包", "requires_confirmation", "evidence-extraction",
            "系统评价范围已提交，需研究者在 OpenCode 中确认。", f"继续证据抽取项目 {project_id}，展示系统评价确认范围并请求 OpenCode 原生确认。",
        )])
    if approval and approval.status == "approved":
        return _result("evidence", project_id, "approved", [_action(
            "start_research_writing", "进入科研写作", "available", "research-writing",
            "证据抽取和系统评价范围已确认，可作为写作来源。", f"使用文献综述项目 {project_id} 已确认的证据抽取结果，开始科研写作。",
        )])
    return _result("evidence", project_id, "basic_evidence_ready", [_action(
        "review_evidence_table", "人工复核并导出证据表", "requires_confirmation", "evidence-extraction",
        "所有基础抽取和安全检查已完成，但结论仍须人工复核。", f"继续证据抽取项目 {project_id}，展示证据表和缺失项，等待我确认后导出。",
    )])


def _writing_actions(session: Session, draft_id: int) -> dict[str, Any]:
    draft = session.get(ResearchWritingDraft, draft_id)
    if not draft:
        raise ValueError(f"Research-writing draft {draft_id} not found.")
    approval = session.exec(select(ResearchWritingApproval).where(
        ResearchWritingApproval.research_writing_draft_id == draft_id
    )).first()
    if approval is None:
        return _result("research_writing", draft_id, draft.status, [_action(
            "review_writing_draft", "审阅草稿并请求确认", "available", "research-writing",
            "草稿已保存，但尚未发起人工确认。", f"继续科研写作草稿 {draft_id}，展示未解决项并请求 OpenCode 原生确认。",
        )])
    if approval.status == "pending":
        return _result("research_writing", draft_id, "approval_pending", [_action(
            "confirm_writing_draft", "确认或退回写作草稿", "requires_confirmation", "research-writing",
            "草稿须经研究者确认后才能导出。", f"继续科研写作草稿 {draft_id}，展示确认范围并请求 OpenCode 原生确认。",
        )])
    if approval.status == "approved":
        return _result("research_writing", draft_id, "approved", [_action(
            "export_writing_bundle", "导出科研写作包", "available", "research-writing",
            "草稿已确认，可以导出版本化写作包。", f"继续科研写作草稿 {draft_id}，导出经确认的写作包。",
        )])
    return _result("research_writing", draft_id, draft.status, [])


def get_next_actions(session: Session, subject_type: str, subject_id: int) -> dict[str, Any]:
    """Return the only user-facing next actions allowed for a persisted subject."""
    handlers = {
        "study_design": _study_actions,
        "review": _review_actions,
        "evidence": _evidence_actions,
        "research_writing": _writing_actions,
    }
    try:
        return handlers[subject_type](session, subject_id)
    except KeyError as error:
        raise ValueError("subject_type must be study_design, review, evidence, or research_writing.") from error
