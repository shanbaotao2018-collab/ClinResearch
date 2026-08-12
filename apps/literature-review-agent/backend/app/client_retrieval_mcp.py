"""Desktop-local MCP connector for public biomedical literature retrieval.

It deliberately contains no database or project mutation tools. The connector
runs on the researcher's computer and sends only normalized citation results to
the central ClinResearch backend through its separate MCP server.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from app.config import settings

# This module runs in the desktop-local MCP process. It must be able to reach
# public databases even when the central backend is deliberately client_online.
settings.literature_access_mode = "online"
from app.services.literature_sources import (
    check_pubmed_retraction_status,
    fetch_europepmc_open_access_full_text,
    fetch_paper_metadata_record,
    search_europepmc_records_page,
    search_europepmc_records,
    search_pubmed_records_page,
    search_pubmed_records,
)


mcp = FastMCP("literature_client", instructions=(
    "This local connector retrieves public PubMed and Europe PMC metadata from "
    "the desktop network. It never stores project data and never accepts patient data."
))
_BACKEND_URL = os.getenv("LRA_BACKEND_URL", "http://127.0.0.1:8010").rstrip("/")
_FORMAL_RETRIEVAL_MAX_RECORDS = 2_000
_FORMAL_RETRIEVAL_PAGE_SIZE = 100


def _validate_query(query: str) -> str:
    normalized = query.strip()
    if not normalized:
        raise ValueError("query must not be empty.")
    if len(normalized) > 4_000:
        raise ValueError("query exceeds the 4,000 character local connector limit.")
    return normalized


def _validate_pmids(pmids: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(item.strip() for item in pmids if item and item.strip()))
    if not normalized:
        raise ValueError("at least one PMID is required.")
    if len(normalized) > 50:
        raise ValueError("the desktop-local connector accepts at most 50 PMIDs per request.")
    if any(not item.isdigit() for item in normalized):
        raise ValueError("every PMID must be numeric.")
    return normalized


def _validate_formal_retrieval_limit(max_records: int) -> int:
    if not isinstance(max_records, int) or max_records < 1:
        raise ValueError("max_records must be a positive integer.")
    if max_records > _FORMAL_RETRIEVAL_MAX_RECORDS:
        raise ValueError(f"max_records may not exceed {_FORMAL_RETRIEVAL_MAX_RECORDS} per formal retrieval run.")
    return max_records


async def _import_formal_retrieval_batch(
    project_id: int,
    source: str,
    citations: list[dict[str, Any]],
) -> int:
    """Write raw client-retrieved records directly to the project system of record."""
    if not citations:
        return 0
    try:
        async with httpx.AsyncClient(timeout=90.0, trust_env=False) as client:
            response = await client.post(
                f"{_BACKEND_URL}/projects/{project_id}/citations/import-manual",
                json={"source": source, "citations": citations},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as error:
        raise ValueError("The ClinResearch backend could not persist a formal retrieval batch.") from error
    return int(payload.get("imported_count", 0))


async def _record_formal_retrieval_run(summary: dict[str, Any]) -> None:
    """Persist completion before the Agent is allowed to advance the workflow."""
    payload = {
        key: summary[key]
        for key in (
            "source", "query", "database_total_count", "retrieved_count",
            "imported_count", "page_count", "complete", "truncated",
            "max_records", "retrieval_channel",
        )
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.post(
                f"{_BACKEND_URL}/projects/{summary['project_id']}/formal-retrieval-runs",
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPError as error:
        raise ValueError("The ClinResearch backend could not record formal retrieval completeness.") from error


async def _retrieve_and_import_formal_records(
    project_id: int,
    query: str,
    source: str,
    max_records: int,
) -> dict[str, Any]:
    """Page through one database and persist every retrieved raw record.

    The model receives only the audit summary. This keeps a formal retrieval
    complete and reproducible without placing hundreds of abstracts in context.
    """
    normalized = _validate_query(query)
    limit = _validate_formal_retrieval_limit(max_records)
    imported_count = 0
    retrieved_count = 0
    page_count = 0
    total_count: int | None = None

    if source == "pubmed":
        offset = 0
        page = await search_pubmed_records_page(
            normalized,
            page_size=min(_FORMAL_RETRIEVAL_PAGE_SIZE, limit),
            offset=offset,
        )
        total_count = page["total_count"]
        if total_count > limit:
            summary = {
                "project_id": project_id, "source": source,
                "retrieval_channel": "client_online_formal_direct_handoff",
                "query": normalized, "database_total_count": total_count,
                "retrieved_count": 0, "imported_count": 0, "page_count": 0,
                "complete": False, "truncated": True, "max_records": limit,
                "requires_refinement": True,
            }
            await _record_formal_retrieval_run(summary)
            return summary
        while retrieved_count < limit:
            records = page["records"]
            if not records:
                break
            imported_count += await _import_formal_retrieval_batch(project_id, source, records)
            retrieved_count += len(records)
            page_count += 1
            if not page["has_more"]:
                break
            offset += len(records)
            page = await search_pubmed_records_page(
                normalized,
                page_size=min(_FORMAL_RETRIEVAL_PAGE_SIZE, limit - retrieved_count),
                offset=offset,
            )
    elif source == "europe_pmc":
        cursor_mark = "*"
        page = await search_europepmc_records_page(
            normalized,
            page_size=min(_FORMAL_RETRIEVAL_PAGE_SIZE, limit),
            cursor_mark=cursor_mark,
        )
        total_count = page["total_count"]
        if total_count > limit:
            summary = {
                "project_id": project_id, "source": source,
                "retrieval_channel": "client_online_formal_direct_handoff",
                "query": normalized, "database_total_count": total_count,
                "retrieved_count": 0, "imported_count": 0, "page_count": 0,
                "complete": False, "truncated": True, "max_records": limit,
                "requires_refinement": True,
            }
            await _record_formal_retrieval_run(summary)
            return summary
        while retrieved_count < limit:
            records = page["records"]
            if not records:
                break
            imported_count += await _import_formal_retrieval_batch(project_id, source, records)
            retrieved_count += len(records)
            page_count += 1
            next_cursor_mark = page["next_cursor_mark"]
            if not page["has_more"] or not next_cursor_mark:
                break
            cursor_mark = next_cursor_mark
            page = await search_europepmc_records_page(
                normalized,
                page_size=min(_FORMAL_RETRIEVAL_PAGE_SIZE, limit - retrieved_count),
                cursor_mark=cursor_mark,
            )
    else:
        raise ValueError("source must be pubmed or europe_pmc.")

    summary = {
        "project_id": project_id,
        "source": source,
        "retrieval_channel": "client_online_formal_direct_handoff",
        "query": normalized,
        "database_total_count": total_count or 0,
        "retrieved_count": retrieved_count,
        "imported_count": imported_count,
        "page_count": page_count,
        "complete": total_count is not None and retrieved_count >= total_count,
        "truncated": total_count is not None and retrieved_count < total_count,
        "max_records": limit,
    }
    await _record_formal_retrieval_run(summary)
    return summary


@mcp.tool()
def get_client_literature_access_status() -> dict[str, object]:
    """Describe the desktop-local retrieval capability without making a network request."""
    return {
        "mode": "client_online",
        "execution_location": "desktop_local",
        "supported_sources": ["pubmed", "europe_pmc"],
        "project_storage": "none",
        "next_step": "Search public literature locally, then import normalized records using the central backend MCP.",
    }


@mcp.tool()
async def client_search_pubmed(query: str, limit: int = 5) -> dict[str, Any]:
    """Search PubMed from the desktop-local network and return normalized records."""
    normalized = _validate_query(query)
    records = await search_pubmed_records(normalized, limit=max(1, min(limit, 20)))
    return {
        "source": "pubmed",
        "retrieval_channel": "client_online",
        "query": normalized,
        "returned_count": len(records),
        "records": records,
    }


@mcp.tool()
async def client_search_europepmc(query: str, limit: int = 5) -> dict[str, Any]:
    """Search Europe PMC from the desktop-local network and return normalized records."""
    normalized = _validate_query(query)
    records = await search_europepmc_records(normalized, limit=max(1, min(limit, 20)))
    return {
        "source": "europe_pmc",
        "retrieval_channel": "client_online",
        "query": normalized,
        "returned_count": len(records),
        "records": records,
    }


@mcp.tool()
async def client_retrieve_pubmed_formal_review(
    project_id: int,
    query: str,
    max_records: int = _FORMAL_RETRIEVAL_MAX_RECORDS,
) -> dict[str, Any]:
    """Retrieve and persist every PubMed record for a formal review search.

    This is the formal-review alternative to client_search_pubmed. It pages
    results directly into the backend so PRISMA counts are based on raw records,
    not a model-selected shortlist. If `truncated` is true, refine the query or
    run a further bounded retrieval before claiming a complete search.
    """
    return await _retrieve_and_import_formal_records(project_id, query, "pubmed", max_records)


@mcp.tool()
async def client_retrieve_europepmc_formal_review(
    project_id: int,
    query: str,
    max_records: int = _FORMAL_RETRIEVAL_MAX_RECORDS,
) -> dict[str, Any]:
    """Retrieve and persist every Europe PMC record for a formal review search.

    Uses Europe PMC cursor pagination and direct backend handoff. It avoids
    placing full result pages in model context while preserving all raw records.
    """
    return await _retrieve_and_import_formal_records(project_id, query, "europe_pmc", max_records)


@mcp.tool()
async def client_fetch_paper_metadata(identifier: str, source: str = "auto") -> dict[str, Any]:
    """Fetch one public paper record from the desktop-local network."""
    normalized = _validate_query(identifier)
    record = await fetch_paper_metadata_record(normalized, source=source)
    return {
        "identifier": normalized,
        "source_hint": source,
        "retrieval_channel": "client_online",
        "found": bool(record),
        "record": record,
    }


@mcp.tool()
async def client_check_pubmed_retractions(pmids: list[str]) -> dict[str, Any]:
    """Check PubMed notice types from the desktop-local network for numeric PMIDs."""
    normalized = _validate_pmids(pmids)
    checks = []
    for pmid in normalized:
        result = await check_pubmed_retraction_status(pmid)
        checks.append(
            {
                "pmid": pmid,
                "status": result["status"],
                "check_source": "pubmed_publication_type_client",
                "details": result["details"],
            }
        )
    return {
        "retrieval_channel": "client_online",
        "checked_count": len(checks),
        "checks": checks,
    }


@mcp.tool()
async def client_fetch_europepmc_open_access_full_text(
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fetch verified Europe PMC open-access XML from the desktop-local network.

    Each item must contain the backend-local citation_id and its numeric PMID.
    The returned text is not stored here; the central backend must receive it
    through save_full_text_documents for validation and audit.
    """
    if not citations or len(citations) > 5:
        raise ValueError("provide between 1 and 5 citations per full-text request.")
    documents = []
    for item in citations:
        citation_id = item.get("citation_id")
        pmid = item.get("pmid")
        doi = item.get("doi")
        if not isinstance(citation_id, int) or citation_id < 1:
            raise ValueError("every citation requires a positive integer citation_id.")
        if not isinstance(pmid, str) or not pmid.isdigit():
            raise ValueError("every citation requires a numeric PMID string.")
        try:
            source = await fetch_europepmc_open_access_full_text(pmid)
        except Exception as error:  # Keep one transient source failure from aborting the batch.
            documents.append({
                "citation_id": citation_id,
                "pmid": pmid,
                "status": "verification_failed",
                "found": False,
                "details": f"Europe PMC full-text verification failed: {type(error).__name__}.",
            })
            continue
        if source is None:
            documents.append({
                "citation_id": citation_id,
                "pmid": pmid,
                "status": "access_unavailable",
                "found": False,
                "details": "No Europe PMC open-access XML record matched this PMID.",
            })
            continue
        if doi and source["doi"] and str(doi).casefold() != source["doi"].casefold():
            raise ValueError(f"Europe PMC DOI does not match citation {citation_id}.")
        documents.append(
            {
                "citation_id": citation_id,
                "pmid": pmid,
                "pmcid": source["pmcid"],
                "status": "full_text_ready",
                "found": True,
                "source_kind": "open_access_html",
                "source_url": source["source_url"],
                "content_text": source["content_text"],
            }
        )
    return {"retrieval_channel": "client_online", "documents": documents}


