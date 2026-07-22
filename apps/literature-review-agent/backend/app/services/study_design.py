from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import random
from datetime import UTC, datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any
from uuid import uuid4

from sqlmodel import Session, select

from app.config import settings
from app.models import (
    StudyDesignApproval,
    StudyDesignApprovalStatus,
    StudyDesignAuditLog,
    StudyDesignProject,
    StudyDesignRandomizationPlan,
    StudyDesignRandomizationSchedule,
    StudyDesignSkillExecutionReceipt,
    StudyDesignStatus,
    StudyDesignWorkflowEvent,
    StudyDesignWorkflowRun,
)
from app.schemas import StudyDesignContentUpdate, StudyDesignProjectCreate
from app.services.phi_guard import assert_no_phi


_STUDY_TYPE_BLUEPRINTS = {
    "diagnostic": {
        "reporting_standard": "STARD",
        "recommended_design": "Diagnostic accuracy study",
        "required_sections": ["Index test and reference standard", "Target condition and recruitment setting", "Diagnostic threshold and blinding plan", "Sensitivity, specificity, and confidence intervals"],
    },
    "efficacy": {
        "reporting_standard": "SPIRIT/CONSORT",
        "recommended_design": "Randomized controlled trial or comparative effectiveness study",
        "required_sections": ["Intervention and comparator", "Allocation, concealment, and blinding", "Primary outcome and follow-up schedule", "Safety monitoring and analysis population"],
    },
    "etiology": {
        "reporting_standard": "STROBE",
        "recommended_design": "Cohort or case-control study",
        "required_sections": ["Exposure definition and ascertainment", "Outcome definition and follow-up window", "Confounders and adjustment plan", "Missing-data and sensitivity-analysis plan"],
    },
    "prognosis": {
        "reporting_standard": "TRIPOD",
        "recommended_design": "Prognostic cohort study",
        "required_sections": ["Index time and target population", "Predictors and outcome time horizon", "Event definition and censoring rules", "Validation and calibration plan"],
    },
}

_SKILL_GATES = {
    "blueprint": {"phi-prompt-guard", "clinic-research-design", "inclusion-criteria-gen", "research-proposal-generator"},
    "content": {"biomed-outline-generator", "method-writing"},
    "sample_size": {"sample-size-basic"},
    "randomization": {"randomization-gen"},
}


def _get_project_or_raise(session: Session, project_id: int) -> StudyDesignProject:
    project = session.get(StudyDesignProject, project_id)
    if not project:
        raise ValueError(f"Study design project {project_id} not found.")
    return project


def _append_audit_log(session: Session, project_id: int, action: str, actor: str, summary: str) -> None:
    session.add(StudyDesignAuditLog(study_design_project_id=project_id, action=action, actor=actor, summary=summary))


def _is_rct(project: StudyDesignProject) -> bool:
    design = project.study_design.lower()
    return (
        "rct" in design
        or "random" in design
        or "随机对照" in project.study_design
        or ("随机" in project.study_design and "对照" in project.study_design)
    )


