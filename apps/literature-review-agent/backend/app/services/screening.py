from collections import Counter

from sqlmodel import Session, select

from app.models import Citation, PrismaCount, ScreeningDecision


def deduplicate_citations(session: Session, project_id: int) -> int:
    citations = session.exec(select(Citation).where(Citation.project_id == project_id)).all()
    seen: set[str] = set()
    removed = 0
    for citation in citations:
        fingerprint = citation.doi or citation.external_id or citation.title.lower()
        if fingerprint in seen:
            citation.is_deduplicated = True
            removed += 1
        else:
            seen.add(fingerprint)
            citation.is_deduplicated = False
    session.commit()
    return removed


def rebuild_prisma_counts(session: Session, project_id: int) -> PrismaCount:
    citations = session.exec(select(Citation).where(Citation.project_id == project_id)).all()
    decisions = session.exec(
        select(ScreeningDecision).where(ScreeningDecision.project_id == project_id)
    ).all()
    counts = Counter(item.decision for item in decisions)
    record = session.exec(select(PrismaCount).where(PrismaCount.project_id == project_id)).first()
    if not record:
        record = PrismaCount(project_id=project_id)

    record.identified_count = len(citations)
    record.deduplicated_count = len([citation for citation in citations if not citation.is_deduplicated])
    record.screened_count = len(decisions)
    record.included_count = counts.get("include", 0)
    record.excluded_count = counts.get("exclude", 0)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record
