from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlmodel import Session

from app.db import engine, init_db
from app.models import ResearchWritingDraft
from app.schemas import (
    EvidenceExtractionCreate,
    ProjectCreate,
    ProjectRead,
    ResearchWritingDraftCreate,
    ScreeningDecisionCreate,
    SearchStrategyRead,
    StudyDesignContentUpdate,
    StudyDesignProjectCreate,
    StudyDesignProjectRead,
)
from app.services.agent_workflows import (
    import_agent_skill_execution_receipts_from_session,
    record_agent_workflow_event,
    require_agent_skill_receipts,
)
from app.services.citations import CitationImportPayload
from app.services.evidence_extraction import (
    EXTRACTION_SKILLS,
    RETRACTION_SKILL,
    build_evidence_table_data,
    check_project_retractions_record,
    render_evidence_table_markdown,
    save_evidence_extractions_record,
    start_evidence_extraction_workflow_record,
)
from app.services.research_writing import (
    build_research_writing_bundle_data,
    get_research_writing_source_data,
    render_research_writing_bundle_markdown,
    request_research_writing_approval_record,
    required_writing_skills,
    research_writing_approval_snapshot,
    save_research_writing_draft_record,
    start_research_writing_workflow_record,
)
from app.services.exporters import (
    build_review_bundle_data,
    render_review_bundle_markdown,
    write_review_bundle_markdown,
)
from app.services.literature_sources import (
    fetch_paper_metadata_record,
    search_europepmc_records,
    search_pubmed_records,
)
from app.services.project_workflow import (
    create_project_record,
    deduplicate_project_record,
    generate_search_strategy_record,
    import_citations_record,
    submit_screening_decisions_record,
)
from app.services.study_design import (
    approval_snapshot,
    build_study_design_bundle_data,
    calculate_study_sample_size_record,
    create_study_design_project_record,
    generate_rct_randomization_record,
    generate_study_design_blueprint_record,
    import_skill_execution_receipts,
    import_skill_execution_receipts_from_session,
    record_study_design_workflow_event,
    render_study_design_bundle_markdown,
    require_skill_receipts,
    request_study_design_approval_record,
    save_study_design_content_record,
    save_rct_randomization_plan_record,
    start_study_design_workflow_run,
)
from app.services.phi_guard import assert_deidentified_attestation

logging.basicConfig(level=logging.INFO)

mcp = FastMCP("literature_review")
init_db()

_MAX_AGENT_ABSTRACT_CHARS = 1_200


