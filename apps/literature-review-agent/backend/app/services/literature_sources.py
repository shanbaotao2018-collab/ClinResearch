from __future__ import annotations

import asyncio
import re
from typing import Any
from xml.etree import ElementTree

import httpx

from app.config import settings
from app.services.literature_access import (
    require_live_literature_access,
    translate_literature_request_error,
)

PUBMED_USER_AGENT = "literature-review-agent/0.1"
DOI_PATTERN = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _itertext(element: ElementTree.Element | None) -> str | None:
    if element is None:
        return None
    return _clean_text("".join(element.itertext()))


def _pubmed_year(article: ElementTree.Element) -> int | None:
    year_text = article.findtext(".//PubDate/Year")
    if year_text and year_text.isdigit():
        return int(year_text)

    medline_date = article.findtext(".//PubDate/MedlineDate")
    if medline_date:
        match = re.search(r"\b(19|20)\d{2}\b", medline_date)
        if match:
            return int(match.group(0))
    return None


def _pubmed_authors(article: ElementTree.Element) -> str | None:
    authors: list[str] = []
    for author in article.findall(".//AuthorList/Author"):
        collective_name = _clean_text(author.findtext("CollectiveName"))
        if collective_name:
            authors.append(collective_name)
            continue
        last_name = _clean_text(author.findtext("LastName"))
        initials = _clean_text(author.findtext("Initials"))
        if last_name and initials:
            authors.append(f"{last_name} {initials}")
        elif last_name:
            authors.append(last_name)
    return "; ".join(authors) if authors else None


def normalize_pubmed_article(article: ElementTree.Element) -> dict[str, Any]:
    """Normalize a PubMed XML article into the workspace citation shape."""
    title = _itertext(article.find(".//ArticleTitle"))
    abstract_parts: list[str] = []
    for abstract_text in article.findall(".//Abstract/AbstractText"):
        label = _clean_text(abstract_text.attrib.get("Label"))
        body = _itertext(abstract_text)
        if not body:
            continue
        abstract_parts.append(f"{label}: {body}" if label else body)

    doi = None
    for node in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
        if node.attrib.get("IdType") == "doi":
            doi = _clean_text(node.text)
            break

    pmid = _clean_text(article.findtext(".//MedlineCitation/PMID"))
    journal = _clean_text(article.findtext(".//Journal/Title"))

    return {
        "source": "pubmed",
        "external_id": pmid,
        "title": title or "Untitled PubMed record",
        "abstract": "\n\n".join(abstract_parts) if abstract_parts else None,
        "authors": _pubmed_authors(article),
        "publication_year": _pubmed_year(article),
        "doi": doi,
        "journal": journal,
    }


