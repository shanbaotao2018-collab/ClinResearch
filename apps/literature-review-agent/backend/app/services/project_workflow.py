from __future__ import annotations

from sqlmodel import Session, select

from app.models import AuditLog, Citation, Project, ProjectStatus, ScreeningDecision, SearchStrategyVersion
from app.schemas import ProjectCreate, ScreeningDecisionCreate, SearchStrategyCreate
from app.services.citations import CitationImportPayload
from app.services.screening import (
    deduplicate_citations,
    latest_screening_decisions,
    rebuild_prisma_counts,
)
from app.services.search_strategy import build_pubmed_query
from app.services.phi_guard import assert_no_phi
from app.services.formal_retrieval import require_formal_retrieval_ready


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


def save_search_strategy_record(
    session: Session,
    project_id: int,
    payload: SearchStrategyCreate,
    actor: str = "system",
) -> SearchStrategyVersion:
    """Persist an Agent-refined executable strategy without overwriting history."""
    project = _get_project_or_raise(session, project_id)
    query_text = payload.query_text.strip()
    if not query_text:
        raise ValueError("Search strategy query_text must not be empty.")
    if len(query_text) > 4_000:
        raise ValueError("Search strategy query_text exceeds the 4,000 character limit.")
    if (
        project.review_mode == "formal_review"
        and payload.source.strip().lower() == "europe_pmc"
        and "OPEN_ACCESS:Y" in query_text.upper()
    ):
        raise ValueError(
            "Formal-review Europe PMC retrieval must not use OPEN_ACCESS:Y. "
            "Assess full-text availability only after scientific screening."
        )

    existing_count = len(
        session.exec(
            select(SearchStrategyVersion).where(
                SearchStrategyVersion.project_id == project_id
            )
        ).all()
    )
    strategy = SearchStrategyVersion(
        project_id=project_id,
        source=payload.source.strip().lower(),
        query_text=query_text,
        version_number=existing_count + 1,
        rationale=payload.rationale.strip(),
    )
    session.add(strategy)
    session.add(
        AuditLog(
            project_id=project_id,
            action="search_strategy.optimized_saved",
            actor=actor,
            summary=f"Saved executable {strategy.source} search strategy version {strategy.version_number}",
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

    require_formal_retrieval_ready(session, project_id)
    removed_count = deduplicate_citations(session, project_id)
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
    screened_citation_ids = set(latest_screening_decisions(session, project_id))
    project.status = (
        ProjectStatus.SCREENING_COMPLETED
        if active_citation_ids and active_citation_ids.issubset(screened_citation_ids)
        else ProjectStatus.CITATIONS_DEDUPLICATED
    )
    session.add(project)
    session.add(
        AuditLog(
            project_id=project_id,
            action="citations.deduplicated",
            actor=actor,
            summary=f"Marked {removed_count} new duplicates",
        )
    )
    session.commit()
    return removed_count


def submit_screening_decisions_record(
    session: Session,
    project_id: int,
    decisions: list[ScreeningDecisionCreate],
    actor: str = "system",
    original_research_only: bool = False,
) -> dict[str, object]:
    _get_project_or_raise(session, project_id)
    require_formal_retrieval_ready(session, project_id)

    # Title/abstract screening narrows a large retrieval set before expensive
    # desktop-local full-text acquisition. The export gate verifies that every
    # final included citation has an explicit availability record, so preflight
    # is still mandatory before a review can be represented as complete.

    if original_research_only:
        citations = {
            item.id: item
            for item in session.exec(
                select(Citation).where(Citation.project_id == project_id)
            ).all()
        }
        non_original_markers = (
            "systematic review",
            "scoping review",
            "meta-analysis",
            "meta analysis",
            "umbrella review",
            "study protocol",
            "protocol for",
            "rationale and design",
        )
        invalid = []
        for item in decisions:
            title = (citations.get(item.citation_id).title if citations.get(item.citation_id) else "").casefold()
            if item.decision == "include" and any(marker in title for marker in non_original_markers):
                invalid.append(item.citation_id)
        if invalid:
            raise ValueError(
                "Original-research-only screening cannot include review, meta-analysis, or protocol titles: "
                f"{sorted(invalid)}. Mark them exclude or human_review instead."
            )

    all_citations = {
        item.id: item
        for item in session.exec(
            select(Citation).where(Citation.project_id == project_id)
        ).all()
        if item.id is not None
    }
    duplicate_ids = sorted(
        item.citation_id
        for item in decisions
        if item.citation_id not in all_citations or all_citations[item.citation_id].is_deduplicated
    )
    if duplicate_ids:
        raise ValueError(
            "Screening decisions must reference active, non-duplicated citations only: "
            f"{duplicate_ids}."
        )

    latest_decisions = latest_screening_decisions(session, project_id)
    created_decisions: list[ScreeningDecision] = []
    unchanged_count = 0
    for item in decisions:
        previous = latest_decisions.get(item.citation_id)
        if (
            previous
            and previous.decision == item.decision
            and previous.reason.strip() == item.reason.strip()
            and previous.actor == item.actor
        ):
            unchanged_count += 1
            continue
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
            summary=(
                f"Saved {len(created_decisions)} screening decisions"
                + (f"; {unchanged_count} unchanged" if unchanged_count else "")
            ),
        )
    )
    session.commit()
    return {
        "submitted_count": len(created_decisions),
        "requested_count": len(decisions),
        "unchanged_count": unchanged_count,
        "decision_ids": [item.id for item in created_decisions if item.id is not None],
        "project_status": project.status.value,
        "identified_count": prisma.identified_count,
        "deduplicated_count": prisma.deduplicated_count,
        "screened_count": prisma.screened_count,
        "included_count": prisma.included_count,
        "excluded_count": prisma.excluded_count,
    }
