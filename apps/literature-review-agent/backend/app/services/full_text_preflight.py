"""Persist client-side full-text availability checks before scientific screening."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models import AuditLog, Citation, FullTextAvailability, FullTextDocument
from app.schemas import FullTextPreflightCreate
from app.services.phi_guard import assert_no_phi, redact_public_contact_emails


READY = "full_text_ready"
MIN_OPEN_ACCESS_XML_BYTES = 10_000


def _citation_ids_or_raise(session: Session, project_id: int, items: list[FullTextPreflightCreate]) -> None:
    requested = {item.citation_id for item in items}
    citations = session.exec(
        select(Citation).where(Citation.project_id == project_id, Citation.id.in_(requested))
    ).all()
    known = {item.id for item in citations}
    unknown = sorted(requested - known)
    if unknown:
        raise ValueError(f"Full-text preflight citations must belong to this project: {unknown}.")


def save_full_text_preflight_record(
    session: Session,
    project_id: int,
    items: list[FullTextPreflightCreate],
    actor: str = "mcp_client",
) -> dict[str, object]:
    """Store availability independently of include/exclude decisions.

    Ready public source text is cached now so the evidence agent consumes the
    exact client-verified document rather than issuing another network request.
    """
    if not items:
        raise ValueError("Full-text preflight requires at least one citation result.")
    if len({item.citation_id for item in items}) != len(items):
        raise ValueError("Submit at most one full-text preflight result per citation.")
    _citation_ids_or_raise(session, project_id, items)

    records: list[FullTextAvailability] = []
    ready_count = 0
    for item in items:
        document_id: int | None = None
        if item.status == READY:
            if not item.source_url or not item.source_url.startswith("https://") or not item.content_text:
                raise ValueError("full_text_ready requires an HTTPS source_url and verified content_text.")
            content = redact_public_contact_emails(item.content_text.strip())
            assert_no_phi({"content_text": content, "source_url": item.source_url})
            if len(content.encode("utf-8")) < MIN_OPEN_ACCESS_XML_BYTES or "<article" not in content[:2_000].lower():
                raise ValueError("full_text_ready requires verified Europe PMC XML article content.")
            if len(content) > 2_000_000:
                raise ValueError("Full-text content exceeds the 2,000,000 character safety limit.")
            checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
            document = session.exec(
                select(FullTextDocument).where(
                    FullTextDocument.project_id == project_id,
                    FullTextDocument.citation_id == item.citation_id,
                    FullTextDocument.source_kind == "open_access_html",
                )
            ).first()
            if document is None:
                document = FullTextDocument(
                    project_id=project_id,
                    citation_id=item.citation_id,
                    source_kind="open_access_html",
                    source_url=item.source_url,
                    content_text=content,
                    content_sha256=checksum,
                )
            else:
                document.source_url = item.source_url
                document.content_text = content
                document.content_sha256 = checksum
                document.updated_at = datetime.now(UTC)
            session.add(document)
            session.flush()
            document_id = document.id
            ready_count += 1

        record = session.exec(
            select(FullTextAvailability).where(
                FullTextAvailability.project_id == project_id,
                FullTextAvailability.citation_id == item.citation_id,
            )
        ).first()
        if record is None:
            record = FullTextAvailability(project_id=project_id, citation_id=item.citation_id, status=item.status)
        record.status = item.status
        record.pmcid = item.pmcid
        record.source_url = item.source_url
        record.local_cache_path = item.local_cache_path
        record.details = item.details
        record.full_text_document_id = document_id
        record.checked_at = datetime.now(UTC)
        session.add(record)
        records.append(record)

    session.add(AuditLog(
        project_id=project_id,
        action="full_text.preflight_completed",
        actor=actor,
        summary=f"Preflighted {len(items)} citations; {ready_count} verified open full texts cached",
    ))
    session.commit()
    for record in records:
        session.refresh(record)
    return {
        "project_id": project_id,
        "checked_count": len(records),
        "full_text_ready_count": ready_count,
        "records": [
            {
                "citation_id": record.citation_id,
                "status": record.status,
                "pmcid": record.pmcid,
                "source_url": record.source_url,
                "local_cache_path": record.local_cache_path,
                "full_text_document_id": record.full_text_document_id,
                "details": record.details,
            }
            for record in records
        ],
    }


def get_full_text_preflight_records(session: Session, project_id: int) -> dict[str, object]:
    citations = session.exec(
        select(Citation).where(Citation.project_id == project_id, Citation.is_deduplicated.is_(False))
    ).all()
    availability = {
        item.citation_id: item
        for item in session.exec(
            select(FullTextAvailability).where(FullTextAvailability.project_id == project_id)
        ).all()
    }
    rows = []
    for citation in citations:
        item = availability.get(citation.id)
        rows.append({
            "citation_id": citation.id,
            "pmid": citation.external_id,
            "doi": citation.doi,
            "title": citation.title,
            "status": item.status if item else "not_checked",
            "pmcid": item.pmcid if item else None,
            "source_url": item.source_url if item else None,
            "local_cache_path": item.local_cache_path if item else None,
            "full_text_document_id": item.full_text_document_id if item else None,
            "details": item.details if item else None,
        })
    return {
        "project_id": project_id,
        "citation_count": len(rows),
        "full_text_ready_count": sum(row["status"] == READY for row in rows),
        "records": rows,
    }
