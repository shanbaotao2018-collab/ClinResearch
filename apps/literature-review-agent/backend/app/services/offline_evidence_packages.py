from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.config import settings
from app.models import Citation
from app.services.citation_files import infer_citation_file_format, parse_citation_path
from app.services.citations import CitationImportPayload
from app.services.project_workflow import import_citations_record


class OfflineEvidencePackageError(ValueError):
    """An invalid or incomplete offline evidence package."""


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag in {"p", "div", "section", "article", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)

    def text(self) -> str:
        return "\n".join(" ".join(part.split()) for part in "".join(self.parts).splitlines() if part.strip())


def _package_root() -> Path:
    return Path(settings.offline_evidence_package_dir).expanduser().resolve()


def _safe_relative_path(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    if root != candidate and root not in candidate.parents:
        raise OfflineEvidencePackageError("Package paths must stay inside the offline evidence package directory.")
    if not candidate.is_file():
        raise OfflineEvidencePackageError(f"Package file not found: {value}")
    return candidate


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clean(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def _read_manifest(package_id: str) -> tuple[Path, dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", package_id):
        raise OfflineEvidencePackageError("package_id may contain only letters, numbers, dot, underscore, and hyphen.")
    root = _package_root()
    manifest_path = _safe_relative_path(root, f"{package_id}/manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise OfflineEvidencePackageError(f"Invalid manifest.json: {error.msg}") from error
    if not isinstance(manifest, dict) or manifest.get("package_id") != package_id:
        raise OfflineEvidencePackageError("manifest.json package_id must match its directory name.")
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("title"), str):
        raise OfflineEvidencePackageError("manifest.json requires schema_version=1 and a title.")
    citation_file = manifest.get("citation_file")
    if not isinstance(citation_file, dict) or not isinstance(citation_file.get("path"), str):
        raise OfflineEvidencePackageError("manifest.json requires citation_file.path.")
    documents = manifest.get("documents", [])
    if not isinstance(documents, list):
        raise OfflineEvidencePackageError("manifest.json documents must be a list.")
    return manifest_path.parent, manifest


def _verified_file(root: Path, descriptor: dict[str, Any]) -> Path:
    path_value = descriptor.get("path")
    expected_sha = descriptor.get("sha256")
    if not isinstance(path_value, str) or not isinstance(expected_sha, str):
        raise OfflineEvidencePackageError("Every package file requires path and sha256.")
    path = _safe_relative_path(root, path_value)
    if _sha256(path) != expected_sha.lower():
        raise OfflineEvidencePackageError(f"Checksum mismatch for {path_value}.")
    return path


def list_offline_evidence_packages() -> list[dict[str, Any]]:
    root = _package_root()
    if not root.exists():
        return []
    packages: list[dict[str, Any]] = []
    for manifest_path in sorted(root.glob("*/manifest.json")):
        try:
            package_root, manifest = _read_manifest(manifest_path.parent.name)
            citation_path = _verified_file(package_root, manifest["citation_file"])
            packages.append({
                "package_id": manifest["package_id"],
                "title": manifest["title"],
                "citation_file": manifest["citation_file"]["path"],
                "citation_format": infer_citation_file_format(citation_path, manifest["citation_file"].get("format")),
                "document_count": len(manifest.get("documents", [])),
                "provenance": manifest.get("provenance", {}),
                "valid": True,
            })
        except OfflineEvidencePackageError as error:
            packages.append({"package_id": manifest_path.parent.name, "valid": False, "error": str(error)})
    return packages


def import_offline_evidence_package_record(session: Session, project_id: int, package_id: str) -> dict[str, Any]:
    root, manifest = _read_manifest(package_id)
    citation_path = _verified_file(root, manifest["citation_file"])
    citations = parse_citation_path(citation_path, manifest["citation_file"].get("format"))
    source = str(manifest.get("source") or f"offline_package:{package_id}")
    imported = import_citations_record(session, project_id, CitationImportPayload(source=source, citations=citations), actor="offline_package")
    return {
        "project_id": project_id,
        "package_id": package_id,
        "title": manifest["title"],
        "source": source,
        "parsed_count": len(citations),
        "imported_count": len(imported),
        "pending_full_text_count": len(manifest.get("documents", [])),
        "citations": [{"id": item.id, "external_id": item.external_id, "doi": item.doi, "title": item.title} for item in imported],
    }


def _match_citation(session: Session, project_id: int, match: dict[str, Any]) -> Citation:
    citations = session.exec(select(Citation).where(Citation.project_id == project_id)).all()
    for field in ("doi", "external_id", "title"):
        expected = _clean(str(match.get(field) or ""))
        if not expected:
            continue
        matched = [item for item in citations if _clean(str(getattr(item, field) or "")) == expected]
        if len(matched) == 1:
            return matched[0]
        if len(matched) > 1:
            raise OfflineEvidencePackageError(f"Document citation_match.{field} matches multiple local citations.")
    raise OfflineEvidencePackageError("Document citation_match did not match a local citation by DOI, external_id, or title.")


def _extract_document(path: Path, content_type: str) -> tuple[str, str, int | None]:
    normalized = content_type.lower()
    if normalized in {"text/html", "application/xhtml+xml", "text/xml", "application/xml"}:
        parser = _HtmlTextExtractor()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        return parser.text(), "offline_html", None
    if normalized == "application/pdf":
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise OfflineEvidencePackageError("PDF parsing requires the pypdf dependency installed with the backend.") from error
        reader = PdfReader(str(path))
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages), "offline_pdf", len(reader.pages)
    raise OfflineEvidencePackageError(f"Unsupported offline full-text content_type: {content_type}")


def load_offline_package_documents(
    session: Session,
    project_id: int,
    package_id: str,
    *,
    included_only: bool = False,
) -> list[dict[str, Any]]:
    """Load verified local source documents, optionally only for screened-in citations."""
    root, manifest = _read_manifest(package_id)
    included_ids: set[int] | None = None
    if included_only:
        # Keep raw packages reusable while enforcing the evidence workflow boundary.
        from app.services.evidence_extraction import included_citations

        included_ids = {
            citation.id
            for citation in included_citations(session, project_id)
            if citation.id is not None
        }
    documents: list[dict[str, Any]] = []
    for descriptor in manifest.get("documents", []):
        if not isinstance(descriptor, dict) or not isinstance(descriptor.get("citation_match"), dict):
            raise OfflineEvidencePackageError("Every document requires citation_match.")
        path = _verified_file(root, descriptor)
        content_text, source_kind, page_count = _extract_document(path, str(descriptor.get("content_type") or ""))
        citation = _match_citation(session, project_id, descriptor["citation_match"])
        if included_ids is not None and citation.id not in included_ids:
            continue
        documents.append({
            "citation_id": citation.id,
            "source_kind": source_kind,
            "content_text": content_text,
            "source_url": descriptor.get("source_url"),
            "page_count": page_count,
        })
    if included_only and not documents:
        raise OfflineEvidencePackageError(
            "No verified package full text is available for the citations included after screening."
        )
    return documents