def _ensure_draft_mutable(project: StudyDesignProject) -> None:
    if project.status in {StudyDesignStatus.APPROVAL_PENDING, StudyDesignStatus.HUMAN_APPROVED, StudyDesignStatus.RANDOMIZATION_READY, StudyDesignStatus.EXPORTED}:
        raise ValueError("This project is under or past internal confirmation. Create a new revision before changing its design assumptions.")


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _receipt_signature(receipt_id: str, session_id: str, skill_name: str, executed_at_ms: int) -> str:
    if not settings.skill_receipt_key:
        raise ValueError("Skill receipt verification is not configured.")
    payload = f"{receipt_id}|{session_id}|{skill_name}|{executed_at_ms}".encode("utf-8")
    return hmac.new(settings.skill_receipt_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _import_skill_execution_receipt_payload(session: Session, payload: dict[str, Any], workflow_run_id: str, project_id: int) -> int:
    if payload.get("version") != 1 or payload.get("workflow_run_id") != workflow_run_id or payload.get("study_design_project_id") != project_id:
        raise ValueError("Skill receipt journal does not match this workflow run.")
    session_id = payload.get("opencode_session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Skill receipt journal is missing its OpenCode session id.")
    imported = 0
    for item in payload.get("receipts", []):
        receipt_id = item.get("receipt_id")
        skill_name = item.get("skill_name")
        executed_at_ms = item.get("executed_at_ms")
        supplied_signature = item.get("signature")
        if not isinstance(receipt_id, str) or not isinstance(skill_name, str) or not isinstance(executed_at_ms, int) or not isinstance(supplied_signature, str):
            raise ValueError("Skill receipt journal contains an invalid receipt.")
        expected_signature = _receipt_signature(receipt_id, session_id, skill_name, executed_at_ms)
        if not hmac.compare_digest(expected_signature, supplied_signature):
            raise ValueError("Skill receipt signature verification failed.")
        if session.exec(select(StudyDesignSkillExecutionReceipt).where(StudyDesignSkillExecutionReceipt.receipt_id == receipt_id)).first():
            continue
        session.add(StudyDesignSkillExecutionReceipt(
            receipt_id=receipt_id,
            workflow_run_id=workflow_run_id,
            study_design_project_id=project_id,
            opencode_session_id=session_id,
            skill_name=skill_name,
            executed_at=datetime.fromtimestamp(executed_at_ms / 1000, UTC),
            signature=supplied_signature,
        ))
        imported += 1
    if imported:
        _append_audit_log(session, project_id, "study_design.skill_receipts_imported", "opencode_runtime", f"Imported {imported} verified OpenCode Skill execution receipts")
        session.commit()
    return imported


def import_skill_execution_receipts(session: Session, workflow_run_id: str, project_id: int) -> int:
    """Import HMAC-signed receipts created by the OpenCode runtime plugin."""
    if not settings.skill_receipt_key:
        return 0
    receipt_path = Path(settings.skill_receipt_dir) / f"{workflow_run_id}.json"
    if not receipt_path.is_file():
        return 0
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Skill receipt journal is unreadable.") from error
    return _import_skill_execution_receipt_payload(session, payload, workflow_run_id, project_id)


def import_skill_execution_receipts_from_session(session: Session, workflow_run_id: str, project_id: int, opencode_session_id: str | None) -> int:
    """Bind the current runtime session's signed Skill receipts at project creation."""
    if not settings.skill_receipt_key or not opencode_session_id:
        return 0
    receipt_path = Path(settings.skill_receipt_dir) / f"session-{opencode_session_id}.json"
    if not receipt_path.is_file():
        return 0
    try:
        session_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Skill receipt session journal is unreadable.") from error
    payload = {
        "version": session_payload.get("version"),
        "workflow_run_id": workflow_run_id,
        "study_design_project_id": project_id,
        "opencode_session_id": opencode_session_id,
        "receipts": session_payload.get("receipts", []),
    }
    return _import_skill_execution_receipt_payload(session, payload, workflow_run_id, project_id)


def require_skill_receipts(session: Session, workflow_run_id: str, project_id: int, gate: str) -> None:
    """Enforce real Skill execution only when the signed-receipt integration is enabled."""
    if not settings.skill_receipt_key:
        return
    import_skill_execution_receipts(session, workflow_run_id, project_id)
    required = _SKILL_GATES[gate]
    received = set(session.exec(select(StudyDesignSkillExecutionReceipt.skill_name).where(StudyDesignSkillExecutionReceipt.workflow_run_id == workflow_run_id)).all())
    missing = sorted(required - received)
    if missing:
        raise ValueError(f"Verified OpenCode Skill receipts are required before {gate}: {', '.join(missing)}.")


def _approval_scope(project: StudyDesignProject, plan: StudyDesignRandomizationPlan | None) -> dict[str, Any]:
    return {
        "project_id": project.id,
        "study_type": project.study_type,
        "study_design": project.study_design,
        "population": project.population,
        "intervention": project.intervention,
        "comparator": project.comparator,
        "outcome": project.outcome,
        "inclusion_criteria": project.inclusion_criteria,
        "exclusion_criteria": project.exclusion_criteria,
        "primary_outcome": project.primary_outcome,
        "secondary_outcomes": project.secondary_outcomes,
        "proposal_outline": project.proposal_outline,
        "sample_size_inputs_json": project.sample_size_inputs_json,
        "sample_size_result_json": project.sample_size_result_json,
        "randomization_plan": None if plan is None else {"total_subjects": plan.total_subjects, "groups_json": plan.groups_json, "block_size": plan.block_size},
    }


def _get_plan(session: Session, project_id: int) -> StudyDesignRandomizationPlan | None:
    return session.exec(select(StudyDesignRandomizationPlan).where(StudyDesignRandomizationPlan.study_design_project_id == project_id)).first()


def _get_approval(session: Session, project_id: int) -> StudyDesignApproval | None:
    return session.exec(select(StudyDesignApproval).where(StudyDesignApproval.study_design_project_id == project_id)).first()


def _require_approved_scope(session: Session, project: StudyDesignProject) -> StudyDesignApproval:
    approval = _get_approval(session, project.id)
    if not approval or approval.status != StudyDesignApprovalStatus.APPROVED:
        raise ValueError("Internal human confirmation is required before this operation.")
    if approval.scope_digest != _canonical_digest(_approval_scope(project, _get_plan(session, project.id))):
        raise ValueError("Confirmed design scope has changed. Request a new internal confirmation.")
    return approval


def create_study_design_project_record(session: Session, payload: StudyDesignProjectCreate, actor: str = "system") -> StudyDesignProject:
    assert_no_phi(payload.model_dump())
    project = StudyDesignProject.model_validate(payload.model_dump())
    session.add(project)
    session.commit()
    session.refresh(project)
    _append_audit_log(session, project.id, "study_design_project.created", actor, f"Created {project.study_type} study-design project: {project.title}")
    session.commit()
    session.refresh(project)
    return project


def generate_study_design_blueprint_record(session: Session, project_id: int, actor: str = "system") -> dict[str, Any]:
    project = _get_project_or_raise(session, project_id)
    _ensure_draft_mutable(project)
    blueprint = _STUDY_TYPE_BLUEPRINTS[project.study_type]
    project.protocol_standard = blueprint["reporting_standard"]
    project.status = StudyDesignStatus.BLUEPRINT_READY
    project.updated_at = datetime.now(UTC)
    session.add(project)
    _append_audit_log(session, project_id, "study_design.blueprint_generated", actor, f"Generated {blueprint['reporting_standard']} blueprint for {project.study_type}")
    session.commit()
    return {"project_id": project_id, "study_type": project.study_type, "study_design": project.study_design, "reporting_standard": blueprint["reporting_standard"], "recommended_design": blueprint["recommended_design"], "required_sections": blueprint["required_sections"], "pico": {"population": project.population, "intervention": project.intervention, "comparator": project.comparator, "outcome": project.outcome}}


def save_study_design_content_record(session: Session, project_id: int, payload: StudyDesignContentUpdate, actor: str = "system") -> StudyDesignProject:
    project = _get_project_or_raise(session, project_id)
    _ensure_draft_mutable(project)
    if project.status == StudyDesignStatus.DRAFT:
        raise ValueError("Generate the study-design blueprint before saving drafted content.")
    draft_content = payload.model_dump()
    assert_no_phi(draft_content)
    if all(getattr(project, field_name) == value for field_name, value in draft_content.items()):
        return project
    for field_name, value in draft_content.items():
        setattr(project, field_name, value)
    project.status = StudyDesignStatus.CONTENT_DRAFTED
    project.updated_at = datetime.now(UTC)
    session.add(project)
    _append_audit_log(session, project_id, "study_design.content_saved", actor, "Saved draft eligibility criteria, outcomes, feasibility, and proposal outline")
    session.commit()
    session.refresh(project)
    return project


def _validate_probability(name: str, value: float) -> None:
    if not 0 < value < 1:
        raise ValueError(f"{name} must be between 0 and 1.")


def calculate_basic_sample_size(method: str, alpha: float, power: float, group_one_value: float, group_two_value: float, standard_deviation: float | None = None) -> dict[str, Any]:
    """Use the scope and formulas of upstream sample-size-basic for two groups."""
    _validate_probability("alpha", alpha)
    _validate_probability("power", power)
    if method not in {"proportions", "means"}:
        raise ValueError("method must be 'proportions' or 'means'.")
    if group_one_value == group_two_value:
        raise ValueError("The two expected group values must differ.")
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1 - alpha / 2)
    z_beta = normal.inv_cdf(power)
    if method == "proportions":
        _validate_probability("group_one_value", group_one_value)
        _validate_probability("group_two_value", group_two_value)
        p_avg = (group_one_value + group_two_value) / 2
        difference = abs(group_one_value - group_two_value)
        per_group = math.ceil(((z_alpha * math.sqrt(2 * p_avg * (1 - p_avg)) + z_beta * math.sqrt(group_one_value * (1 - group_one_value) + group_two_value * (1 - group_two_value))) ** 2) / difference**2)
        assumptions = "Two-sided comparison of two independent proportions with equal allocation."
    else:
        if standard_deviation is None or standard_deviation <= 0:
            raise ValueError("standard_deviation must be greater than 0 for means.")
        difference = abs(group_one_value - group_two_value)
        per_group = math.ceil(2 * (z_alpha + z_beta) ** 2 * standard_deviation**2 / difference**2)
        assumptions = "Two-sided comparison of two independent means with equal allocation."
    return {"method": method, "alpha": alpha, "power": power, "group_one_value": group_one_value, "group_two_value": group_two_value, "standard_deviation": standard_deviation, "per_group": per_group, "total": per_group * 2, "assumptions": assumptions, "source_skill": "sample-size-basic", "human_review_required": True}


