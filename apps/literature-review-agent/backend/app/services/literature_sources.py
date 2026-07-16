from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree

import httpx

from app.config import settings

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


async def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    headers = {"User-Agent": PUBMED_USER_AGENT}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


async def _get_text(url: str, params: dict[str, Any]) -> str:
    headers = {"User-Agent": PUBMED_USER_AGENT}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.text


async def search_pubmed_records(query: str, limit: int = 5) -> list[dict[str, Any]]:
    esearch_payload = await _get_json(
        f"{settings.pubmed_base_url}/esearch.fcgi",
        {
            "db": "pubmed",
            "retmode": "json",
            "retmax": max(1, min(limit, 20)),
            "term": query,
        },
    )
    ids = esearch_payload.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    xml_text = await _get_text(
        f"{settings.pubmed_base_url}/efetch.fcgi",
        {
            "db": "pubmed",
            "retmode": "xml",
            "id": ",".join(ids),
        },
    )
    root = ElementTree.fromstring(xml_text)
    articles = [normalize_pubmed_article(article) for article in root.findall(".//PubmedArticle")]
    article_by_id = {item.get("external_id"): item for item in articles}
    return [article_by_id[item_id] for item_id in ids if item_id in article_by_id]


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


async def search_europepmc_records(query: str, limit: int = 5) -> list[dict[str, Any]]:
    payload = await _get_json(
        f"{settings.europe_pmc_base_url}/search",
        {
            "query": query,
            "format": "json",
            "pageSize": max(1, min(limit, 20)),
            "resultType": "core",
        },
    )
    results = payload.get("resultList", {}).get("result", [])
    return [normalize_europepmc_record(item) for item in results]


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