def _compact_records_for_agent(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep search results usable for selection without overloading model context."""
    compact_records: list[dict[str, Any]] = []
    for record in records:
        compact_record = dict(record)
        abstract = compact_record.get("abstract") or ""
        if len(abstract) > _MAX_AGENT_ABSTRACT_CHARS:
            compact_record["abstract"] = f"{abstract[:_MAX_AGENT_ABSTRACT_CHARS - 3].rstrip()}..."
        compact_records.append(compact_record)
    return compact_records


@mcp.tool()
def create_review_project(
    title: str,
    research_question: str,
    pico_population: str | None = None,
    pico_intervention: str | None = None,
    pico_comparator: str | None = None,
    pico_outcome: str | None = None,
    inclusion_criteria: str | None = None,
    exclusion_criteria: str | None = None,
) -> dict[str, Any]:
    """Create a literature review project in the local backend database."""
    payload = ProjectCreate(
        title=title,
        research_question=research_question,
        pico_population=pico_population,
        pico_intervention=pico_intervention,
        pico_comparator=pico_comparator,
        pico_outcome=pico_outcome,
        inclusion_criteria=inclusion_criteria,
        exclusion_criteria=exclusion_criteria,
    )
    with Session(engine) as session:
        project = create_project_record(session, payload, actor="mcp")
    return {
        "project": ProjectRead.model_validate(project).model_dump(),
    }


@mcp.tool()
def generate_project_search_strategy(project_id: int) -> dict[str, Any]:
    """Generate a PubMed search strategy for a project."""
    with Session(engine) as session:
        strategy = generate_search_strategy_record(session, project_id, actor="mcp")
    return {
        "project_id": project_id,
        "search_strategy": SearchStrategyRead.model_validate(strategy).model_dump(),
    }


@mcp.tool()
def import_citations_to_project(
    project_id: int,
    source: str,
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Import normalized citation records into a project."""
    payload = CitationImportPayload.model_validate(
        {
            "source": source,
            "citations": citations,
        }
    )
    with Session(engine) as session:
        imported_citations = import_citations_record(session, project_id, payload, actor="mcp")
    return {
        "project_id": project_id,
        "source": source,
        "imported_count": len(imported_citations),
        "citations": [
            {
                "id": citation.id,
                "external_id": citation.external_id,
                "title": citation.title,
            }
            for citation in imported_citations
        ],
    }


@mcp.tool()
def deduplicate_project_citations(project_id: int) -> dict[str, Any]:
    """Deduplicate imported citations for a project."""
    with Session(engine) as session:
        removed_count = deduplicate_project_record(session, project_id, actor="mcp")
    return {
        "project_id": project_id,
        "removed_count": removed_count,
    }


@mcp.tool()
def submit_screening_decisions(
    project_id: int,
    decisions: list[dict[str, Any]],
    actor: str = "mcp_reviewer",
) -> dict[str, Any]:
    """Submit one or more screening decisions and refresh PRISMA counts."""
    decision_models = [
        ScreeningDecisionCreate.model_validate(
            {
                **item,
                "actor": item.get("actor", actor),
            }
        )
        for item in decisions
    ]
    with Session(engine) as session:
        result = submit_screening_decisions_record(
            session,
            project_id,
            decision_models,
            actor=actor,
        )
    return {
        "project_id": project_id,
        **result,
    }


@mcp.tool()
async def search_pubmed(query: str, limit: int = 5) -> dict[str, Any]:
    """Search PubMed and return normalized metadata records.

    Args:
        query: PubMed search query.
        limit: Max number of records to return, capped at 20.
    """
    records = await search_pubmed_records(query, limit=limit)
    return {
        "source": "pubmed",
        "query": query,
        "returned_count": len(records),
        "records": _compact_records_for_agent(records),
    }


@mcp.tool()
async def search_europepmc(query: str, limit: int = 5) -> dict[str, Any]:
    """Search Europe PMC and return normalized metadata records.

    Args:
        query: Europe PMC query syntax.
        limit: Max number of records to return, capped at 20.
    """
    records = await search_europepmc_records(query, limit=limit)
    return {
        "source": "europe_pmc",
        "query": query,
        "returned_count": len(records),
        "records": _compact_records_for_agent(records),
    }


@mcp.tool()
async def fetch_paper_metadata(identifier: str, source: str = "auto") -> dict[str, Any]:
    """Fetch one paper's metadata by PMID, DOI, or external identifier.

    Args:
        identifier: PMID, DOI, or another paper identifier.
        source: One of auto, pubmed, or europe_pmc.
    """
    record = await fetch_paper_metadata_record(identifier, source=source)
    return {
        "identifier": identifier,
        "source_hint": source,
        "found": bool(record),
        "record": record,
    }


@mcp.tool()
def export_review_bundle(
    project_id: int,
    format: str = "markdown",
    output_path: str | None = None,
) -> dict[str, Any]:
    """Export a literature review project bundle from the local SQLite workspace.

    Args:
        project_id: Local project id in the literature review backend database.
        format: markdown or json.
        output_path: Optional file path for markdown export.
    """
    with Session(engine) as session:
        bundle = build_review_bundle_data(session, project_id)

    if not bundle:
        raise ValueError(f"Project {project_id} not found.")

    normalized_format = format.strip().lower()
    if normalized_format == "json":
        return {
            "project_id": project_id,
            "format": "json",
            "bundle": bundle,
        }

    if normalized_format != "markdown":
        raise ValueError("format must be 'markdown' or 'json'.")

    markdown = render_review_bundle_markdown(bundle)
    result: dict[str, Any] = {
        "project_id": project_id,
        "format": "markdown",
        "markdown": markdown,
    }
    if output_path:
        result["output_path"] = write_review_bundle_markdown(markdown, output_path)
    return result


@mcp.tool()
def start_evidence_extraction_workflow(
    project_id: int,
    opencode_session_id: str | None = None,
) -> dict[str, Any]:
    """Start a persisted evidence-extraction workflow for a screened review project."""
    with Session(engine) as session:
        run = start_evidence_extraction_workflow_record(session, project_id, actor="mcp")
        import_agent_skill_execution_receipts_from_session(
            session,
            run.run_id,
            "evidence_extraction",
            "review",
            project_id,
            opencode_session_id,
        )
        result = {
            "project_id": project_id,
            "workflow": {
                "run_id": run.run_id,
                "workflow_type": "evidence_extraction",
                "subject_type": "review",
                "subject_id": project_id,
                "operation": "start_evidence_extraction_workflow",
            },
        }
        record_agent_workflow_event(
            session,
            run.run_id,
            "evidence_extraction",
            "review",
            project_id,
            "start_evidence_extraction_workflow",
            {},
            result,
        )
    return result


@mcp.tool()
def save_evidence_extractions(
    project_id: int,
    workflow_run_id: str,
    extractions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Save source-bounded study characteristics for included review citations."""
    payloads = [EvidenceExtractionCreate.model_validate(item) for item in extractions]
    with Session(engine) as session:
        require_agent_skill_receipts(
            session,
            workflow_run_id,
            "evidence_extraction",
            "review",
            project_id,
            "evidence_extraction",
            EXTRACTION_SKILLS,
        )
        records = save_evidence_extractions_record(
            session, project_id, workflow_run_id, payloads, actor="mcp"
        )
        result = {
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "saved_count": len(records),
            "citation_ids": [item.citation_id for item in records],
        }
    return result


@mcp.tool()
async def check_project_retractions(
    project_id: int,
    workflow_run_id: str,
) -> dict[str, Any]:
    """Run a PubMed notice-type safety check for every included citation."""
    with Session(engine) as session:
        require_agent_skill_receipts(
            session,
            workflow_run_id,
            "evidence_extraction",
            "review",
            project_id,
            "retraction_check",
            RETRACTION_SKILL,
        )
        checks = await check_project_retractions_record(
            session, project_id, workflow_run_id, actor="mcp"
        )
        result = {
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "checked_count": len(checks),
            "checks": [
                {
                    "citation_id": item.citation_id,
                    "status": item.status,
                    "check_source": item.check_source,
                    "details": item.details,
                    "needs_human_review": item.needs_human_review,
                }
                for item in checks
            ],
        }
    return result


@mcp.tool()
def export_evidence_table(
    project_id: int,
    workflow_run_id: str,
    format: str = "markdown",
) -> dict[str, Any]:
    """Export a verified, source-bounded evidence table after safety checks."""
    if format not in {"markdown", "json"}:
        raise ValueError("format must be 'markdown' or 'json'.")
    with Session(engine) as session:
        require_agent_skill_receipts(
            session,
            workflow_run_id,
            "evidence_extraction",
            "review",
            project_id,
            "evidence_export",
            EXTRACTION_SKILLS | RETRACTION_SKILL,
        )
        bundle = build_evidence_table_data(session, project_id, workflow_run_id)
        if format == "markdown":
            result = {
                "project_id": project_id,
                "workflow_run_id": workflow_run_id,
                "format": "markdown",
                "markdown": render_evidence_table_markdown(bundle),
            }
        else:
            result = {
                "project_id": project_id,
                "workflow_run_id": workflow_run_id,
                "format": "json",
                "bundle": bundle,
            }
        record_agent_workflow_event(
            session,
            workflow_run_id,
            "evidence_extraction",
            "review",
            project_id,
            "export_evidence_table",
            {"format": format},
            result,
        )
    return result


@mcp.tool()
def start_research_writing_workflow(
    source_type: str,
    source_id: int,
    document_type: str,
    opencode_session_id: str | None = None,
) -> dict[str, Any]:
    """Start a persisted writing workflow from a study-design or evidence-review source."""
    with Session(engine) as session:
        run = start_research_writing_workflow_record(
            session, source_type, source_id, document_type, actor="mcp"
        )
        import_agent_skill_execution_receipts_from_session(
            session,
            run.run_id,
            "research_writing",
            source_type,
            source_id,
            opencode_session_id,
        )
        result = {
            "source_type": source_type,
            "source_id": source_id,
            "document_type": document_type,
            "workflow": {
                "run_id": run.run_id,
                "workflow_type": "research_writing",
                "subject_type": source_type,
                "subject_id": source_id,
                "operation": "start_research_writing_workflow",
            },
        }
        record_agent_workflow_event(
            session,
            run.run_id,
            "research_writing",
            source_type,
            source_id,
            "start_research_writing_workflow",
            {"document_type": document_type},
            result,
        )
    return result


@mcp.tool()
def get_research_writing_source(source_type: str, source_id: int) -> dict[str, Any]:
    """Read the persisted, source-bounded facts available to a writing workflow."""
    with Session(engine) as session:
        return get_research_writing_source_data(session, source_type, source_id)


@mcp.tool()
def save_research_writing_draft(
    source_type: str,
    source_id: int,
    workflow_run_id: str,
    document_type: str,
    draft: dict[str, Any],
) -> dict[str, Any]:
    """Persist a versioned, source-manifest-bound research writing draft."""
    payload = ResearchWritingDraftCreate.model_validate(draft)
    with Session(engine) as session:
        require_agent_skill_receipts(
            session,
            workflow_run_id,
            "research_writing",
            source_type,
            source_id,
            "research_writing_draft",
            required_writing_skills(document_type),
        )
        record = save_research_writing_draft_record(
            session,
            source_type,
            source_id,
            workflow_run_id,
            document_type,
            payload,
            actor="mcp",
        )
        result = {
            "draft_id": record.id,
            "workflow_run_id": workflow_run_id,
            "document_type": record.document_type,
            "version_number": record.version_number,
            "status": record.status,
        }
    return result


@mcp.tool()
def request_research_writing_approval(
    draft_id: int,
    workflow_run_id: str,
) -> dict[str, Any]:
    """Request external human approval; the Agent cannot approve a writing draft itself."""
    with Session(engine) as session:
        approval = request_research_writing_approval_record(
            session, draft_id, workflow_run_id, actor="mcp"
        )
        result = {
            "draft_id": draft_id,
            "workflow_run_id": workflow_run_id,
            "approval": {
                "status": approval.status,
                "requested_at": approval.requested_at,
                "scope_digest": approval.scope_digest,
            },
            "next_step": "An authorized operator must approve through the protected REST endpoint before export.",
        }
    return result


@mcp.tool()
def get_research_writing_approval_status(draft_id: int) -> dict[str, Any]:
    """Read external writing-draft approval status without exposing credentials."""
    with Session(engine) as session:
        return research_writing_approval_snapshot(session, draft_id)


@mcp.tool()
def export_research_writing_bundle(
    draft_id: int,
    workflow_run_id: str,
    format: str = "markdown",
) -> dict[str, Any]:
    """Export an externally approved, versioned research-writing draft."""
    if format not in {"markdown", "json"}:
        raise ValueError("format must be 'markdown' or 'json'.")
    with Session(engine) as session:
        draft_record = session.get(ResearchWritingDraft, draft_id)
        if not draft_record:
            raise ValueError(f"Research-writing draft {draft_id} not found.")
        if draft_record.workflow_run_id != workflow_run_id:
            raise ValueError("workflow_run_id does not belong to this writing draft.")
        require_agent_skill_receipts(
            session,
            workflow_run_id,
            "research_writing",
            draft_record.source_type,
            draft_record.source_id,
            "research_writing_export",
            required_writing_skills(draft_record.document_type),
        )
        bundle = build_research_writing_bundle_data(session, draft_id, workflow_run_id)
        if format == "markdown":
            result = {
                "draft_id": draft_id,
                "workflow_run_id": workflow_run_id,
                "format": "markdown",
                "markdown": render_research_writing_bundle_markdown(bundle),
            }
        else:
            result = {
                "draft_id": draft_id,
                "workflow_run_id": workflow_run_id,
                "format": "json",
                "bundle": bundle,
            }
        record_agent_workflow_event(
            session,
            workflow_run_id,
            "research_writing",
            bundle["draft"].source_type,
            bundle["draft"].source_id,
            "export_research_writing_bundle",
            {"draft_id": draft_id, "format": format},
            result,
        )
    return result


@mcp.tool()
def create_study_design_project(
    title: str,
    research_question: str,
    study_type: str,
    study_design: str,
    population: str,
    outcome: str,
    intervention: str | None = None,
    comparator: str | None = None,
    department: str | None = None,
    resource_summary: str | None = None,
    data_attestation: str = "",
    opencode_session_id: str | None = None,
) -> dict[str, Any]:
    """Create a de-identified clinical study-design project and start a traceable workflow run."""
    assert_deidentified_attestation(data_attestation)
    payload = StudyDesignProjectCreate.model_validate(
        {
            "title": title,
            "research_question": research_question,
            "study_type": study_type,
            "study_design": study_design,
            "population": population,
            "outcome": outcome,
            "intervention": intervention,
            "comparator": comparator,
            "department": department,
            "resource_summary": resource_summary,
        }
    )
    with Session(engine) as session:
        project = create_study_design_project_record(session, payload, actor="mcp")
        run = start_study_design_workflow_run(session, project.id, actor="mcp")
        import_skill_execution_receipts_from_session(session, run.run_id, project.id, opencode_session_id)
        result = {"project": StudyDesignProjectRead.model_validate(project).model_dump(), "workflow": {"run_id": run.run_id, "project_id": project.id, "operation": "create_study_design_project"}}
        record_study_design_workflow_event(session, run.run_id, project.id, "create_study_design_project", {"data_attestation": data_attestation}, result)
    return result


def _record_study_tool_result(session: Session, workflow_run_id: str, project_id: int, operation: str, inputs: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    import_skill_execution_receipts(session, workflow_run_id, project_id)
    result["workflow"] = {"run_id": workflow_run_id, "project_id": project_id, "operation": operation}
    record_study_design_workflow_event(session, workflow_run_id, project_id, operation, inputs, result)
    return result


@mcp.tool()
def generate_study_design_blueprint(project_id: int, workflow_run_id: str) -> dict[str, Any]:
    """Generate the reporting-standard checklist and protocol skeleton for a study-design project."""
    with Session(engine) as session:
        require_skill_receipts(session, workflow_run_id, project_id, "blueprint")
        result = generate_study_design_blueprint_record(session, project_id, actor="mcp")
        return _record_study_tool_result(session, workflow_run_id, project_id, "generate_study_design_blueprint", {}, result)


@mcp.tool()
def save_study_design_content(
    project_id: int,
    workflow_run_id: str,
    inclusion_criteria: str,
    exclusion_criteria: str,
    primary_outcome: str,
    proposal_outline: str,
    secondary_outcomes: str | None = None,
    innovation_notes: str | None = None,
    feasibility_notes: str | None = None,
) -> dict[str, Any]:
    """Persist the agent-drafted, human-reviewable protocol content in the local project record."""
    payload = StudyDesignContentUpdate(
        inclusion_criteria=inclusion_criteria,
        exclusion_criteria=exclusion_criteria,
        primary_outcome=primary_outcome,
        proposal_outline=proposal_outline,
        secondary_outcomes=secondary_outcomes,
        innovation_notes=innovation_notes,
        feasibility_notes=feasibility_notes,
    )
    with Session(engine) as session:
        require_skill_receipts(session, workflow_run_id, project_id, "content")
        project = save_study_design_content_record(session, project_id, payload, actor="mcp")
        return _record_study_tool_result(session, workflow_run_id, project_id, "save_study_design_content", payload.model_dump(), {"project": StudyDesignProjectRead.model_validate(project).model_dump()})


@mcp.tool()
def calculate_study_sample_size(
    project_id: int,
    workflow_run_id: str,
    method: str,
    group_one_value: float,
    group_two_value: float,
    alpha: float = 0.05,
    power: float = 0.8,
    standard_deviation: float | None = None,
) -> dict[str, Any]:
    """Calculate basic equal-allocation two-group sample size for means or proportions."""
    with Session(engine) as session:
        require_skill_receipts(session, workflow_run_id, project_id, "sample_size")
        result = calculate_study_sample_size_record(
            session,
            project_id,
            method,
            alpha,
            power,
            group_one_value,
            group_two_value,
            standard_deviation,
            actor="mcp",
        )
        return _record_study_tool_result(session, workflow_run_id, project_id, "calculate_study_sample_size", {"method": method, "group_one_value": group_one_value, "group_two_value": group_two_value, "alpha": alpha, "power": power, "standard_deviation": standard_deviation}, {"project_id": project_id, "sample_size": result})


@mcp.tool()
def save_rct_randomization_plan(
    project_id: int,
    workflow_run_id: str,
    total_subjects: int,
    groups: list[str],
    block_size: int,
) -> dict[str, Any]:
    """Save an RCT randomization plan. This does not generate or reveal allocations."""
    with Session(engine) as session:
        require_skill_receipts(session, workflow_run_id, project_id, "randomization")
        plan = save_rct_randomization_plan_record(session, project_id, total_subjects, groups, block_size, actor="mcp")
        result = {"project_id": project_id, "randomization_plan": {"total_subjects": plan.total_subjects, "groups": groups, "block_size": plan.block_size, "allocations_generated": False}}
        return _record_study_tool_result(session, workflow_run_id, project_id, "save_rct_randomization_plan", {"total_subjects": total_subjects, "groups": groups, "block_size": block_size}, result)


@mcp.tool()
def request_study_design_approval(project_id: int, workflow_run_id: str) -> dict[str, Any]:
    """Request external human approval. The MCP agent cannot approve a project itself."""
    with Session(engine) as session:
        approval = request_study_design_approval_record(session, project_id, actor="mcp")
        result = {"project_id": project_id, "approval": {"status": approval.status, "requested_at": approval.requested_at, "scope_digest": approval.scope_digest}, "next_step": "An authorized operator must approve through the protected REST endpoint before allocations can be generated or the bundle exported."}
        return _record_study_tool_result(session, workflow_run_id, project_id, "request_study_design_approval", {}, result)


@mcp.tool()
def get_study_design_approval_status(project_id: int, workflow_run_id: str) -> dict[str, Any]:
    """Read external approval status without exposing approval credentials or allocations."""
    with Session(engine) as session:
        result = approval_snapshot(session, project_id)
        return _record_study_tool_result(session, workflow_run_id, project_id, "get_study_design_approval_status", {}, result)


@mcp.tool()
def generate_rct_randomization_schedule(project_id: int, workflow_run_id: str) -> dict[str, Any]:
    """Generate a concealed schedule only after external approval; allocations are never returned to the agent."""
    with Session(engine) as session:
        result = {"project_id": project_id, "randomization_schedule": generate_rct_randomization_record(session, project_id, actor="mcp")}
        return _record_study_tool_result(session, workflow_run_id, project_id, "generate_rct_randomization_schedule", {}, result)


@mcp.tool()
def export_study_design_bundle(project_id: int, workflow_run_id: str, format: str = "markdown") -> dict[str, Any]:
    """Export an externally approved bundle; allocation sequence remains redacted."""
    if format not in {"markdown", "json"}:
        raise ValueError("format must be 'markdown' or 'json'.")
    with Session(engine) as session:
        import_skill_execution_receipts(session, workflow_run_id, project_id)
        bundle = build_study_design_bundle_data(session, project_id, workflow_run_id)
        if not bundle:
            raise ValueError(f"Study design project {project_id} not found.")
        project = StudyDesignProjectRead.model_validate(bundle["project"]).model_dump()
        if format == "json":
            result = {
                "project_id": project_id,
                "format": "json",
                "project": project,
                "sample_size": bundle["sample_size"],
                "approval": {"status": bundle["approval"].status, "approved_by": bundle["approval"].approved_by},
                "randomization_plan": bundle["randomization_plan"],
                "randomization_schedule_metadata": bundle["randomization_schedule_metadata"],
                "skill_receipts": bundle["skill_receipts"],
                "audit_logs": bundle["audit_logs"],
            }
        else:
            result = {"project_id": project_id, "format": "markdown", "markdown": render_study_design_bundle_markdown(bundle)}
        return _record_study_tool_result(session, workflow_run_id, project_id, "export_study_design_bundle", {"format": format}, result)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
