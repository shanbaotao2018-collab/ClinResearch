import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.main import app
from app.mcp_server import save_full_text_documents
from app.models import BiasAssessment, BinaryMetaAnalysisRun, FullTextDocument, FullTextEvidenceDetail
from app.schemas import (
    FullTextDocumentCreate,
    FullTextEvidenceDetailCreate,
    ProjectCreate,
    ScreeningDecisionCreate,
)
from app.services.agent_workflows import require_agent_skill_receipts
from app.services.citations import CitationImportPayload
from app.services.evidence_extraction import start_evidence_extraction_workflow_record
from app.services.phi_guard import PotentialPHIError
from app.services.project_workflow import (
    create_project_record,
    import_citations_record,
    submit_screening_decisions_record,
)
from app.services.systematic_evaluation import (
    BIAS_SKILLS,
    DETAIL_EXTRACTION_SKILLS,
    FULL_TEXT_SCREENING_SKILL,
    META_ANALYSIS_SKILLS,
    PDF_EXTRACTION_SKILL,
    build_systematic_evidence_bundle_data,
    request_systematic_evidence_review_record,
    require_systematic_evidence_approval,
    run_binary_meta_analysis_record,
    save_bias_assessments_record,
    save_full_text_documents_record,
    save_full_text_evidence_details_record,
    systematic_evidence_review_snapshot,
)


def _screened_project(session: Session):
    project = create_project_record(
        session,
        ProjectCreate(
            title="SGLT2 full-text evidence",
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
                    {"external_id": "26378978", "title": "Empagliflozin trial", "abstract": "RCT."},
                    {"external_id": "30415602", "title": "Dapagliflozin trial", "abstract": "RCT."},
                ],
            }
        ),
        actor="test",
    )
    submit_screening_decisions_record(
        session,
        project.id,
        [
            ScreeningDecisionCreate(citation_id=item.id, decision="include", reason="Eligible RCT.", actor="test")
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
            f"{receipt_id}|ses_systematic|{skill_name}|{timestamp}".encode(),
            hashlib.sha256,
        ).hexdigest()
        receipts.append(
            {
                "receipt_id": receipt_id,
                "opencode_session_id": "ses_systematic",
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
                "opencode_session_id": "ses_systematic",
                "receipts": receipts,
            }
        ),
        encoding="utf-8",
    )


def _rob2_domains() -> list[dict[str, str]]:
    return [
        {
            "domain": name,
            "judgement": "low",
            "rationale": "Reported in the supplied full-text methods section.",
            "source_locator": "Methods, page 3",
        }
        for name in [
            "randomization_process",
            "deviations_from_intended_interventions",
            "missing_outcome_data",
            "measurement_of_outcome",
            "selection_of_reported_result",
        ]
    ]


def test_public_full_text_contact_email_is_redacted_but_user_text_remains_guarded():
    with Session(engine) as session:
        project, citations = _screened_project(session)
        run = start_evidence_extraction_workflow_record(session, project.id, actor="test")
        saved = save_full_text_documents_record(
            session,
            project.id,
            run.run_id,
            [
                FullTextDocumentCreate(
                    citation_id=citations[0].id,
                    source_kind="open_access_html",
                    source_url="https://example.org/paper",
                    content_text="Correspondence author@example.org. This is a public article with enough source text.",
                )
            ],
            actor="test",
        )
        assert "author@example.org" not in saved[0].content_text
        assert "[redacted-public-contact-email]" in saved[0].content_text

        xml_saved = save_full_text_documents_record(
            session,
            project.id,
            run.run_id,
            [
                FullTextDocumentCreate(
                    citation_id=citations[0].id,
                    source_kind="open_access_html",
                    source_url="https://example.org/paper.xml",
                    content_text="<article><email>author@example.org</email><p>Public XML source text.</p></article>",
                )
            ],
            actor="test",
        )
        assert "author@example.org" not in xml_saved[0].content_text

        with pytest.raises(PotentialPHIError):
            save_full_text_documents_record(
                session,
                project.id,
                run.run_id,
                [
                    FullTextDocumentCreate(
                        citation_id=citations[1].id,
                        source_kind="user_provided_full_text",
                        content_text="Patient contact author@example.org. This user-provided text remains unchanged.",
                    )
                ],
                actor="test",
            )


