from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import (
    AgentWorkflowEvent,
    BiasAssessment,
    BinaryMetaAnalysisRun,
    Citation,
    CitationSafetyCheck,
    EvidenceExtraction,
    FullTextDocument,
    FullTextEvidenceDetail,
    Project,
    ProjectStatus,
    ScreeningDecision,
)
from app.schemas import CitationSafetyCheckCreate, EvidenceExtractionCreate
from app.services.agent_workflows import (
    get_agent_skill_receipts,
    get_agent_workflow_run,
    record_agent_workflow_event,
    start_agent_workflow_run,
)
from app.services.literature_sources import check_pubmed_retraction_status
from app.services.phi_guard import assert_no_phi
from app.services.screening import latest_screening_decisions


_WORKFLOW_TYPE = "evidence_extraction"
_SUBJECT_TYPE = "review"
_EXTRACTION_SKILLS = {"clinical-study-info-extractor", "methodology-extractor"}
_RETRACTION_SKILL = {"retraction-watcher"}


def _project_or_raise(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise ValueError(f"Review project {project_id} not found.")
    return project


def included_citations(session: Session, project_id: int) -> list[Citation]:
    _project_or_raise(session, project_id)
    included_ids = {
        citation_id
        for citation_id, item in latest_screening_decisions(session, project_id).items()
        if item.decision == "include"
    }
    if not included_ids:
        return []
    return [
        citation
        for citation in session.exec(
            select(Citation).where(Citation.project_id == project_id).order_by(Citation.id)
        ).all()
        if citation.id in included_ids and not citation.is_deduplicated
    ]


def start_evidence_extraction_workflow_record(
    session: Session, project_id: int, actor: str = "mcp"
):
    project = _project_or_raise(session, project_id)
    if project.status not in {
        ProjectStatus.SCREENING_COMPLETED,
        ProjectStatus.PRISMA_GENERATED,
        ProjectStatus.EXPORTED,
    }:
        raise ValueError("Complete citation screening before starting evidence extraction.")
    if not included_citations(session, project_id):
        raise ValueError("At least one citation must be included before evidence extraction.")
    return start_agent_workflow_run(
        session, _WORKFLOW_TYPE, _SUBJECT_TYPE, project_id, actor=actor
    )


def validate_evidence_extractions(
    session: Session, project_id: int, extractions: list[EvidenceExtractionCreate]
) -> None:
    included_ids = {item.id for item in included_citations(session, project_id)}
    submitted_ids = [item.citation_id for item in extractions]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise ValueError("Each citation may have only one extraction per save operation.")
    unknown = sorted(set(submitted_ids) - included_ids)
    if unknown:
        raise ValueError(f"Evidence extraction requires included citations only: {unknown}.")
    for item in extractions:
        assert_no_phi(item.model_dump())
        if item.evidence_basis == "metadata" and item.effect_estimates:
            raise ValueError("Effect estimates require an abstract or full_text_excerpt evidence basis.")
        if item.evidence_basis == "metadata" and item.methods_summary:
            raise ValueError("Methods summary requires an abstract or full_text_excerpt evidence basis.")


def save_evidence_extractions_record(
    session: Session,
    project_id: int,
    workflow_run_id: str,
    extractions: list[EvidenceExtractionCreate],
    actor: str = "mcp",
) -> list[EvidenceExtraction]:
    get_agent_workflow_run(
        session, workflow_run_id, _WORKFLOW_TYPE, _SUBJECT_TYPE, project_id
    )
    validate_evidence_extractions(session, project_id, extractions)
    saved: list[EvidenceExtraction] = []
    for payload in extractions:
        record = session.exec(
            select(EvidenceExtraction).where(
                EvidenceExtraction.project_id == project_id,
                EvidenceExtraction.citation_id == payload.citation_id,
            )
        ).first()
        values = payload.model_dump(exclude={"missing_fields"})
        values["missing_fields_json"] = json.dumps(
            sorted(set(payload.missing_fields)), ensure_ascii=False
        )
        if record is None:
            record = EvidenceExtraction(project_id=project_id, **values)
        else:
            for field_name, value in values.items():
                setattr(record, field_name, value)
            record.updated_at = datetime.now(UTC)
        session.add(record)
        saved.append(record)
    session.commit()
    for record in saved:
        session.refresh(record)
    result = {
        "project_id": project_id,
        "saved_count": len(saved),
        "citation_ids": [item.citation_id for item in saved],
    }
    record_agent_workflow_event(
        session,
        workflow_run_id,
        _WORKFLOW_TYPE,
        _SUBJECT_TYPE,
        project_id,
        "save_evidence_extractions",
        {"count": len(extractions), "citation_ids": [item.citation_id for item in extractions]},
        result,
    )
    return saved


async def check_project_retractions_record(
    session: Session,
    project_id: int,
    workflow_run_id: str,
    actor: str = "mcp",
) -> list[CitationSafetyCheck]:
    get_agent_workflow_run(
        session, workflow_run_id, _WORKFLOW_TYPE, _SUBJECT_TYPE, project_id
    )
    checks: list[CitationSafetyCheck] = []
    for citation in included_citations(session, project_id):
        if citation.source == "pubmed" and citation.external_id:
            result = await check_pubmed_retraction_status(citation.external_id)
        else:
            result = {
                "status": "unavailable",
                "check_source": "pubmed_publication_type",
                "details": "Automated check requires a PubMed citation with a numeric PMID.",
            }
        record = session.exec(
            select(CitationSafetyCheck).where(
                CitationSafetyCheck.project_id == project_id,
                CitationSafetyCheck.citation_id == citation.id,
            )
        ).first()
        if record is None:
            record = CitationSafetyCheck(
                project_id=project_id,
                citation_id=citation.id,
                status=result["status"],
                check_source=result["check_source"],
                details=result["details"],
                needs_human_review=True,
            )
        else:
            record.status = result["status"]
            record.check_source = result["check_source"]
            record.details = result["details"]
            record.needs_human_review = True
            record.checked_at = datetime.now(UTC)
        session.add(record)
        checks.append(record)
    session.commit()
    for record in checks:
        session.refresh(record)
    result = {
        "project_id": project_id,
        "checked_count": len(checks),
        "statuses": {str(item.citation_id): item.status for item in checks},
    }
    record_agent_workflow_event(
        session,
        workflow_run_id,
        _WORKFLOW_TYPE,
        _SUBJECT_TYPE,
        project_id,
        "check_project_retractions",
        {"included_count": len(checks), "actor": actor},
        result,
    )
    return checks


def save_project_retraction_checks_record(
    session: Session,
    project_id: int,
    workflow_run_id: str,
    checks: list[CitationSafetyCheckCreate],
    actor: str = "mcp_client",
) -> list[CitationSafetyCheck]:
    """Persist PubMed notice checks performed by the desktop-local connector.

    The central backend intentionally does not repeat the network request in
    client_online mode. It validates the project/citation relationship and
    keeps the submitted result auditable instead.
    """
    get_agent_workflow_run(
        session, workflow_run_id, _WORKFLOW_TYPE, _SUBJECT_TYPE, project_id
    )
    included_ids = {citation.id for citation in included_citations(session, project_id)}
    submitted_ids = [item.citation_id for item in checks]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise ValueError("Each included citation may have only one safety check per save operation.")
    missing = sorted(included_ids - set(submitted_ids))
    unknown = sorted(set(submitted_ids) - included_ids)
    if missing or unknown:
        raise ValueError(
            "Client safety checks must cover exactly the included citations. "
            f"Missing: {missing}; unknown: {unknown}."
        )

    saved: list[CitationSafetyCheck] = []
    for payload in checks:
        assert_no_phi(payload.model_dump())
        record = session.exec(
            select(CitationSafetyCheck).where(
                CitationSafetyCheck.project_id == project_id,
                CitationSafetyCheck.citation_id == payload.citation_id,
            )
        ).first()
        if record is None:
            record = CitationSafetyCheck(
                project_id=project_id,
                citation_id=payload.citation_id,
                status=payload.status,
                check_source=payload.check_source,
                details=payload.details,
                needs_human_review=True,
            )
        else:
            record.status = payload.status
            record.check_source = payload.check_source
            record.details = payload.details
            record.needs_human_review = True
            record.checked_at = datetime.now(UTC)
        session.add(record)
        saved.append(record)
    session.commit()
    for record in saved:
        session.refresh(record)
    record_agent_workflow_event(
        session,
        workflow_run_id,
        _WORKFLOW_TYPE,
        _SUBJECT_TYPE,
        project_id,
        "save_project_retraction_checks",
        {"citation_ids": submitted_ids, "actor": actor},
        {"saved_count": len(saved), "citation_ids": submitted_ids},
    )
    return saved


def build_evidence_table_data(
    session: Session, project_id: int, workflow_run_id: str
) -> dict[str, Any]:
    get_agent_workflow_run(
        session, workflow_run_id, _WORKFLOW_TYPE, _SUBJECT_TYPE, project_id
    )
    citations = included_citations(session, project_id)
    if not citations:
        raise ValueError("No included citations are available for evidence export.")
    citation_ids = {item.id for item in citations}
    extraction_by_citation = {
        item.citation_id: item
        for item in session.exec(
            select(EvidenceExtraction).where(EvidenceExtraction.project_id == project_id)
        ).all()
    }
    check_by_citation = {
        item.citation_id: item
        for item in session.exec(
            select(CitationSafetyCheck).where(CitationSafetyCheck.project_id == project_id)
        ).all()
    }
    missing_extractions = sorted(citation_ids - extraction_by_citation.keys())
    missing_checks = sorted(citation_ids - check_by_citation.keys())
    if missing_extractions or missing_checks:
        raise ValueError(
            "Evidence export requires extraction and safety-check records for every included citation. "
            f"Missing extractions: {missing_extractions}; missing checks: {missing_checks}."
        )
    rows = []
    for citation in citations:
        extraction = extraction_by_citation[citation.id]
        check = check_by_citation[citation.id]
        rows.append(
            {
                "citation_id": citation.id,
                "title": citation.title,
                "external_id": citation.external_id,
                "doi": citation.doi,
                "study_design": extraction.study_design,
                "population": extraction.population,
                "sample_size": extraction.sample_size,
                "intervention_or_exposure": extraction.intervention_or_exposure,
                "comparator": extraction.comparator,
                "outcomes": extraction.outcomes,
                "effect_estimates": extraction.effect_estimates,
                "methods_summary": extraction.methods_summary,
                "evidence_basis": extraction.evidence_basis,
                "missing_fields": json.loads(extraction.missing_fields_json),
                "needs_human_review": extraction.needs_human_review,
                "safety_check": {
                    "status": check.status,
                    "check_source": check.check_source,
                    "details": check.details,
                    "needs_human_review": check.needs_human_review,
                },
            }
        )
    receipts = [
        {
            "receipt_id": item.receipt_id,
            "skill_name": item.skill_name,
            "executed_at": item.executed_at,
            "opencode_session_id": item.opencode_session_id,
        }
        for item in get_agent_skill_receipts(session, workflow_run_id)
    ]
    operations = {
        item.operation
        for item in session.exec(
            select(AgentWorkflowEvent).where(
                AgentWorkflowEvent.workflow_run_id == workflow_run_id
            )
        ).all()
    }
    full_text_ids = {
        item.citation_id
        for item in session.exec(
            select(FullTextDocument).where(FullTextDocument.project_id == project_id)
        ).all()
        if item.citation_id in citation_ids
    }
    detail_ids = {
        item.citation_id
        for item in session.exec(
            select(FullTextEvidenceDetail).where(FullTextEvidenceDetail.project_id == project_id)
        ).all()
        if item.citation_id in citation_ids
    }
    bias_ids = {
        item.citation_id
        for item in session.exec(
            select(BiasAssessment).where(BiasAssessment.project_id == project_id)
        ).all()
        if item.citation_id in citation_ids
    }
    meta_runs = [
        {
            "meta_analysis_id": item.id,
            "outcome_label": item.outcome_label,
            "effect_measure": item.effect_measure,
            "study_count": json.loads(item.result_json).get("study_count"),
            "needs_human_review": item.needs_human_review,
        }
        for item in session.exec(
            select(BinaryMetaAnalysisRun).where(
                BinaryMetaAnalysisRun.project_id == project_id,
                BinaryMetaAnalysisRun.workflow_run_id == workflow_run_id,
            )
        ).all()
    ]
    missing_full_text = sorted(citation_ids - full_text_ids)
    missing_details = sorted(citation_ids - detail_ids)
    missing_bias = sorted(citation_ids - bias_ids)
    available_full_text_ids = sorted(full_text_ids)
    evaluated_full_text_ids = sorted(full_text_ids & detail_ids & bias_ids)
    partial_full_text = bool(missing_full_text or missing_details or missing_bias)
    return {
        "project_id": project_id,
        "workflow_run_id": workflow_run_id,
        "rows": rows,
        "skill_receipts": receipts,
        "workflow_provenance": {
            "evidence_rows_saved_in_this_run": "save_evidence_extractions" in operations,
            "safety_checks_saved_in_this_run": "save_project_retraction_checks" in operations,
            "note": (
                "Evidence rows were reused from the persisted review project in this workflow run."
                if "save_evidence_extractions" not in operations
                else "Evidence rows were saved or refreshed in this workflow run."
            ),
        },
        "systematic_evaluation": {
            "included_count": len(citation_ids),
            "full_text_ready_count": len(full_text_ids),
            "detailed_extraction_count": len(detail_ids),
            "bias_assessment_count": len(bias_ids),
            "available_full_text_citation_ids": available_full_text_ids,
            "evaluated_full_text_citation_ids": evaluated_full_text_ids,
            "evidence_synthesis_scope": (
                "complete_systematic_review"
                if not partial_full_text
                else "available_full_text_only"
            ),
            "missing_full_text_citation_ids": missing_full_text,
            "missing_detail_citation_ids": missing_details,
            "missing_bias_citation_ids": missing_bias,
            "status": (
                "complete_full_text_assessment"
                if not partial_full_text
                else "partial_full_text_assessment"
            ),
            "meta_analyses_in_this_run": meta_runs,
        },
        "limitations": [
            "Fields are limited to the cited metadata, abstract, or user-supplied full-text excerpt basis recorded per row.",
            "PubMed safety checks report notice flags at check time and do not guarantee future citation safety.",
            "Human review remains required for every evidence row.",
            *( [
                "This is an available-full-text-only synthesis. Detailed findings, bias assessments, and any meta-analysis "
                "must be limited to citations with saved full-text details and bias assessments; unavailable full text is a coverage gap, not a scientific exclusion."
            ] if partial_full_text else [] ),
        ],
    }


def render_evidence_table_markdown(bundle: dict[str, Any]) -> str:
    lines = [
        f"# Evidence Table: Review Project {bundle['project_id']}",
        "",
        "## Evidence Rows",
        "",
        "| Citation | Design | Population | Sample Size | Outcome / Effect | Basis | Safety Check | Human Review |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in bundle["rows"]:
        outcome = row["effect_estimates"] or row["outcomes"] or "not_reported"
        safety = row["safety_check"]["status"]
        lines.append(
            "| {title} | {design} | {population} | {sample} | {outcome} | {basis} | {safety} | {review} |".format(
                title=(row["title"] or "").replace("|", "\\|"),
                design=row["study_design"] or "not_reported",
                population=row["population"] or "not_reported",
                sample=row["sample_size"] or "not_reported",
                outcome=outcome.replace("|", "\\|"),
                basis=row["evidence_basis"],
                safety=safety,
                review="required" if row["needs_human_review"] else "not_marked",
            )
        )
    provenance = bundle["workflow_provenance"]
    systematic = bundle["systematic_evaluation"]
    lines.extend(
        [
            "",
            "## Workflow Provenance",
            f"- Evidence rows saved in this run: {'yes' if provenance['evidence_rows_saved_in_this_run'] else 'no'}",
            f"- Safety checks saved in this run: {'yes' if provenance['safety_checks_saved_in_this_run'] else 'no'}",
            f"- {provenance['note']}",
            "",
            "## Full-Text Systematic Evaluation Status",
            f"- Status: {systematic['status']}",
            f"- Evidence synthesis scope: {systematic['evidence_synthesis_scope']}",
            f"- Full text ready: {systematic['full_text_ready_count']}/{systematic['included_count']}",
            f"- Fully evaluated full-text citation IDs: {systematic['evaluated_full_text_citation_ids'] or 'none'}",
            f"- Detailed extraction: {systematic['detailed_extraction_count']}/{systematic['included_count']}",
            f"- Bias assessment: {systematic['bias_assessment_count']}/{systematic['included_count']}",
            f"- Missing full text citation IDs: {systematic['missing_full_text_citation_ids'] or 'none'}",
            f"- Missing detailed extraction citation IDs: {systematic['missing_detail_citation_ids'] or 'none'}",
            f"- Missing bias assessment citation IDs: {systematic['missing_bias_citation_ids'] or 'none'}",
        ]
    )
    if systematic["evidence_synthesis_scope"] == "available_full_text_only":
        lines.extend([
            "- Interpretation boundary: 基于可获取全文的部分证据综合，非完整系统评价。",
            "- Detailed findings, quality assessments, and any Meta analysis apply only to the fully evaluated full-text citation IDs above.",
        ])
    if systematic["meta_analyses_in_this_run"]:
        lines.append("")
        lines.append("## Exploratory Binary Meta-Analysis")
        for item in systematic["meta_analyses_in_this_run"]:
            lines.append(
                "- {outcome} | {measure} | {count} studies | human review required".format(
                    outcome=item["outcome_label"],
                    measure=item["effect_measure"].upper(),
                    count=item["study_count"],
                )
            )
        lines.append("- This is not a complete systematic review unless every included citation has full text, detailed extraction, and bias assessment.")
    lines.extend(["", "## Limitations"])
    lines.extend(f"- {item}" for item in bundle["limitations"])
    lines.extend(["", "## Verified Skill Execution Receipts"])
    if bundle["skill_receipts"]:
        lines.extend(
            f"- {item['skill_name']} | {item['executed_at'].isoformat()} | receipt {item['receipt_id']}"
            for item in bundle["skill_receipts"]
        )
    else:
        lines.append("- No signed Skill receipts were captured for this workflow run.")
    lines.append("")
    return "\n".join(lines)


EXTRACTION_SKILLS = _EXTRACTION_SKILLS
RETRACTION_SKILL = _RETRACTION_SKILL
