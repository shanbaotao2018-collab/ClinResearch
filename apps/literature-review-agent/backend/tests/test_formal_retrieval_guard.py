from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _project() -> dict:
    return client.post(
        "/projects",
        json={"title": "Formal review guard", "research_question": "Does the guard stop incomplete retrieval?"},
    ).json()


def _import_one(project_id: int) -> None:
    response = client.post(
        f"/projects/{project_id}/citations/import-manual",
        json={"source": "pubmed", "citations": [{"title": "Candidate", "external_id": "1"}]},
    )
    assert response.status_code == 201


def _current_pubmed_strategy(project_id: int) -> dict:
    response = client.post(f"/projects/{project_id}/search-strategies/generate")
    assert response.status_code == 201
    return response.json()


def _record_run(project_id: int, *, complete: bool, truncated: bool, query: str) -> None:
    response = client.post(
        f"/projects/{project_id}/formal-retrieval-runs",
        json={
            "source": "pubmed",
            "query": query,
            "database_total_count": 1001 if truncated else 1,
            "retrieved_count": 1000 if truncated else 1,
            "imported_count": 1000 if truncated else 1,
            "page_count": 10 if truncated else 1,
            "complete": complete,
            "truncated": truncated,
            "max_records": 1000,
            "retrieval_channel": "test",
        },
    )
    assert response.status_code == 201


def test_incomplete_formal_retrieval_blocks_downstream_deduplication():
    project = _project()
    _import_one(project["id"])
    strategy = _current_pubmed_strategy(project["id"])
    _record_run(project["id"], complete=False, truncated=True, query=strategy["query_text"])

    response = client.post(f"/projects/{project['id']}/deduplicate")

    assert response.status_code == 409
    assert "Formal retrieval is incomplete" in response.json()["detail"]
    status = client.get(f"/projects/{project['id']}/formal-retrieval-status").json()
    assert status["ready"] is False
    assert status["runs"][0]["truncated"] is True


def test_repeated_deduplication_is_idempotent_and_preserves_screening_status():
    project = _project()
    strategy = _current_pubmed_strategy(project["id"])
    response = client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={
            "source": "pubmed",
            "citations": [
                {"title": "Candidate", "external_id": "1", "doi": "10.1/example"},
                {"title": "Candidate duplicate", "external_id": "2", "doi": "10.1/example"},
            ],
        },
    )
    assert response.status_code == 201
    _record_run(project["id"], complete=True, truncated=False, query=strategy["query_text"])

    assert client.post(f"/projects/{project['id']}/deduplicate").json()["removed_count"] == 1
    citation_id = client.get(f"/projects/{project['id']}/export").status_code
    assert citation_id == 409
    decision = client.post(
        f"/projects/{project['id']}/screening-decisions",
        json={"citation_id": 1, "decision": "exclude", "reason": "test", "actor": "reviewer"},
    )
    assert decision.status_code == 201
    repeated = client.post(f"/projects/{project['id']}/deduplicate")
    assert repeated.status_code == 200
    assert repeated.json()["removed_count"] == 0
    assert client.get(f"/projects/{project['id']}").json()["status"] == "screening_completed"
