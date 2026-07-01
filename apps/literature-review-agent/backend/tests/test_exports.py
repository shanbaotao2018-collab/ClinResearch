from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


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

    response = client.get(f"/projects/{project['id']}/export")
    assert response.status_code == 200
    payload = response.json()
    assert payload["project"]["id"] == project["id"]
    assert isinstance(payload["citations"], list)
    assert "audit_logs" in payload
