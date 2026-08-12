import asyncio
import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import (
    AgentSkillExecutionReceipt,
    BiasAssessment,
    CitationSafetyCheck,
    EvidenceExtraction,
    FullTextDocument,
    FullTextEvidenceDetail,
)
from app.schemas import (
    CitationSafetyCheckCreate,
    EvidenceExtractionCreate,
    ProjectCreate,
    ScreeningDecisionCreate,
)
from app.services.agent_workflows import (
    ingest_agent_skill_execution_receipt_journal,
    require_agent_skill_receipts,
)
from app.services.evidence_extraction import (
    EXTRACTION_SKILLS,
    RETRACTION_SKILL,
    build_evidence_table_data,
    check_project_retractions_record,
    render_evidence_table_markdown,
    save_evidence_extractions_record,
    save_project_retraction_checks_record,
    start_evidence_extraction_workflow_record,
)
from app.services.project_workflow import (
    create_project_record,
    import_citations_record,
    submit_screening_decisions_record,
)
from app.services.next_actions import get_next_actions
from app.services.citations import CitationImportPayload


def _screened_project(session: Session):
    project = create_project_record(
        session,
        ProjectCreate(
            title="SGLT2 evidence extraction",
            research_question="Do SGLT2 inhibitors reduce heart-failure hospitalization in type 2 diabetes?",
        ),
        actor="test",
    )
    citations = import_citations_record(
        session,
        project.id,
        CitationImportPayload.model_validate(
            {
                "source": "pubmed",
                "citations": [
                    {
                        "external_id": "26378978",
                        "title": "Empagliflozin, Cardiovascular Outcomes, and Mortality in Type 2 Diabetes",
                        "abstract": "Randomized trial in adults with type 2 diabetes reporting cardiovascular outcomes.",
                    },
                    {
                        "external_id": "30415602",
                        "title": "Dapagliflozin and Cardiovascular Outcomes in Type 2 Diabetes",
                        "abstract": "Large randomized trial evaluating cardiovascular outcomes in type 2 diabetes.",
                    },
                ],
            }
        ),
        actor="test",
    )
    submit_screening_decisions_record(
        session,
        project.id,
        [
            ScreeningDecisionCreate(citation_id=item.id, decision="include", reason="Matches question.", actor="test")
            for item in citations
        ],
        actor="test",
    )
    return project, citations


def _write_receipts(tmp_path, secret: str, run, skills: set[str]) -> None:
    receipts = []
    for index, skill_name in enumerate(sorted(skills)):
        receipt_id = str(uuid4())
        timestamp = 1_784_107_500_000 + index
        signature = hmac.new(
            secret.encode(),
            f"{receipt_id}|ses_evidence|{skill_name}|{timestamp}".encode(),
            hashlib.sha256,
        ).hexdigest()
        receipts.append(
            {
                "receipt_id": receipt_id,
                "opencode_session_id": "ses_evidence",
                "skill_name": skill_name,
                "executed_at_ms": timestamp,
                "signature": signature,
            }
        )
    tmp_path.joinpath(f"{run.run_id}.json").write_text(
        json.dumps(
            {
                "version": 1,
                "workflow_run_id": run.run_id,
                "workflow_type": "evidence_extraction",
                "subject_type": "review",
                "subject_id": run.subject_id,
                "opencode_session_id": "ses_evidence",
                "receipts": receipts,
            }
        ),
        encoding="utf-8",
    )


