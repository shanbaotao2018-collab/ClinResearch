import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.main import app
from app.models import AgentSkillExecutionReceipt, ResearchWritingDraft
from app.schemas import ResearchWritingDraftCreate, StudyDesignContentUpdate, StudyDesignProjectCreate
from app.services.agent_workflows import require_agent_skill_receipts
from app.services.research_writing import (
    BASE_WRITING_SKILLS,
    PROPOSAL_SKILL,
    approve_research_writing_record,
    build_research_writing_bundle_data,
    get_research_writing_source_data,
    render_research_writing_bundle_markdown,
    request_research_writing_approval_record,
    required_writing_skills,
    save_research_writing_draft_record,
    start_research_writing_workflow_record,
)
from app.services.study_design import (
    create_study_design_project_record,
    generate_study_design_blueprint_record,
    save_study_design_content_record,
)


def _study_design_source(session: Session):
    project = create_study_design_project_record(
        session,
        StudyDesignProjectCreate(
            title="Frailty and heart-failure readmission cohort",
            research_question="Does baseline frailty predict readmission in older adults with heart failure?",
            study_type="prognosis",
            study_design="Prospective cohort",
            population="Adults aged 65 years or older admitted with heart failure",
            outcome="All-cause readmission within 90 days",
            department="Cardiology",
            resource_summary="De-identified registry with approximately 600 eligible admissions.",
        ),
        actor="test",
    )
    generate_study_design_blueprint_record(session, project.id, actor="test")
    save_study_design_content_record(
        session,
        project.id,
        StudyDesignContentUpdate(
            inclusion_criteria="Adults aged 65 years or older with an index heart-failure admission.",
            exclusion_criteria="Missing baseline frailty assessment or unavailable 90-day follow-up.",
            primary_outcome="First all-cause readmission within 90 days after discharge.",
            proposal_outline="Background; objective; cohort; variables; outcome; analysis; limitations.",
            feasibility_notes="Registry data are de-identified and available after governance review.",
        ),
        actor="test",
    )
    return project


def _write_receipts(tmp_path, secret: str, run, skills: set[str]) -> None:
    receipts = []
    for index, skill_name in enumerate(sorted(skills)):
        receipt_id = str(uuid4())
        timestamp = 1_784_207_500_000 + index
        signature = hmac.new(
            secret.encode(),
            f"{receipt_id}|ses_writing|{skill_name}|{timestamp}".encode(),
            hashlib.sha256,
        ).hexdigest()
        receipts.append(
            {
                "receipt_id": receipt_id,
                "opencode_session_id": "ses_writing",
                "skill_name": skill_name,
                "executed_at_ms": timestamp,
                "signature": signature,
            }
        )
    tmp_path.joinpath(f"{run.run_id}.json").write_text(
        json.dumps(
            {
                "version": 1,
                "workflow_run_id": run.run_id,
                "workflow_type": "research_writing",
                "subject_type": run.subject_type,
                "subject_id": run.subject_id,
                "opencode_session_id": "ses_writing",
                "receipts": receipts,
            }
        ),
        encoding="utf-8",
    )


def _protocol_payload(project_id: int) -> ResearchWritingDraftCreate:
    return ResearchWritingDraftCreate(
        title="Frailty and 90-day readmission: protocol draft",
        target_audience="department research review meeting",
        source_manifest=[
            {
                "source_type": "study_design",
                "source_id": str(project_id),
                "description": "Saved study-design protocol content and feasibility notes.",
            }
        ],
        outline="Background; objective; design; participants; predictors; outcome; analysis; limitations.",
        methods_draft="Prospective cohort using the approved de-identified registry definition set.",
        discussion_framework="Explain clinical relevance, residual confounding, and single-center limits without claiming results.",
        limitations="No observed effect estimates or causal conclusions are available in this draft.",
        unresolved_items="Confirm frailty instrument, missing-data rule, and governance approval before execution.",
    )


def _review_article_payload(project_id: int) -> ResearchWritingDraftCreate:
    return ResearchWritingDraftCreate(
        title="Proteomics and incident diabetes: partial evidence synthesis",
        target_audience="clinical research team",
        source_manifest=[
            {
                "source_type": "review",
                "source_id": str(project_id),
                "description": "open_access_evidence_synthesis from saved evidence extraction records.",
            }
        ],
        outline="Background; search and evidence scope; study characteristics; findings; limitations; conclusion.",
        review_draft="This is a researcher-reviewable review article draft based on recorded evidence.",
        limitations="Based on available full text only; not a complete systematic review.",
        unresolved_items="Confirm all extracted effect estimates against full text before publication use.",
    )


