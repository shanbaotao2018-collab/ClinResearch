from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_deduplicate_and_screening_updates_prisma_counts():
    project = client.post(
        "/projects",
        json={
            "title": "Stroke AI review",
            "research_question": "Can AI diagnose stroke on CT?",
        },
    ).json()
    client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={
            "source": "pubmed",
            "citations": [
                {"title": "AI stroke CT", "external_id": "1", "doi": "10.1/a"},
                {"title": "AI stroke CT duplicate", "external_id": "2", "doi": "10.1/a"},
                {"title": "Unrelated radiology paper", "external_id": "3", "doi": "10.1/b"},
            ],
        },
    )

    dedup_response = client.post(f"/projects/{project['id']}/deduplicate")
    assert dedup_response.status_code == 200
    assert dedup_response.json()["removed_count"] == 1

    screening_response = client.post(
        f"/projects/{project['id']}/screening-decisions",
        json={
            "citation_id": 1,
            "decision": "include",
            "reason": "Matches topic",
            "actor": "reviewer_a",
        },
    )
    assert screening_response.status_code == 201

    prisma_response = client.get(f"/projects/{project['id']}/prisma")
    assert prisma_response.status_code == 200
    assert prisma_response.json()["identified_count"] == 3
    assert prisma_response.json()["deduplicated_count"] == 2
