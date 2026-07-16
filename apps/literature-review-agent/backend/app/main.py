from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlmodel import Session, select

from .config import settings
from .db import get_session, init_db
from .models import (
    AuditLog,
    Project,
)
from .schemas import (
    AuditLogRead,
    PrismaRead,
    ProjectCreate,
    ProjectRead,
    ScreeningDecisionCreate,
    SearchStrategyRead,
    StudyDesignApprovalRequest,
    StudyDesignWorkflowEventRead,
)
from .services.citations import CitationImportPayload
from .services.exporters import build_review_bundle_data
from .services.project_workflow import (
    create_project_record,
    deduplicate_project_record,
    generate_search_strategy_record,
    import_citations_record,
    submit_screening_decisions_record,
)
from .services.research_writing import (
    approve_research_writing_record,
    research_writing_approval_snapshot,
    verify_research_writing_approval_key,
)
from .services.screening import rebuild_prisma_counts
from .services.study_design import (
    approval_snapshot,
    approve_study_design_record,
    get_study_design_workflow_events,
    read_randomization_schedule_record,
    verify_approval_key,
)

app = FastAPI(title=settings.app_name)
init_db()


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    session: Session = Depends(get_session),
):
    project = create_project_record(session, payload, actor="system")
    return ProjectRead.model_validate(project).model_dump()


@app.get("/projects/{project_id}")
def get_project(
    project_id: int,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectRead.model_validate(project).model_dump()


@app.get("/projects")
def list_projects(session: Session = Depends(get_session)):
    projects = session.exec(select(Project)).all()
    return [ProjectRead.model_validate(project).model_dump() for project in projects]


@app.post(
    "/projects/{project_id}/search-strategies/generate",
    status_code=status.HTTP_201_CREATED,
)
def generate_search_strategy(
    project_id: int,
    session: Session = Depends(get_session),
):
    try:
        strategy = generate_search_strategy_record(session, project_id, actor="system")
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
    return SearchStrategyRead.model_validate(strategy).model_dump()


@app.post(
    "/projects/{project_id}/citations/import-manual",
    status_code=status.HTTP_201_CREATED,
)
def import_manual_citations(
    project_id: int,
    payload: CitationImportPayload,
    session: Session = Depends(get_session),
):
    try:
        imported_citations = import_citations_record(session, project_id, payload, actor="system")
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"imported_count": len(imported_citations)}


@app.post("/projects/{project_id}/deduplicate")
def deduplicate(
    project_id: int,
    session: Session = Depends(get_session),
):
    try:
        removed_count = deduplicate_project_record(session, project_id, actor="system")
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"removed_count": removed_count}


@app.post(
    "/projects/{project_id}/screening-decisions",
    status_code=status.HTTP_201_CREATED,
)
def create_screening_decision(
    project_id: int,
    payload: ScreeningDecisionCreate,
    session: Session = Depends(get_session),
):
    try:
        result = submit_screening_decisions_record(
            session,
            project_id,
            [payload],
            actor=payload.actor,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
    prisma = rebuild_prisma_counts(session, project_id)
    return {
        "decision_id": result["decision_ids"][0] if result["decision_ids"] else None,
        "submitted_count": result["submitted_count"],
        "prisma": PrismaRead.model_validate(prisma).model_dump(),
    }


@app.get("/projects/{project_id}/prisma")
def get_prisma(
    project_id: int,
    session: Session = Depends(get_session),
):
    record = rebuild_prisma_counts(session, project_id)
    return PrismaRead.model_validate(record).model_dump()


@app.get("/projects/{project_id}/audit-logs")
def get_audit_logs(
    project_id: int,
    session: Session = Depends(get_session),
):
    audit_logs = session.exec(select(AuditLog).where(AuditLog.project_id == project_id)).all()
    return [AuditLogRead.model_validate(item).model_dump() for item in audit_logs]


@app.get("/projects/{project_id}/export")
def export_project_bundle(
    project_id: int,
    session: Session = Depends(get_session),
):
    try:
        bundle = build_review_bundle_data(session, project_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    if not bundle:
        raise HTTPException(status_code=404, detail="Project not found")
    return bundle


def _require_study_approval_key(approval_key: str | None) -> None:
    try:
        verify_approval_key(approval_key)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


@app.get("/study-design-projects/{project_id}/approval")
def get_study_design_approval(project_id: int, session: Session = Depends(get_session)):
    try:
        return approval_snapshot(session, project_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _require_research_writing_approval_key(approval_key: str | None) -> None:
    try:
        verify_research_writing_approval_key(approval_key)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


@app.get("/research-writing-drafts/{draft_id}/approval")
def get_research_writing_approval(draft_id: int, session: Session = Depends(get_session)):
    try:
        return research_writing_approval_snapshot(session, draft_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/research-writing-drafts/{draft_id}/approve")
def approve_research_writing(
    draft_id: int,
    payload: StudyDesignApprovalRequest,
    x_research_writing_approval_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    _require_research_writing_approval_key(x_research_writing_approval_key)
    try:
        approval = approve_research_writing_record(session, draft_id, payload.approved_by)
        return {
            "draft_id": draft_id,
            "approval": {
                "status": approval.status,
                "approved_by": approval.approved_by,
                "approved_at": approval.approved_at,
                "scope_digest": approval.scope_digest,
            },
        }
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/study-design-projects/{project_id}/approve")
def approve_study_design(
    project_id: int,
    payload: StudyDesignApprovalRequest,
    x_study_approval_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    _require_study_approval_key(x_study_approval_key)
    try:
        approval = approve_study_design_record(session, project_id, payload.approved_by)
        return {"project_id": project_id, "approval": {"status": approval.status, "approved_by": approval.approved_by, "approved_at": approval.approved_at, "scope_digest": approval.scope_digest}}
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/study-design-projects/{project_id}/randomization-schedule")
def get_randomization_schedule(
    project_id: int,
    x_study_approval_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    _require_study_approval_key(x_study_approval_key)
    try:
        # This privileged endpoint is for an authorized trial operator, never for MCP/model use.
        return {"project_id": project_id, "schedule": read_randomization_schedule_record(session, project_id)}
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/study-design-projects/{project_id}/workflow-runs/{run_id}/events")
def get_study_design_workflow_events_endpoint(
    project_id: int,
    run_id: str,
    session: Session = Depends(get_session),
):
    try:
        events = get_study_design_workflow_events(session, project_id, run_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return [StudyDesignWorkflowEventRead.model_validate(event).model_dump() for event in events]
