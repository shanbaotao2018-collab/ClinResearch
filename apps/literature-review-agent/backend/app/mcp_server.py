from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlmodel import Session, select

from app.db import engine
from app.config import settings
from app.models import Citation, Project, ResearchWritingDraft, StudyDesignProject
from app.schemas import (
    BiasAssessmentCreate,
    EvidenceExtractionCreate,
    CitationSafetyCheckCreate,
    FullTextPreflightCreate,
    FullTextDocumentCreate,
    FullTextEvidenceDetailCreate,
    ProjectCreate,
    ProjectRead,
    ResearchWritingDraftCreate,
    ScreeningDecisionCreate,
    SearchStrategyCreate,
    SearchStrategyRead,
    StudyDesignContentUpdate,
    StudyDesignProjectCreate,
    StudyDesignProjectRead,
)
from app.services.agent_workflows import (
    get_agent_workflow_run,
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
    save_project_retraction_checks_record,
    start_evidence_extraction_workflow_record,
)
from app.services.systematic_evaluation import (
    BIAS_SKILLS,
    DETAIL_EXTRACTION_SKILLS,
    FULL_TEXT_FETCH_SKILL,
    FULL_TEXT_SCREENING_SKILL,
    META_ANALYSIS_SKILLS,
    PDF_EXTRACTION_SKILL,
    build_systematic_evidence_bundle_data,
    render_systematic_evidence_bundle_markdown,
    request_systematic_evidence_review_record,
    require_systematic_evidence_approval,
    required_bias_skills_for_project,
    run_binary_meta_analysis_record,
    save_bias_assessments_record,
    save_full_text_documents_record,
    save_full_text_evidence_details_record,
    systematic_evidence_review_snapshot,
)
from app.services.research_writing import (
    approve_research_writing_record,
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
from app.services.citation_files import parse_citation_file
from app.services.literature_sources import (
    fetch_paper_metadata_record,
    fetch_europepmc_open_access_full_text,
    search_europepmc_records,
    search_pubmed_records,
)
from app.services.literature_access import literature_access_status
from app.services.full_text_preflight import (
    get_full_text_preflight_records,
    save_full_text_preflight_record,
)
from app.services.next_actions import get_next_actions as get_next_actions_record
from app.services.offline_evidence_packages import (
    import_offline_evidence_package_record,
    list_offline_evidence_packages as list_offline_evidence_package_records,
    load_offline_package_documents,
)
from app.services.project_workflow import (
    create_project_record,
    deduplicate_project_record,
    generate_search_strategy_record,
    import_citations_record,
    save_search_strategy_record,
    submit_screening_decisions_record,
)
from app.services.formal_retrieval import formal_retrieval_readiness
from app.services.project_context import get_agent_project_context_record
from app.services.screening import latest_screening_decisions, list_pending_screening_batch
from app.services.research_cases import (
    create_research_case_record,
    get_research_case_record,
    link_research_case_record,
)
from app.services.study_design import (
    approve_study_design_record,
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

# This server is mounted by app.main at /mcp. Keep the transport path at /
# because the FastAPI mount already supplies the public /mcp prefix.
mcp = FastMCP("literature_review", streamable_http_path="/")

_MAX_AGENT_ABSTRACT_CHARS = 1_200
_BACKEND_URL = os.getenv("LRA_BACKEND_URL", "http://127.0.0.1:8010").rstrip("/")


def _post_human_approval(
    path: str,
    header_name: str,
    key_env_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Bridge a permission-gated MCP call to the protected approval API.

    The approval key is read by the local MCP process and is never a tool
    argument, so it cannot be placed in the model context.
    """
    approval_key = os.getenv(key_env_name)
    if not approval_key:
        raise ValueError(
            f"{key_env_name} is not configured for the local approval bridge."
        )
    request = urllib.request.Request(
        f"{_BACKEND_URL}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            header_name: approval_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ValueError(f"Approval endpoint rejected the request: {detail}") from error
    except urllib.error.URLError as error:
        raise ValueError("Approval backend is unavailable at the configured local URL.") from error


def _get_human_approval_snapshot(path: str) -> dict[str, Any]:
    request = urllib.request.Request(f"{_BACKEND_URL}{path}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError) as error:
        raise ValueError("Approval backend is unavailable or rejected the status request.") from error


def _assert_current_scope(snapshot: dict[str, Any], scope_digest: str) -> None:
    approval = snapshot.get("approval") or {}
    if approval.get("status") != "pending":
        raise ValueError("This approval is not pending.")
    if approval.get("scope_digest") != scope_digest:
        raise ValueError("Approval scope changed; refresh the approval request before confirming.")


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


def _normalize_evidence_extraction_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Accept the Agent's common `fields` envelope without silently dropping evidence.

    The persisted schema deliberately uses explicit, source-bound columns. The
    Agent commonly groups those same values under `fields`; normalize that
    representation before Pydantic validation so a successful MCP call cannot
    result in an empty evidence row.
    """
    normalized = dict(item)
    fields = normalized.pop("fields", None)
    if fields is not None:
        if not isinstance(fields, dict):
            raise ValueError("Evidence extraction 'fields' must be an object when supplied.")
        for key, value in fields.items():
            normalized.setdefault(key, value)

    aliases = {
        "intervention": "intervention_or_exposure",
        "primary_outcome": "outcomes",
        "key_finding": "methods_summary",
        "population_summary": "population",
        "intervention_summary": "intervention_or_exposure",
        "comparator_summary": "comparator",
        "outcome_summary": "outcomes",
        "design_summary": "study_design",
        "key_findings": "methods_summary",
    }
    for source_key, target_key in aliases.items():
        if source_key in normalized and target_key not in normalized:
            normalized[target_key] = normalized[source_key]

    if "sample_size" not in normalized:
        intervention_n = normalized.get("sample_size_intervention")
        comparator_n = normalized.get("sample_size_comparator")
        if intervention_n is not None or comparator_n is not None:
            normalized["sample_size"] = f"intervention={intervention_n}; comparator={comparator_n}"
    elif normalized["sample_size"] is not None and not isinstance(normalized["sample_size"], str):
        normalized["sample_size"] = str(normalized["sample_size"])
    missing_fields = normalized.get("missing_fields")
    if isinstance(missing_fields, str):
        normalized["missing_fields"] = [
            value.strip() for value in missing_fields.split(",") if value.strip()
        ]
    evidence_basis = normalized.get("evidence_basis")
    if isinstance(evidence_basis, str):
        basis = evidence_basis.strip().casefold()
        if basis in {"pubmed摘要", "pubmed全文摘要", "摘要", "abstract"} or "摘要" in basis:
            normalized["evidence_basis"] = "abstract"
        elif basis in {"metadata", "元数据"} or "元数据" in basis:
            normalized["evidence_basis"] = "metadata"
        elif basis in {"full_text_excerpt", "全文", "全文节选", "全文摘录"} or "全文" in basis:
            normalized["evidence_basis"] = "full_text_excerpt"
    return normalized


def _normalize_full_text_document_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize common full-text fetcher field names to the persisted schema."""
    normalized = dict(item)
    if "content_text" not in normalized and "source_text" in normalized:
        normalized["content_text"] = normalized["source_text"]
    if "source_kind" not in normalized:
        content_type = str(normalized.get("content_type") or "").lower()
        if content_type in {"text/html", "text/xml", "application/xml"}:
            normalized["source_kind"] = "open_access_html"
        elif "pdf" in content_type:
            normalized["source_kind"] = "pdf_extracted_markdown"
    return normalized


def _normalize_full_text_detail_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Map common flat trial-extraction output into the source-bound detail schema."""
    normalized = dict(item)
    if "baseline" not in normalized and normalized.get("baseline_summary"):
        normalized["baseline"] = {"summary": normalized["baseline_summary"]}
    if "outcomes" not in normalized and normalized.get("outcome_label"):
        intervention_events = normalized.get("intervention_events", normalized.get("group1_events"))
        intervention_total = normalized.get(
            "intervention_total", normalized.get("group1_n", normalized.get("group1_total"))
        )
        comparator_events = normalized.get("comparator_events", normalized.get("group2_events"))
        comparator_total = normalized.get(
            "comparator_total", normalized.get("group2_n", normalized.get("group2_total"))
        )
        normalized["outcomes"] = [{
            "outcome_label": normalized["outcome_label"],
            "effect_measure": normalized.get("effect_measure", "rr"),
            "timepoint": normalized.get("timepoint", "not_reported"),
            "intervention_events": intervention_events,
            "intervention_total": intervention_total,
            "comparator_events": comparator_events,
            "comparator_total": comparator_total,
        }]
    return normalized


def _normalize_research_writing_draft_payload(draft: dict[str, Any]) -> dict[str, Any]:
    """Make structured Agent notes compatible with the versioned draft schema.

    The stored draft deliberately keeps its main sections as Markdown/text so
    they can be rendered consistently. Agents naturally construct outlines and
    unresolved items as arrays; serialize those losslessly at the MCP boundary.
    """
    normalized = dict(draft)
    for field in (
        "outline",
        "limitations",
        "unresolved_items",
        "methods_draft",
        "discussion_framework",
        "proposal_draft",
    ):
        value = normalized.get(field)
        if isinstance(value, (dict, list)):
            normalized[field] = json.dumps(value, ensure_ascii=False, indent=2)
    manifest = normalized.get("source_manifest")
    if isinstance(manifest, list):
        normalized_manifest: list[dict[str, str]] = []
        for item in manifest:
            if not isinstance(item, dict):
                raise ValueError("source_manifest items must be objects.")
            normalized_manifest.append(
                {
                    str(key): str(value)
                    for key, value in item.items()
                    if value is not None
                }
            )
        normalized["source_manifest"] = normalized_manifest
    return normalized


def _normalize_bias_assessment_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Convert standard RoB 2 shorthand into the explicit persisted domain names."""
    normalized = dict(item)
    if "instrument" not in normalized and normalized.get("tool"):
        normalized["instrument"] = normalized["tool"]
    if "overall_judgement" not in normalized and normalized.get("overall"):
        normalized["overall_judgement"] = normalized["overall"]
    def normalize_judgement(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return value.strip().casefold().replace(" ", "_").replace("-", "_")

    normalized["overall_judgement"] = normalize_judgement(normalized.get("overall_judgement"))
    domain_names = [
        "randomization_process",
        "deviations_from_intended_interventions",
        "missing_outcome_data",
        "measurement_of_outcome",
        "selection_of_reported_result",
    ]
    domains = normalized.get("domains")
    if isinstance(domains, list) and normalized.get("instrument") == "rob2":
        converted = []
        for index, domain in enumerate(domains):
            value = dict(domain)
            shorthand = value.pop("domain_id", None)
            domain_value = value.get("domain")
            if isinstance(domain_value, str) and domain_value.casefold().startswith("d"):
                prefix = domain_value.split(":", 1)[0].strip().upper()
                if len(prefix) == 2 and prefix[1].isdigit():
                    shorthand = prefix
                    value.pop("domain", None)
            if "domain" not in value:
                if shorthand and shorthand.upper().startswith("D"):
                    position = int(shorthand[1:]) - 1
                    value["domain"] = domain_names[position]
                elif index < len(domain_names):
                    value["domain"] = domain_names[index]
            if "source_locator" not in value and value.get("locator"):
                value["source_locator"] = value["locator"]
            value["judgement"] = normalize_judgement(value.get("judgement"))
            converted.append(value)
        normalized["domains"] = converted
    return normalized


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
    review_mode: str = "formal_review",
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
        review_mode=review_mode,
    )
    with Session(engine) as session:
        project = create_project_record(session, payload, actor="mcp")
    return {
        "project": ProjectRead.model_validate(project).model_dump(),
    }


@mcp.tool()
def generate_project_search_strategy(project_id: int) -> dict[str, Any]:
    """Generate a PICO-derived draft strategy; refine it before online execution."""
    with Session(engine) as session:
        strategy = generate_search_strategy_record(session, project_id, actor="mcp")
    return {
        "project_id": project_id,
        "search_strategy": SearchStrategyRead.model_validate(strategy).model_dump(),
    }


@mcp.tool()
def save_project_search_strategy(
    project_id: int,
    source: str,
    query_text: str,
    rationale: str,
) -> dict[str, Any]:
    """Save the Agent-refined executable PubMed or Europe PMC strategy.

    Keep the generated PICO draft as an audit record, then save each actual
    database query through this tool before client-side retrieval.
    """
    normalized_source = source.strip().lower()
    if normalized_source not in {"pubmed", "europe_pmc"}:
        raise ValueError("source must be 'pubmed' or 'europe_pmc'.")
    if settings.literature_access_mode == "client_online" and normalized_source == "europe_pmc":
        raise ValueError(
            "Europe PMC retrieval is disabled in the current PubMed-only demonstration mode. "
            "Use PubMed for retrieval; Europe PMC is reserved for open-access full-text preflight."
        )
    if any("\u4e00" <= character <= "\u9fff" for character in query_text):
        raise ValueError(
            "Executable online strategies must use database-ready English/controlled vocabulary, not raw Chinese PICO prose."
        )
    payload = SearchStrategyCreate(
        source=normalized_source,
        query_text=query_text,
        rationale=rationale,
    )
    with Session(engine) as session:
        strategy = save_search_strategy_record(session, project_id, payload, actor="mcp")
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
    """Import a quick-exploration candidate set into a project.

    Formal-review projects must use the desktop direct-handoff pagination
    tools, so their PRISMA records cannot become a model-selected shortlist.
    """
    payload = CitationImportPayload.model_validate(
        {
            "source": source,
            "citations": citations,
        }
    )
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if project and project.review_mode == "formal_review":
            raise ValueError(
                "Formal-review projects reject manual candidate imports. Use "
                "client_retrieve_pubmed_formal_review or "
                "client_retrieve_europepmc_formal_review instead."
            )
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
def import_citations_file_to_project(
    project_id: int,
    file_path: str,
    source: str = "offline_file",
    file_format: str | None = None,
) -> dict[str, Any]:
    """Import citation records from a server-side JSON/CSV/RIS/NBIB file.

    The file must be located under LRA_LITERATURE_IMPORT_DIR. This is the
    offline fallback when PubMed or Europe PMC cannot be reached from the server.
    """
    citations = parse_citation_file(file_path, file_format)
    payload = CitationImportPayload(source=source, citations=citations)
    with Session(engine) as session:
        imported_citations = import_citations_record(session, project_id, payload, actor="mcp")
    return {
        "project_id": project_id,
        "source": source,
        "file_path": file_path,
        "parsed_count": len(citations),
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
def list_offline_evidence_packages() -> dict[str, Any]:
    """List validated raw-data evidence packages available on this offline server."""
    packages = list_offline_evidence_package_records()
    return {"package_count": len(packages), "packages": packages}


@mcp.tool()
def import_offline_evidence_package(project_id: int, package_id: str) -> dict[str, Any]:
    """Import an offline package's raw citations into a review project without screening them."""
    with Session(engine) as session:
        return import_offline_evidence_package_record(session, project_id, package_id)


@mcp.tool()
def ingest_offline_package_full_text(
    project_id: int,
    workflow_run_id: str,
    package_id: str,
) -> dict[str, Any]:
    """Parse raw local PDF/HTML for already-included citations during evidence extraction."""
    with Session(engine) as session:
        documents = load_offline_package_documents(
            session, project_id, package_id, included_only=True
        )
    return save_full_text_documents(project_id, workflow_run_id, documents)


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
def get_formal_retrieval_status(project_id: int) -> dict[str, Any]:
    """Show whether tracked formal retrieval is complete before downstream review steps."""
    with Session(engine) as session:
        readiness = formal_retrieval_readiness(session, project_id)
    return {
        "project_id": project_id,
        "review_mode": readiness["review_mode"],
        "tracked": readiness["tracked"],
        "ready": readiness["ready"],
        "runs": [
            {
                "source": item.source,
                "database_total_count": item.database_total_count,
                "retrieved_count": item.retrieved_count,
                "imported_count": item.imported_count,
                "complete": item.complete,
                "truncated": item.truncated,
            }
            for item in readiness["runs"]
        ],
    }


@mcp.tool()
def list_review_citation_batch(
    project_id: int,
    offset: int = 0,
    limit: int = 50,
    include_deduplicated: bool = False,
) -> dict[str, Any]:
    """Read one bounded, auditable title/abstract screening batch.

    Formal review retrieval can contain hundreds of records. This tool keeps
    the raw records in the backend and exposes only one bounded batch to the
    screening Agent, so every imported record can be reviewed without a
    model-selected shortlist.
    """
    normalized_offset = max(0, offset)
    normalized_limit = max(1, min(limit, 50))
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            raise ValueError("Project not found")
        citations = session.exec(
            select(Citation).where(Citation.project_id == project_id).order_by(Citation.id)
        ).all()
        if not include_deduplicated:
            citations = [citation for citation in citations if not citation.is_deduplicated]
        decisions = latest_screening_decisions(session, project_id)

    batch = citations[normalized_offset : normalized_offset + normalized_limit]
    return {
        "project_id": project_id,
        "total_count": len(citations),
        "offset": normalized_offset,
        "limit": normalized_limit,
        "next_offset": normalized_offset + len(batch) if normalized_offset + len(batch) < len(citations) else None,
        "citations": [
            {
                "id": citation.id,
                "external_id": citation.external_id,
                "source": citation.source,
                "title": citation.title,
                "abstract": citation.abstract,
                "authors": citation.authors,
                "publication_year": citation.publication_year,
                "doi": citation.doi,
                "existing_decision": decisions.get(citation.id).decision if citation.id in decisions else None,
            }
            for citation in batch
        ],
    }


@mcp.tool()
def list_pending_screening_citation_batch(
    project_id: int,
    after_id: int | None = None,
    limit: int = 25,
    original_research_only: bool = True,
) -> dict[str, Any]:
    """Read only active, unreviewed citations with high-precision rule suggestions.

    Rule suggestions are non-final. They reduce model review work but must not
    be saved as final include/exclude decisions before researcher confirmation.
    """
    with Session(engine) as session:
        if not session.get(Project, project_id):
            raise ValueError("Project not found")
        return list_pending_screening_batch(
            session,
            project_id,
            after_id=after_id,
            limit=limit,
            original_research_only=original_research_only,
        )


@mcp.tool()
def save_project_full_text_preflight(
    project_id: int,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist desktop-local Europe PMC full-text availability and cache verified open XML.

    This is an acquisition record, not a scientific include/exclude decision.
    Call after deduplication and before title/abstract screening in demo mode.
    """
    # v0.3.1 desktop clients returned only found/content_text. Infer a safe
    # status so global-Agent upgrades remain compatible until the desktop app
    # itself is replaced with v0.3.2.
    normalized_results = [
        {
            **item,
            "status": item.get("status") or (
                "full_text_ready" if item.get("found") and item.get("content_text")
                else "access_unavailable"
            ),
        }
        for item in results
    ]
    payloads = [FullTextPreflightCreate.model_validate(item) for item in normalized_results]
    with Session(engine) as session:
        return save_full_text_preflight_record(session, project_id, payloads)


@mcp.tool()
def get_project_full_text_availability(project_id: int) -> dict[str, Any]:
    """List preflight availability for active citations, including cached full-text document IDs."""
    with Session(engine) as session:
        return get_full_text_preflight_records(session, project_id)


@mcp.tool()
def submit_screening_decisions(
    project_id: int,
    decisions: list[dict[str, Any]],
    actor: str = "mcp_reviewer",
    original_research_only: bool = False,
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
            original_research_only=original_research_only,
        )
    return {
        "project_id": project_id,
        **result,
    }


@mcp.tool()
def get_literature_access_status() -> dict[str, object]:
    """Read whether this deployment should use live databases or offline citation-file import."""
    return literature_access_status()


@mcp.tool()
def get_workflow_next_actions(subject_type: str, subject_id: int) -> dict[str, Any]:
    """Return the controlled next actions for one persisted Agent subject.

    Use this as the final tool call in every Agent response. Render only the
    returned action cards; do not invent additional routes or expose tool names.
    """
    with Session(engine) as session:
        return get_next_actions_record(session, subject_type, subject_id)


@mcp.tool()
def create_research_case(title: str, description: str | None = None) -> dict[str, object]:
    """Create a case-level container that can link study-design and review projects."""
    with Session(engine) as session:
        return create_research_case_record(session, title, description)


@mcp.tool()
def link_research_case(
    case_id: int,
    study_design_project_id: int | None = None,
    review_project_id: int | None = None,
) -> dict[str, object]:
    """Link independently persisted study-design and review projects to one research case."""
    with Session(engine) as session:
        return link_research_case_record(session, case_id, study_design_project_id, review_project_id)


@mcp.tool()
def get_research_case(case_id: int) -> dict[str, object]:
    """Read the current project links and statuses for one research case."""
    with Session(engine) as session:
        return get_research_case_record(session, case_id)


if settings.literature_access_mode != "client_online":
    @mcp.tool()
    async def search_pubmed(query: str, limit: int = 5) -> dict[str, Any]:
        """Search PubMed and return normalized metadata records."""
        records = await search_pubmed_records(query, limit=limit)
        return {
            "source": "pubmed",
            "query": query,
            "returned_count": len(records),
            "records": _compact_records_for_agent(records),
        }


    @mcp.tool()
    async def search_europepmc(query: str, limit: int = 5) -> dict[str, Any]:
        """Search Europe PMC and return normalized metadata records."""
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
def get_included_review_citations(project_id: int) -> dict[str, Any]:
    """Return the authoritative current include set for evidence extraction.

    Do not infer inclusion from a review export or conversation history. Only
    these citation IDs may be submitted to evidence-extraction tools.
    """
    from app.services.evidence_extraction import included_citations

    with Session(engine) as session:
        citations = included_citations(session, project_id)
        return {
            "project_id": project_id,
            "included_count": len(citations),
            "citations": [
                {
                    "citation_id": item.id,
                    "pmid": item.external_id if item.external_id and item.external_id.isdigit() else None,
                    "source": item.source,
                    "title": item.title,
                    "abstract": item.abstract,
                    "doi": item.doi,
                }
                for item in citations
            ],
        }


@mcp.tool()
def save_evidence_extractions(
    project_id: int,
    workflow_run_id: str,
    extractions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Save source-bounded study characteristics for included review citations."""
    payloads = [
        EvidenceExtractionCreate.model_validate(_normalize_evidence_extraction_payload(item))
        for item in extractions
    ]
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
def save_project_retraction_checks(
    project_id: int,
    workflow_run_id: str,
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Save PubMed notice checks fetched by the desktop-local connector.

    Use this instead of check_project_retractions when the backend reports
    literature access mode client_online. The connector must check every
    currently included citation and return pubmed_publication_type_client.
    """
    payloads = [CitationSafetyCheckCreate.model_validate(item) for item in checks]
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
        records = save_project_retraction_checks_record(
            session, project_id, workflow_run_id, payloads, actor="mcp_client"
        )
        return {
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "saved_count": len(records),
            "checks": [
                {
                    "citation_id": item.citation_id,
                    "status": item.status,
                    "check_source": item.check_source,
                    "needs_human_review": item.needs_human_review,
                }
                for item in records
            ],
        }


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
def save_full_text_documents(
    project_id: int,
    workflow_run_id: str,
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Store source text from a public HTML fetch, PDF extraction, or researcher-supplied full text.

    This tool does not crawl arbitrary URLs. The agent must use the approved Skills first and
    submit the resulting source text with its URL and content type for auditability.
    """
    payloads = [
        FullTextDocumentCreate.model_validate(_normalize_full_text_document_payload(item))
        for item in documents
    ]
    required_skills = set(FULL_TEXT_SCREENING_SKILL)
    for payload in payloads:
        if payload.source_kind == "open_access_html":
            required_skills.update(FULL_TEXT_FETCH_SKILL)
        if payload.source_kind == "pdf_extracted_markdown":
            required_skills.update(PDF_EXTRACTION_SKILL)
    with Session(engine) as session:
        require_agent_skill_receipts(
            session, workflow_run_id, "evidence_extraction", "review", project_id,
            "full_text_ingestion", required_skills,
        )
        records = save_full_text_documents_record(
            session, project_id, workflow_run_id, payloads, actor="mcp"
        )
        return {
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "saved_count": len(records),
            "documents": [
                {
                    "id": item.id,
                    "citation_id": item.citation_id,
                    "source_kind": item.source_kind,
                    "content_sha256": item.content_sha256,
                    "needs_human_review": item.needs_human_review,
                }
                for item in records
            ],
        }


@mcp.tool()
async def fetch_and_save_open_access_full_text(
    project_id: int,
    workflow_run_id: str,
    citation_ids: list[int],
) -> dict[str, Any]:
    """Fetch and save Europe PMC XML only after verifying its PMID/DOI against local citations.

    Agents supply local citation IDs, never guessed PMC URLs. This prevents a
    plausible but unrelated open-access article from being attached to evidence.
    """
    with Session(engine) as session:
        require_agent_skill_receipts(
            session, workflow_run_id, "evidence_extraction", "review", project_id,
            "controlled_full_text_fetch", FULL_TEXT_SCREENING_SKILL | FULL_TEXT_FETCH_SKILL,
        )
        unique_ids = list(dict.fromkeys(citation_ids))
        if not unique_ids:
            raise ValueError("citation_ids must not be empty.")
        citations = session.exec(
            select(Citation).where(Citation.project_id == project_id, Citation.id.in_(unique_ids))
        ).all()
        if len(citations) != len(unique_ids):
            raise ValueError("Every citation_id must belong to this review project.")
        local_citations = {item.id: item for item in citations}

    documents: list[dict[str, Any]] = []
    for citation_id in unique_ids:
        citation = local_citations[citation_id]
        if not citation.external_id or not citation.external_id.isdigit():
            raise ValueError(f"Citation {citation_id} needs a numeric PubMed ID for controlled full-text fetch.")
        source = await fetch_europepmc_open_access_full_text(citation.external_id)
        if source is None:
            raise ValueError(f"No verified open-access Europe PMC full text was found for citation {citation_id}.")
        if citation.doi and source["doi"] and citation.doi.casefold() != source["doi"].casefold():
            raise ValueError(f"Europe PMC DOI does not match citation {citation_id}; refusing to attach full text.")
        documents.append({
            "citation_id": citation_id,
            "source_kind": "open_access_html",
            "source_url": source["source_url"],
            "content_text": source["content_text"],
        })

    return save_full_text_documents(project_id, workflow_run_id, documents)


@mcp.tool()
def save_full_text_evidence_details(
    project_id: int,
    workflow_run_id: str,
    details: list[dict[str, Any]],
) -> dict[str, Any]:
    """Save full-text baseline fields and binary outcome counts for included studies."""
    missing_document_ids = [
        item.get("citation_id")
        for item in details
        if not isinstance(item.get("full_text_document_id"), int)
    ]
    if missing_document_ids:
        raise ValueError(
            "Full-text evidence details require full_text_document_id values returned by "
            "save_full_text_documents or fetch_and_save_open_access_full_text. "
            f"Do not submit abstract-only citations: {missing_document_ids}."
        )
    payloads = [
        FullTextEvidenceDetailCreate.model_validate(_normalize_full_text_detail_payload(item))
        for item in details
    ]
    with Session(engine) as session:
        require_agent_skill_receipts(
            session, workflow_run_id, "evidence_extraction", "review", project_id,
            "full_text_data_extraction", DETAIL_EXTRACTION_SKILLS,
        )
        records = save_full_text_evidence_details_record(
            session, project_id, workflow_run_id, payloads, actor="mcp"
        )
        return {
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "saved_count": len(records),
            "detail_ids": [item.id for item in records],
            "needs_human_review": True,
        }


@mcp.tool()
def save_bias_assessments(
    project_id: int,
    workflow_run_id: str,
    assessments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Save preliminary RoB 2, NOS, or QUADAS-2 domains tied to full-text locations."""
    payloads = [
        BiasAssessmentCreate.model_validate(_normalize_bias_assessment_payload(item))
        for item in assessments
    ]
    required_skills: set[str] = set()
    for payload in payloads:
        required_skills.update(BIAS_SKILLS[payload.instrument])
    with Session(engine) as session:
        require_agent_skill_receipts(
            session, workflow_run_id, "evidence_extraction", "review", project_id,
            "bias_assessment", required_skills,
        )
        records = save_bias_assessments_record(
            session, project_id, workflow_run_id, payloads, actor="mcp"
        )
        return {
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "saved_count": len(records),
            "assessment_ids": [item.id for item in records],
            "needs_human_review": True,
        }


@mcp.tool()
def run_binary_meta_analysis(
    project_id: int,
    workflow_run_id: str,
    outcome_label: str,
    effect_measure: str = "rr",
    model: str = "random_effects",
) -> dict[str, Any]:
    """Pool matching full-text 2x2 binary outcomes and return an SVG forest plot."""
    with Session(engine) as session:
        require_agent_skill_receipts(
            session, workflow_run_id, "evidence_extraction", "review", project_id,
            "binary_meta_analysis", META_ANALYSIS_SKILLS,
        )
        record = run_binary_meta_analysis_record(
            session, project_id, workflow_run_id, outcome_label, effect_measure, model, actor="mcp"
        )
        return {
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "meta_analysis_id": record.id,
            "result": json.loads(record.result_json),
            "forest_plot_svg": record.forest_plot_svg,
            "needs_human_review": True,
        }


@mcp.tool()
def request_systematic_evidence_review(
    project_id: int,
    workflow_run_id: str,
) -> dict[str, Any]:
    """Request internal researcher confirmation for the exact current evidence bundle."""
    with Session(engine) as session:
        approval = request_systematic_evidence_review_record(
            session, project_id, workflow_run_id, actor="mcp"
        )
        return {
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "approval": {
                "status": approval.status,
                "scope_digest": approval.scope_digest,
                "requested_at": approval.requested_at,
            },
            "next_step": "Immediately call approve_systematic_evidence with this scope_digest. OpenCode will show its native Allow/Deny confirmation; do not stop at this request result.",
        }


@mcp.tool()
def confirm_systematic_evidence_phase_start(
    project_id: int,
    workflow_run_id: str,
) -> dict[str, Any]:
    """Record OpenCode-native approval before obtaining full text or running appraisal.

    This tool is permission-gated by OpenCode. Its invocation presents the
    native Allow/Deny control instead of relying on a free-text confirmation.
    """
    with Session(engine) as session:
        get_agent_workflow_run(
            session, workflow_run_id, "evidence_extraction", "review", project_id
        )
        result = {
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "phase": "full_text_systematic_evaluation",
            "status": "approved_in_opencode",
        }
        record_agent_workflow_event(
            session,
            workflow_run_id,
            "evidence_extraction",
            "review",
            project_id,
            "confirm_systematic_evidence_phase_start",
            {},
            result,
        )
        return result


@mcp.tool()
def get_systematic_evidence_review_status(
    project_id: int,
    workflow_run_id: str,
) -> dict[str, Any]:
    """Read the external-review status; an Agent cannot approve its own evidence bundle."""
    with Session(engine) as session:
        return systematic_evidence_review_snapshot(session, project_id, workflow_run_id)


@mcp.tool()
def export_systematic_evidence_bundle(
    project_id: int,
    workflow_run_id: str,
    format: str = "markdown",
) -> dict[str, Any]:
    """Export the full-text evidence, bias assessments, and available binary meta-analysis."""
    if format not in {"markdown", "json"}:
        raise ValueError("format must be 'markdown' or 'json'.")
    with Session(engine) as session:
        bias_skills = required_bias_skills_for_project(session, project_id)
        require_agent_skill_receipts(
            session, workflow_run_id, "evidence_extraction", "review", project_id,
            "systematic_evidence_export", FULL_TEXT_SCREENING_SKILL | DETAIL_EXTRACTION_SKILLS | bias_skills,
        )
        require_systematic_evidence_approval(session, project_id, workflow_run_id)
        bundle = build_systematic_evidence_bundle_data(session, project_id, workflow_run_id)
        if format == "markdown":
            result: dict[str, Any] = {
                "project_id": project_id,
                "workflow_run_id": workflow_run_id,
                "format": "markdown",
                "markdown": render_systematic_evidence_bundle_markdown(bundle),
            }
        else:
            result = {
                "project_id": project_id,
                "workflow_run_id": workflow_run_id,
                "format": "json",
                "bundle": bundle,
            }
        record_agent_workflow_event(
            session, workflow_run_id, "evidence_extraction", "review", project_id,
            "export_systematic_evidence_bundle", {"format": format}, result,
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
    """Persist a versioned research-writing draft.

    ``draft.source_manifest`` must be a list whose item includes both the exact
    ``source_type`` and string ``source_id`` for this workflow, for example
    ``[{"source_type": "review", "source_id": "5", "description": "..."}]``.
    """
    payload = ResearchWritingDraftCreate.model_validate(_normalize_research_writing_draft_payload(draft))
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
    """Request internal human confirmation; the Agent cannot approve a writing draft itself."""
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
            "next_step": "Immediately call approve_research_writing with this scope_digest. OpenCode will show its native Allow/Deny confirmation; do not stop at this request result.",
        }
    return result


@mcp.tool()
def get_research_writing_approval_status(draft_id: int) -> dict[str, Any]:
    """Read external writing-draft approval status without exposing credentials."""
    with Session(engine) as session:
        return research_writing_approval_snapshot(session, draft_id)


@mcp.tool()
def approve_study_design(
    project_id: int,
    scope_digest: str,
    approved_by: str,
) -> dict[str, Any]:
    """Request native OpenCode confirmation, then approve the current study-design scope."""
    snapshot = _get_human_approval_snapshot(f"/study-design-projects/{project_id}/approval")
    _assert_current_scope(snapshot, scope_digest)
    return _post_human_approval(
        f"/study-design-projects/{project_id}/approve",
        "X-Study-Approval-Key",
        "LRA_STUDY_DESIGN_APPROVAL_KEY",
        {"approved_by": approved_by},
    )


@mcp.tool()
def approve_systematic_evidence(
    project_id: int,
    workflow_run_id: str,
    scope_digest: str,
    approved_by: str,
) -> dict[str, Any]:
    """Request native OpenCode confirmation, then approve the current evidence scope."""
    snapshot = _get_human_approval_snapshot(
        f"/projects/{project_id}/systematic-evidence/{workflow_run_id}/approval"
    )
    _assert_current_scope(snapshot, scope_digest)
    return _post_human_approval(
        f"/projects/{project_id}/systematic-evidence/{workflow_run_id}/approve",
        "X-Systematic-Evidence-Approval-Key",
        "LRA_SYSTEMATIC_EVIDENCE_APPROVAL_KEY",
        {"approved_by": approved_by},
    )


@mcp.tool()
def approve_research_writing(
    draft_id: int,
    scope_digest: str,
    approved_by: str,
) -> dict[str, Any]:
    """Approve a draft after the OpenCode-native Allow/Deny confirmation.

    This MCP tool is permission-gated by OpenCode. It writes through the local
    service directly instead of making an HTTP request back into the same
    backend process, which avoids deadlocking the single-process local server.
    """
    with Session(engine) as session:
        snapshot = research_writing_approval_snapshot(session, draft_id)
        _assert_current_scope(snapshot, scope_digest)
        approval = approve_research_writing_record(session, draft_id, approved_by)
        return {
            "draft_id": draft_id,
            "approval": {
                "status": approval.status,
                "approved_by": approval.approved_by,
                "approved_at": approval.approved_at,
                "scope_digest": approval.scope_digest,
            },
        }


@mcp.tool()
def export_research_writing_bundle(
    draft_id: int,
    workflow_run_id: str,
    format: str = "markdown",
) -> dict[str, Any]:
    """Export an internally confirmed, versioned research-writing draft."""
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


@mcp.tool()
def get_agent_project_context(project_type: str, project_id: int) -> dict[str, Any]:
    """Read one persisted Agent project by type and ID across OpenCode sessions.

    Use references such as ``study_design:50`` or ``review:14``. Evidence
    extraction uses its parent review ID. The result is read-only and excludes
    concealed randomization allocations and full-text source bodies.
    """
    with Session(engine) as session:
        return get_agent_project_context_record(session, project_type, project_id)


@mcp.tool()
def get_confirmed_study_design_context(project_id: int) -> dict[str, Any]:
    """Read a human-confirmed study-design project's PICO for downstream evidence retrieval.

    This tool exposes research-design context only. It does not expose concealed
    allocation schedules or permit any study-design mutation.
    """
    with Session(engine) as session:
        context = get_agent_project_context_record(session, "study_design", project_id)
        if not context["is_human_confirmed"]:
            raise ValueError(
                f"Study-design project {project_id} is not human-confirmed; do not use it as downstream evidence context."
            )
        project = context["context"]["project"]
        return {
            "project_id": project["id"],
            "title": project["title"],
            "status": project["status"],
            "research_question": project["research_question"],
            "study_type": project["study_type"],
            "study_design": project["study_design"],
            "pico": {
                "population": project["population"],
                "intervention": project["intervention"],
                "comparator": project["comparator"],
                "outcome": project["outcome"],
            },
            "inclusion_criteria": project["inclusion_criteria"],
            "exclusion_criteria": project["exclusion_criteria"],
            "primary_outcome": project["primary_outcome"],
            "secondary_outcomes": project["secondary_outcomes"],
            "source_project_confirmed_at": project["human_confirmed_at"],
        }


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
    """Create a pending approval that must be confirmed through the gated approval tool."""
    with Session(engine) as session:
        approval = request_study_design_approval_record(session, project_id, actor="mcp")
        result = {
            "project_id": project_id,
            "approval": {
                "status": approval.status,
                "requested_at": approval.requested_at,
                "scope_digest": approval.scope_digest,
            },
            "next_step": "Immediately call approve_study_design with this scope_digest. OpenCode will show its native Allow/Deny confirmation; do not stop at this request result.",
        }
        return _record_study_tool_result(session, workflow_run_id, project_id, "request_study_design_approval", {}, result)


@mcp.tool()
def get_study_design_approval_status(project_id: int, workflow_run_id: str) -> dict[str, Any]:
    """Read internal confirmation status without exposing approval credentials or allocations."""
    with Session(engine) as session:
        result = approval_snapshot(session, project_id)
        return _record_study_tool_result(session, workflow_run_id, project_id, "get_study_design_approval_status", {}, result)


@mcp.tool()
def finalize_study_design(
    project_id: int,
    workflow_run_id: str,
    approved_by: str,
    format: str = "markdown",
) -> dict[str, Any]:
    """Confirm the current design once, then generate the concealed schedule and export bundle.

    OpenCode permission-gates this single tool call. After the user selects Allow,
    the backend records that internal confirmation directly, then performs the
    post-approval operations. No shared approval key is used in this MCP path.
    """
    if format not in {"markdown", "json"}:
        raise ValueError("format must be 'markdown' or 'json'.")
    with Session(engine) as session:
        approval = request_study_design_approval_record(session, project_id, actor="mcp_internal")
        scope_digest = approval.scope_digest
        if approval.status.value != "approved":
            # OpenCode's ask permission is the single human confirmation gate for
            # the default desktop workflow. The approval record preserves auditability.
            approve_study_design_record(session, project_id, approved_by)

        session.expire_all()
        project = session.get(StudyDesignProject, project_id)
        if project is None:
            raise ValueError(f"Study design project {project_id} not found.")
        # The MVP only creates concealed allocations for an RCT with a saved plan.
        if "RCT" in (project.study_design or "").upper() or "随机" in (project.study_design or ""):
            schedule = generate_rct_randomization_record(session, project_id, actor="mcp")
        else:
            schedule = None

        import_skill_execution_receipts(session, workflow_run_id, project_id)
        bundle = build_study_design_bundle_data(session, project_id, workflow_run_id)
        if not bundle:
            raise ValueError(f"Study design project {project_id} not found.")
        project_data = StudyDesignProjectRead.model_validate(bundle["project"]).model_dump()
        if format == "json":
            result = {
                "project_id": project_id,
                "format": "json",
                "approval": {"status": bundle["approval"].status, "approved_by": bundle["approval"].approved_by},
                "scope_digest": scope_digest,
                "randomization_schedule": schedule,
                "project": project_data,
                "sample_size": bundle["sample_size"],
                "randomization_plan": bundle["randomization_plan"],
                "randomization_schedule_metadata": bundle["randomization_schedule_metadata"],
                "skill_receipts": bundle["skill_receipts"],
                "audit_logs": bundle["audit_logs"],
            }
        else:
            result = {
                "project_id": project_id,
                "format": "markdown",
                "approval": {"status": bundle["approval"].status, "approved_by": bundle["approval"].approved_by},
                "scope_digest": scope_digest,
                "randomization_schedule": schedule,
                "markdown": render_study_design_bundle_markdown(bundle),
            }
        return _record_study_tool_result(
            session,
            workflow_run_id,
            project_id,
            "finalize_study_design",
            {"format": format},
            result,
        )


@mcp.tool()
def generate_rct_randomization_schedule(project_id: int, workflow_run_id: str) -> dict[str, Any]:
    """Generate a concealed schedule only after internal confirmation; allocations are never returned to the agent."""
    with Session(engine) as session:
        result = {"project_id": project_id, "randomization_schedule": generate_rct_randomization_record(session, project_id, actor="mcp")}
        return _record_study_tool_result(session, workflow_run_id, project_id, "generate_rct_randomization_schedule", {}, result)


@mcp.tool()
def export_study_design_bundle(project_id: int, workflow_run_id: str, format: str = "markdown") -> dict[str, Any]:
    """Export an internally confirmed bundle; allocation sequence remains redacted."""
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
