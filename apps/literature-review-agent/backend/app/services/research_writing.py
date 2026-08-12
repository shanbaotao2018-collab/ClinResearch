from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.config import settings
from app.models import (
    BiasAssessment,
    BinaryMetaAnalysisRun,
    CitationSafetyCheck,
    EvidenceExtraction,
    FullTextDocument,
    FullTextEvidenceDetail,
    Project,
    ResearchCase,
    ResearchWritingApproval,
    ResearchWritingDraft,
    StudyDesignProject,
)
from app.schemas import ResearchWritingDraftCreate
from app.services.agent_workflows import (
    get_agent_skill_receipts,
    get_agent_workflow_run,
    record_agent_workflow_event,
    start_agent_workflow_run,
)
from app.services.evidence_extraction import included_citations
from app.services.phi_guard import assert_no_phi


_WORKFLOW_TYPE = "research_writing"
_BASE_SKILLS = {
    "biomed-outline-generator",
    "method-writing",
    "discussion-section-architect",
}
_PROPOSAL_SKILL = {"research-proposal-generator"}
_DOCUMENT_TYPES = {"protocol", "proposal", "methods", "discussion", "review_article"}


def _document_type_error() -> ValueError:
    return ValueError(
        "document_type must be protocol, proposal, methods, discussion, or review_article."
    )


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_source_ready(session: Session, source_type: str, source_id: int) -> None:
    if source_type == "research_case":
        case = session.get(ResearchCase, source_id)
        if not case:
            raise ValueError(f"Research case {source_id} not found.")
        if case.study_design_project_id is None or case.review_project_id is None:
            raise ValueError("Research case writing requires both a linked study-design project and review project.")
        _validate_source_ready(session, "study_design", case.study_design_project_id)
        _validate_source_ready(session, "review", case.review_project_id)
        return
    if source_type == "study_design":
        project = session.get(StudyDesignProject, source_id)
        if not project:
            raise ValueError(f"Study-design project {source_id} not found.")
        if not project.proposal_outline or not project.primary_outcome:
            raise ValueError("Study-design source requires saved draft content before writing.")
        return
    if source_type == "review":
        project = session.get(Project, source_id)
        if not project:
            raise ValueError(f"Review project {source_id} not found.")
        citation_ids = {item.id for item in included_citations(session, source_id)}
        extracted_ids = {
            item.citation_id
            for item in session.exec(
                select(EvidenceExtraction).where(EvidenceExtraction.project_id == source_id)
            ).all()
        }
        if not citation_ids or not citation_ids.issubset(extracted_ids):
            raise ValueError("Review source requires a completed evidence extraction for every included citation.")
        return
    raise ValueError("source_type must be 'study_design', 'review', or 'research_case'.")