def test_research_writing_requires_signed_skills_and_external_approval(monkeypatch, tmp_path):
    secret = "test-writing-receipt-key"
    monkeypatch.setattr(settings, "skill_receipt_key", secret)
    monkeypatch.setattr(settings, "skill_receipt_dir", str(tmp_path))
    monkeypatch.setattr(settings, "skill_receipt_enforcement", "strict")
    with Session(engine) as session:
        project = _study_design_source(session)
        source = get_research_writing_source_data(session, "study_design", project.id)
        assert source["project"]["primary_outcome"] == "First all-cause readmission within 90 days after discharge."
        assert "unresolved_items" in source["writing_rule"]
        run = start_research_writing_workflow_record(
            session, "study_design", project.id, "protocol", actor="test"
        )
        with pytest.raises(ValueError, match="biomed-outline-generator"):
            require_agent_skill_receipts(
                session, run.run_id, "research_writing", "study_design", project.id,
                "research_writing_draft", required_writing_skills("protocol"),
            )
        _write_receipts(tmp_path, secret, run, BASE_WRITING_SKILLS)
        require_agent_skill_receipts(
            session, run.run_id, "research_writing", "study_design", project.id,
            "research_writing_draft", required_writing_skills("protocol"),
        )
        draft = save_research_writing_draft_record(
            session, "study_design", project.id, run.run_id, "protocol", _protocol_payload(project.id), actor="test"
        )
        assert draft.version_number == 1
        with pytest.raises(ValueError, match="Internal human confirmation"):
            build_research_writing_bundle_data(session, draft.id, run.run_id)
        approval = request_research_writing_approval_record(session, draft.id, run.run_id, actor="test")
        assert approval.status == "pending"
        approve_research_writing_record(session, draft.id, "authorized_researcher")
        bundle = build_research_writing_bundle_data(session, draft.id, run.run_id)
        markdown = render_research_writing_bundle_markdown(bundle)
        assert "External approval: approved" in markdown
        assert "No observed effect estimates" in markdown
        captured = {
            item.skill_name
            for item in session.exec(select(AgentSkillExecutionReceipt)).all()
        }
        assert captured == BASE_WRITING_SKILLS
        assert session.get(ResearchWritingDraft, draft.id).status == "exported"


def test_proposal_requires_proposal_skill_and_approval_endpoint_is_protected(monkeypatch, tmp_path):
    secret = "test-proposal-receipt-key"
    monkeypatch.setattr(settings, "skill_receipt_key", secret)
    monkeypatch.setattr(settings, "skill_receipt_dir", str(tmp_path))
    monkeypatch.setattr(settings, "skill_receipt_enforcement", "strict")
    monkeypatch.setattr(settings, "research_writing_approval_key", "writing-approval-key")
    with Session(engine) as session:
        project = _study_design_source(session)
        run = start_research_writing_workflow_record(
            session, "study_design", project.id, "proposal", actor="test"
        )
        _write_receipts(tmp_path, secret, run, BASE_WRITING_SKILLS)
        with pytest.raises(ValueError, match="research-proposal-generator"):
            require_agent_skill_receipts(
                session, run.run_id, "research_writing", "study_design", project.id,
                "research_writing_draft", required_writing_skills("proposal"),
            )
        _write_receipts(tmp_path, secret, run, BASE_WRITING_SKILLS | PROPOSAL_SKILL)
        proposal = _protocol_payload(project.id).model_copy(
            update={
                "title": "Frailty and readmission: proposal draft",
                "proposal_draft": "Scientific question; cohort plan; variable definitions; proposed milestones. No budget figures are invented.",
            }
        )
        draft = save_research_writing_draft_record(
            session, "study_design", project.id, run.run_id, "proposal", proposal, actor="test"
        )
        request_research_writing_approval_record(session, draft.id, run.run_id, actor="test")
        draft_id = draft.id

    client = TestClient(app)
    denied = client.post(
        f"/research-writing-drafts/{draft_id}/approve", json={"approved_by": "operator"}
    )
    assert denied.status_code == 403
    approved = client.post(
        f"/research-writing-drafts/{draft_id}/approve",
        headers={"X-Research-Writing-Approval-Key": "writing-approval-key"},
        json={"approved_by": "operator"},
    )
    assert approved.status_code == 200


def test_review_article_requires_review_source_and_persists_review_content(monkeypatch, tmp_path):
    secret = "test-review-article-receipt-key"
    monkeypatch.setattr(settings, "skill_receipt_key", secret)
    monkeypatch.setattr(settings, "skill_receipt_dir", str(tmp_path))
    monkeypatch.setattr(settings, "skill_receipt_enforcement", "strict")
    with Session(engine) as session:
        project = _study_design_source(session)
        run = start_research_writing_workflow_record(
            session, "study_design", project.id, "protocol", actor="test"
        )
        _write_receipts(tmp_path, secret, run, BASE_WRITING_SKILLS)
        with pytest.raises(ValueError, match="requires source_type='review'"):
            save_research_writing_draft_record(
                session,
                "study_design",
                project.id,
                run.run_id,
                "review_article",
                _review_article_payload(project.id),
                actor="test",
            )
