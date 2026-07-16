import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import engine
from app.main import app
from app.services.exporters import build_review_bundle_data, render_review_bundle_markdown


client = TestClient(app)


def test_review_bundle_requires_completed_screening():
    project = client.post(
        "/projects",
        json={
            "title": "Screening gate review",
            "research_question": "Does the workflow enforce screening before export?",
        },
    ).json()
    client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={
            "source": "pubmed",
            "citations": [{"title": "Candidate study", "external_id": "123"}],
        },
    )
    client.post(f"/projects/{project['id']}/deduplicate")
    with Session(engine) as session:
        with pytest.raises(ValueError, match="Screening decisions must be completed"):
            build_review_bundle_data(session, project["id"])


def test_review_bundle_markdown_includes_strategy_and_prisma():
    project = client.post(
        "/projects",
        json={
            "title": "SGLT2 heart failure review",
            "research_question": "Do SGLT2 inhibitors reduce heart failure hospitalization?",
            "pico_population": "Adults with type 2 diabetes",
            "pico_intervention": "SGLT2 inhibitors",
            "pico_outcome": "Heart failure hospitalization",
        },
    ).json()
    client.post(f"/projects/{project['id']}/search-strategies/generate")
    client.post(
        f"/projects/{project['id']}/citations/import-manual",
        json={
            "source": "pubmed",
            "citations": [
                {
                    "title": "Empagliflozin, Cardiovascular Outcomes, and Mortality in Type 2 Diabetes",
                    "external_id": "26378978",
                    "doi": "10.1056/NEJMoa1504720",
                },
                {
                    "title": "Empagliflozin, Cardiovascular Outcomes, and Mortality in Type 2 Diabetes",
                    "external_id": "26378978-dup",
                    "doi": "10.1056/NEJMoa1504720",
                },
            ],
        },
    )
    client.post(f"/projects/{project['id']}/deduplicate")
    client.post(
        f"/projects/{project['id']}/screening-decisions",
        json={
            "citation_id": 1,
            "decision": "include",
            "reason": "Directly matches the review question.",
            "actor": "test_reviewer",
        },
    )

    with Session(engine) as session:
        bundle = build_review_bundle_data(session, project["id"])

    assert bundle is not None
    assert len(bundle["search_strategies"]) == 1
    assert bundle["prisma"]["identified_count"] == 2
    assert bundle["prisma"]["deduplicated_count"] == 1

    markdown = render_review_bundle_markdown(bundle)
    assert "# SGLT2 heart failure review" in markdown
    assert "## Search Strategies" in markdown
    assert "SGLT2 inhibitors" in markdown
    assert "## PRISMA Snapshot" in markdown