def get_research_writing_source_data(
    session: Session, source_type: str, source_id: int
) -> dict[str, Any]:
    """Return the saved, source-bounded facts a writing Agent may use."""
    _validate_source_ready(session, source_type, source_id)
    if source_type == "research_case":
        case = session.get(ResearchCase, source_id)
        return {
            "source_type": source_type,
            "source_id": source_id,
            "case": {"title": case.title, "description": case.description},
            "study_design_source": get_research_writing_source_data(
                session, "study_design", case.study_design_project_id
            ),
            "review_source": get_research_writing_source_data(
                session, "review", case.review_project_id
            ),
            "writing_rule": (
                "Use only facts from the linked saved study-design and review sources. "
                "The draft source_manifest must name research_case plus both linked source records."
            ),
        }
    if source_type == "study_design":
        project = session.get(StudyDesignProject, source_id)
        return {
            "source_type": source_type,
            "source_id": source_id,
            "project": {
                "title": project.title,
                "research_question": project.research_question,
                "study_type": project.study_type,
                "study_design": project.study_design,
                "population": project.population,
                "intervention": project.intervention,
                "comparator": project.comparator,
                "outcome": project.outcome,
                "protocol_standard": project.protocol_standard,
                "inclusion_criteria": project.inclusion_criteria,
                "exclusion_criteria": project.exclusion_criteria,
                "primary_outcome": project.primary_outcome,
                "secondary_outcomes": project.secondary_outcomes,
                "innovation_notes": project.innovation_notes,
                "feasibility_notes": project.feasibility_notes,
                "proposal_outline": project.proposal_outline,
                "status": project.status,
            },
            "writing_rule": "Use only these saved project facts. Put absent details into unresolved_items instead of inventing them.",
        }
    project = session.get(Project, source_id)
    evidence_by_citation = {
        item.citation_id: item
        for item in session.exec(
            select(EvidenceExtraction).where(EvidenceExtraction.project_id == source_id)
        ).all()
    }
    safety_by_citation = {
        item.citation_id: item
        for item in session.exec(
            select(CitationSafetyCheck).where(CitationSafetyCheck.project_id == source_id)
        ).all()
    }
    documents_by_id = {
        item.id: item
        for item in session.exec(
            select(FullTextDocument).where(FullTextDocument.project_id == source_id)
        ).all()
    }
    details_by_citation: dict[int, list[FullTextEvidenceDetail]] = {}
    for item in session.exec(
        select(FullTextEvidenceDetail).where(FullTextEvidenceDetail.project_id == source_id)
    ).all():
        details_by_citation.setdefault(item.citation_id, []).append(item)
    bias_by_citation: dict[int, list[BiasAssessment]] = {}
    for item in session.exec(
        select(BiasAssessment).where(BiasAssessment.project_id == source_id)
    ).all():
        bias_by_citation.setdefault(item.citation_id, []).append(item)

    rows = []
    for citation in included_citations(session, source_id):
        extraction = evidence_by_citation[citation.id]
        safety = safety_by_citation.get(citation.id)
        full_text_details = []
        for detail in details_by_citation.get(citation.id, []):
            document = documents_by_id.get(detail.full_text_document_id)
            full_text_details.append(
                {
                    "full_text_document_id": detail.full_text_document_id,
                    "source_kind": document.source_kind if document else "unknown",
                    "source_url": document.source_url if document else None,
                    "content_sha256": document.content_sha256 if document else None,
                    "baseline": json.loads(detail.baseline_json),
                    "outcomes": json.loads(detail.outcomes_json),
                    "extraction_notes": detail.extraction_notes,
                    "needs_human_review": detail.needs_human_review,
                }
            )
        bias_assessments = [
            {
                "instrument": assessment.instrument,
                "overall_judgement": assessment.overall_judgement,
                "domains": json.loads(assessment.domains_json),
                "needs_human_review": assessment.needs_human_review,
            }
            for assessment in bias_by_citation.get(citation.id, [])
        ]
        rows.append(
            {
                "citation_id": citation.id,
                "title": citation.title,
                "study_design": extraction.study_design,
                "population": extraction.population,
                "outcomes": extraction.outcomes,
                "effect_estimates": extraction.effect_estimates,
                "evidence_basis": extraction.evidence_basis,
                "missing_fields": json.loads(extraction.missing_fields_json),
                "safety_status": safety.status if safety else "not_checked",
                "full_text_details": full_text_details,
                "bias_assessments": bias_assessments,
            }
        )
    # Keep the newest run for each synthesis specification. Re-running an
    # unchanged analysis is expected during review and should not look like
    # multiple independent meta-analyses to the writing Agent.
    meta_analyses = []
    seen_meta_specs: set[tuple[str, str, str]] = set()
    for item in session.exec(
        select(BinaryMetaAnalysisRun)
        .where(BinaryMetaAnalysisRun.project_id == source_id)
        .order_by(BinaryMetaAnalysisRun.created_at.desc())
    ).all():
        specification = (item.outcome_label, item.effect_measure, item.model)
        if specification in seen_meta_specs:
            continue
        seen_meta_specs.add(specification)
        meta_analyses.append(
            {
                "meta_analysis_id": item.id,
                "workflow_run_id": item.workflow_run_id,
                "outcome_label": item.outcome_label,
                "effect_measure": item.effect_measure,
                "model": item.model,
                "result": json.loads(item.result_json),
                "needs_human_review": item.needs_human_review,
            }
        )
    full_text_detail_ids = {
        citation_id for citation_id, values in details_by_citation.items() if values
    }
    bias_ids = {citation_id for citation_id, values in bias_by_citation.items() if values}
    included_ids = {item["citation_id"] for item in rows}
    evaluated_full_text_ids = sorted(full_text_detail_ids & bias_ids)
    missing_full_text_ids = sorted(included_ids - {
        citation_id
        for citation_id, values in details_by_citation.items()
        if values
    })
    open_access_limited = bool(missing_full_text_ids or set(included_ids) - set(evaluated_full_text_ids))
    return {
        "source_type": source_type,
        "source_id": source_id,
        "project": {
            "title": project.title,
            "research_question": project.research_question,
            "pico_population": project.pico_population,
            "pico_intervention": project.pico_intervention,
            "pico_comparator": project.pico_comparator,
            "pico_outcome": project.pico_outcome,
        },
        "evidence_rows": rows,
        "binary_meta_analyses": meta_analyses,
        "evidence_coverage": {
            "included_count": len(included_ids),
            "evaluated_full_text_citation_ids": evaluated_full_text_ids,
            "evaluated_full_text_count": len(evaluated_full_text_ids),
            "missing_full_text_detail_citation_ids": missing_full_text_ids,
            "synthesis_scope": "available_full_text_only" if open_access_limited else "complete_systematic_review",
        },
        "writing_rule": (
            "Use only these saved evidence rows, full-text details, bias assessments, and meta-analysis results. "
            "Every field marked needs_human_review remains preliminary; do not state missing fields as findings "
            "or present preliminary synthesis as a final clinical conclusion. "
            + (
                "This review has partial full-text coverage: substantive evidence claims may use only rows with both "
                "full-text details and bias assessments. State that the draft is based on available full text and list "
                "the coverage gap in limitations."
                if open_access_limited else ""
            )
        ),
    }


