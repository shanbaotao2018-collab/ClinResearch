from collections import Counter
from typing import Any

from sqlmodel import Session, select

from app.models import Citation, PrismaCount, ScreeningDecision


def latest_screening_decisions(session: Session, project_id: int) -> dict[int, ScreeningDecision]:
    """Return one authoritative, latest screening decision for each citation."""
    decisions = session.exec(
        select(ScreeningDecision)
        .where(ScreeningDecision.project_id == project_id)
        .order_by(ScreeningDecision.id)
    ).all()
    return {item.citation_id: item for item in decisions}


def screening_rule_suggestion(
    citation: Citation,
    *,
    original_research_only: bool,
) -> dict[str, str] | None:
    """Return a high-precision, non-final screening suggestion from metadata."""
    if not original_research_only:
        return None

    title = citation.title.casefold()
    text = " ".join(filter(None, [citation.title, citation.abstract])).casefold()
    rules = (
        (
            "original_research.review_or_meta_analysis",
            ("review", "meta-analysis", "meta analysis", "umbrella review"),
            "题名或摘要表明该记录为综述/Meta分析，不属于原始研究。",
        ),
        (
            "clinical_research.non_human_model",
            ("animal model", "animal models", " rat ", " mice ", " mouse ", "murine"),
            "题名或摘要表明该记录为非人类动物模型研究，不属于临床人群研究。",
        ),
        (
            "original_research.protocol_or_design",
            ("study protocol", "trial protocol", "protocol for", "rationale and design"),
            "题名或摘要表明该记录为研究方案或设计论文，未报告原始结果。",
        ),
        (
            "original_research.editorial_or_commentary",
            ("editorial", "commentary", "letter to the editor"),
            "题名或摘要表明该记录为评论性文章，未报告原始研究结果。",
        ),
    )
    for rule_id, markers, reason in rules:
        searchable_text = title if rule_id == "original_research.review_or_meta_analysis" else text
        if any(marker in searchable_text for marker in markers):
            return {
                "decision": "exclude_candidate",
                "rule_id": rule_id,
                "reason": reason,
                "confidence": "high",
            }
    return None


def list_pending_screening_batch(
    session: Session,
    project_id: int,
    *,
    after_id: int | None = None,
    limit: int = 25,
    original_research_only: bool = False,
) -> dict[str, Any]:
    """Read only active citations that do not yet have a screening decision.

    Cursor pagination uses citation IDs rather than mutable offsets so a retry
    cannot reintroduce already screened or deduplicated records.
    """
    normalized_limit = max(1, min(limit, 50))
    citations = session.exec(
        select(Citation)
        .where(
            Citation.project_id == project_id,
            Citation.is_deduplicated.is_(False),
        )
        .order_by(Citation.id)
    ).all()
    decisions = latest_screening_decisions(session, project_id)
    pending = [item for item in citations if item.id not in decisions]
    if after_id is not None:
        pending = [item for item in pending if item.id is not None and item.id > after_id]

    batch = pending[:normalized_limit]
    records = []
    auto_exclude_count = 0
    for citation in batch:
        suggestion = screening_rule_suggestion(
            citation,
            original_research_only=original_research_only,
        )
        if suggestion:
            auto_exclude_count += 1
        records.append(
            {
                "id": citation.id,
                "external_id": citation.external_id,
                "source": citation.source,
                "title": citation.title,
                "abstract": citation.abstract,
                "authors": citation.authors,
                "publication_year": citation.publication_year,
                "doi": citation.doi,
                "rule_suggestion": suggestion,
            }
        )

    next_after_id = batch[-1].id if batch and len(pending) > len(batch) else None
    return {
        "project_id": project_id,
        "remaining_count": len(pending),
        "batch_count": len(records),
        "after_id": after_id,
        "next_after_id": next_after_id,
        "rules_applied": [
            "original_research.review_or_meta_analysis",
            "clinical_research.non_human_model",
            "original_research.protocol_or_design",
            "original_research.editorial_or_commentary",
        ] if original_research_only else [],
        "rule_exclude_candidate_count": auto_exclude_count,
        "ai_review_candidate_count": len(records) - auto_exclude_count,
        "citations": records,
    }


def deduplicate_citations(session: Session, project_id: int) -> int:
    citations = session.exec(select(Citation).where(Citation.project_id == project_id)).all()
    seen: set[str] = set()
    removed = 0
    for citation in citations:
        fingerprint = citation.doi or citation.external_id or citation.title.lower()
        if fingerprint in seen:
            was_deduplicated = citation.is_deduplicated
            citation.is_deduplicated = True
            # A retry must not rediscover and recount the same duplicate.
            if not was_deduplicated:
                removed += 1
        else:
            seen.add(fingerprint)
            citation.is_deduplicated = False
    session.commit()
    return removed


def rebuild_prisma_counts(session: Session, project_id: int) -> PrismaCount:
    citations = session.exec(select(Citation).where(Citation.project_id == project_id)).all()
    decisions = latest_screening_decisions(session, project_id)
    active_citation_ids = {item.id for item in citations if not item.is_deduplicated and item.id is not None}
    active_decisions = [item for citation_id, item in decisions.items() if citation_id in active_citation_ids]
    counts = Counter(item.decision for item in active_decisions)
    record = session.exec(select(PrismaCount).where(PrismaCount.project_id == project_id)).first()
    if not record:
        record = PrismaCount(project_id=project_id)

    record.identified_count = len(citations)
    record.deduplicated_count = len([citation for citation in citations if not citation.is_deduplicated])
    record.screened_count = len(active_decisions)
    record.included_count = counts.get("include", 0)
    record.excluded_count = counts.get("exclude", 0)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record
