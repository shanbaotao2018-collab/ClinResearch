import hashlib
import hmac
import json
import stat
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import StudyDesignAuditLog, StudyDesignRandomizationSchedule, StudyDesignSkillExecutionReceipt
from app.schemas import StudyDesignContentUpdate, StudyDesignProjectCreate
from app.services.phi_guard import PotentialPHIError
from app.services.study_design import (
    approve_study_design_record,
    build_study_design_bundle_data,
    calculate_study_sample_size_record,
    create_study_design_project_record,
    generate_rct_randomization_record,
    generate_study_design_blueprint_record,
    read_randomization_schedule_record,
    render_study_design_bundle_markdown,
    require_skill_receipts,
    request_study_design_approval_record,
    save_rct_randomization_plan_record,
    save_study_design_content_record,
    start_study_design_workflow_run,
)
from app.main import app


def _create_rct_project(session: Session):
    return create_study_design_project_record(session, StudyDesignProjectCreate(
        title="SGLT2 pragmatic RCT", research_question="Can an SGLT2 inhibitor reduce heart-failure hospitalization?",
        study_type="efficacy", study_design="RCT, parallel-group", population="Adults with type 2 diabetes and high cardiovascular risk",
        intervention="SGLT2 inhibitor", comparator="Standard care", outcome="Heart-failure hospitalization within 12 months",
        department="Cardiology", resource_summary="Estimated 300 eligible cases annually"), actor="test")


def _prepare_for_approval(session: Session, project_id: int) -> None:
    generate_study_design_blueprint_record(session, project_id, actor="test")
    save_study_design_content_record(session, project_id, StudyDesignContentUpdate(
        inclusion_criteria="Adults with confirmed type 2 diabetes and documented cardiovascular risk.",
        exclusion_criteria="Pregnancy, contraindication, or an unresolved safety concern.",
        primary_outcome="First heart-failure hospitalization within 12 months.",
        secondary_outcomes="All-cause hospitalization and renal function change.",
        innovation_notes="Pragmatic implementation in routine cardiometabolic care.",
        feasibility_notes="The department estimates 300 potentially eligible cases per year.",
        proposal_outline="Background; objectives; design; participants; outcomes; analysis; ethics."), actor="test")
    calculate_study_sample_size_record(session, project_id, method="proportions", alpha=0.05, power=0.8, group_one_value=0.18, group_two_value=0.12, actor="test")
    save_rct_randomization_plan_record(session, project_id, 24, ["standard_care", "sglt2"], 4, actor="test")


def test_rct_schedule_requires_external_approval_and_stays_redacted(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "randomization_storage_dir", str(tmp_path))
    with Session(engine) as session:
        project = _create_rct_project(session)
        _prepare_for_approval(session, project.id)
        with pytest.raises(ValueError, match="Internal human confirmation"):
            generate_rct_randomization_record(session, project.id, actor="test")
        with pytest.raises(ValueError, match="Internal human confirmation"):
            build_study_design_bundle_data(session, project.id)

        approval = request_study_design_approval_record(session, project.id, actor="test")
        assert approval.status == "pending"
        approve_study_design_record(session, project.id, "authorized_researcher")
        metadata = generate_rct_randomization_record(session, project.id, actor="test")
        assert metadata["allocation_visible_to_agent"] is False
        assert metadata["total_subjects"] == 24
        assert "schedule" not in metadata

        stored = session.exec(select(StudyDesignRandomizationSchedule)).one()
        assert stat.S_IMODE(tmp_path.joinpath(f"study-design-{project.id}-randomization.json").stat().st_mode) == 0o600
        assert stored.checksum == metadata["checksum"]
        operator_schedule = read_randomization_schedule_record(session, project.id)
        assert len(operator_schedule) == 24
        assert {item["allocation"] for item in operator_schedule} == {"standard_care", "sglt2"}

        bundle = build_study_design_bundle_data(session, project.id)
        assert bundle is not None
        assert "randomization_schedule" not in bundle
        markdown = render_study_design_bundle_markdown(bundle)
        assert "Allocation sequence is withheld" in markdown
        assert "| Sequence |" not in markdown
        assert "standard_care" in markdown  # Plan groups are visible; assignments are not.


def test_sample_size_rejects_unsupported_or_invalid_inputs():
    with Session(engine) as session:
        project = _create_rct_project(session)
        generate_study_design_blueprint_record(session, project.id, actor="test")
        with pytest.raises(ValueError, match="method must be"):
            calculate_study_sample_size_record(session, project.id, "survival", 0.05, 0.8, 1.0, 0.8, actor="test")
        with pytest.raises(ValueError, match="standard_deviation"):
            calculate_study_sample_size_record(session, project.id, "means", 0.05, 0.8, 7.0, 6.5, actor="test")


def test_non_rct_rejects_randomization_plan():
    with Session(engine) as session:
        project = create_study_design_project_record(session, StudyDesignProjectCreate(
            title="Prognostic cohort", research_question="Can baseline frailty predict hospitalization?", study_type="prognosis",
            study_design="Prospective cohort", population="Older adults with heart failure", outcome="Hospitalization within one year"), actor="test")
        with pytest.raises(ValueError, match="only available"):
            save_rct_randomization_plan_record(session, project.id, 20, ["control", "treatment"], 4, actor="test")