@mcp.tool()
async def client_preflight_europepmc_open_access_full_text_to_project(
    project_id: int,
    citations: list[dict[str, Any]],
    workspace_dir: str | None = None,
) -> dict[str, Any]:
    """Fetch then persist a small full-text batch without exposing XML to the Agent.

    The desktop connector retrieves Europe PMC XML and sends it directly to the
    central backend. The model receives only availability states and document
    IDs, preventing temporary-file/Shell workarounds for large XML payloads.
    """
    if not isinstance(project_id, int) or project_id < 1:
        raise ValueError("project_id must be a positive integer.")
    retrieved = await client_fetch_europepmc_open_access_full_text(citations)
    local_cache = _cache_verified_full_texts(workspace_dir, project_id, retrieved["documents"])
    try:
        async with httpx.AsyncClient(timeout=90.0, trust_env=False) as client:
            response = await client.post(
                f"{_BACKEND_URL}/projects/{project_id}/full-text-preflight",
                json={"results": retrieved["documents"]},
            )
            response.raise_for_status()
            saved = response.json()
    except httpx.HTTPError as error:
        raise ValueError("The ClinResearch backend could not save the full-text preflight batch.") from error

    return {
        "project_id": project_id,
        "retrieval_channel": "client_online_direct_handoff",
        "checked_count": saved["checked_count"],
        "full_text_ready_count": saved["full_text_ready_count"],
        "records": [
            {
                "citation_id": item["citation_id"],
                "status": item["status"],
                "pmcid": item.get("pmcid"),
                "full_text_document_id": item.get("full_text_document_id"),
                "details": item.get("details"),
                **local_cache.get(item["citation_id"], {
                    "local_cache_path": None,
                    "local_cache_status": "not_applicable",
                }),
            }
            for item in saved["records"]
        ],
    }