def calculate_study_sample_size_record(session: Session, project_id: int, method: str, alpha: float, power: float, group_one_value: float, group_two_value: float, standard_deviation: float | None = None, actor: str = "system") -> dict[str, Any]:
    project = _get_project_or_raise(session, project_id)
    _ensure_draft_mutable(project)
    if project.status == StudyDesignStatus.DRAFT:
        raise ValueError("Generate the study-design blueprint before calculating sample size.")
    result = calculate_basic_sample_size(method, alpha, power, group_one_value, group_two_value, standard_deviation)
    inputs = {"method": method, "alpha": alpha, "power": power, "group_one_value": group_one_value, "group_two_value": group_two_value, "standard_deviation": standard_deviation}
    serialized_inputs = json.dumps(inputs, ensure_ascii=False, sort_keys=True)
    if project.sample_size_inputs_json == serialized_inputs and project.sample_size_result_json:
        return json.loads(project.sample_size_result_json)
    project.sample_size_method = method
    project.sample_size_inputs_json = serialized_inputs
    project.sample_size_result_json = json.dumps(result, ensure_ascii=False)
    project.status = StudyDesignStatus.SAMPLE_SIZE_READY
    project.updated_at = datetime.now(UTC)
    session.add(project)
    _append_audit_log(session, project_id, "study_design.sample_size_calculated", actor, f"Calculated {result['total']} total participants using {method}")
    session.commit()
    return result