def test_evidence_extraction_requires_signed_skills_and_exports_source_bounded_rows(monkeypatch, tmp_path):
    secret = "test-evidence-receipt-key"
    monkeypatch.setattr(settings, "skill_receipt_key", secret)
    monkeypatch.setattr(settings, "skill_receipt_dir", str(tmp_path))
    monkeypatch.setattr(settings, "skill_receipt_enforcement", "strict")

    async def fake_retraction_check(pmid: str):
        return {
            "status": "not_flagged_at_check_time",
            "check_source": "pubmed_publication_type",
            "details": f"No PubMed notice flag for PMID {pmid} at check time.",
        }

    monkeypatch.setattr(
        "app.services.evidence_extraction.check_pubmed_retraction_status", fake_retraction_check
    )
    with Session(engine) as session:
        project, citations = _screened_project(session)
        run = start_evidence_extraction_workflow_record(session, project.id, actor="test")
        with pytest.raises(ValueError, match="clinical-study-info-extractor"):
            require_agent_skill_receipts(
                session, run.run_id, "evidence_extraction", "review", project.id,
                "evidence_extraction", EXTRACTION_SKILLS,
            )
        _write_receipts(tmp_path, secret, run, EXTRACTION_SKILLS)
        require_agent_skill_receipts(
            session, run.run_id, "evidence_extraction", "review", project.id,
            "evidence_extraction", EXTRACTION_SKILLS,
        )
        saved = save_evidence_extractions_record(
            session,
            project.id,
            run.run_id,
            [
                EvidenceExtractionCreate(
                    citation_id=citations[0].id,
                    study_design="Randomized controlled trial",
                    population="Adults with type 2 diabetes",
                    outcomes="Heart-failure hospitalization",
                    effect_estimates="Reported in abstract; confirm exact estimate from full text.",
                    methods_summary="Parallel-group trial reported in abstract.",
                    evidence_basis="abstract",
                    missing_fields=["exact sample size", "exact confidence interval"],
                ),
                EvidenceExtractionCreate(
                    citation_id=citations[1].id,
                    study_design="Randomized controlled trial",
                    population="Adults with type 2 diabetes",
                    outcomes="Cardiovascular outcomes",
                    evidence_basis="abstract",
                    missing_fields=["heart-failure hospitalization effect estimate"],
                ),
            ],
            actor="test",
        )
        assert len(saved) == 2
        _write_receipts(tmp_path, secret, run, EXTRACTION_SKILLS | RETRACTION_SKILL)
        require_agent_skill_receipts(
            session, run.run_id, "evidence_extraction", "review", project.id,
            "retraction_check", RETRACTION_SKILL,
        )
        checks = asyncio.run(check_project_retractions_record(session, project.id, run.run_id, actor="test"))
        assert len(checks) == 2
        bundle = build_evidence_table_data(session, project.id, run.run_id)
        assert len(bundle["rows"]) == 2
        assert {item["skill_name"] for item in bundle["skill_receipts"]} == EXTRACTION_SKILLS | RETRACTION_SKILL
        markdown = render_evidence_table_markdown(bundle)
        assert "not_flagged_at_check_time" in markdown
        assert "Human review remains required" in markdown
        assert "partial_full_text_assessment" in markdown
        assert "Evidence rows were saved or refreshed in this workflow run." in markdown
        assert len(session.exec(select(EvidenceExtraction)).all()) == 2
        assert len(session.exec(select(CitationSafetyCheck)).all()) == 2
        captured = {
            item.skill_name
            for item in session.exec(select(AgentSkillExecutionReceipt)).all()
        }
        assert captured == EXTRACTION_SKILLS | RETRACTION_SKILL


def test_evidence_extraction_rejects_effect_estimates_without_abstract_or_full_text():
    with Session(engine) as session:
        project, citations = _screened_project(session)
        run = start_evidence_extraction_workflow_record(session, project.id, actor="test")
        with pytest.raises(ValueError, match="Effect estimates require"):
            save_evidence_extractions_record(
                session,
                project.id,
                run.run_id,
                [
                    EvidenceExtractionCreate(
                        citation_id=citations[0].id,
                        effect_estimates="HR 0.80",
                        evidence_basis="metadata",
                    )
                ],
                actor="test",
            )


def test_partial_full_text_assessment_remains_resumable(monkeypatch, tmp_path):
    secret = "test-partial-evidence-receipt-key"
    monkeypatch.setattr(settings, "skill_receipt_key", secret)
    monkeypatch.setattr(settings, "skill_receipt_dir", str(tmp_path))
    monkeypatch.setattr(settings, "skill_receipt_enforcement", "strict")
    with Session(engine) as session:
        project, citations = _screened_project(session)
        run = start_evidence_extraction_workflow_record(session, project.id, actor="test")
        _write_receipts(tmp_path, secret, run, EXTRACTION_SKILLS | RETRACTION_SKILL)
        save_evidence_extractions_record(
            session,
            project.id,
            run.run_id,
            [
                EvidenceExtractionCreate(citation_id=item.id, evidence_basis="abstract")
                for item in citations
            ],
            actor="test",
        )
        save_project_retraction_checks_record(
            session,
            project.id,
            run.run_id,
            [
                CitationSafetyCheckCreate(
                    citation_id=item.id,
                    status="not_flagged_at_check_time",
                    check_source="pubmed_publication_type_client",
                )
                for item in citations
            ],
            actor="test",
        )
        session.add(
            FullTextDocument(
                project_id=project.id,
                citation_id=citations[0].id,
                source_kind="open_access_html",
                source_url="https://example.org/full-text",
                content_text="Enough source text for this partial-full-text workflow test.",
                content_sha256="test-partial-full-text",
                needs_human_review=True,
            )
        )
        session.commit()

        result = get_next_actions(session, "evidence", project.id)
        missing_citation_id = citations[1].id

    assert result["workflow_status"] == "partial_full_text_assessment"
    assert [item["action_id"] for item in result["actions"]] == [
        "complete_available_full_text_assessment",
        "export_partial_evidence_report",
        "provide_missing_full_text",
    ]
    assert str(missing_citation_id) in result["actions"][2]["prompt"]


