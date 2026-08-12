from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session

from app.models import Project, ResearchCase, StudyDesignProject


def _case_payload(session: Session, case: ResearchCase) -> dict[str, object]:
    study = session.get(StudyDesignProject, case.study_design_project_id) if case.study_design_project_id else None
    review = session.get(Project, case.review_project_id) if case.review_project_id else None
    return {
        "id": case.id,
        "title": case.title,
        "description": case.description,
        "study_design_project": (
            {"id": study.id, "title": study.title, "status": study.status.value} if study else None
        ),
        "review_project": (
            {"id": review.id, "title": review.title, "status": review.status.value} if review else None
        ),
    }


def create_research_case_record(session: Session, title: str, description: str | None = None) -> dict[str, object]:
    if not title.strip():
        raise ValueError("Case title must not be empty.")
    case = ResearchCase(title=title.strip(), description=description.strip() if description else None)
    session.add(case)
    session.commit()
    session.refresh(case)
    return _case_payload(session, case)


def link_research_case_record(
    session: Session,
    case_id: int,
    study_design_project_id: int | None = None,
    review_project_id: int | None = None,
) -> dict[str, object]:
    case = session.get(ResearchCase, case_id)
    if not case:
        raise ValueError(f"Research case {case_id} not found.")
    if study_design_project_id is not None:
        if not session.get(StudyDesignProject, study_design_project_id):
            raise ValueError(f"Study-design project {study_design_project_id} not found.")
        case.study_design_project_id = study_design_project_id
    if review_project_id is not None:
        if not session.get(Project, review_project_id):
            raise ValueError(f"Review project {review_project_id} not found.")
        case.review_project_id = review_project_id
    if case.study_design_project_id is None and case.review_project_id is None:
        raise ValueError("Link at least one study-design project or review project.")
    case.updated_at = datetime.now(UTC)
    session.add(case)
    session.commit()
    session.refresh(case)
    return _case_payload(session, case)


def get_research_case_record(session: Session, case_id: int) -> dict[str, object]:
    case = session.get(ResearchCase, case_id)
    if not case:
        raise ValueError(f"Research case {case_id} not found.")
    return _case_payload(session, case)
