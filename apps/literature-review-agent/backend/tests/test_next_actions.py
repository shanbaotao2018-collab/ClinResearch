from sqlmodel import Session

from app.db import engine
from app.models import Project, ProjectStatus, StudyDesignProject, StudyDesignStatus
from app.services.next_actions import get_next_actions


def test_study_design_only_hands_off_after_export():
    with Session(engine) as session:
        project = StudyDesignProject(
            title="Next action study",
            research_question="Can next actions stay in one agent?",
            study_type="observational",
            study_design="cohort",
            population="Adults",
            outcome="Follow-up",
            status=StudyDesignStatus.SAMPLE_SIZE_READY,
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        pending = get_next_actions(session, "study_design", project.id)
        assert pending["actions"][0]["target_agent"] == "study-design"

        project.status = StudyDesignStatus.EXPORTED
        session.add(project)
        session.commit()
        completed = get_next_actions(session, "study_design", project.id)
        assert completed["actions"][0]["target_agent"] == "literature-review"


def test_review_requires_screening_before_evidence_handoff():
    with Session(engine) as session:
        project = Project(
            title="Next action review",
            research_question="Can review wait for screening?",
            status=ProjectStatus.SEARCH_STRATEGY_READY,
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        pending = get_next_actions(session, "review", project.id)
        assert pending["actions"][0]["target_agent"] == "literature-review"
        assert pending["actions"][0]["action_id"] == "retrieve_citations"


def test_evidence_is_blocked_without_included_citations():
    with Session(engine) as session:
        project = Project(
            title="Blocked evidence",
            research_question="Can evidence start without inclusion?",
            status=ProjectStatus.SCREENING_COMPLETED,
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        result = get_next_actions(session, "evidence", project.id)
        assert result["workflow_status"] == "blocked"
        assert result["actions"][0]["target_agent"] == "literature-review"
