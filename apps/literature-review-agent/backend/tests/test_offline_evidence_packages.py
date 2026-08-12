import hashlib
import json

import pytest
from sqlmodel import Session

from app.config import settings
from app.db import engine
from app.schemas import ProjectCreate
from app.services.offline_evidence_packages import (
    _extract_document,
    import_offline_evidence_package_record,
    list_offline_evidence_packages,
    load_offline_package_documents,
)
from app.services.project_workflow import create_project_record
from app.services.project_workflow import submit_screening_decisions_record
from app.schemas import ScreeningDecisionCreate


def _write_package(root, package_id="heart-failure-demo"):
    package = root / package_id
    (package / "fulltext").mkdir(parents=True)
    citations = [{
        "title": "Pharmacist transition care after heart failure discharge",
        "external_id": "OFFLINE-HF-001",
        "abstract": "A deidentified public-study demonstration record.",
        "authors": "Example A",
        "publication_year": 2024,
        "doi": "10.1000/offline.hf.001",
    }]
    citation_path = package / "citations.json"
    citation_path.write_text(json.dumps({"citations": citations}), encoding="utf-8")
    full_text_path = package / "fulltext" / "offline-hf-001.html"
    full_text_path.write_text(
        "<html><body><h1>Methods</h1><p>Original local HTML source text for audit.</p>"
        "<script>ignore()</script><p>Results were reported in the source document.</p></body></html>",
        encoding="utf-8",
    )
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "package_id": package_id,
        "title": "Heart failure transition-care offline evidence package",
        "source": "offline_pubmed_export",
        "provenance": {
            "databases": [{"name": "PubMed", "searched_at": "2026-08-03", "query": "demo query", "exported_count": 1}],
        },
        "citation_file": {"path": "citations.json", "format": "json", "sha256": digest(citation_path)},
        "documents": [{
            "path": "fulltext/offline-hf-001.html",
            "content_type": "text/html",
            "sha256": digest(full_text_path),
            "citation_match": {"doi": "10.1000/offline.hf.001"},
        }],
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_offline_package_imports_raw_citations_and_loads_matching_html(monkeypatch, tmp_path):
    _write_package(tmp_path)
    monkeypatch.setattr(settings, "offline_evidence_package_dir", str(tmp_path))
    packages = list_offline_evidence_packages()
    assert packages == [
        {
            "package_id": "heart-failure-demo",
            "title": "Heart failure transition-care offline evidence package",
            "citation_file": "citations.json",
            "citation_format": "json",
            "document_count": 1,
            "provenance": {"databases": [{"name": "PubMed", "searched_at": "2026-08-03", "query": "demo query", "exported_count": 1}]},
            "valid": True,
        }
    ]

    with Session(engine) as session:
        project = create_project_record(session, ProjectCreate(title="Offline package", research_question="Does transition care help?"))
        imported = import_offline_evidence_package_record(session, project.id, "heart-failure-demo")
        documents = load_offline_package_documents(session, project.id, "heart-failure-demo")

    assert imported["imported_count"] == 1
    assert imported["pending_full_text_count"] == 1
    assert documents[0]["citation_id"] == imported["citations"][0]["id"]
    assert documents[0]["source_kind"] == "offline_html"
    assert "Original local HTML source text" in documents[0]["content_text"]
    assert "ignore()" not in documents[0]["content_text"]


def test_offline_package_rejects_tampered_raw_file(monkeypatch, tmp_path):
    _write_package(tmp_path)
    monkeypatch.setattr(settings, "offline_evidence_package_dir", str(tmp_path))
    path = tmp_path / "heart-failure-demo" / "citations.json"
    path.write_text("[]", encoding="utf-8")

    packages = list_offline_evidence_packages()

    assert packages[0]["valid"] is False
    assert "Checksum mismatch" in packages[0]["error"]


def test_offline_package_can_limit_full_text_to_included_citations(monkeypatch, tmp_path):
    _write_package(tmp_path)
    monkeypatch.setattr(settings, "offline_evidence_package_dir", str(tmp_path))

    with Session(engine) as session:
        project = create_project_record(session, ProjectCreate(title="Offline package", research_question="Does transition care help?"))
        imported = import_offline_evidence_package_record(session, project.id, "heart-failure-demo")
        citation_id = imported["citations"][0]["id"]
        with pytest.raises(ValueError, match="No verified package full text"):
            load_offline_package_documents(
                session, project.id, "heart-failure-demo", included_only=True
            )
        submit_screening_decisions_record(
            session,
            project.id,
            [ScreeningDecisionCreate(citation_id=citation_id, decision="include", reason="Demo inclusion", actor="test")],
        )
        documents = load_offline_package_documents(
            session, project.id, "heart-failure-demo", included_only=True
        )

    assert len(documents) == 1
    assert documents[0]["citation_id"] == citation_id


def test_offline_pdf_parser_reads_a_raw_pdf_file(tmp_path):
    from pypdf import PdfWriter

    path = tmp_path / "source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as output:
        writer.write(output)

    content, source_kind, page_count = _extract_document(path, "application/pdf")

    assert content == ""
    assert source_kind == "offline_pdf"
    assert page_count == 1