def normalize_europepmc_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Europe PMC JSON record into the workspace citation shape."""
    external_id = record.get("pmid") or record.get("id")
    pub_year = record.get("pubYear")
    publication_year = int(pub_year) if isinstance(pub_year, str) and pub_year.isdigit() else pub_year
    return {
        "source": "europe_pmc",
        "external_id": external_id,
        "title": _clean_text(record.get("title")) or "Untitled Europe PMC record",
        "abstract": _clean_text(record.get("abstractText")),
        "authors": _clean_text(record.get("authorString")),
        "publication_year": publication_year if isinstance(publication_year, int) else None,
        "doi": _clean_text(record.get("doi")),
        "journal": _clean_text(record.get("journalTitle")),
        "pmcid": _clean_text(record.get("pmcid")),
    }


async def _get_json(url: str, params: dict[str, Any], source: str) -> dict[str, Any]:
    require_live_literature_access(source)
    headers = {"User-Agent": PUBMED_USER_AGENT}
    error: httpx.HTTPError | None = None
    for attempt in range(3):
        try:
            # Desktop connectors use the user's direct public-network path,
            # not stale shell proxy variables inherited by OpenCode.
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as request_error:
            error = request_error
            if attempt < 2:
                await asyncio.sleep(0.4 * (attempt + 1))
    assert error is not None
    fallback = translate_literature_request_error(source, error)
    if fallback:
        raise fallback from error
    raise error


async def _get_text(url: str, params: dict[str, Any], source: str) -> str:
    require_live_literature_access(source)
    headers = {"User-Agent": PUBMED_USER_AGENT}
    error: httpx.HTTPError | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.text
        except httpx.HTTPError as request_error:
            error = request_error
            if attempt < 2:
                await asyncio.sleep(0.4 * (attempt + 1))
    assert error is not None
    fallback = translate_literature_request_error(source, error)
    if fallback:
        raise fallback from error
    raise error


async def search_pubmed_records_page(
    query: str,
    *,
    page_size: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Retrieve one stable PubMed result page with the source hit count."""
    normalized_page_size = max(1, min(page_size, 100))
    normalized_offset = max(0, offset)
    esearch_payload = await _get_json(
        f"{settings.pubmed_base_url}/esearch.fcgi",
        {
            "db": "pubmed",
            "retmode": "json",
            "retmax": normalized_page_size,
            "retstart": normalized_offset,
            "term": query,
        },
        "pubmed",
    )
    result = esearch_payload.get("esearchresult", {})
    ids = result.get("idlist", [])
    try:
        total_count = int(result.get("count", 0))
    except (TypeError, ValueError):
        total_count = 0
    if not ids:
        return {
            "records": [],
            "total_count": total_count,
            "offset": normalized_offset,
            "page_size": normalized_page_size,
            "has_more": False,
        }

    xml_text = await _get_text(
        f"{settings.pubmed_base_url}/efetch.fcgi",
        {
            "db": "pubmed",
            "retmode": "xml",
            "id": ",".join(ids),
        },
        "pubmed",
    )
    root = ElementTree.fromstring(xml_text)
    articles = [normalize_pubmed_article(article) for article in root.findall(".//PubmedArticle")]
    article_by_id = {item.get("external_id"): item for item in articles}
    records = [article_by_id[item_id] for item_id in ids if item_id in article_by_id]
    return {
        "records": records,
        "total_count": total_count,
        "offset": normalized_offset,
        "page_size": normalized_page_size,
        "has_more": normalized_offset + len(ids) < total_count,
    }


