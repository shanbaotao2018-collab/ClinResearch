"""Read-only projections for the medical research workbench UI.

The Agent tools remain the system of record for mutations. These helpers only
assemble persisted records into UI-friendly views and never expose concealed
randomization allocations.
"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, select

from app.models import (
    AgentSkillExecutionReceipt,
    AgentWorkflowEvent,
    AgentWorkflowRun,
    AuditLog,
    BiasAssessment,
    BinaryMetaAnalysisRun,
    Citation,
    CitationSafetyCheck,
    EvidenceExtraction,
    FullTextDocument,
    FullTextEvidenceDetail,
    PrismaCount,
    Project,
    ResearchWritingApproval,
    ResearchWritingDraft,
    SearchStrategyVersion,
    StudyDesignApproval,
    StudyDesignAuditLog,
    StudyDesignProject,
    StudyDesignRandomizationPlan,
    StudyDesignRandomizationSchedule,
    StudyDesignSkillExecutionReceipt,
    StudyDesignWorkflowEvent,
    StudyDesignWorkflowRun,
    SystematicEvidenceReviewApproval,
)


def _json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _record(record: Any) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _approval(record: Any | None) -> dict[str, Any] | None:
    return None if record is None else _record(record)


def _review_summary(session: Session, project: Project) -> dict[str, Any]:
    prisma = session.exec(
        select(PrismaCount).where(PrismaCount.project_id == project.id)
    ).first()
    evidence_runs = session.exec(
        select(AgentWorkflowRun).where(
            AgentWorkflowRun.workflow_type == "evidence_extraction",
            AgentWorkflowRun.subject_type == "review",
            AgentWorkflowRun.subject_id == project.id,
        )
    ).all()
    writing_drafts = session.exec(
        select(ResearchWritingDraft).where(
            ResearchWritingDraft.source_type == "review",
            ResearchWritingDraft.source_id == project.id,
        )
    ).all()
    return {
        "agent_type": "literature_review",
        "id": project.id,
        "title": project.title,
        "status": project.status,
        "updated_at": project.updated_at,
        "created_at": project.created_at,
        "research_question": project.research_question,
        "prisma": None if prisma is None else _record(prisma),
        "evidence_run_count": len(evidence_runs),
        "writing_draft_count": len(writing_drafts),
    }


def _study_summary(session: Session, project: StudyDesignProject) -> dict[str, Any]:
    approval = session.exec(
        select(StudyDesignApproval).where(
            StudyDesignApproval.study_design_project_id == project.id
        )
    ).first()
    return {
        "agent_type": "study_design",
        "id": project.id,
        "title": project.title,
        "status": project.status,
        "updated_at": project.updated_at,
        "created_at": project.created_at,
        "research_question": project.research_question,
        "study_type": project.study_type,
        "approval": _approval(approval),
    }


def workbench_overview(session: Session) -> dict[str, Any]:
    reviews = session.exec(select(Project).order_by(Project.updated_at.desc())).all()
    studies = session.exec(
        select(StudyDesignProject).order_by(StudyDesignProject.updated_at.desc())
    ).all()
    writing_drafts = session.exec(
        select(ResearchWritingDraft).order_by(ResearchWritingDraft.updated_at.desc())
    ).all()
    evidence_approvals = session.exec(select(SystematicEvidenceReviewApproval)).all()
    writing_approvals = session.exec(select(ResearchWritingApproval)).all()
    pending = [
        {
            "kind": "study_design",
            "id": item.study_design_project_id,
            "status": item.status,
            "scope_digest": item.scope_digest,
            "requested_at": item.requested_at,
        }
        for item in session.exec(
            select(StudyDesignApproval).where(StudyDesignApproval.status == "pending")
        ).all()
    ]
    pending.extend(
        {
            "kind": "systematic_evidence",
            "id": item.project_id,
            "workflow_run_id": item.workflow_run_id,
            "status": item.status,
            "scope_digest": item.scope_digest,
            "requested_at": item.requested_at,
        }
        for item in evidence_approvals
        if item.status == "pending"
    )
    pending.extend(
        {
            "kind": "research_writing",
            "id": item.research_writing_draft_id,
            "status": item.status,
            "scope_digest": item.scope_digest,
            "requested_at": item.requested_at,
        }
        for item in writing_approvals
        if item.status == "pending"
    )
    return {
        "summary": {
            "study_design_projects": len(studies),
            "review_projects": len(reviews),
            "evidence_workflows": len(
                session.exec(
                    select(AgentWorkflowRun).where(
                        AgentWorkflowRun.workflow_type == "evidence_extraction"
                    )
                ).all()
            ),
            "writing_drafts": len(writing_drafts),
            "pending_approvals": len(pending),
        },
        "study_design_projects": [_study_summary(session, item) for item in studies],
        "review_projects": [_review_summary(session, item) for item in reviews],
        "writing_drafts": [_writing_summary(session, item) for item in writing_drafts],
        "pending_approvals": sorted(
            pending, key=lambda item: item["requested_at"], reverse=True
        ),
    }


def study_design_detail(session: Session, project_id: int) -> dict[str, Any] | None:
    project = session.get(StudyDesignProject, project_id)
    if not project:
        return None
    # Allocation seed and sequence are deliberately excluded from the workbench.
    project_data = _record(project)
    project_data.pop("randomization_seed", None)
    project_data.pop("randomization_schedule_json", None)
    approval = session.exec(
        select(StudyDesignApproval).where(
            StudyDesignApproval.study_design_project_id == project_id
        )
    ).first()
    plan = session.exec(
        select(StudyDesignRandomizationPlan).where(
            StudyDesignRandomizationPlan.study_design_project_id == project_id
        )
    ).first()
    schedule = session.exec(
        select(StudyDesignRandomizationSchedule).where(
            StudyDesignRandomizationSchedule.study_design_project_id == project_id
        )
    ).first()
    runs = session.exec(
        select(StudyDesignWorkflowRun)
        .where(StudyDesignWorkflowRun.study_design_project_id == project_id)
        .order_by(StudyDesignWorkflowRun.created_at.desc())
    ).all()
    return {
        "project": project_data,
        "approval": _approval(approval),
        "sample_size": {
            "method": project.sample_size_method,
            "inputs": _json(project.sample_size_inputs_json, {}),
            "result": _json(project.sample_size_result_json, {}),
        },
        "randomization": {
            "plan": None
            if plan is None
            else {
                "total_subjects": plan.total_subjects,
                "groups": _json(plan.groups_json, []),
                "block_size": plan.block_size,
            },
            "schedule_generated": schedule is not None,
            "allocation_visible_to_workbench": False,
        },
        "workflow_runs": [_record(item) for item in runs],
        "workflow_events": [
            _record(item)
            for item in session.exec(
                select(StudyDesignWorkflowEvent)
                .where(StudyDesignWorkflowEvent.study_design_project_id == project_id)
                .order_by(StudyDesignWorkflowEvent.created_at.desc())
            ).all()
        ],
        "skill_receipts": [
            _record(item)
            for item in session.exec(
                select(StudyDesignSkillExecutionReceipt)
                .where(StudyDesignSkillExecutionReceipt.study_design_project_id == project_id)
                .order_by(StudyDesignSkillExecutionReceipt.executed_at.desc())
            ).all()
        ],
        "audit_logs": [
            _record(item)
            for item in session.exec(
                select(StudyDesignAuditLog)
                .where(StudyDesignAuditLog.study_design_project_id == project_id)
                .order_by(StudyDesignAuditLog.created_at.desc())
            ).all()
        ],
    }


def review_detail(session: Session, project_id: int) -> dict[str, Any] | None:
    project = session.get(Project, project_id)
    if not project:
        return None
    citations = session.exec(
        select(Citation).where(Citation.project_id == project_id).order_by(Citation.id)
    ).all()
    full_text_documents = session.exec(
        select(FullTextDocument).where(FullTextDocument.project_id == project_id)
    ).all()
    document_data = [
        {
            **_record(item),
            "content_text": None,
            "content_length": len(item.content_text),
        }
        for item in full_text_documents
    ]
    evidence_runs = session.exec(
        select(AgentWorkflowRun)
        .where(
            AgentWorkflowRun.workflow_type == "evidence_extraction",
            AgentWorkflowRun.subject_type == "review",
            AgentWorkflowRun.subject_id == project_id,
        )
        .order_by(AgentWorkflowRun.created_at.desc())
    ).all()
    writing_drafts = session.exec(
        select(ResearchWritingDraft)
        .where(
            ResearchWritingDraft.source_type == "review",
            ResearchWritingDraft.source_id == project_id,
        )
        .order_by(ResearchWritingDraft.updated_at.desc())
    ).all()
    return {
        "project": _record(project),
        "search_strategies": [
            _record(item)
            for item in session.exec(
                select(SearchStrategyVersion)
                .where(SearchStrategyVersion.project_id == project_id)
                .order_by(SearchStrategyVersion.version_number.desc())
            ).all()
        ],
        "citations": [_record(item) for item in citations],
        "prisma": _approval(
            session.exec(select(PrismaCount).where(PrismaCount.project_id == project_id)).first()
        ),
        "audit_logs": [
            _record(item)
            for item in session.exec(
                select(AuditLog)
                .where(AuditLog.project_id == project_id)
                .order_by(AuditLog.created_at.desc())
            ).all()
        ],
        "evidence": {
            "workflow_runs": [_record(item) for item in evidence_runs],
            "extractions": [
                {**_record(item), "missing_fields": _json(item.missing_fields_json, [])}
                for item in session.exec(
                    select(EvidenceExtraction).where(EvidenceExtraction.project_id == project_id)
                ).all()
            ],
            "full_text_documents": document_data,
            "full_text_details": [
                {
                    **_record(item),
                    "baseline": _json(item.baseline_json, {}),
                    "outcomes": _json(item.outcomes_json, []),
                }
                for item in session.exec(
                    select(FullTextEvidenceDetail).where(
                        FullTextEvidenceDetail.project_id == project_id
                    )
                ).all()
            ],
            "bias_assessments": [
                {**_record(item), "domains": _json(item.domains_json, [])}
                for item in session.exec(
                    select(BiasAssessment).where(BiasAssessment.project_id == project_id)
                ).all()
            ],
            "safety_checks": [
                _record(item)
                for item in session.exec(
                    select(CitationSafetyCheck).where(
                        CitationSafetyCheck.project_id == project_id
                    )
                ).all()
            ],
            "meta_analyses": [
                {**_record(item), "result": _json(item.result_json, {}), "forest_plot_svg": None}
                for item in session.exec(
                    select(BinaryMetaAnalysisRun).where(
                        BinaryMetaAnalysisRun.project_id == project_id
                    )
                ).all()
            ],
            "approvals": [
                _record(item)
                for item in session.exec(
                    select(SystematicEvidenceReviewApproval).where(
                        SystematicEvidenceReviewApproval.project_id == project_id
                    )
                ).all()
            ],
        },
        "writing_drafts": [_writing_summary(session, item) for item in writing_drafts],
        "workflow_events": [
            _record(item)
            for item in session.exec(
                select(AgentWorkflowEvent)
                .where(AgentWorkflowEvent.subject_type == "review", AgentWorkflowEvent.subject_id == project_id)
                .order_by(AgentWorkflowEvent.created_at.desc())
            ).all()
        ],
        "skill_receipts": [
            _record(item)
            for item in session.exec(
                select(AgentSkillExecutionReceipt)
                .where(AgentSkillExecutionReceipt.subject_type == "review", AgentSkillExecutionReceipt.subject_id == project_id)
                .order_by(AgentSkillExecutionReceipt.executed_at.desc())
            ).all()
        ],
    }


def _writing_summary(session: Session, draft: ResearchWritingDraft) -> dict[str, Any]:
    approval = session.exec(
        select(ResearchWritingApproval).where(
            ResearchWritingApproval.research_writing_draft_id == draft.id
        )
    ).first()
    return {
        **_record(draft),
        "source_manifest": _json(draft.source_manifest_json, []),
        "approval": _approval(approval),
    }


def writing_detail(session: Session, draft_id: int) -> dict[str, Any] | None:
    draft = session.get(ResearchWritingDraft, draft_id)
    if not draft:
        return None
    detail = _writing_summary(session, draft)
    detail["workflow_events"] = [
        _record(item)
        for item in session.exec(
            select(AgentWorkflowEvent)
            .where(AgentWorkflowEvent.workflow_run_id == draft.workflow_run_id)
            .order_by(AgentWorkflowEvent.created_at.desc())
        ).all()
    ]
    detail["skill_receipts"] = [
        _record(item)
        for item in session.exec(
            select(AgentSkillExecutionReceipt)
            .where(AgentSkillExecutionReceipt.workflow_run_id == draft.workflow_run_id)
            .order_by(AgentSkillExecutionReceipt.executed_at.desc())
        ).all()
    ]
    return detail
