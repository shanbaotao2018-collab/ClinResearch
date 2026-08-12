from fastapi.testclient import TestClient

from app.main import app
from app.models import Citation, StudyDesignProject
from app.db import engine
from sqlmodel import Session, select


client = TestClient(app)


def test_workbench_overview_lists_review_projects():
    project = client.post(
        "/projects",
        json={"title": "Workbench review", "research_question": "Does the UI read projects?"},
    ).json()

    response = client.get("/workbench/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["review_projects"] == 1
    assert payload["review_projects"][0]["id"] == project["id"]


def test_workbench_study_detail_redacts_randomization_values():
    with Session(engine) as session:
        project = StudyDesignProject(
            title="Workbench study",
            research_question="Can a workbench protect allocations?",
            study_type="efficacy",
            study_design="RCT",
            population="Adults",
            outcome="Follow-up",
            randomization_seed=123,
            randomization_schedule_json='["A", "B"]',
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        project_id = project.id

    response = client.get(f"/workbench/study-design-projects/{project_id}")

    assert response.status_code == 200
    stored_project = response.json()["project"]
    assert "randomization_seed" not in stored_project
    assert "randomization_schedule_json" not in stored_project
    assert response.json()["randomization"]["allocation_visible_to_workbench"] is False


def test_workbench_downloads_completed_review_as_markdown():
    project = client.post(
        "/projects",
        json={"title": "Downloadable review", "research_question": "Can the workbench export?"},
    ).json()
    client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={"source": "pubmed", "citations": [{"title": "Candidate", "external_id": "90"}]},
    )
    with Session(engine) as session:
        citation = session.exec(
            select(Citation).where(Citation.project_id == project["id"])
        ).one()
    client.post(
        f"/projects/{project['id']}/full-text-preflight",
        json={
            "results": [{
                "citation_id": citation.id,
                "pmid": "90",
                "status": "access_unavailable",
                "details": "Test-only availability record.",
            }],
        },
    )
    client.post(f"/projects/{project['id']}/deduplicate")
    client.post(
        f"/projects/{project['id']}/screening-decisions",
        json={
            "citation_id": citation.id,
            "decision": "include",
            "reason": "Matches.",
            "actor": "reviewer",
        },
    )

    response = client.get(f"/workbench/review-projects/{project['id']}/export?format=markdown")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert f"review-project-{project['id']}.md" in response.headers["content-disposition"]
    assert "# Downloadable review" in response.text


def test_workbench_blocks_evidence_export_without_approval():
    response = client.get("/workbench/review-projects/999/evidence-workflows/missing/export")

    assert response.status_code == 409
