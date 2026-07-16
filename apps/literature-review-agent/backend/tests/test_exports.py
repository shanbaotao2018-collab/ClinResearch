from fastapi.testclient import TestClient

from app.main import app


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
    client.post(
        f"/projects/{project['id']}/screening-decisions",
        json={
            "citation_id": 1,
            "decision": "include",
            "reason": "Matches the review question.",
            "actor": "test_reviewer",
        },
    )

    response = client.get(f"/projects/{project['id']}/export")
    assert response.status_code == 200
    payload = response.json()
    assert payload["project"]["id"] == project["id"]
    assert isinstance(payload["citations"], list)
    assert "audit_logs" in payload
