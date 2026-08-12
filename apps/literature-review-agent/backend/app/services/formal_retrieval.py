from __future__ import annotations

from sqlmodel import Session, select

from app.models import AuditLog, FormalRetrievalRun, Project, SearchStrategyVersion
from app.schemas import FormalRetrievalRunCreate


def record_formal_retrieval_run(
    session: Session,
    project_id: int,
    payload: FormalRetrievalRunCreate,
    actor: str = "desktop_client",
) -> FormalRetrievalRun:
    project = session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found.")
    if project.review_mode != "formal_review":
        raise ValueError("Formal retrieval runs can only be recorded for formal_review projects.")
    if payload.database_total_count < 0 or payload.retrieved_count < 0 or payload.imported_count < 0:
        raise ValueError("Formal retrieval counts must not be negative.")
    if payload.imported_count > payload.retrieved_count:
        raise ValueError("imported_count cannot exceed retrieved_count.")
    if payload.complete and payload.truncated:
        raise ValueError("A formal retrieval cannot be both complete and truncated.")
    if payload.complete and payload.retrieved_count < payload.database_total_count:
        raise ValueError("A complete formal retrieval must include every database record.")

    run = FormalRetrievalRun(
        project_id=project_id,
        source=payload.source,
        query_text=payload.query.strip(),
        database_total_count=payload.database_total_count,
        retrieved_count=payload.retrieved_count,
        imported_count=payload.imported_count,
        page_count=payload.page_count,
        complete=payload.complete,
        truncated=payload.truncated,
        max_records=payload.max_records,
        retrieval_channel=payload.retrieval_channel,
    )
    session.add(run)
    summary = (
        f"{payload.source} formal retrieval: {payload.retrieved_count}/{payload.database_total_count} records; "
        f"{'complete' if payload.complete else 'incomplete'}"
    )
    session.add(AuditLog(
        project_id=project_id,
        action="formal_retrieval.completed" if payload.complete else "formal_retrieval.incomplete",
        actor=actor,
        summary=summary,
    ))
    session.commit()
    session.refresh(run)
    return run


def formal_retrieval_readiness(session: Session, project_id: int) -> dict[str, object]:
    project = session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found.")
    runs = session.exec(
        select(FormalRetrievalRun)
        .where(FormalRetrievalRun.project_id == project_id)
        .order_by(FormalRetrievalRun.id)
    ).all()
    # A refined strategy replaces the previous strategy for the same database.
    # Historical incomplete attempts remain in the audit trail, but must not
    # permanently block a later, explicitly saved replacement strategy.
    strategies = session.exec(
        select(SearchStrategyVersion)
        .where(SearchStrategyVersion.project_id == project_id)
        .order_by(SearchStrategyVersion.version_number)
    ).all()
    active_by_source: dict[str, SearchStrategyVersion] = {}
    for strategy in strategies:
        active_by_source[strategy.source] = strategy

    active_runs: list[FormalRetrievalRun] = []
    missing_strategies: list[SearchStrategyVersion] = []
    incomplete: list[FormalRetrievalRun] = []
    for source, strategy in active_by_source.items():
        matching_runs = [
            run for run in runs
            if run.source == source and run.query_text == strategy.query_text
        ]
        if not matching_runs:
            missing_strategies.append(strategy)
            continue
        latest_run = matching_runs[-1]
        active_runs.append(latest_run)
        if not latest_run.complete or latest_run.truncated:
            incomplete.append(latest_run)

    # Preserve compatibility for legacy manual imports that have no tracked run.
    ready = not runs or (not incomplete and not missing_strategies)
    return {
        "project_id": project_id,
        "review_mode": project.review_mode,
        "tracked": bool(runs),
        "ready": ready,
        "runs": runs,
        "active_strategies": list(active_by_source.values()),
        "active_runs": active_runs,
        "incomplete_runs": incomplete,
        "missing_strategies": missing_strategies,
    }


def require_formal_retrieval_ready(session: Session, project_id: int) -> None:
    readiness = formal_retrieval_readiness(session, project_id)
    # Legacy direct imports predate the tracked connector. Preserve their
    # compatibility while making every new tracked formal run a hard gate.
    if not readiness["tracked"]:
        return
    incomplete = readiness["incomplete_runs"]
    missing = readiness["missing_strategies"]
    if incomplete or missing:
        details = "; ".join(
            f"{item.source}: {item.retrieved_count}/{item.database_total_count}"
            for item in incomplete
        )
        if missing:
            missing_details = "; ".join(item.source for item in missing)
            details = "; ".join(filter(None, [details, f"no run for current strategy: {missing_details}"]))
        raise ValueError(
            "Formal retrieval is incomplete. Refine the query and complete retrieval before "
            f"deduplication, screening, or export. Incomplete runs: {details}."
        )