def start_research_writing_workflow_record(
    session: Session,
    source_type: str,
    source_id: int,
    document_type: str,
    actor: str = "mcp",
):
    if document_type not in _DOCUMENT_TYPES:
        raise _document_type_error()
    _validate_source_ready(session, source_type, source_id)
    return start_agent_workflow_run(
        session, _WORKFLOW_TYPE, source_type, source_id, actor=actor
    )


def required_writing_skills(document_type: str) -> set[str]:
    if document_type not in _DOCUMENT_TYPES:
        raise _document_type_error()
    return _BASE_SKILLS | (_PROPOSAL_SKILL if document_type == "proposal" else set())


def _validate_manifest(payload: ResearchWritingDraftCreate, source_type: str, source_id: int) -> None:
    if not payload.outline.strip() or not payload.limitations.strip() or not payload.unresolved_items.strip():
        raise ValueError("outline, limitations, and unresolved_items must not be empty.")
    matches_source = any(
        item.get("source_type") == source_type and item.get("source_id") == str(source_id)
        for item in payload.source_manifest
    )
    if not matches_source:
        raise ValueError("source_manifest must include the workflow source_type and source_id.")
    assert_no_phi(payload.model_dump())


def save_research_writing_draft_record(
    session: Session,
    source_type: str,
    source_id: int,
    workflow_run_id: str,
    document_type: str,
    payload: ResearchWritingDraftCreate,
    actor: str = "mcp",
) -> ResearchWritingDraft:
    get_agent_workflow_run(
        session, workflow_run_id, _WORKFLOW_TYPE, source_type, source_id
    )
    _validate_source_ready(session, source_type, source_id)
    if document_type == "review_article":
        if source_type != "review":
            raise ValueError("document_type='review_article' requires source_type='review'.")
        if not payload.review_draft:
            raise ValueError("review_draft is required for document_type='review_article'.")
    _validate_manifest(payload, source_type, source_id)
    if document_type == "proposal" and not payload.proposal_draft:
        raise ValueError("proposal_draft is required for document_type='proposal'.")
    prior_versions = session.exec(
        select(ResearchWritingDraft).where(
            ResearchWritingDraft.source_type == source_type,
            ResearchWritingDraft.source_id == source_id,
            ResearchWritingDraft.document_type == document_type,
        )
    ).all()
    draft = ResearchWritingDraft(
        workflow_run_id=workflow_run_id,
        source_type=source_type,
        source_id=source_id,
        document_type=document_type,
        title=payload.title.strip(),
        target_audience=payload.target_audience.strip() if payload.target_audience else None,
        source_manifest_json=json.dumps(payload.source_manifest, ensure_ascii=False, sort_keys=True),
        outline=payload.outline.strip(),
        methods_draft=payload.methods_draft.strip() if payload.methods_draft else None,
        discussion_framework=payload.discussion_framework.strip() if payload.discussion_framework else None,
        proposal_draft=payload.proposal_draft.strip() if payload.proposal_draft else None,
        review_draft=payload.review_draft.strip() if payload.review_draft else None,
        limitations=payload.limitations.strip(),
        unresolved_items=payload.unresolved_items.strip(),
        version_number=len(prior_versions) + 1,
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)
    result = {
        "draft_id": draft.id,
        "version_number": draft.version_number,
        "status": draft.status,
    }
    record_agent_workflow_event(
        session,
        workflow_run_id,
        _WORKFLOW_TYPE,
        source_type,
        source_id,
        "save_research_writing_draft",
        {"document_type": document_type, "source_manifest_count": len(payload.source_manifest)},
        result,
    )
    return draft