def test_mcp_full_text_save_returns_records_before_session_closes(monkeypatch):
    monkeypatch.setattr(settings, "skill_receipt_key", None)
    with Session(engine) as session:
        project, citations = _screened_project(session)
        run = start_evidence_extraction_workflow_record(session, project.id, actor="test")
        project_id = project.id
        citation_id = citations[0].id
        workflow_run_id = run.run_id

    result = save_full_text_documents(
        project_id,
        workflow_run_id,
        [
            {
                "citation_id": citation_id,
                "source_kind": "open_access_html",
                "source_url": "https://example.org/public-paper",
                "content_text": "Public full-text content with enough non-identifying detail for a source-bound test.",
            }
        ],
    )

    assert result["saved_count"] == 1
    assert result["documents"][0]["citation_id"] == citation_id
    assert result["documents"][0]["id"] > 0


def test_full_text_evidence_bias_and_binary_meta_analysis_require_signed_skills(monkeypatch, tmp_path):
    secret = "test-systematic-receipt-key"
    monkeypatch.setattr(settings, "skill_receipt_key", secret)
    monkeypatch.setattr(settings, "skill_receipt_dir", str(tmp_path))
    monkeypatch.setattr(settings, "skill_receipt_enforcement", "strict")
    with Session(engine) as session:
        project, citations = _screened_project(session)
        run = start_evidence_extraction_workflow_record(session, project.id, actor="test")
        full_text_skills = FULL_TEXT_SCREENING_SKILL | PDF_EXTRACTION_SKILL
        with pytest.raises(ValueError, match="meta-screening-fulltext"):
            require_agent_skill_receipts(
                session, run.run_id, "evidence_extraction", "review", project.id,
                "full_text_ingestion", full_text_skills,
            )
        _write_receipts(tmp_path, secret, run, full_text_skills | DETAIL_EXTRACTION_SKILLS | BIAS_SKILLS["rob2"] | META_ANALYSIS_SKILLS)
        require_agent_skill_receipts(
            session, run.run_id, "evidence_extraction", "review", project.id,
            "full_text_ingestion", full_text_skills,
        )
        documents = save_full_text_documents_record(
            session,
            project.id,
            run.run_id,
            [
                FullTextDocumentCreate(
                    citation_id=citations[0].id,
                    source_kind="pdf_extracted_markdown",
                    source_url="https://example.org/empagliflozin.pdf",
                    content_text="Methods page 3. Randomized double-blind trial with outcome counts reported in Table 2.",
                    page_count=12,
                ),
                FullTextDocumentCreate(
                    citation_id=citations[1].id,
                    source_kind="pdf_extracted_markdown",
                    source_url="https://example.org/dapagliflozin.pdf",
                    content_text="Methods page 4. Randomized double-blind trial with outcome counts reported in Table 3.",
                    page_count=14,
                ),
            ],
            actor="test",
        )
        by_citation = {item.citation_id: item for item in documents}
        require_agent_skill_receipts(
            session, run.run_id, "evidence_extraction", "review", project.id,
            "full_text_data_extraction", DETAIL_EXTRACTION_SKILLS,
        )
        details = save_full_text_evidence_details_record(
            session,
            project.id,
            run.run_id,
            [
                FullTextEvidenceDetailCreate(
                    citation_id=citations[0].id,
                    full_text_document_id=by_citation[citations[0].id].id,
                    baseline={"participants": 100, "mean_age": 63.0},
                    outcomes=[
                        {
                            "outcome_label": "Heart-failure hospitalization",
                            "effect_measure": "rr",
                            "intervention_events": 20,
                            "intervention_total": 100,
                            "comparator_events": 35,
                            "comparator_total": 100,
                            "timepoint": "3 years",
                        }
                    ],
                ),
                FullTextEvidenceDetailCreate(
                    citation_id=citations[1].id,
                    full_text_document_id=by_citation[citations[1].id].id,
                    baseline={"participants": 160, "mean_age": 64.0},
                    outcomes=[
                        {
                            "outcome_label": "Heart-failure hospitalization",
                            "effect_measure": "rr",
                            "intervention_events": 15,
                            "intervention_total": 80,
                            "comparator_events": 28,
                            "comparator_total": 80,
                            "timepoint": "3 years",
                        }
                    ],
                ),
            ],
            actor="test",
        )
        assert len(details) == 2
        require_agent_skill_receipts(
            session, run.run_id, "evidence_extraction", "review", project.id,
            "bias_assessment", BIAS_SKILLS["rob2"],
        )
        assessments = save_bias_assessments_record(
            session,
            project.id,
            run.run_id,
            [
                {"citation_id": citation.id, "full_text_document_id": by_citation[citation.id].id, "instrument": "rob2", "overall_judgement": "low", "domains": _rob2_domains()}
                for citation in citations
            ],
            actor="test",
        )
        assert len(assessments) == 2
        require_agent_skill_receipts(
            session, run.run_id, "evidence_extraction", "review", project.id,
            "binary_meta_analysis", META_ANALYSIS_SKILLS,
        )
        meta = run_binary_meta_analysis_record(
            session, project.id, run.run_id, "Heart-failure hospitalization", "rr", "random_effects", actor="test"
        )
        result = json.loads(meta.result_json)
        assert result["study_count"] == 2
        assert result["pooled_estimate"] < 1
        assert "<svg" in meta.forest_plot_svg
        bundle = build_systematic_evidence_bundle_data(session, project.id, run.run_id)
        assert len(bundle["rows"]) == 2
        assert bundle["binary_meta_analyses"][0]["result"]["study_count"] == 2
        assert len(session.exec(select(FullTextDocument)).all()) == 2
        assert len(session.exec(select(FullTextEvidenceDetail)).all()) == 2
        assert len(session.exec(select(BiasAssessment)).all()) == 2
        assert len(session.exec(select(BinaryMetaAnalysisRun)).all()) == 1
        approval = request_systematic_evidence_review_record(session, project.id, run.run_id, actor="test")
        assert approval.status == "pending"
        with pytest.raises(ValueError, match="External researcher approval"):
            require_systematic_evidence_approval(session, project.id, run.run_id)

    monkeypatch.setattr(settings, "systematic_evidence_approval_key", "systematic-review-key")
    client = TestClient(app)
    url = f"/projects/{project.id}/systematic-evidence/{run.run_id}/approve"
    assert client.post(url, json={"approved_by": "reviewer"}).status_code == 403
    approved = client.post(
        url,
        headers={"X-Systematic-Evidence-Approval-Key": "systematic-review-key"},
        json={"approved_by": "reviewer"},
    )
    assert approved.status_code == 200
    assert approved.json()["approval"]["status"] == "approved"
    with Session(engine) as session:
        snapshot = systematic_evidence_review_snapshot(session, project.id, run.run_id)
        assert snapshot["approval"]["scope_current"] is True
        require_systematic_evidence_approval(session, project.id, run.run_id)


def test_bias_assessment_rejects_missing_full_text_domain_locator():
    with Session(engine) as session:
        project, citations = _screened_project(session)
        run = start_evidence_extraction_workflow_record(session, project.id, actor="test")
        document = save_full_text_documents_record(
            session,
            project.id,
            run.run_id,
            [
                FullTextDocumentCreate(
                    citation_id=citations[0].id,
                    source_kind="user_provided_full_text",
                    content_text="This researcher-supplied full text contains enough non-identifying source material for validation.",
                )
            ],
            actor="test",
        )[0]
        malformed = _rob2_domains()
        malformed[0].pop("source_locator")
        with pytest.raises(ValueError, match="source_locator"):
            save_bias_assessments_record(
                session,
                project.id,
                run.run_id,
                [
                    {
                        "citation_id": citations[0].id,
                        "full_text_document_id": document.id,
                        "instrument": "rob2",
                        "overall_judgement": "low",
                        "domains": malformed,
                    }
                ],
                actor="test",
            )