def _cache_verified_full_texts(
    workspace_dir: str | None,
    project_id: int,
    documents: list[dict[str, Any]],
) -> dict[int, dict[str, str | None]]:
    """Save verified public XML beside the user's local project exports."""
    root = Path(workspace_dir).expanduser() if workspace_dir else Path.cwd()
    if not root.is_absolute():
        raise ValueError("workspace_dir must be an absolute path when provided.")
    cache_dir = root / "临床科研智能体工作台导出" / "全文缓存" / f"项目{project_id}"
    results: dict[int, dict[str, str | None]] = {}
    for document in documents:
        if document.get("status") != "full_text_ready" or not document.get("content_text"):
            continue
        citation_id = int(document["citation_id"])
        filename = f"citation-{citation_id}-PMID{document['pmid']}-{document['pmcid']}.xml"
        destination = cache_dir / filename
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f"{destination.name}.tmp-{os.getpid()}")
            temporary.write_text(document["content_text"], encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(destination)
            results[citation_id] = {
                "local_cache_path": str(destination),
                "local_cache_status": "saved",
            }
        except OSError as error:
            results[citation_id] = {
                "local_cache_path": None,
                "local_cache_status": "write_failed",
                "local_cache_error": str(error),
            }
    return results


if __name__ == "__main__":
    mcp.run(transport="stdio")
