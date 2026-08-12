from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlmodel import Session, select

from .config import settings
from .db import get_session, init_db
from .models import (
    AuditLog,
    Project,
    ResearchWritingDraft,
)
from .schemas import (
    AuditLogRead,
    CitationFileImportRequest,
    FullTextPreflightBatchCreate,
    FormalRetrievalRunCreate,
    PrismaRead,
    ProjectCreate,
    ProjectRead,
    ScreeningDecisionCreate,
    SearchStrategyRead,
    StudyDesignApprovalRequest,
    SystematicEvidenceApprovalRequest,
    StudyDesignWorkflowEventRead,
)
from .services.citation_files import parse_citation_file
from .services.literature_access import literature_access_status
from .services.full_text_preflight import save_full_text_preflight_record
from .services.agent_workflows import ingest_agent_skill_execution_receipt_journal
from .services.next_actions import get_next_actions
from .services.offline_evidence_packages import (
    OfflineEvidencePackageError,
    import_offline_evidence_package_record,
    list_offline_evidence_packages,
)
from .services.citations import CitationImportPayload
from .services.exporters import build_review_bundle_data, render_review_bundle_markdown
from .services.project_workflow import (
    create_project_record,
    deduplicate_project_record,
    generate_search_strategy_record,
    import_citations_record,
    submit_screening_decisions_record,
)
from .services.formal_retrieval import formal_retrieval_readiness, record_formal_retrieval_run
from .services.research_writing import (
    approve_research_writing_record,
    build_research_writing_bundle_data,
    render_research_writing_bundle_markdown,
    research_writing_approval_snapshot,
    verify_research_writing_approval_key,
)
from .services.screening import list_pending_screening_batch, rebuild_prisma_counts
from .services.study_design import (
    approval_snapshot,
    approve_study_design_record,
    get_study_design_workflow_events,
    read_randomization_schedule_record,
    build_study_design_bundle_data,
    render_study_design_bundle_markdown,
    verify_approval_key,
)
from .services.systematic_evaluation import (
    approve_systematic_evidence_review_record,
    build_systematic_evidence_bundle_data,
    render_systematic_evidence_bundle_markdown,
    require_systematic_evidence_approval,
    systematic_evidence_review_snapshot,
)
from .services.workbench import review_detail, study_design_detail, workbench_overview, writing_detail
from .mcp_server import mcp


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run HTTP API and MCP transport under one authoritative backend process."""
    init_db()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.mount("/mcp", mcp.streamable_http_app())


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "literature_access": literature_access_status()}


@app.post("/agent-workflows/skill-receipts")
def ingest_skill_receipt_journal(
    payload: dict[str, Any],
    session: Session = Depends(get_session),
):
    """Accept signed Skill receipts directly from the desktop OpenCode plugin."""
    try:
        imported_count = ingest_agent_skill_execution_receipt_journal(session, payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"imported_count": imported_count, "workflow_run_id": payload["workflow_run_id"]}


@app.get("/literature-access-status")
def get_literature_access_status() -> dict[str, object]:
    """Expose the active retrieval policy for the B/S workbench and operators."""
    return literature_access_status()


@app.get("/offline-evidence-packages")
def get_offline_evidence_packages() -> dict[str, object]:
    packages = list_offline_evidence_packages()
    return {"package_count": len(packages), "packages": packages}


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


@app.get("/workflow-next-actions/{subject_type}/{subject_id}")
def workflow_next_actions(
    subject_type: str,
    subject_id: int,
    session: Session = Depends(get_session),
):
    """Read the authoritative next-action cards for the workbench or an Agent."""
    try:
        return get_next_actions(session, subject_type, subject_id)
    except ValueError as error:
        detail = str(error)
        code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail) from error


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
    except ValueError as error:
        detail = str(error)
        code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=detail) from error
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


@app.post(
    "/projects/{project_id}/formal-retrieval-runs",
    status_code=status.HTTP_201_CREATED,
)
def create_formal_retrieval_run(
    project_id: int,
    payload: FormalRetrievalRunCreate,
    session: Session = Depends(get_session),
):
    try:
        run = record_formal_retrieval_run(session, project_id, payload)
    except ValueError as error:
        detail = str(error)
        code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail) from error
    return {"run_id": run.id, "complete": run.complete, "truncated": run.truncated}


@app.get("/projects/{project_id}/formal-retrieval-status")
def get_formal_retrieval_status(project_id: int, session: Session = Depends(get_session)):
    try:
        readiness = formal_retrieval_readiness(session, project_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        **{key: value for key, value in readiness.items() if key not in {"runs", "incomplete_runs"}},
        "runs": [
            {
                "id": item.id, "source": item.source, "query": item.query_text,
                "database_total_count": item.database_total_count,
                "retrieved_count": item.retrieved_count, "imported_count": item.imported_count,
                "page_count": item.page_count, "complete": item.complete,
                "truncated": item.truncated, "max_records": item.max_records,
            }
            for item in readiness["runs"]
        ],
    }


@app.post(
    "/projects/{project_id}/citations/import-file",
    status_code=status.HTTP_201_CREATED,
)
def import_citations_from_file(
    project_id: int,
    payload: CitationFileImportRequest,
    session: Session = Depends(get_session),
):
    try:
        citations = parse_citation_file(payload.file_path, payload.file_format)
        imported_citations = import_citations_record(
            session,
            project_id,
            CitationImportPayload(source=payload.source, citations=citations),
            actor="system",
        )
    except ValueError as error:
        if str(error) == "Project not found":
            raise HTTPException(status_code=404, detail="Project not found") from error
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "project_id": project_id,
        "source": payload.source,
        "file_path": payload.file_path,
        "parsed_count": len(citations),
        "imported_count": len(imported_citations),
    }


@app.post("/projects/{project_id}/offline-evidence-packages/{package_id}/import")
def import_offline_evidence_package(
    project_id: int,
    package_id: str,
    session: Session = Depends(get_session),
):
    try:
        return import_offline_evidence_package_record(session, project_id, package_id)
    except OfflineEvidencePackageError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ValueError as error:
        if "not found" in str(error).lower():
            raise HTTPException(status_code=404, detail=str(error)) from error
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/projects/{project_id}/deduplicate")
def deduplicate(
    project_id: int,
    session: Session = Depends(get_session),
):
    try:
        removed_count = deduplicate_project_record(session, project_id, actor="system")
    except ValueError as error:
        detail = str(error)
        code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=detail) from error
    return {"removed_count": removed_count}


@app.post("/projects/{project_id}/full-text-preflight")
def save_full_text_preflight(
    project_id: int,
    payload: FullTextPreflightBatchCreate,
    session: Session = Depends(get_session),
):
    """Accept direct desktop-to-backend full-text handoff without model context."""
    try:
        return save_full_text_preflight_record(session, project_id, payload.results, actor="desktop_client")
    except ValueError as error:
        detail = str(error)
        code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail) from error


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
    except ValueError as error:
        detail = str(error)
        code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=detail) from error
    prisma = rebuild_prisma_counts(session, project_id)
    return {
        "decision_id": result["decision_ids"][0] if result["decision_ids"] else None,
        "submitted_count": result["submitted_count"],
        "prisma": PrismaRead.model_validate(prisma).model_dump(),
    }


@app.get("/projects/{project_id}/screening/pending-batch")
def get_pending_screening_batch(
    project_id: int,
    after_id: int | None = Query(default=None, ge=0),
    limit: int = Query(default=25, ge=1, le=50),
    original_research_only: bool = True,
    session: Session = Depends(get_session),
):
    """Return only active citations that still need screening, with rule suggestions."""
    if not session.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return list_pending_screening_batch(
        session,
        project_id,
        after_id=after_id,
        limit=limit,
        original_research_only=original_research_only,
    )


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


@app.get("/workbench/overview")
def get_workbench_overview(session: Session = Depends(get_session)):
    """Read-only summary for the B/S research workbench."""
    return workbench_overview(session)


@app.get("/workbench/study-design-projects/{project_id}")
def get_workbench_study_design_detail(
    project_id: int, session: Session = Depends(get_session)
):
    detail = study_design_detail(session, project_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Study-design project not found")
    return detail


@app.get("/workbench/review-projects/{project_id}")
def get_workbench_review_detail(project_id: int, session: Session = Depends(get_session)):
    detail = review_detail(session, project_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Review project not found")
    return detail


@app.get("/workbench/research-writing-drafts/{draft_id}")
def get_workbench_writing_detail(draft_id: int, session: Session = Depends(get_session)):
    detail = writing_detail(session, draft_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Research-writing draft not found")
    return detail


def _workbench_export_response(
    payload: dict,
    format: str,
    filename_stem: str,
) -> PlainTextResponse | JSONResponse:
    if format == "markdown":
        markdown = payload["markdown"]
        return PlainTextResponse(
            markdown,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename_stem}.md"'},
        )
    return JSONResponse(
        jsonable_encoder(payload["bundle"]),
        headers={"Content-Disposition": f'attachment; filename="{filename_stem}.json"'},
    )


@app.get("/workbench/review-projects/{project_id}/export")
def download_workbench_review_bundle(
    project_id: int,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    session: Session = Depends(get_session),
):
    try:
        bundle = build_review_bundle_data(session, project_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if bundle is None:
        raise HTTPException(status_code=404, detail="Review project not found")
    payload = {"markdown": render_review_bundle_markdown(bundle), "bundle": bundle}
    return _workbench_export_response(payload, format, f"review-project-{project_id}")


@app.get("/workbench/study-design-projects/{project_id}/export")
def download_workbench_study_design_bundle(
    project_id: int,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    session: Session = Depends(get_session),
):
    try:
        bundle = build_study_design_bundle_data(session, project_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if bundle is None:
        raise HTTPException(status_code=404, detail="Study-design project not found")
    payload = {"markdown": render_study_design_bundle_markdown(bundle), "bundle": bundle}
    return _workbench_export_response(payload, format, f"study-design-project-{project_id}")


@app.get("/workbench/review-projects/{project_id}/evidence-workflows/{workflow_run_id}/export")
def download_workbench_systematic_evidence_bundle(
    project_id: int,
    workflow_run_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    session: Session = Depends(get_session),
):
    try:
        require_systematic_evidence_approval(session, project_id, workflow_run_id)
        bundle = build_systematic_evidence_bundle_data(session, project_id, workflow_run_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    payload = {"markdown": render_systematic_evidence_bundle_markdown(bundle), "bundle": bundle}
    return _workbench_export_response(
        payload, format, f"systematic-evidence-{project_id}-{workflow_run_id[:8]}"
    )


@app.get("/workbench/research-writing-drafts/{draft_id}/export")
def download_workbench_research_writing_bundle(
    draft_id: int,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    session: Session = Depends(get_session),
):
    draft = session.get(ResearchWritingDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Research-writing draft not found")
    try:
        bundle = build_research_writing_bundle_data(session, draft_id, draft.workflow_run_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    payload = {"markdown": render_research_writing_bundle_markdown(bundle), "bundle": bundle}
    return _workbench_export_response(payload, format, f"research-writing-draft-{draft_id}")


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


def _require_systematic_evidence_approval_key(approval_key: str | None) -> None:
    configured = settings.systematic_evidence_approval_key
    if not configured or approval_key != configured:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Systematic evidence approval key is not valid or not configured.",
        )


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


@app.get("/projects/{project_id}/systematic-evidence/{workflow_run_id}/approval")
def get_systematic_evidence_approval(
    project_id: int,
    workflow_run_id: str,
    session: Session = Depends(get_session),
):
    try:
        return systematic_evidence_review_snapshot(session, project_id, workflow_run_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/projects/{project_id}/systematic-evidence/{workflow_run_id}/approve")
def approve_systematic_evidence(
    project_id: int,
    workflow_run_id: str,
    payload: SystematicEvidenceApprovalRequest,
    x_systematic_evidence_approval_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    _require_systematic_evidence_approval_key(x_systematic_evidence_approval_key)
    try:
        approval = approve_systematic_evidence_review_record(
            session, project_id, workflow_run_id, payload.approved_by
        )
        return {
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "approval": {
                "status": approval.status,
                "scope_digest": approval.scope_digest,
                "approved_by": approval.approved_by,
                "approved_at": approval.approved_at,
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
