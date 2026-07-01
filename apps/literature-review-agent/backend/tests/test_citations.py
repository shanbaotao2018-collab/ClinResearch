from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_import_manual_citations_updates_project_status():
    project = client.post(
        "/projects",
        json={
            "title": "ICU delirium review",
            "research_question": "How common is ICU delirium?",
        },
    ).json()

    response = client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={
            "source": "pubmed",
            "citations": [
                {
                    "title": "ICU delirium cohort study",
                    "external_id": "PMID123",
                    "abstract": "Abstract 1",
                },
                {
                    "title": "ICU delirium meta analysis",
                    "external_id": "PMID456",
                    "abstract": "Abstract 2",
                },
            ],
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["imported_count"] == 2
    project_after = client.get(f"/projects/{project['id']}").json()
    assert project_after["status"] == "search_executed"
