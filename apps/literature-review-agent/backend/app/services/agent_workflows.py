from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlmodel import Session, select

from app.config import settings
from app.models import (
    AgentSkillExecutionReceipt,
    AgentWorkflowEvent,
    AgentWorkflowRun,
    Project,
    StudyDesignProject,
)


logger = logging.getLogger(__name__)


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _receipt_signature(receipt_id: str, session_id: str, skill_name: str, executed_at_ms: int) -> str:
    if not settings.skill_receipt_key:
        raise ValueError("Skill receipt verification is not configured.")
    payload = f"{receipt_id}|{session_id}|{skill_name}|{executed_at_ms}".encode("utf-8")
    return hmac.new(settings.skill_receipt_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _validate_subject(session: Session, subject_type: str, subject_id: int) -> None:
    if subject_type == "review" and session.get(Project, subject_id):
        return
    if subject_type == "study_design" and session.get(StudyDesignProject, subject_id):
        return
    raise ValueError(f"{subject_type} subject {subject_id} was not found.")


def start_agent_workflow_run(
    session: Session,
    workflow_type: str,
    subject_type: str,
    subject_id: int,
    actor: str = "mcp",
) -> AgentWorkflowRun:
    if workflow_type not in {"evidence_extraction", "research_writing"}:
        raise ValueError("Unsupported agent workflow type.")
    _validate_subject(session, subject_type, subject_id)
    run = AgentWorkflowRun(
        run_id=uuid4().hex,
        workflow_type=workflow_type,
        subject_type=subject_type,
        subject_id=subject_id,
        actor=actor,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_agent_workflow_run(
    session: Session,
    workflow_run_id: str,
    workflow_type: str,
    subject_type: str,
    subject_id: int,
) -> AgentWorkflowRun:
    run = session.exec(
        select(AgentWorkflowRun).where(AgentWorkflowRun.run_id == workflow_run_id)
    ).first()
    if not run or (
        run.workflow_type != workflow_type
        or run.subject_type != subject_type
        or run.subject_id != subject_id
    ):
        raise ValueError("workflow_run_id does not belong to this agent workflow subject.")
    return run


def record_agent_workflow_event(
    session: Session,
    workflow_run_id: str,
    workflow_type: str,
    subject_type: str,
    subject_id: int,
    operation: str,
    inputs: Any,
    output: Any,
) -> None:
    get_agent_workflow_run(session, workflow_run_id, workflow_type, subject_type, subject_id)
    session.add(
        AgentWorkflowEvent(
            workflow_run_id=workflow_run_id,
            workflow_type=workflow_type,
            subject_type=subject_type,
            subject_id=subject_id,
            operation=operation,
            input_digest=_canonical_digest(inputs),
            output_digest=_canonical_digest(output),
        )
    )
    session.commit()


def _import_receipt_payload(
    session: Session,
    payload: dict[str, Any],
    workflow_run_id: str,
    workflow_type: str,
    subject_type: str,
    subject_id: int,
) -> int:
    if payload.get("workflow_run_id") != workflow_run_id:
        raise ValueError("Skill receipt journal does not match this workflow run.")
    if payload.get("workflow_type") != workflow_type or payload.get("subject_type") != subject_type or payload.get("subject_id") != subject_id:
        raise ValueError("Skill receipt journal does not match this workflow subject.")
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
        if session.exec(
            select(AgentSkillExecutionReceipt).where(AgentSkillExecutionReceipt.receipt_id == receipt_id)
        ).first():
            continue
        session.add(
            AgentSkillExecutionReceipt(
                receipt_id=receipt_id,
                workflow_run_id=workflow_run_id,
                workflow_type=workflow_type,
                subject_type=subject_type,
                subject_id=subject_id,
                opencode_session_id=session_id,
                skill_name=skill_name,
                executed_at=datetime.fromtimestamp(executed_at_ms / 1000, UTC),
                signature=supplied_signature,
            )
        )
        imported += 1
    if imported:
        session.commit()
    return imported


def import_agent_skill_execution_receipts(
    session: Session,
    workflow_run_id: str,
    workflow_type: str,
    subject_type: str,
    subject_id: int,
) -> int:
    if not settings.skill_receipt_key:
        return 0
    receipt_path = Path(settings.skill_receipt_dir) / f"{workflow_run_id}.json"
    if not receipt_path.is_file():
        return 0
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Skill receipt journal is unreadable.") from error
    return _import_receipt_payload(session, payload, workflow_run_id, workflow_type, subject_type, subject_id)


def import_agent_skill_execution_receipts_from_session(
    session: Session,
    workflow_run_id: str,
    workflow_type: str,
    subject_type: str,
    subject_id: int,
    opencode_session_id: str | None,
) -> int:
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
        "version": 1,
        "workflow_run_id": workflow_run_id,
        "workflow_type": workflow_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "opencode_session_id": opencode_session_id,
        "receipts": session_payload.get("receipts", []),
    }
    return _import_receipt_payload(session, payload, workflow_run_id, workflow_type, subject_type, subject_id)


def ingest_agent_skill_execution_receipt_journal(
    session: Session, payload: dict[str, Any]
) -> int:
    """Verify and persist a journal posted directly by the OpenCode plugin."""
    workflow_run_id = payload.get("workflow_run_id")
    if not isinstance(workflow_run_id, str) or not workflow_run_id:
        raise ValueError("Skill receipt journal is missing its workflow_run_id.")
    run = session.exec(
        select(AgentWorkflowRun).where(AgentWorkflowRun.run_id == workflow_run_id)
    ).first()
    if not run:
        raise ValueError("Skill receipt journal references an unknown workflow run.")
    return _import_receipt_payload(
        session,
        payload,
        run.run_id,
        run.workflow_type,
        run.subject_type,
        run.subject_id,
    )


def require_agent_skill_receipts(
    session: Session,
    workflow_run_id: str,
    workflow_type: str,
    subject_type: str,
    subject_id: int,
    operation: str,
    required_skills: set[str],
) -> None:
    """Require signed OpenCode Skill calls when receipt verification is configured."""
    get_agent_workflow_run(session, workflow_run_id, workflow_type, subject_type, subject_id)
    if not settings.skill_receipt_key:
        return
    import_agent_skill_execution_receipts(session, workflow_run_id, workflow_type, subject_type, subject_id)
    captured = {
        item.skill_name
        for item in session.exec(
            select(AgentSkillExecutionReceipt).where(
                AgentSkillExecutionReceipt.workflow_run_id == workflow_run_id
            )
        ).all()
    }
    missing = sorted(required_skills - captured)
    if missing:
        message = (
            f"Verified OpenCode Skill receipts are required before {operation}: {', '.join(missing)}."
        )
        if settings.skill_receipt_enforcement == "strict":
            raise ValueError(message)
        logger.warning("%s Proceeding because skill receipt enforcement is warn.", message)


def get_agent_skill_receipts(session: Session, workflow_run_id: str) -> list[AgentSkillExecutionReceipt]:
    return session.exec(
        select(AgentSkillExecutionReceipt)
        .where(AgentSkillExecutionReceipt.workflow_run_id == workflow_run_id)
        .order_by(AgentSkillExecutionReceipt.executed_at)
    ).all()
