from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import (
    Citation,
    CitationSafetyCheck,
    EvidenceExtraction,
    Project,
    ProjectStatus,
    ScreeningDecision,
)
from app.schemas import EvidenceExtractionCreate
from app.services.agent_workflows import (
    get_agent_skill_receipts,
    get_agent_workflow_run,
    record_agent_workflow_event,
    start_agent_workflow_run,
)
from app.services.literature_sources import check_pubmed_retraction_status
from app.services.phi_guard import assert_no_phi


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
        item.citation_id
        for item in session.exec(
            select(ScreeningDecision).where(
                ScreeningDecision.project_id == project_id,
                ScreeningDecision.decision == "include",
            )
        ).all()
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
    return {
        "project_id": project_id,
        "workflow_run_id": workflow_run_id,
        "rows": rows,
        "skill_receipts": receipts,
        "limitations": [
            "Fields are limited to the cited metadata, abstract, or user-supplied full-text excerpt basis recorded per row.",
            "PubMed safety checks report notice flags at check time and do not guarantee future citation safety.",
            "Human review remains required for every evidence row.",
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
