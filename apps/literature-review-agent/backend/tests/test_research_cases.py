from sqlmodel import Session

from app.db import engine
from app.models import StudyDesignProject
from app.schemas import ProjectCreate
from app.services.project_workflow import create_project_record
from app.services.research_cases import (
    create_research_case_record,
    get_research_case_record,
    link_research_case_record,
)


def test_research_case_links_study_design_and_review_projects():
    with Session(engine) as session:
        review = create_project_record(
            session,
            ProjectCreate(title="Offline review", research_question="Does an intervention help?"),
        )
        study = StudyDesignProject(
            title="Offline study design",
            research_question="Does an intervention help?",
            study_type="efficacy",
            study_design="rct",
            population="Adults",
            outcome="Readmission",
        )
        session.add(study)
        session.commit()
        session.refresh(study)
        case = create_research_case_record(session, "Heart failure transition care")
        linked = link_research_case_record(
            session,
            case["id"],
            study_design_project_id=study.id,
            review_project_id=review.id,
        )
        reread = get_research_case_record(session, case["id"])

    assert linked["study_design_project"]["id"] == study.id
    assert linked["review_project"]["id"] == review.id
    assert reread["title"] == "Heart failure transition care"
