import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine
from app.main import app
from app.models import Citation
from app.schemas import ScreeningDecisionCreate


client = TestClient(app)


def test_screening_decision_rejects_undefined_decision_value():
    with pytest.raises(ValidationError):
        ScreeningDecisionCreate(
            citation_id=1,
            decision="maybe",
            reason="Not an allowed decision value.",
            actor="reviewer_a",
        )


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


def test_pending_screening_batch_excludes_duplicates_and_completed_records():
    project = client.post(
        "/projects",
        json={
            "title": "Pending screening queue",
            "research_question": "Which original studies should remain for review?",
        },
    ).json()
    imported = client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={
            "source": "pubmed",
            "citations": [
                {"title": "A systematic review of diabetes proteomics", "external_id": "review", "doi": "10.1/review"},
                {"title": "Prospective cohort study of diabetes proteomics", "external_id": "cohort", "doi": "10.1/cohort"},
                {"title": "Duplicate prospective cohort study", "external_id": "cohort-dup", "doi": "10.1/cohort"},
                {"title": "Original cohort study", "external_id": "cohort-original", "doi": "10.1/cohort-original"},
            ],
        },
    )
    assert imported.status_code == 201
    assert client.post(f"/projects/{project['id']}/deduplicate").status_code == 200

    with Session(engine) as session:
        cohort_id = session.exec(
            select(Citation.id).where(
                Citation.project_id == project["id"],
                Citation.external_id == "cohort",
            )
        ).one()
    saved = client.post(
        f"/projects/{project['id']}/screening-decisions",
        json={
            "citation_id": cohort_id,
            "decision": "include",
            "reason": "Already reviewed.",
            "actor": "reviewer_a",
        },
    )
    assert saved.status_code == 201

    response = client.get(
        f"/projects/{project['id']}/screening/pending-batch",
        params={"limit": 25, "original_research_only": "true"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["remaining_count"] == 2
    assert {item["external_id"] for item in payload["citations"]} == {"review", "cohort-original"}
    review = next(item for item in payload["citations"] if item["external_id"] == "review")
    assert review["rule_suggestion"]["decision"] == "exclude_candidate"
    assert review["rule_suggestion"]["rule_id"] == "original_research.review_or_meta_analysis"
    cohort = next(item for item in payload["citations"] if item["external_id"] == "cohort-original")
    assert cohort["rule_suggestion"] is None


def test_screening_rejects_a_deduplicated_citation_and_prisma_ignores_its_history():
    project = client.post(
        "/projects",
        json={"title": "Duplicate decision guard", "research_question": "Does screening reject duplicates?"},
    ).json()
    client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={
            "source": "pubmed",
            "citations": [
                {"title": "Original study", "external_id": "one", "doi": "10.1/same"},
                {"title": "Original study duplicate", "external_id": "two", "doi": "10.1/same"},
            ],
        },
    )
    assert client.post(f"/projects/{project['id']}/deduplicate").status_code == 200

    with Session(engine) as session:
        duplicate_id = session.exec(
            select(Citation.id).where(
                Citation.project_id == project["id"],
                Citation.is_deduplicated.is_(True),
            )
        ).one()

    response = client.post(
        f"/projects/{project['id']}/screening-decisions",
        json={
            "citation_id": duplicate_id,
            "decision": "exclude",
            "reason": "Should be rejected before saving.",
            "actor": "reviewer_a",
        },
    )

    assert response.status_code == 409
    assert client.get(f"/projects/{project['id']}/prisma").json()["screened_count"] == 0


def test_pending_screening_batch_marks_non_human_models_for_rule_exclusion():
    project = client.post(
        "/projects",
        json={"title": "Clinical screening", "research_question": "Does a clinical review exclude animal models?"},
    ).json()
    client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={
            "source": "pubmed",
            "citations": [{"title": "A rat model of diabetes proteomics", "external_id": "rat-study"}],
        },
    )
    response = client.get(f"/projects/{project['id']}/screening/pending-batch")

    assert response.status_code == 200
    suggestion = response.json()["citations"][0]["rule_suggestion"]
    assert suggestion["decision"] == "exclude_candidate"
    assert suggestion["rule_id"] == "clinical_research.non_human_model"
