from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.models import AuditLog, Citation, FullTextAvailability, Project, ProjectStatus, SearchStrategyVersion
from app.schemas import AuditLogRead, CitationRead, PrismaRead, ProjectRead, SearchStrategyRead
from app.services.screening import rebuild_prisma_counts
from app.services.screening import latest_screening_decisions
from app.services.formal_retrieval import require_formal_retrieval_ready


def build_review_bundle_data(
    session: Session,
    project_id: int,
) -> dict[str, Any] | None:
    project = session.get(Project, project_id)
    if not project:
        return None

    require_formal_retrieval_ready(session, project_id)

    exportable_statuses = {
        ProjectStatus.SCREENING_COMPLETED,
        ProjectStatus.PRISMA_GENERATED,
        ProjectStatus.EXPORTED,
    }
    if project.status not in exportable_statuses:
        raise ValueError("Screening decisions must be completed before exporting a review bundle.")

    pending_human_review = sorted(
        item.citation_id
        for item in latest_screening_decisions(session, project_id).values()
        if item.decision == "human_review"
    )
    if pending_human_review:
        raise ValueError(
            "Resolve every human_review decision before exporting a final review bundle. "
            f"Pending citation IDs: {pending_human_review}."
        )

    citations = session.exec(
        select(Citation).where(Citation.project_id == project_id).order_by(Citation.id)
    ).all()
    audit_logs = session.exec(
        select(AuditLog).where(AuditLog.project_id == project_id).order_by(AuditLog.id)
    ).all()
    strategies = session.exec(
        select(SearchStrategyVersion)
        .where(SearchStrategyVersion.project_id == project_id)
        .order_by(SearchStrategyVersion.version_number)
    ).all()
    prisma = rebuild_prisma_counts(session, project_id)
    availability = {
        item.citation_id: item
        for item in session.exec(
            select(FullTextAvailability).where(FullTextAvailability.project_id == project_id)
        ).all()
    }
    included_ids = sorted(
        citation_id
        for citation_id, decision in latest_screening_decisions(session, project_id).items()
        if decision.decision == "include"
    )
    missing_preflight = sorted(set(included_ids) - set(availability))
    if missing_preflight:
        raise ValueError(
            "Final included citations require an explicit full-text preflight record before exporting a review bundle. "
            f"Missing citation IDs: {missing_preflight}."
        )

    included_preflight = [availability[citation_id] for citation_id in included_ids]
    full_text_preflight = {
        "included_count": len(included_ids),
        "preflighted_count": len(included_preflight),
        "full_text_ready_count": sum(item.status == "full_text_ready" for item in included_preflight),
        "cached_full_text_count": sum(item.full_text_document_id is not None for item in included_preflight),
        "pdf_needed_citation_ids": sorted(
            item.citation_id for item in included_preflight if item.status == "pdf_needed"
        ),
        "access_unavailable_citation_ids": sorted(
            item.citation_id for item in included_preflight if item.status == "access_unavailable"
        ),
        "verification_failed_citation_ids": sorted(
            item.citation_id for item in included_preflight if item.status == "verification_failed"
        ),
    }

    project.status = ProjectStatus.EXPORTED
    session.add(project)
    session.commit()
    session.refresh(project)

    return {
        "project": ProjectRead.model_validate(project).model_dump(),
        "search_strategies": [
            SearchStrategyRead.model_validate(item).model_dump() for item in strategies
        ],
        "citations": [CitationRead.model_validate(item).model_dump() for item in citations],
        "full_text_availability": [
            {
                "citation_id": citation.id,
                "status": availability[citation.id].status if citation.id in availability else "not_checked",
                "pmcid": availability[citation.id].pmcid if citation.id in availability else None,
                "source_url": availability[citation.id].source_url if citation.id in availability else None,
                "local_cache_path": availability[citation.id].local_cache_path if citation.id in availability else None,
                "details": availability[citation.id].details if citation.id in availability else None,
            }
            for citation in citations
            if not citation.is_deduplicated
        ],
        "full_text_preflight": full_text_preflight,
        "prisma": PrismaRead.model_validate(prisma).model_dump(),
        "audit_logs": [AuditLogRead.model_validate(item).model_dump() for item in audit_logs],
    }


