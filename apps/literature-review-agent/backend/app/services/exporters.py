from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.models import AuditLog, Citation, Project, ProjectStatus, SearchStrategyVersion
from app.schemas import AuditLogRead, CitationRead, PrismaRead, ProjectRead, SearchStrategyRead
from app.services.screening import rebuild_prisma_counts


def build_review_bundle_data(
    session: Session,
    project_id: int,
) -> dict[str, Any] | None:
    project = session.get(Project, project_id)
    if not project:
        return None

    exportable_statuses = {
        ProjectStatus.SCREENING_COMPLETED,
        ProjectStatus.PRISMA_GENERATED,
        ProjectStatus.EXPORTED,
    }
    if project.status not in exportable_statuses:
        raise ValueError("Screening decisions must be completed before exporting a review bundle.")

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
        "prisma": PrismaRead.model_validate(prisma).model_dump(),
        "audit_logs": [AuditLogRead.model_validate(item).model_dump() for item in audit_logs],
    }


def render_review_bundle_markdown(bundle: dict[str, Any]) -> str:
    project = bundle["project"]
    strategies = bundle.get("search_strategies", [])
    citations = bundle.get("citations", [])
    prisma = bundle["prisma"]
    audit_logs = bundle.get("audit_logs", [])

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
            "## Included Citation Candidates",
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