def save_rct_randomization_plan_record(session: Session, project_id: int, total_subjects: int, groups: list[str], block_size: int, actor: str = "system") -> StudyDesignRandomizationPlan:
    project = _get_project_or_raise(session, project_id)
    _ensure_draft_mutable(project)
    if not _is_rct(project):
        raise ValueError("Randomization is only available when study_design explicitly indicates an RCT.")
    if total_subjects < 2:
        raise ValueError("total_subjects must be at least 2.")
    normalized_groups = [item.strip() for item in groups if item.strip()]
    if len(normalized_groups) < 2 or len(set(normalized_groups)) != len(normalized_groups):
        raise ValueError("groups must contain at least two unique non-empty labels.")
    if block_size <= 0 or block_size % len(normalized_groups) != 0:
        raise ValueError("block_size must be divisible by the number of groups.")
    groups_json = json.dumps(normalized_groups, ensure_ascii=False)
    plan = _get_plan(session, project_id)
    if plan and (plan.total_subjects, plan.groups_json, plan.block_size) == (total_subjects, groups_json, block_size):
        return plan
    if plan is None:
        plan = StudyDesignRandomizationPlan(study_design_project_id=project_id, total_subjects=total_subjects, groups_json=groups_json, block_size=block_size)
    else:
        plan.total_subjects, plan.groups_json, plan.block_size, plan.updated_at = total_subjects, groups_json, block_size, datetime.now(UTC)
    session.add(plan)
    _append_audit_log(session, project_id, "study_design.randomization_plan_saved", actor, f"Saved concealed block-randomization plan for {total_subjects} subjects across {len(normalized_groups)} groups")
    session.commit()
    session.refresh(plan)
    return plan