def _draft_or_raise(session: Session, draft_id: int) -> ResearchWritingDraft:
    draft = session.get(ResearchWritingDraft, draft_id)
    if not draft:
        raise ValueError(f"Research-writing draft {draft_id} not found.")
    return draft


def _approval_scope(draft: ResearchWritingDraft) -> dict[str, Any]:
    return {
        "draft_id": draft.id,
        "workflow_run_id": draft.workflow_run_id,
        "source_type": draft.source_type,
        "source_id": draft.source_id,
        "document_type": draft.document_type,
        "version_number": draft.version_number,
        "title": draft.title,
        "source_manifest": json.loads(draft.source_manifest_json),
        "outline": draft.outline,
        "methods_draft": draft.methods_draft,
        "discussion_framework": draft.discussion_framework,
        "proposal_draft": draft.proposal_draft,
        "review_draft": draft.review_draft,
        "limitations": draft.limitations,
        "unresolved_items": draft.unresolved_items,
    }


def request_research_writing_approval_record(
    session: Session, draft_id: int, workflow_run_id: str, actor: str = "mcp"
) -> ResearchWritingApproval:
    draft = _draft_or_raise(session, draft_id)
    if draft.workflow_run_id != workflow_run_id:
        raise ValueError("workflow_run_id does not belong to this writing draft.")
    if draft.status == "exported":
        raise ValueError("Exported drafts are immutable; create a new version for changes.")
    digest = _canonical_digest(_approval_scope(draft))
    approval = session.exec(
        select(ResearchWritingApproval).where(
            ResearchWritingApproval.research_writing_draft_id == draft_id
        )
    ).first()
    if approval and approval.status == "approved" and approval.scope_digest == digest:
        return approval
    if approval is None:
        approval = ResearchWritingApproval(
            research_writing_draft_id=draft_id, scope_digest=digest
        )
    else:
        approval.scope_digest = digest
        approval.status = "pending"
        approval.requested_at = datetime.now(UTC)
        approval.approved_by = None
        approval.approved_at = None
    draft.status = "approval_pending"
    draft.updated_at = datetime.now(UTC)
    session.add(draft)
    session.add(approval)
    session.commit()
    session.refresh(approval)
    record_agent_workflow_event(
        session,
        draft.workflow_run_id,
        _WORKFLOW_TYPE,
        draft.source_type,
        draft.source_id,
        "request_research_writing_approval",
        {"draft_id": draft_id, "actor": actor},
        {"draft_id": draft_id, "approval_status": approval.status},
    )
    return approval


def approve_research_writing_record(
    session: Session, draft_id: int, approved_by: str
) -> ResearchWritingApproval:
    draft = _draft_or_raise(session, draft_id)
    approval = session.exec(
        select(ResearchWritingApproval).where(
            ResearchWritingApproval.research_writing_draft_id == draft_id
        )
    ).first()
    if not approval or approval.status != "pending":
        raise ValueError("No pending internal confirmation request exists for this writing draft.")
    if not approved_by.strip():
        raise ValueError("approved_by must not be empty.")
    if approval.scope_digest != _canonical_digest(_approval_scope(draft)):
        raise ValueError("Approval scope changed. Request approval again.")
    approval.status = "approved"
    approval.approved_by = approved_by.strip()
    approval.approved_at = datetime.now(UTC)
    draft.status = "approved"
    draft.updated_at = approval.approved_at
    session.add(approval)
    session.add(draft)
    session.commit()
    session.refresh(approval)
    return approval


