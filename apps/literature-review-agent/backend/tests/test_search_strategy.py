from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_generate_search_strategy_creates_version():
    project = client.post(
        "/projects",
        json={
            "title": "ARDS ventilation review",
            "research_question": "Does lung protective ventilation reduce mortality in ARDS?",
            "pico_population": "Adults with ARDS",
            "pico_intervention": "Lung protective ventilation",
            "pico_outcome": "Mortality",
        },
    ).json()

    response = client.post(f"/projects/{project['id']}/search-strategies/generate")
    assert response.status_code == 201
    payload = response.json()
    assert payload["source"] == "pubmed"
    assert "ARDS" in payload["query_text"]
    assert payload["version_number"] == 1