def request_study_design_approval_record(session: Session, project_id: int, actor: str = "system") -> StudyDesignApproval:
    project = _get_project_or_raise(session, project_id)
    if not project.inclusion_criteria or not project.exclusion_criteria or not project.proposal_outline:
        raise ValueError("Save the draft study-design content before requesting internal confirmation.")
    if not project.sample_size_result_json:
        raise ValueError("Calculate and review sample size before requesting internal confirmation.")
    plan = _get_plan(session, project_id)
    if _is_rct(project) and plan is None:
        raise ValueError("Save an RCT randomization plan before requesting internal confirmation.")
    digest = _canonical_digest(_approval_scope(project, plan))
    approval = _get_approval(session, project_id)
    if approval and approval.status == StudyDesignApprovalStatus.APPROVED and approval.scope_digest == digest:
        return approval
    if approval is None:
        approval = StudyDesignApproval(study_design_project_id=project_id, scope_digest=digest)
    else:
        approval.scope_digest, approval.status, approval.requested_at, approval.approved_by, approval.approved_at = digest, StudyDesignApprovalStatus.PENDING, datetime.now(UTC), None, None
    project.status = StudyDesignStatus.APPROVAL_PENDING
    project.updated_at = datetime.now(UTC)
    session.add(project)
    session.add(approval)
    _append_audit_log(session, project_id, "study_design.internal_confirmation_requested", actor, "Requested internal human confirmation for the locked study-design scope")
    session.commit()
    session.refresh(approval)
    return approval


def approve_study_design_record(session: Session, project_id: int, approved_by: str) -> StudyDesignApproval:
    project = _get_project_or_raise(session, project_id)
    approval = _get_approval(session, project_id)
    if not approval or approval.status != StudyDesignApprovalStatus.PENDING:
        raise ValueError("No pending internal confirmation request exists for this project.")
    if not approved_by.strip():
        raise ValueError("approved_by must not be empty.")
    if approval.scope_digest != _canonical_digest(_approval_scope(project, _get_plan(session, project_id))):
        raise ValueError("Approval scope changed. Request approval again.")
    approval.status, approval.approved_by, approval.approved_at = StudyDesignApprovalStatus.APPROVED, approved_by.strip(), datetime.now(UTC)
    project.status, project.human_confirmed_by, project.human_confirmed_at, project.updated_at = StudyDesignStatus.HUMAN_APPROVED, approved_by.strip(), approval.approved_at, datetime.now(UTC)
    session.add(approval)
    session.add(project)
    _append_audit_log(session, project_id, "study_design.internal_confirmation_approved", "opencode", f"Study-design scope confirmed by {approved_by.strip()}")
    session.commit()
    session.refresh(approval)
    return approval


def approval_snapshot(session: Session, project_id: int) -> dict[str, Any]:
    project = _get_project_or_raise(session, project_id)
    approval = _get_approval(session, project_id)
    return {"project_id": project_id, "project_status": project.status, "approval": None if approval is None else {"status": approval.status, "requested_at": approval.requested_at, "approved_by": approval.approved_by, "approved_at": approval.approved_at, "scope_digest": approval.scope_digest}}


