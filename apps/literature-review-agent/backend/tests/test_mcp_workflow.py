import asyncio

import pytest
from sqlmodel import Session

from app.config import settings
from app.db import engine
from app.mcp_server import (
    calculate_study_sample_size, create_study_design_project, create_review_project,
    deduplicate_project_citations, export_study_design_bundle, generate_rct_randomization_schedule,
    generate_study_design_blueprint, generate_project_search_strategy, get_study_design_approval_status,
    import_citations_to_project, mcp, request_study_design_approval, save_rct_randomization_plan,
    save_study_design_content, search_pubmed, submit_screening_decisions,
)
from app.services.study_design import approve_study_design_record, get_study_design_workflow_events


def test_mcp_workflow_tools_are_registered():
    tool_names = sorted(mcp._tool_manager._tools.keys())
    for name in ["create_review_project", "generate_project_search_strategy", "import_citations_to_project", "deduplicate_project_citations", "submit_screening_decisions", "create_study_design_project", "generate_study_design_blueprint", "calculate_study_sample_size", "save_rct_randomization_plan", "request_study_design_approval", "get_study_design_approval_status", "generate_rct_randomization_schedule", "export_study_design_bundle"]:
        assert name in tool_names
    assert "confirm_study_design" not in tool_names
    for name in [
        "start_evidence_extraction_workflow",
        "save_evidence_extractions",
        "check_project_retractions",
        "export_evidence_table",
        "start_research_writing_workflow",
        "get_research_writing_source",
        "save_research_writing_draft",
        "request_research_writing_approval",
        "get_research_writing_approval_status",
        "export_research_writing_bundle",
    ]:
        assert name in tool_names


def test_mcp_study_design_workflow_requires_external_approval(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "randomization_storage_dir", str(tmp_path))
    created = create_study_design_project(title="SGLT2 pragmatic RCT", research_question="Can an SGLT2 inhibitor reduce heart-failure hospitalization?", study_type="efficacy", study_design="RCT, parallel-group", population="Adults with type 2 diabetes and high cardiovascular risk", intervention="SGLT2 inhibitor", comparator="Standard care", outcome="Heart-failure hospitalization within 12 months", department="Cardiology", resource_summary="Estimated 300 eligible cases annually", data_attestation="deidentified_or_aggregate")
    project_id, run_id = created["project"]["id"], created["workflow"]["run_id"]
    blueprint = generate_study_design_blueprint(project_id, run_id)
    assert blueprint["reporting_standard"] == "SPIRIT/CONSORT"
    saved = save_study_design_content(project_id, run_id, inclusion_criteria="Adults with type 2 diabetes and documented cardiovascular risk.", exclusion_criteria="Pregnancy, contraindication, or unresolved safety concern.", primary_outcome="First heart-failure hospitalization within 12 months.", proposal_outline="Background; objectives; design; participants; outcomes; analysis; ethics.", secondary_outcomes="All-cause hospitalization and renal function change.", innovation_notes="Pragmatic implementation in routine cardiometabolic care.", feasibility_notes="The department estimates 300 potentially eligible cases per year.")
    assert saved["project"]["status"] == "content_drafted"
    sample_size = calculate_study_sample_size(project_id, run_id, method="proportions", group_one_value=0.18, group_two_value=0.12)
    assert sample_size["sample_size"]["total"] > 0
    plan = save_rct_randomization_plan(project_id, run_id, 24, ["standard_care", "sglt2"], 4)
    assert plan["randomization_plan"]["allocations_generated"] is False
    approval = request_study_design_approval(project_id, run_id)
    assert approval["approval"]["status"] == "pending"
    with pytest.raises(ValueError, match="External human approval"):
        generate_rct_randomization_schedule(project_id, run_id)
    with Session(engine) as session:
        approve_study_design_record(session, project_id, "authorized_researcher")
        assert len(get_study_design_workflow_events(session, project_id, run_id)) >= 6
    status = get_study_design_approval_status(project_id, run_id)
    assert status["approval"]["status"] == "approved"
    schedule = generate_rct_randomization_schedule(project_id, run_id)
    assert schedule["randomization_schedule"]["allocation_visible_to_agent"] is False
    exported = export_study_design_bundle(project_id, run_id)
    assert "Allocation sequence is withheld" in exported["markdown"]


def test_mcp_project_workflow_closes_the_basic_loop():
    created = create_review_project(title="SGLT2 review", research_question="Do SGLT2 inhibitors reduce heart failure hospitalization?", pico_population="Adults with type 2 diabetes", pico_intervention="SGLT2 inhibitors", pico_comparator="Placebo or standard care", pico_outcome="Heart failure hospitalization")
    project_id = created["project"]["id"]
    strategy = generate_project_search_strategy(project_id)
    assert strategy["search_strategy"]["project_id"] == project_id
    imported = import_citations_to_project(project_id, "pubmed", [{"title": "Empagliflozin, Cardiovascular Outcomes, and Mortality in Type 2 Diabetes", "external_id": "26378978", "doi": "10.1056/NEJMoa1504720"}, {"title": "Empagliflozin duplicate", "external_id": "26378978-dup", "doi": "10.1056/NEJMoa1504720"}, {"title": "Dapagliflozin and Cardiovascular Outcomes in Type 2 Diabetes", "external_id": "30415602", "doi": "10.1056/NEJMoa1812389"}])
    assert imported["imported_count"] == 3
    assert deduplicate_project_citations(project_id)["removed_count"] == 1
    screening = submit_screening_decisions(project_id, [{"citation_id": imported["citations"][0]["id"], "decision": "include", "reason": "Directly matches the review question."}, {"citation_id": imported["citations"][2]["id"], "decision": "exclude", "reason": "Outcome reporting is not sufficiently aligned."}])
    assert screening["project_status"] == "screening_completed"


def test_search_pubmed_limits_abstract_context_for_agents(monkeypatch):
    async def fake_search_pubmed_records(query: str, limit: int):
        return [{"source": "pubmed", "external_id": "123", "title": "A relevant trial", "abstract": "A" * 4_000, "authors": "Author A", "publication_year": 2025, "doi": "10.1000/example"}]
    monkeypatch.setattr("app.mcp_server.search_pubmed_records", fake_search_pubmed_records)
    record = asyncio.run(search_pubmed("example query", limit=1))["records"][0]
    assert len(record["abstract"]) <= 1_200
    assert record["abstract"].endswith("...")