def research_writing_approval_snapshot(session: Session, draft_id: int) -> dict[str, Any]:
    draft = _draft_or_raise(session, draft_id)
    approval = session.exec(
        select(ResearchWritingApproval).where(
            ResearchWritingApproval.research_writing_draft_id == draft_id
        )
    ).first()
    return {
        "draft_id": draft.id,
        "draft_status": draft.status,
        "approval": None
        if approval is None
        else {
            "status": approval.status,
            "requested_at": approval.requested_at,
            "approved_by": approval.approved_by,
            "approved_at": approval.approved_at,
            "scope_digest": approval.scope_digest,
        },
    }


def verify_research_writing_approval_key(provided_key: str | None) -> None:
    configured_key = settings.research_writing_approval_key
    if not configured_key or not provided_key or not hmac.compare_digest(configured_key, provided_key):
        raise PermissionError("A valid X-Research-Writing-Approval-Key is required.")


def build_research_writing_bundle_data(
    session: Session, draft_id: int, workflow_run_id: str
) -> dict[str, Any]:
    draft = _draft_or_raise(session, draft_id)
    if draft.workflow_run_id != workflow_run_id:
        raise ValueError("workflow_run_id does not belong to this writing draft.")
    approval = session.exec(
        select(ResearchWritingApproval).where(
            ResearchWritingApproval.research_writing_draft_id == draft_id
        )
    ).first()
    if not approval or approval.status != "approved":
        raise ValueError("Internal human confirmation is required before exporting a research-writing bundle.")
    if approval.scope_digest != _canonical_digest(_approval_scope(draft)):
        raise ValueError("Approval scope changed. Request approval again.")
    draft.status = "exported"
    draft.updated_at = datetime.now(UTC)
    session.add(draft)
    session.commit()
    receipts = [
        {
            "receipt_id": item.receipt_id,
            "skill_name": item.skill_name,
            "executed_at": item.executed_at,
            "opencode_session_id": item.opencode_session_id,
        }
        for item in get_agent_skill_receipts(session, workflow_run_id)
    ]
    return {
        "draft": draft,
        "approval": approval,
        "source_manifest": json.loads(draft.source_manifest_json),
        "skill_receipts": receipts,
        "limitations": [
            "This is a human-reviewable draft, not a final clinical, ethical, statistical, or publication decision.",
            "The draft is constrained to the recorded source manifest; unresolved items must be completed by a researcher.",
        ],
    }


def render_research_writing_bundle_markdown(bundle: dict[str, Any]) -> str:
    draft: ResearchWritingDraft = bundle["draft"]
    approval: ResearchWritingApproval = bundle["approval"]
    lines = [
        f"# {draft.title}",
        "",
        "## Draft Metadata",
        f"- Document type: {draft.document_type}",
        f"- Version: {draft.version_number}",
        f"- Target audience: {draft.target_audience or 'not_specified'}",
        f"- External approval: {approval.status} by {approval.approved_by or 'not_recorded'}",
        "",
        "## Source Manifest",
    ]
    lines.extend(
        f"- {item.get('source_type', 'unknown')} #{item.get('source_id', 'unknown')}: {item.get('description', 'no description')}"
        for item in bundle["source_manifest"]
    )
    lines.extend(["", "## Outline", draft.outline, "", "## Methods Draft", draft.methods_draft or "not_provided", "", "## Discussion Framework", draft.discussion_framework or "not_provided"])
    if draft.proposal_draft:
        lines.extend(["", "## Proposal Draft", draft.proposal_draft])
    if draft.review_draft:
        lines.extend(["", "## Review Article Draft", draft.review_draft])
    lines.extend(["", "## Limitations", draft.limitations, "", "## Unresolved Items", draft.unresolved_items, "", "## Verified Skill Execution Receipts"])
    if bundle["skill_receipts"]:
        lines.extend(
            f"- {item['skill_name']} | {item['executed_at'].isoformat()} | receipt {item['receipt_id']}"
            for item in bundle["skill_receipts"]
        )
    else:
        lines.append("- No signed Skill receipts were captured for this workflow run.")
    lines.extend(["", "## Export Limits"])
    lines.extend(f"- {item}" for item in bundle["limitations"])
    lines.append("")
    return "\n".join(lines)


BASE_WRITING_SKILLS = _BASE_SKILLS
PROPOSAL_SKILL = _PROPOSAL_SKILL
