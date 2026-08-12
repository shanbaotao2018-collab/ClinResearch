from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.citations import CitationIn


SUPPORTED_CITATION_FILE_FORMATS = {"json", "csv", "ris", "nbib"}


def resolve_literature_import_path(file_path: str) -> Path:
    """Resolve a user-supplied citation file path inside the configured import directory."""
    import_dir = Path(settings.literature_import_dir).expanduser().resolve()
    requested = Path(file_path).expanduser()
    resolved = requested.resolve() if requested.is_absolute() else (import_dir / requested).resolve()
    if import_dir != resolved and import_dir not in resolved.parents:
        raise ValueError(f"Citation files must be under the configured import directory: {import_dir}")
    if not resolved.is_file():
        raise ValueError(f"Citation file not found: {resolved}")
    return resolved


def infer_citation_file_format(path: Path, file_format: str | None = None) -> str:
    normalized = (file_format or path.suffix.lstrip(".")).strip().lower()
    if normalized == "txt":
        normalized = "nbib"
    if normalized not in SUPPORTED_CITATION_FILE_FORMATS:
        raise ValueError(
            "Unsupported citation file format. Supported formats: "
            f"{', '.join(sorted(SUPPORTED_CITATION_FILE_FORMATS))}."
        )
    return normalized


def parse_citation_file(file_path: str, file_format: str | None = None) -> list[CitationIn]:
    path = resolve_literature_import_path(file_path)
    return parse_citation_path(path, file_format)


def parse_citation_path(path: Path, file_format: str | None = None) -> list[CitationIn]:
    """Parse a previously authorized citation path without changing path authorization rules."""
    normalized_format = infer_citation_file_format(path, file_format)
    text = path.read_text(encoding="utf-8-sig")
    if normalized_format == "json":
        return _parse_json(text)
    if normalized_format == "csv":
        return _parse_csv(text)
    if normalized_format == "ris":
        return _parse_ris(text)
    if normalized_format == "nbib":
        return _parse_nbib(text)
    raise ValueError(f"Unsupported citation file format: {normalized_format}")


def _normalize_year(value: Any) -> int | None:
    if value is None:
        return None
    match = re.search(r"\b(19|20)\d{2}\b", str(value))
    return int(match.group(0)) if match else None


def _first_value(record: dict[str, Any], keys: list[str]) -> Any:
    lowered = {str(key).lower().strip(): value for key, value in record.items()}
    for key in keys:
        value = lowered.get(key)
        if value not in (None, ""):
            return value
    return None


def _citation_from_mapping(record: dict[str, Any]) -> CitationIn | None:
    title = _first_value(record, ["title", "ti", "t1", "article_title"])
    if not title:
        return None
    authors = _first_value(record, ["authors", "author", "au", "fa", "authorstring"])
    if isinstance(authors, list):
        authors = "; ".join(str(item).strip() for item in authors if str(item).strip())
    return CitationIn(
        title=str(title).strip(),
        external_id=_clean_optional(_first_value(record, ["external_id", "pmid", "id", "ui"])),
        abstract=_clean_optional(_first_value(record, ["abstract", "ab"])),
        authors=_clean_optional(authors),
        publication_year=_normalize_year(_first_value(record, ["publication_year", "year", "py", "dp", "y1"])),
        doi=_clean_optional(_first_value(record, ["doi", "do", "aid"])),
    )


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def _parse_json(text: str) -> list[CitationIn]:
    payload = json.loads(text)
    if isinstance(payload, dict):
        records = payload.get("citations") or payload.get("records") or payload.get("items")
    else:
        records = payload
    if not isinstance(records, list):
        raise ValueError("JSON citation file must contain a list or an object with citations/records/items.")
    citations = [_citation_from_mapping(item) for item in records if isinstance(item, dict)]
    return [item for item in citations if item is not None]


def _parse_csv(text: str) -> list[CitationIn]:
    rows = csv.DictReader(text.splitlines())
    citations = [_citation_from_mapping(row) for row in rows]
    return [item for item in citations if item is not None]


def _parse_ris(text: str) -> list[CitationIn]:
    records: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("ER  -"):
            if current:
                records.append(current)
                current = {}
            continue
        if len(line) < 6 or line[2:6] != "  - ":
            continue
        tag = line[:2].lower()
        value = line[6:].strip()
        if tag == "au":
            current.setdefault("authors", []).append(value)
        elif tag in {"ti", "t1"}:
            current.setdefault("title", value)
        elif tag == "ab":
            current["abstract"] = value
        elif tag in {"py", "y1"}:
            current["publication_year"] = value
        elif tag == "do":
            current["doi"] = value
        elif tag in {"id", "ui"}:
            current["external_id"] = value
    if current:
        records.append(current)
    citations = [_citation_from_mapping(record) for record in records]
    return [item for item in citations if item is not None]


def _parse_nbib(text: str) -> list[CitationIn]:
    records: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    last_tag: str | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip():
            if current:
                records.append(current)
                current = {}
                last_tag = None
            continue
        if len(raw_line) >= 6 and raw_line[4:6] == "- ":
            tag = raw_line[:4].strip().lower()
            value = raw_line[6:].strip()
            last_tag = tag
            if tag == "au":
                current.setdefault("authors", []).append(value)
            elif tag == "pmid":
                current["external_id"] = value
            elif tag == "ti":
                current["title"] = value
            elif tag == "ab":
                current["abstract"] = value
            elif tag == "dp":
                current["publication_year"] = value
            elif tag == "aid" and "[doi]" in value.lower():
                current["doi"] = value.split("[", 1)[0].strip()
            elif tag == "doi":
                current["doi"] = value
            continue
        if raw_line.startswith("      ") and last_tag:
            value = raw_line.strip()
            if last_tag == "ti" and current.get("title"):
                current["title"] = f"{current['title']} {value}"
            elif last_tag == "ab" and current.get("abstract"):
                current["abstract"] = f"{current['abstract']} {value}"
    if current:
        records.append(current)
    citations = [_citation_from_mapping(record) for record in records]
    return [item for item in citations if item is not None]
