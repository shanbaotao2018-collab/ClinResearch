from __future__ import annotations

from sqlmodel import Session, select

from app.models import AuditLog, Citation, Project, ProjectStatus, ScreeningDecision, SearchStrategyVersion
from app.schemas import ProjectCreate, ScreeningDecisionCreate
from app.services.citations import CitationImportPayload
from app.services.screening import deduplicate_citations, rebuild_prisma_counts
from app.services.search_strategy import build_pubmed_query
from app.services.phi_guard import assert_no_phi


def _get_project_or_raise(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found.")
    return project


def create_project_record(
    session: Session,
    payload: ProjectCreate,
    actor: str = "system",
) -> Project:
    assert_no_phi(payload.model_dump())
    project = Project.model_validate(payload.model_dump())
    session.add(project)
    session.commit()
    session.refresh(project)

    session.add(
        AuditLog(
            project_id=project.id,
            action="project.created",
            actor=actor,
            summary=f"Project {project.title} created",
        )
    )
    session.commit()
    session.refresh(project)
    return project


def generate_search_strategy_record(
    session: Session,
    project_id: int,
    actor: str = "system",
) -> SearchStrategyVersion:
    project = _get_project_or_raise(session, project_id)
    query_text, rationale = build_pubmed_query(project)
    existing_count = len(
        session.exec(
            select(SearchStrategyVersion).where(
                SearchStrategyVersion.project_id == project_id
            )
        ).all()
    )
    strategy = SearchStrategyVersion(
        project_id=project_id,
        query_text=query_text,
        source="pubmed",
        version_number=existing_count + 1,
        rationale=rationale,
    )
    session.add(strategy)
    project.status = ProjectStatus.SEARCH_STRATEGY_READY
    session.add(project)
    session.add(
        AuditLog(
            project_id=project_id,
            action="search_strategy.generated",
            actor=actor,
            summary="Generated PubMed search strategy",
        )
    )
    session.commit()
    session.refresh(strategy)
    return strategy


def import_citations_record(
    session: Session,
    project_id: int,
    payload: CitationImportPayload,
    actor: str = "system",
) -> list[Citation]:
    project = _get_project_or_raise(session, project_id)

    imported_citations: list[Citation] = []
    for item in payload.citations:
        citation = Citation(
            project_id=project_id,
            source=payload.source,
            **item.model_dump(),
        )
        session.add(citation)
        imported_citations.append(citation)

    project.status = ProjectStatus.SEARCH_EXECUTED
    session.add(project)
    session.add(
        AuditLog(
            project_id=project_id,
            action="citations.imported",
            actor=actor,
            summary=f"Imported {len(imported_citations)} citations from {payload.source}",
        )
    )
    session.commit()
    for citation in imported_citations:
        session.refresh(citation)
    return imported_citations


def deduplicate_project_record(
    session: Session,
    project_id: int,
    actor: str = "system",
) -> int:
    project = _get_project_or_raise(session, project_id)

    removed_count = deduplicate_citations(session, project_id)
    project.status = ProjectStatus.CITATIONS_DEDUPLICATED
    session.add(project)
    session.add(
        AuditLog(
            project_id=project_id,
            action="citations.deduplicated",
            actor=actor,
            summary=f"Removed {removed_count} duplicates",
        )
    )
    session.commit()
    return removed_count


def submit_screening_decisions_record(
    session: Session,
    project_id: int,
    decisions: list[ScreeningDecisionCreate],
    actor: str = "system",
) -> dict[str, object]:
    _get_project_or_raise(session, project_id)

    created_decisions: list[ScreeningDecision] = []
    for item in decisions:
        decision = ScreeningDecision(project_id=project_id, **item.model_dump())
        session.add(decision)
        created_decisions.append(decision)

    session.commit()
    for decision in created_decisions:
        session.refresh(decision)
    prisma = rebuild_prisma_counts(session, project_id)

    unique_screened_ids = {
        item.citation_id
        for item in session.exec(
            select(ScreeningDecision).where(ScreeningDecision.project_id == project_id)
        ).all()
    }
    active_citation_ids = {
        citation.id
        for citation in session.exec(
            select(Citation).where(
                Citation.project_id == project_id,
                Citation.is_deduplicated.is_(False),
            )
        ).all()
        if citation.id is not None
    }
    project = _get_project_or_raise(session, project_id)
    project.status = (
        ProjectStatus.SCREENING_COMPLETED
        if active_citation_ids and active_citation_ids.issubset(unique_screened_ids)
        else ProjectStatus.SCREENING_IN_PROGRESS
    )
    session.add(project)
    session.add(
        AuditLog(
            project_id=project_id,
            action="screening.decisions_submitted",
            actor=actor,
            summary=f"Submitted {len(decisions)} screening decisions",
        )
    )
    session.commit()
    return {
        "submitted_count": len(decisions),
        "decision_ids": [item.id for item in created_decisions if item.id is not None],
        "project_status": project.status.value,
        "identified_count": prisma.identified_count,
        "deduplicated_count": prisma.deduplicated_count,
        "screened_count": prisma.screened_count,
        "included_count": prisma.included_count,
        "excluded_count": prisma.excluded_count,
    }
