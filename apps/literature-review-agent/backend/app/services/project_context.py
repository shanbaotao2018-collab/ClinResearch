"""Read-only, cross-Agent project context for persisted research work.

The four Agents share one database but use different primary records.  This
module gives them one safe way to resume work in a new OpenCode session
without relying on conversational memory.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.models import ResearchWritingDraft, StudyDesignProject
from app.services.next_actions import get_next_actions
from app.services.research_cases import get_research_case_record
from app.services.workbench import review_detail, study_design_detail, writing_detail


_TYPE_ALIASES = {
    "study_design": "study_design",
    "study-design": "study_design",
    "review": "review",
    "literature_review": "review",
    "literature-review": "review",
    "evidence": "evidence",
    "evidence_extraction": "evidence",
    "evidence-extraction": "evidence",
    "research_writing": "research_writing",
    "research-writing": "research_writing",
    "writing": "research_writing",
    "research_case": "research_case",
    "research-case": "research_case",
}


def _normalized_type(project_type: str) -> str:
    value = _TYPE_ALIASES.get(project_type.strip().lower())
    if not value:
        raise ValueError(
            "project_type must be study_design, review, evidence, research_writing, or research_case."
        )
    return value


def _summary(next_actions: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow_status": next_actions["workflow_status"],
        "handoff_ready": any(
            action["target_agent"] != next_actions["subject_type"]
            and action["status"] == "available"
            for action in next_actions["actions"]
        ),
        "allowed_next_actions": next_actions["actions"],
    }


def get_agent_project_context_record(
    session: Session, project_type: str, project_id: int
) -> dict[str, Any]:
    """Return safe persisted context for one Agent project reference.

    ``evidence`` is intentionally addressed by its literature-review project
    ID: evidence extraction is a stage of a review, not a separate project.
    Full-text bodies and concealed randomization data are excluded.
    """
    normalized_type = _normalized_type(project_type)

    if normalized_type == "study_design":
        detail = study_design_detail(session, project_id)
        if detail is None:
            raise ValueError(f"Study-design project {project_id} not found.")
        project = detail["project"]
        actions = get_next_actions(session, "study_design", project_id)
        return {
            "reference": f"study_design:{project_id}",
            "project_type": normalized_type,
            "project_id": project_id,
            "title": project["title"],
            "status": project["status"],
            "is_human_confirmed": project.get("human_confirmed_at") is not None,
            "source_refs": [],
            "context": detail,
            **_summary(actions),
        }

    if normalized_type in {"review", "evidence"}:
        detail = review_detail(session, project_id)
        if detail is None:
            raise ValueError(f"Literature-review project {project_id} not found.")
        project = detail["project"]
        actions = get_next_actions(session, normalized_type, project_id)
        evidence = detail["evidence"]
        full_text_ids = {
            item["citation_id"] for item in evidence["full_text_documents"]
        }
        detail_ids = {
            item["citation_id"] for item in evidence["full_text_details"]
        }
        bias_ids = {
            item["citation_id"] for item in evidence["bias_assessments"]
        }
        fully_evaluated_ids = sorted(full_text_ids & detail_ids & bias_ids)
        return {
            "reference": f"{normalized_type}:{project_id}",
            "project_type": normalized_type,
            "project_id": project_id,
            "title": project["title"],
            "status": project["status"],
            "is_human_confirmed": project["status"] in {"screening_completed", "prisma_generated", "exported"},
            "source_refs": [{"project_type": "review", "project_id": project_id}],
            "context": detail,
            "evidence_resume_summary": {
                "basic_extraction_count": len(evidence["extractions"]),
                "citation_safety_check_count": len(evidence["safety_checks"]),
                "full_text_cached_count": len(full_text_ids),
                "full_text_detail_count": len(detail_ids),
                "bias_assessment_count": len(bias_ids),
                "fully_evaluated_full_text_citation_ids": fully_evaluated_ids,
                "resume_rule": (
                    "已有全文评价记录应直接复用；仅当已缓存全文缺少详细抽取或偏倚评价时，"
                    "才请求进入全文系统评价阶段。"
                ),
            },
            **_summary(actions),
        }

    if normalized_type == "research_writing":
        detail = writing_detail(session, project_id)
        if detail is None:
            raise ValueError(f"Research-writing draft {project_id} not found.")
        draft = session.get(ResearchWritingDraft, project_id)
        actions = get_next_actions(session, "research_writing", project_id)
        return {
            "reference": f"research_writing:{project_id}",
            "project_type": normalized_type,
            "project_id": project_id,
            "title": detail["title"],
            "status": detail["status"],
            "is_human_confirmed": detail.get("approval", {}).get("status") == "approved" if detail.get("approval") else False,
            "source_refs": [{"project_type": draft.source_type, "project_id": draft.source_id}],
            "context": detail,
            **_summary(actions),
        }

    case = get_research_case_record(session, project_id)
    source_refs = []
    if case["study_design_project"]:
        source_refs.append({"project_type": "study_design", "project_id": case["study_design_project"]["id"]})
    if case["review_project"]:
        source_refs.append({"project_type": "review", "project_id": case["review_project"]["id"]})
    return {
        "reference": f"research_case:{project_id}",
        "project_type": normalized_type,
        "project_id": project_id,
        "title": case["title"],
        "status": "linked" if source_refs else "empty",
        "is_human_confirmed": False,
        "source_refs": source_refs,
        "context": case,
        "workflow_status": "linked" if source_refs else "empty",
        "handoff_ready": len(source_refs) == 2,
        "allowed_next_actions": [],
    }
