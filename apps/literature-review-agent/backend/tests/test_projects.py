from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_create_project_returns_draft_status():
    response = client.post(
        "/projects",
        json={
            "title": "Sepsis biomarker review",
            "research_question": "What biomarkers predict sepsis mortality?",
            "pico_population": "Adults with sepsis",
            "pico_outcome": "Mortality",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "draft"
    assert payload["title"] == "Sepsis biomarker review"
