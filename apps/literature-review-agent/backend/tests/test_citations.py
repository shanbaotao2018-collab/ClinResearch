from fastapi.testclient import TestClient

from app.config import settings
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


def test_import_citations_from_json_file(monkeypatch, tmp_path):
    import_dir = tmp_path / "literature-imports"
    import_dir.mkdir()
    citation_file = import_dir / "records.json"
    citation_file.write_text(
        """
        {
          "citations": [
            {
              "title": "Pharmacist discharge education after heart failure hospitalization",
              "pmid": "PMID9001",
              "abstract": "A pragmatic discharge management study.",
              "authors": ["Chen A", "Wang B"],
              "year": "2024",
              "doi": "10.1000/hf-discharge"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "literature_import_dir", str(import_dir))
    project = client.post(
        "/projects",
        json={
            "title": "Heart failure discharge review",
            "research_question": "Do discharge interventions improve follow-up?",
        },
    ).json()

    response = client.post(
        f"/projects/{project['id']}/citations/import-file",
        json={"file_path": "records.json", "source": "offline_pubmed_export"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["parsed_count"] == 1
    assert payload["imported_count"] == 1
    detail = client.get(f"/workbench/review-projects/{project['id']}").json()
    assert detail["citations"][0]["source"] == "offline_pubmed_export"
    assert detail["citations"][0]["external_id"] == "PMID9001"


def test_import_citations_file_rejects_paths_outside_import_dir(monkeypatch, tmp_path):
    import_dir = tmp_path / "literature-imports"
    import_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(settings, "literature_import_dir", str(import_dir))
    project = client.post(
        "/projects",
        json={
            "title": "Restricted path review",
            "research_question": "Can unsafe paths be imported?",
        },
    ).json()

    response = client.post(
        f"/projects/{project['id']}/citations/import-file",
        json={"file_path": str(outside), "source": "offline_file"},
    )

    assert response.status_code == 400
    assert "configured import directory" in response.json()["detail"]
