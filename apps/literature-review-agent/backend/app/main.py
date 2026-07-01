from fastapi import Depends, FastAPI, HTTPException, status
from sqlmodel import Session, select

from .config import settings
from .db import get_session, init_db
from .models import AuditLog, Project, ProjectStatus, SearchStrategyVersion
from .schemas import ProjectCreate, ProjectRead, SearchStrategyRead
from .services.search_strategy import build_pubmed_query

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
    project = Project.model_validate(payload.model_dump())
    session.add(project)
    session.commit()
    session.refresh(project)

    session.add(
        AuditLog(
            project_id=project.id,
            action="project.created",
            actor="system",
            summary=f"Project {project.title} created",
        )
    )
    session.commit()
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
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

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
            actor="system",
            summary="Generated PubMed search strategy",
        )
    )
    session.commit()
    session.refresh(strategy)
    return SearchStrategyRead.model_validate(strategy).model_dump()