def test_repeated_draft_operations_are_idempotent():
    with Session(engine) as session:
        project = _create_rct_project(session)
        generate_study_design_blueprint_record(session, project.id, actor="test")
        content = StudyDesignContentUpdate(inclusion_criteria="Adults with confirmed type 2 diabetes.", exclusion_criteria="Pregnancy or a major safety concern.", primary_outcome="Heart-failure hospitalization within 12 months.", proposal_outline="Background; objectives; design; outcomes; analysis; ethics.")
        save_study_design_content_record(session, project.id, content, actor="test")
        calculate_study_sample_size_record(session, project.id, "proportions", 0.05, 0.8, 0.18, 0.12, actor="test")
        save_rct_randomization_plan_record(session, project.id, 24, ["standard_care", "sglt2"], 4, actor="test")
        before_count = len(session.exec(select(StudyDesignAuditLog).where(StudyDesignAuditLog.study_design_project_id == project.id)).all())
        save_study_design_content_record(session, project.id, content, actor="retry")
        calculate_study_sample_size_record(session, project.id, "proportions", 0.05, 0.8, 0.18, 0.12, actor="retry")
        save_rct_randomization_plan_record(session, project.id, 24, ["standard_care", "sglt2"], 4, actor="retry")
        after_count = len(session.exec(select(StudyDesignAuditLog).where(StudyDesignAuditLog.study_design_project_id == project.id)).all())
        assert after_count == before_count


def test_phi_guard_rejects_identifiers_before_project_creation():
    with Session(engine) as session:
        with pytest.raises(PotentialPHIError, match="Potential PHI"):
            create_study_design_project_record(session, StudyDesignProjectCreate(
                title="Patient MRN: A12345", research_question="Example", study_type="efficacy", study_design="RCT",
                population="Adults", outcome="Outcome"), actor="test")


def test_protected_approval_and_schedule_endpoints(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "randomization_storage_dir", str(tmp_path))
    monkeypatch.setattr(settings, "study_design_approval_key", "test-approval-key")
    with Session(engine) as session:
        project = _create_rct_project(session)
        project_id = project.id
        _prepare_for_approval(session, project.id)
        request_study_design_approval_record(session, project.id, actor="test")

    client = TestClient(app)
    denied = client.post(f"/study-design-projects/{project_id}/approve", json={"approved_by": "operator"})
    assert denied.status_code == 403
    approved = client.post(
        f"/study-design-projects/{project_id}/approve",
        headers={"X-Study-Approval-Key": "test-approval-key"},
        json={"approved_by": "operator"},
    )
    assert approved.status_code == 200
    with Session(engine) as session:
        generate_rct_randomization_record(session, project_id, actor="test")
    denied_schedule = client.get(f"/study-design-projects/{project_id}/randomization-schedule")
    assert denied_schedule.status_code == 403
    authorized_schedule = client.get(
        f"/study-design-projects/{project_id}/randomization-schedule",
        headers={"X-Study-Approval-Key": "test-approval-key"},
    )
    assert authorized_schedule.status_code == 200
    assert len(authorized_schedule.json()["schedule"]) == 24


def test_signed_skill_receipts_are_required_and_tampering_is_rejected(monkeypatch, tmp_path):
    secret = "test-skill-receipt-key"
    monkeypatch.setattr(settings, "skill_receipt_key", secret)
    monkeypatch.setattr(settings, "skill_receipt_dir", str(tmp_path))
    with Session(engine) as session:
        project = _create_rct_project(session)
        run = start_study_design_workflow_run(session, project.id, actor="test")
        with pytest.raises(ValueError, match="Verified OpenCode Skill receipts"):
            require_skill_receipts(session, run.run_id, project.id, "blueprint")

        receipts = []
        for skill_name in ["phi-prompt-guard", "clinic-research-design", "inclusion-criteria-gen", "research-proposal-generator"]:
            receipt_id = str(uuid4())
            timestamp = 1_784_107_500_000
            signature = hmac.new(secret.encode(), f"{receipt_id}|ses_test|{skill_name}|{timestamp}".encode(), hashlib.sha256).hexdigest()
            receipts.append({"receipt_id": receipt_id, "opencode_session_id": "ses_test", "skill_name": skill_name, "executed_at_ms": timestamp, "signature": signature})
        journal = {"version": 1, "workflow_run_id": run.run_id, "study_design_project_id": project.id, "opencode_session_id": "ses_test", "receipts": receipts}
        tmp_path.joinpath(f"{run.run_id}.json").write_text(json.dumps(journal), encoding="utf-8")
        require_skill_receipts(session, run.run_id, project.id, "blueprint")
        assert len(session.exec(select(StudyDesignSkillExecutionReceipt)).all()) == 4

        receipts[0]["signature"] = "tampered"
        tmp_path.joinpath(f"{run.run_id}.json").write_text(json.dumps(journal), encoding="utf-8")
        with pytest.raises(ValueError, match="signature verification failed"):
            require_skill_receipts(session, run.run_id, project.id, "blueprint")
