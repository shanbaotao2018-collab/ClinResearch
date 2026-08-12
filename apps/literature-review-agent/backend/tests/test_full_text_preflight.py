from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import engine
from app.main import app
from app.schemas import FullTextPreflightCreate, ProjectCreate
from app.services.citations import CitationImportPayload
from app.services.full_text_preflight import (
    get_full_text_preflight_records,
    save_full_text_preflight_record,
)
from app.services.project_workflow import create_project_record, import_citations_record


def test_preflight_caches_verified_open_text_before_screening():
    with Session(engine) as session:
        project = create_project_record(session, ProjectCreate(title="Demo", research_question="Does follow-up help?"))
        citation = import_citations_record(
            session,
            project.id,
            CitationImportPayload(source="pubmed", citations=[{
                "title": "Open study", "external_id": "1001", "doi": "10.1000/demo",
            }]),
        )[0]
        saved = save_full_text_preflight_record(
            session,
            project.id,
            [FullTextPreflightCreate(
                citation_id=citation.id,
                pmid="1001",
                pmcid="PMC1001",
                status="full_text_ready",
                source_url="https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1001/fullTextXML",
                local_cache_path="/tmp/workspace/临床科研智能体工作台导出/全文缓存/项目1/citation-1-PMID1001-PMC1001.xml",
                content_text="<article><front>Open source article</front><body>" + ("Verified source text. " * 600) + "</body></article>",
            )],
        )

        assert saved["full_text_ready_count"] == 1
        assert saved["records"][0]["full_text_document_id"]
        assert saved["records"][0]["local_cache_path"].endswith("PMID1001-PMC1001.xml")
        records = get_full_text_preflight_records(session, project.id)
        assert records["full_text_ready_count"] == 1
        assert records["records"][0]["status"] == "full_text_ready"


def test_preflight_records_unavailable_without_creating_document():
    with Session(engine) as session:
        project = create_project_record(session, ProjectCreate(title="Demo", research_question="Does follow-up help?"))
        citation = import_citations_record(
            session,
            project.id,
            CitationImportPayload(source="pubmed", citations=[{"title": "Closed study", "external_id": "1002"}]),
        )[0]
        saved = save_full_text_preflight_record(
            session,
            project.id,
            [FullTextPreflightCreate(
                citation_id=citation.id,
                pmid="1002",
                status="access_unavailable",
                details="No Europe PMC open-access XML record matched this PMID.",
            )],
        )

        assert saved["full_text_ready_count"] == 0
        assert saved["records"][0]["full_text_document_id"] is None


def test_desktop_direct_handoff_endpoint_stores_xml_without_agent_payload_relay():
    with Session(engine) as session:
        project = create_project_record(session, ProjectCreate(title="Direct handoff", research_question="Does follow-up help?"))
        citation = import_citations_record(
            session,
            project.id,
            CitationImportPayload(source="pubmed", citations=[{"title": "Open study", "external_id": "1003"}]),
        )[0]
        project_id = project.id
        citation_id = citation.id
    response = TestClient(app).post(
        f"/projects/{project_id}/full-text-preflight",
        json={"results": [{
            "citation_id": citation_id,
            "pmid": "1003",
            "pmcid": "PMC1003",
            "status": "full_text_ready",
            "source_url": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1003/fullTextXML",
            "local_cache_path": "/tmp/workspace/citation-1003.xml",
            "content_text": "<article><body>" + ("verified XML text " * 800) + "</body></article>",
        }]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["full_text_ready_count"] == 1
    assert body["records"][0]["full_text_document_id"]
    assert body["records"][0]["local_cache_path"] == "/tmp/workspace/citation-1003.xml"