def test_partial_full_text_assessment_can_handoff_after_available_full_text_is_evaluated(
    monkeypatch, tmp_path
):
    secret = "test-open-access-handoff-receipt-key"
    monkeypatch.setattr(settings, "skill_receipt_key", secret)
    monkeypatch.setattr(settings, "skill_receipt_dir", str(tmp_path))
    monkeypatch.setattr(settings, "skill_receipt_enforcement", "strict")
    with Session(engine) as session:
        project, citations = _screened_project(session)
        run = start_evidence_extraction_workflow_record(session, project.id, actor="test")
        _write_receipts(tmp_path, secret, run, EXTRACTION_SKILLS | RETRACTION_SKILL)
        save_evidence_extractions_record(
            session,
            project.id,
            run.run_id,
            [EvidenceExtractionCreate(citation_id=item.id, evidence_basis="abstract") for item in citations],
            actor="test",
        )
        save_project_retraction_checks_record(
            session,
            project.id,
            run.run_id,
            [
                CitationSafetyCheckCreate(
                    citation_id=item.id,
                    status="not_flagged_at_check_time",
                    check_source="pubmed_publication_type_client",
                )
                for item in citations
            ],
            actor="test",
        )
        document = FullTextDocument(
            project_id=project.id,
            citation_id=citations[0].id,
            source_kind="open_access_html",
            source_url="https://example.org/full-text",
            content_text="Enough source text for the open-access handoff test.",
            content_sha256="test-open-access-handoff",
            needs_human_review=True,
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        session.add(FullTextEvidenceDetail(
            project_id=project.id,
            citation_id=citations[0].id,
            full_text_document_id=document.id,
            extraction_notes="Full-text evidence was extracted.",
        ))
        session.add(BiasAssessment(
            project_id=project.id,
            citation_id=citations[0].id,
            full_text_document_id=document.id,
            instrument="rob2",
            overall_judgement="some_concerns",
            domains_json="[]",
        ))
        session.commit()

        result = get_next_actions(session, "evidence", project.id)

    assert result["workflow_status"] == "partial_full_text_assessment"
    assert result["actions"][0]["action_id"] == "start_open_access_research_writing"
    assert result["actions"][0]["target_agent"] == "research-writing"
    assert "现在进入科研写作" in result["actions"][0]["label"]
    assert result["actions"][2]["action_id"] == "provide_missing_full_text"
    assert "可选" in result["actions"][2]["label"]


def test_client_retraction_checks_can_complete_evidence_export_without_server_network_access():
    """The client_online path stores desktop PubMed results without backend retrieval."""
    with Session(engine) as session:
        project, citations = _screened_project(session)
        run = start_evidence_extraction_workflow_record(session, project.id, actor="test")
        save_evidence_extractions_record(
            session,
            project.id,
            run.run_id,
            [
                EvidenceExtractionCreate(
                    citation_id=item.id,
                    study_design="Randomized controlled trial",
                    evidence_basis="abstract",
                    missing_fields=["exact effect estimate"],
                )
                for item in citations
            ],
            actor="test",
        )
        checks = save_project_retraction_checks_record(
            session,
            project.id,
            run.run_id,
            [
                CitationSafetyCheckCreate(
                    citation_id=item.id,
                    status="not_flagged_at_check_time",
                    check_source="pubmed_publication_type_client",
                    details=f"Desktop-local PubMed notice check completed for PMID {item.external_id}.",
                )
                for item in citations
            ],
            actor="test_client",
        )
        bundle = build_evidence_table_data(session, project.id, run.run_id)

    assert len(checks) == 2
    assert len(bundle["rows"]) == 2
    assert all(
        row["safety_check"]["check_source"] == "pubmed_publication_type_client"
        for row in bundle["rows"]
    )


def test_direct_plugin_receipt_ingestion_binds_signed_receipts_to_the_workflow(monkeypatch):
    secret = "test-direct-receipt-key"
    monkeypatch.setattr(settings, "skill_receipt_key", secret)
    monkeypatch.setattr(settings, "skill_receipt_enforcement", "strict")
    receipt_id = str(uuid4())
    session_id = "ses_desktop"
    timestamp = 1_784_107_500_000
    skill_name = "retraction-watcher"
    signature = hmac.new(
        secret.encode(),
        f"{receipt_id}|{session_id}|{skill_name}|{timestamp}".encode(),
        hashlib.sha256,
    ).hexdigest()
    with Session(engine) as session:
        project, _ = _screened_project(session)
        run = start_evidence_extraction_workflow_record(session, project.id, actor="test")
        imported = ingest_agent_skill_execution_receipt_journal(
            session,
            {
                "version": 1,
                "workflow_run_id": run.run_id,
                "workflow_type": "evidence_extraction",
                "subject_type": "review",
                "subject_id": project.id,
                "opencode_session_id": session_id,
                "receipts": [
                    {
                        "receipt_id": receipt_id,
                        "opencode_session_id": session_id,
                        "skill_name": skill_name,
                        "executed_at_ms": timestamp,
                        "signature": signature,
                    }
                ],
            },
        )
        require_agent_skill_receipts(
            session,
            run.run_id,
            "evidence_extraction",
            "review",
            project.id,
            "retraction_check",
            RETRACTION_SKILL,
        )

    assert imported == 1