def render_review_bundle_markdown(bundle: dict[str, Any]) -> str:
    project = bundle["project"]
    strategies = bundle.get("search_strategies", [])
    citations = bundle.get("citations", [])
    prisma = bundle["prisma"]
    audit_logs = bundle.get("audit_logs", [])
    availability = {item["citation_id"]: item for item in bundle.get("full_text_availability", [])}
    preflight = bundle["full_text_preflight"]

    non_duplicate_citations = [item for item in citations if not item.get("is_deduplicated")]
    lines = [
        f"# {project['title']}",
        "",
        "## Research Question",
        project["research_question"],
        "",
        "## PICO",
        f"- Population: {project.get('pico_population') or 'N/A'}",
        f"- Intervention: {project.get('pico_intervention') or 'N/A'}",
        f"- Comparator: {project.get('pico_comparator') or 'N/A'}",
        f"- Outcome: {project.get('pico_outcome') or 'N/A'}",
        "",
        "## Eligibility",
        f"- Inclusion: {project.get('inclusion_criteria') or 'N/A'}",
        f"- Exclusion: {project.get('exclusion_criteria') or 'N/A'}",
        "",
        "## Search Strategies",
    ]

    if strategies:
        for strategy in strategies:
            lines.extend(
                [
                    f"### Version {strategy['version_number']} ({strategy['source']})",
                    "",
                    strategy["query_text"],
                    "",
                    f"Rationale: {strategy.get('rationale') or 'N/A'}",
                    "",
                ]
            )
    else:
        lines.extend(["No search strategy has been generated yet.", ""])

    lines.extend(
        [
            "## PRISMA Snapshot",
            f"- Identified: {prisma['identified_count']}",
            f"- After deduplication: {prisma['deduplicated_count']}",
            f"- Screened: {prisma['screened_count']}",
            f"- Included: {prisma['included_count']}",
            f"- Excluded: {prisma['excluded_count']}",
            "",
            "## Full-Text Preflight",
            f"- Included citations preflighted: {preflight['preflighted_count']}/{preflight['included_count']}",
            f"- Verified open full text cached: {preflight['full_text_ready_count']}",
            f"- Cached full-text documents: {preflight['cached_full_text_count']}",
            f"- Researcher PDF needed citation IDs: {preflight['pdf_needed_citation_ids'] or 'none'}",
            f"- Access unavailable citation IDs: {preflight['access_unavailable_citation_ids'] or 'none'}",
            f"- Verification failed citation IDs: {preflight['verification_failed_citation_ids'] or 'none'}",
            "- This is a screening-level review bundle. Full-text extraction remains pending unless every included citation has a cached full-text document.",
            "",
            "## Local Full-Text Cache",
        ]
    )

    cached_paths = [
        (citation, availability.get(citation["id"]))
        for citation in non_duplicate_citations
        if availability.get(citation["id"], {}).get("local_cache_path")
    ]
    if cached_paths:
        lines.extend([
            "| Citation ID | PMID / Source ID | Full-text status | Local cached file |",
            "| --- | --- | --- | --- |",
        ])
        for citation, item in cached_paths:
            lines.append(
                f"| {citation['id']} | {citation.get('external_id') or 'N/A'} | {item['status']} | `{item['local_cache_path']}` |"
            )
    else:
        lines.append("No desktop-local full-text cache path was recorded for this export.")

    lines.extend(
        [
            "",
            "## Retrieved Citation Candidates",
        ]
    )

    if non_duplicate_citations:
        for citation in non_duplicate_citations:
            year = citation.get("publication_year") or "N/A"
            doi = citation.get("doi") or "N/A"
            lines.extend(
                [
                    f"### Citation {citation['id']}",
                    f"- Title: {citation['title']}",
                    f"- Authors: {citation.get('authors') or 'N/A'}",
                    f"- Year: {year}",
                    f"- DOI: {doi}",
                    f"- Source ID: {citation.get('external_id') or 'N/A'}",
                    f"- Full Text Status: {availability.get(citation['id'], {}).get('status', 'not_checked')}",
                    f"- Full Text URL: {availability.get(citation['id'], {}).get('source_url') or 'N/A'}",
                    "",
                ]
            )
    else:
        lines.extend(["No non-duplicate citations are available.", ""])

    lines.extend(["## Audit Log", ""])
    if audit_logs:
        for log in audit_logs:
            lines.append(f"- {log['action']} | {log['actor']} | {log['summary']}")
    else:
        lines.append("- No audit log entries found.")

    lines.append("")
    return "\n".join(lines)


def write_review_bundle_markdown(markdown: str, output_path: str) -> str:
    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(markdown, encoding="utf-8")
    return str(destination.resolve())