def _schedule_storage_path(project_id: int) -> Path:
    directory = Path(settings.randomization_storage_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    return directory / f"study-design-{project_id}-randomization.json"


def generate_rct_randomization_record(session: Session, project_id: int, actor: str = "system") -> dict[str, Any]:
    project = _get_project_or_raise(session, project_id)
    _require_approved_scope(session, project)
    plan = _get_plan(session, project_id)
    if plan is None:
        raise ValueError("No approved randomization plan exists for this project.")
    existing = session.exec(select(StudyDesignRandomizationSchedule).where(StudyDesignRandomizationSchedule.study_design_project_id == project_id)).first()
    if existing:
        return {"schedule_id": existing.id, "total_subjects": existing.total_subjects, "groups": json.loads(plan.groups_json), "block_size": plan.block_size, "checksum": existing.checksum, "allocation_visible_to_agent": False}
    groups = json.loads(plan.groups_json)
    generator = random.SystemRandom()
    schedule: list[dict[str, Any]] = []
    subject_id = 1
    while subject_id <= plan.total_subjects:
        block = [group for group in groups for _ in range(plan.block_size // len(groups))]
        generator.shuffle(block)
        for assignment in block:
            if subject_id > plan.total_subjects:
                break
            schedule.append({"subject_sequence": subject_id, "allocation": assignment, "block": (subject_id - 1) // plan.block_size + 1})
            subject_id += 1
    encoded = json.dumps(schedule, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    path = _schedule_storage_path(project_id)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as file_handle:
        file_handle.write(encoded)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    record = StudyDesignRandomizationSchedule(study_design_project_id=project_id, storage_path=str(path), checksum=hashlib.sha256(encoded).hexdigest(), total_subjects=plan.total_subjects)
    project.status, project.updated_at = StudyDesignStatus.RANDOMIZATION_READY, datetime.now(UTC)
    session.add(project)
    session.add(record)
    _append_audit_log(session, project_id, "study_design.randomization_generated", actor, "Generated concealed randomization schedule in restricted local storage")
    session.commit()
    session.refresh(record)
    return {"schedule_id": record.id, "total_subjects": record.total_subjects, "groups": groups, "block_size": plan.block_size, "checksum": record.checksum, "allocation_visible_to_agent": False}


def read_randomization_schedule_record(session: Session, project_id: int) -> list[dict[str, Any]]:
    project = _get_project_or_raise(session, project_id)
    _require_approved_scope(session, project)
    schedule = session.exec(select(StudyDesignRandomizationSchedule).where(StudyDesignRandomizationSchedule.study_design_project_id == project_id)).first()
    if not schedule:
        raise ValueError("No generated randomization schedule exists for this project.")
    try:
        encoded = Path(schedule.storage_path).read_bytes()
    except OSError as error:
        raise ValueError("Randomization schedule storage is unavailable.") from error
    if not hmac.compare_digest(hashlib.sha256(encoded).hexdigest(), schedule.checksum):
        raise ValueError("Randomization schedule integrity check failed.")
    return json.loads(encoded)


def verify_approval_key(provided_key: str | None) -> None:
    configured_key = settings.study_design_approval_key
    if not configured_key or not provided_key or not hmac.compare_digest(configured_key, provided_key):
        raise PermissionError("A valid X-Study-Approval-Key is required.")


def start_study_design_workflow_run(session: Session, project_id: int, actor: str = "mcp") -> StudyDesignWorkflowRun:
    _get_project_or_raise(session, project_id)
    run = StudyDesignWorkflowRun(run_id=uuid4().hex, study_design_project_id=project_id, actor=actor)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def record_study_design_workflow_event(session: Session, run_id: str, project_id: int, operation: str, inputs: Any, output: Any) -> None:
    run = session.exec(select(StudyDesignWorkflowRun).where(StudyDesignWorkflowRun.run_id == run_id)).first()
    if not run or run.study_design_project_id != project_id:
        raise ValueError("workflow_run_id does not belong to this study-design project.")
    session.add(StudyDesignWorkflowEvent(workflow_run_id=run_id, study_design_project_id=project_id, operation=operation, input_digest=_canonical_digest(inputs), output_digest=_canonical_digest(output)))
    session.commit()


def get_study_design_workflow_events(session: Session, project_id: int, run_id: str) -> list[StudyDesignWorkflowEvent]:
    run = session.exec(select(StudyDesignWorkflowRun).where(StudyDesignWorkflowRun.run_id == run_id)).first()
    if not run or run.study_design_project_id != project_id:
        raise ValueError("workflow_run_id does not belong to this study-design project.")
    return session.exec(select(StudyDesignWorkflowEvent).where(StudyDesignWorkflowEvent.workflow_run_id == run_id).order_by(StudyDesignWorkflowEvent.id)).all()


def build_study_design_bundle_data(session: Session, project_id: int, workflow_run_id: str | None = None) -> dict[str, Any] | None:
    project = session.get(StudyDesignProject, project_id)
    if not project:
        return None
    approval = _require_approved_scope(session, project)
    plan = _get_plan(session, project_id)
    schedule = session.exec(select(StudyDesignRandomizationSchedule).where(StudyDesignRandomizationSchedule.study_design_project_id == project_id)).first()
    if _is_rct(project) and not schedule:
        raise ValueError("Generate the concealed RCT randomization schedule after approval before exporting.")
    project.status, project.updated_at = StudyDesignStatus.EXPORTED, datetime.now(UTC)
    session.add(project)
    _append_audit_log(session, project_id, "study_design.exported", "system", "Exported externally approved study-design bundle without allocation sequence")
    session.commit()
    session.refresh(project)
    audit_logs = [{"id": item.id, "action": item.action, "actor": item.actor, "summary": item.summary} for item in session.exec(select(StudyDesignAuditLog).where(StudyDesignAuditLog.study_design_project_id == project_id).order_by(StudyDesignAuditLog.id)).all()]
    receipt_run_id = workflow_run_id or session.exec(
        select(StudyDesignWorkflowRun.run_id)
        .where(StudyDesignWorkflowRun.study_design_project_id == project_id)
        .order_by(StudyDesignWorkflowRun.id.desc())
    ).first()
    skill_receipts = [
        {"receipt_id": item.receipt_id, "skill_name": item.skill_name, "executed_at": item.executed_at, "opencode_session_id": item.opencode_session_id}
        for item in ([] if receipt_run_id is None else session.exec(
            select(StudyDesignSkillExecutionReceipt)
            .where(StudyDesignSkillExecutionReceipt.workflow_run_id == receipt_run_id)
            .order_by(StudyDesignSkillExecutionReceipt.executed_at)
        ).all())
    ]
    return {"project": project, "sample_size": json.loads(project.sample_size_result_json or "{}"), "approval": approval, "randomization_plan": None if plan is None else {"total_subjects": plan.total_subjects, "groups": json.loads(plan.groups_json), "block_size": plan.block_size}, "randomization_schedule_metadata": None if schedule is None else {"schedule_id": schedule.id, "total_subjects": schedule.total_subjects, "checksum": schedule.checksum, "allocation_visible_to_agent": False}, "skill_receipts": skill_receipts, "audit_logs": audit_logs}


def render_study_design_bundle_markdown(bundle: dict[str, Any]) -> str:
    project: StudyDesignProject = bundle["project"]
    sample_size = bundle["sample_size"]
    approval: StudyDesignApproval = bundle["approval"]
    plan = bundle["randomization_plan"]
    schedule = bundle["randomization_schedule_metadata"]
    lines = [f"# {project.title}", "", "## Research Question", project.research_question, "", "## Study Design", f"- Study type: {project.study_type}", f"- Study design: {project.study_design}", f"- Reporting standard: {project.protocol_standard or 'N/A'}", f"- Department: {project.department or 'N/A'}", f"- Resource summary: {project.resource_summary or 'N/A'}", "", "## PICO", f"- Population: {project.population}", f"- Intervention: {project.intervention or 'N/A'}", f"- Comparator: {project.comparator or 'N/A'}", f"- Outcome: {project.outcome}", "", "## Eligibility Draft", f"- Inclusion: {project.inclusion_criteria}", f"- Exclusion: {project.exclusion_criteria}", "", "## Outcomes And Feasibility", f"- Primary outcome: {project.primary_outcome or 'N/A'}", f"- Secondary outcomes: {project.secondary_outcomes or 'N/A'}", f"- Innovation notes: {project.innovation_notes or 'N/A'}", f"- Feasibility notes: {project.feasibility_notes or 'N/A'}", "", "## Sample Size", f"- Method: {sample_size.get('method', 'N/A')}", f"- Per group: {sample_size.get('per_group', 'N/A')}", f"- Total: {sample_size.get('total', 'N/A')}", f"- Assumptions: {sample_size.get('assumptions', 'N/A')}", "", "## Proposal Outline", project.proposal_outline or 'N/A', "", "## External Approval", f"- Status: {approval.status}", f"- Approved by: {approval.approved_by or 'N/A'}", f"- Approved at: {approval.approved_at.isoformat() if approval.approved_at else 'N/A'}", "", "## Randomization Control"]
    if plan:
        lines.extend([f"- Plan: {plan['total_subjects']} participants, groups {', '.join(plan['groups'])}, block size {plan['block_size']}", f"- Schedule generated: {'yes' if schedule else 'no'}", "- Allocation sequence is withheld from this export and is available only through the protected operator endpoint."])
    else:
        lines.append("Not applicable.")
    lines.extend(["", "## Verified Skill Execution Receipts"])
    if bundle["skill_receipts"]:
        for receipt in bundle["skill_receipts"]:
            lines.append(f"- {receipt['skill_name']} | {receipt['executed_at'].isoformat()} | receipt {receipt['receipt_id']}")
    else:
        lines.append("No signed Skill receipts were captured for this workflow run.")
    lines.extend(["", "## Audit Log", ""])
    for log in bundle["audit_logs"]:
        lines.append(f"- {log['action']} | {log['actor']} | {log['summary']}")
    lines.append("")
    return "\n".join(lines)
