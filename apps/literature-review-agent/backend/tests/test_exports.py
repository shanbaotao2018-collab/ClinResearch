from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine
from app.main import app
from app.models import Citation


client = TestClient(app)


def test_export_endpoint_returns_conflict_until_screening_complete():
    project = client.post(
        "/projects",
        json={
            "title": "Blocked export review",
            "research_question": "Does export wait for screening?",
        },
    ).json()
    client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={
            "source": "pubmed",
            "citations": [{"title": "Candidate study", "external_id": "101"}],
        },
    )
    client.post(f"/projects/{project['id']}/deduplicate")

    non_raising_client = TestClient(app, raise_server_exceptions=False)
    response = non_raising_client.get(f"/projects/{project['id']}/export")

    assert response.status_code == 409
    assert "Screening decisions must be completed" in response.json()["detail"]


def test_export_bundle_returns_project_citations_prisma_and_audit():
    project = client.post(
        "/projects",
        json={
            "title": "ARDS review",
            "research_question": "How to ventilate ARDS?",
        },
    ).json()
    client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={
            "source": "pubmed",
            "citations": [{"title": "ARDS paper", "external_id": "100"}],
        },
    )
    client.post(f"/projects/{project['id']}/deduplicate")
    with Session(engine) as session:
        citation = session.exec(
            select(Citation).where(Citation.project_id == project["id"])
        ).first()
    client.post(
        f"/projects/{project['id']}/screening-decisions",
        json={
            "citation_id": citation.id,
            "decision": "include",
            "reason": "Matches the review question.",
            "actor": "test_reviewer",
        },
    )
    preflight_response = client.post(
        f"/projects/{project['id']}/full-text-preflight",
        json={"results": [{
            "citation_id": citation.id,
            "pmid": "100",
            "status": "access_unavailable",
            "details": "Test fixture verified the public full text was unavailable.",
        }]},
    )
    assert preflight_response.status_code == 200

    response = client.get(f"/projects/{project['id']}/export")
    assert response.status_code == 200
    payload = response.json()
    assert payload["project"]["id"] == project["id"]
    assert isinstance(payload["citations"], list)
    assert "audit_logs" in payload
