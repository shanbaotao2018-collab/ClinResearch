from sqlmodel import Session

from app.db import engine
from app.models import StudyDesignProject
from app.schemas import ProjectCreate
from app.services.project_context import get_agent_project_context_record
from app.services.project_workflow import create_project_record, import_citations_record
from app.services.citations import CitationImportPayload


def test_study_design_context_is_readable_without_exposing_allocations():
    with Session(engine) as session:
        project = StudyDesignProject(
            title="Transition-care RCT",
            research_question="Does follow-up reduce readmission?",
            study_type="efficacy",
            study_design="RCT",
            population="Adults with heart failure",
            intervention="Pharmacist telephone follow-up",
            comparator="Usual care",
            outcome="30-day readmission",
            randomization_seed=123,
            randomization_schedule_json='[{"allocation":"hidden"}]',
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        context = get_agent_project_context_record(session, "study_design", project.id)

    assert context["reference"] == f"study_design:{project.id}"
    assert context["context"]["project"]["population"] == "Adults with heart failure"
    assert "randomization_seed" not in context["context"]["project"]
    assert "randomization_schedule_json" not in context["context"]["project"]


def test_evidence_context_uses_the_parent_review_project_id():
    with Session(engine) as session:
        review = create_project_record(
            session,
            ProjectCreate(title="Heart failure review", research_question="Does follow-up reduce readmission?"),
        )
        import_citations_record(
            session,
            review.id,
            CitationImportPayload(
                source="pubmed",
                citations=[{"external_id": "123", "title": "Example trial", "abstract": "Trial abstract."}],
            ),
            actor="test",
        )

        context = get_agent_project_context_record(session, "evidence_extraction", review.id)

    assert context["reference"] == f"evidence:{review.id}"
    assert context["source_refs"] == [{"project_type": "review", "project_id": review.id}]
    assert context["context"]["citations"][0]["title"] == "Example trial"
    assert context["evidence_resume_summary"] == {
        "basic_extraction_count": 0,
        "citation_safety_check_count": 0,
        "full_text_cached_count": 0,
        "full_text_detail_count": 0,
        "bias_assessment_count": 0,
        "fully_evaluated_full_text_citation_ids": [],
        "resume_rule": "已有全文评价记录应直接复用；仅当已缓存全文缺少详细抽取或偏倚评价时，才请求进入全文系统评价阶段。",
    }