async def search_pubmed_records(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Retrieve the first small PubMed result page for interactive exploration."""
    page = await search_pubmed_records_page(query, page_size=max(1, min(limit, 20)))
    return page["records"]


async def fetch_pubmed_record(pmid: str) -> dict[str, Any] | None:
    records = await search_pubmed_records(f"{pmid}[PMID]", limit=1)
    return records[0] if records else None


async def check_pubmed_retraction_status(pmid: str) -> dict[str, str]:
    """Check PubMed notice publication types for one PMID.

    A negative lookup only means no matching PubMed notice was found at check
    time; it is deliberately not represented as a permanent safety guarantee.
    """
    if not pmid.isdigit():
        return {
            "status": "unavailable",
            "check_source": "pubmed_publication_type",
            "details": "A numeric PMID is required for the automated PubMed notice check.",
        }
    payload = await _get_json(
        f"{settings.pubmed_base_url}/esearch.fcgi",
        {
            "db": "pubmed",
            "retmode": "json",
            "retmax": 1,
            "term": (
                f"{pmid}[PMID] AND (\"Retracted Publication\"[Publication Type] "
                "OR \"Retraction of Publication\"[Publication Type] "
                "OR \"Expression of Concern\"[Publication Type] "
                "OR \"Published Erratum\"[Publication Type])"
            ),
        },
        "pubmed",
    )
    ids = payload.get("esearchresult", {}).get("idlist", [])
    if pmid in ids:
        return {
            "status": "flagged_needs_human_review",
            "check_source": "pubmed_publication_type",
            "details": "PubMed returned a retraction, correction, or concern publication-type flag; verify the linked notice before use.",
        }
    return {
        "status": "not_flagged_at_check_time",
        "check_source": "pubmed_publication_type",
        "details": "No matching PubMed notice publication-type flag was returned at check time; this is not a permanent safety guarantee.",
    }


async def search_europepmc_records_page(
    query: str,
    *,
    page_size: int = 20,
    cursor_mark: str = "*",
) -> dict[str, Any]:
    """Retrieve one Europe PMC cursor page without losing the total hit count."""
    normalized_page_size = max(1, min(page_size, 100))
    payload = await _get_json(
        f"{settings.europe_pmc_base_url}/search",
        {
            "query": query,
            "format": "json",
            "pageSize": normalized_page_size,
            "resultType": "core",
            "cursorMark": cursor_mark or "*",
        },
        "europe_pmc",
    )
    results = payload.get("resultList", {}).get("result", [])
    try:
        total_count = int(payload.get("hitCount", 0))
    except (TypeError, ValueError):
        total_count = 0
    next_cursor_mark = payload.get("nextCursorMark")
    return {
        "records": [normalize_europepmc_record(item) for item in results],
        "total_count": total_count,
        "cursor_mark": cursor_mark or "*",
        "next_cursor_mark": next_cursor_mark,
        "has_more": bool(results) and bool(next_cursor_mark) and next_cursor_mark != cursor_mark,
    }


async def search_europepmc_records(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Retrieve the first small Europe PMC page for interactive exploration."""
    page = await search_europepmc_records_page(query, page_size=max(1, min(limit, 20)))
    return page["records"]


async def fetch_europepmc_open_access_full_text(pmid: str) -> dict[str, Any] | None:
    """Resolve a PMID to one verified Europe PMC open-access full-text XML record."""
    if not pmid.isdigit():
        return None
    payload = await _get_json(
        f"{settings.europe_pmc_base_url}/search",
        {
            "query": f"EXT_ID:{pmid}",
            "format": "json",
            "pageSize": 1,
            "resultType": "core",
        },
        "europe_pmc",
    )
    records = payload.get("resultList", {}).get("result", [])
    if not records:
        return None
    record = records[0]
    pmcid = _clean_text(record.get("pmcid"))
    matched_pmid = _clean_text(record.get("pmid"))
    if not pmcid or matched_pmid != pmid:
        return None
    source_url = f"{settings.europe_pmc_base_url}/{pmcid}/fullTextXML"
    content_text = await _get_text(source_url, {}, "europe_pmc")
    if len(content_text.encode("utf-8")) < 10_000 or "<article" not in content_text[:2_000].lower():
        return None
    return {
        "pmid": pmid,
        "pmcid": pmcid,
        "doi": _clean_text(record.get("doi")),
        "title": _clean_text(record.get("title")),
        "source_url": source_url,
        "content_text": content_text,
    }


def _looks_like_doi(identifier: str) -> bool:
    return bool(DOI_PATTERN.fullmatch(identifier.strip()))


async def fetch_paper_metadata_record(
    identifier: str,
    source: str = "auto",
) -> dict[str, Any] | None:
    normalized_source = source.lower().strip()
    clean_identifier = identifier.strip()

    if normalized_source in {"auto", "pubmed"} and clean_identifier.isdigit():
        pubmed_record = await fetch_pubmed_record(clean_identifier)
        if pubmed_record:
            return pubmed_record
        if normalized_source == "pubmed":
            return None

    if normalized_source in {"auto", "europe_pmc"}:
        if _looks_like_doi(clean_identifier):
            europe_records = await search_europepmc_records(f'DOI:"{clean_identifier}"', limit=1)
        else:
            europe_records = await search_europepmc_records(f'EXT_ID:"{clean_identifier}"', limit=1)
        if europe_records:
            return europe_records[0]
        if normalized_source == "europe_pmc":
            return None

    if normalized_source in {"auto", "pubmed"} and _looks_like_doi(clean_identifier):
        pubmed_records = await search_pubmed_records(f'"{clean_identifier}"[DOI]', limit=1)
        if pubmed_records:
            return pubmed_records[0]

    if normalized_source == "auto":
        pubmed_title_records = await search_pubmed_records(f'"{clean_identifier}"[Title]', limit=1)
        if pubmed_title_records:
            return pubmed_title_records[0]

        europe_title_records = await search_europepmc_records(f'TITLE:"{clean_identifier}"', limit=1)
        if europe_title_records:
            return europe_title_records[0]

    return None
