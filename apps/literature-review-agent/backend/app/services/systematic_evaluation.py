from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from html import escape
from typing import Any

from sqlmodel import Session, select

from app.models import (
    BiasAssessment,
    BinaryMetaAnalysisRun,
    FullTextDocument,
    FullTextEvidenceDetail,
    SystematicEvidenceReviewApproval,
)
from app.schemas import BiasAssessmentCreate, FullTextDocumentCreate, FullTextEvidenceDetailCreate
from app.services.agent_workflows import get_agent_workflow_run, record_agent_workflow_event
from app.services.evidence_extraction import included_citations
from app.services.phi_guard import assert_no_phi, redact_public_contact_emails


_WORKFLOW_TYPE = "evidence_extraction"
_SUBJECT_TYPE = "review"
FULL_TEXT_SCREENING_SKILL = {"meta-screening-fulltext"}
FULL_TEXT_FETCH_SKILL = {"fulltext-fetcher"}
PDF_EXTRACTION_SKILL = {"pdf-extract"}
DETAIL_EXTRACTION_SKILLS = {
    "baseline-extraction-for-clinical-trials",
    "outcome-extraction-for-clinical-trials",
}
META_ANALYSIS_SKILLS = {"meta-analysis", "meta-forest-binary-plot"}
BIAS_SKILLS = {
    "rob2": {"rct-bias-assessment-rob"},
    "nos": {"cohort-study-quality-assessment-nos"},
    "quadas2": {"diagnostic-study-quality-assessment-quadas"},
}

_BIAS_DOMAINS = {
    "rob2": {
        "randomization_process",
        "deviations_from_intended_interventions",
        "missing_outcome_data",
        "measurement_of_outcome",
        "selection_of_reported_result",
    },
    "nos": {"selection", "comparability", "outcome_or_exposure"},
    "quadas2": {"patient_selection", "index_test", "reference_standard", "flow_and_timing"},
}
_BIAS_JUDGEMENTS = {
    "rob2": {"low", "some_concerns", "high"},
    "nos": {"low", "moderate", "high"},
    "quadas2": {"low", "high", "unclear"},
}


def _workflow_or_raise(session: Session, project_id: int, workflow_run_id: str) -> None:
    get_agent_workflow_run(
        session, workflow_run_id, _WORKFLOW_TYPE, _SUBJECT_TYPE, project_id
    )


def _included_ids(session: Session, project_id: int) -> set[int]:
    return {citation.id for citation in included_citations(session, project_id)}


def _full_text_or_raise(
    session: Session, project_id: int, citation_id: int, document_id: int
) -> FullTextDocument:
    document = session.get(FullTextDocument, document_id)
    if not document or document.project_id != project_id or document.citation_id != citation_id:
        raise ValueError("full_text_document_id must belong to the included citation in this project.")
    return document


def _stored_full_text_content(payload: FullTextDocumentCreate) -> str:
    """Keep public-paper contact metadata out of the stored evidence source text."""
    content = payload.content_text.strip()
    if payload.source_kind != "user_provided_full_text":
        return redact_public_contact_emails(content)
    return content


def validate_full_text_documents(
    session: Session, project_id: int, documents: list[FullTextDocumentCreate]
) -> None:
    included_ids = _included_ids(session, project_id)
    submitted_ids = [item.citation_id for item in documents]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise ValueError("Each citation may have only one full-text document per save operation.")
    unknown = sorted(set(submitted_ids) - included_ids)
    if unknown:
        raise ValueError(f"Full-text documents require included citations only: {unknown}.")
    for item in documents:
        content = _stored_full_text_content(item)
        # Public HTML/PDF sometimes contains author contact details. Only those
        # addresses are redacted; all remaining text still passes the PHI guard.
        assert_no_phi({**item.model_dump(), "content_text": content})
        if len(content) < 40:
            raise ValueError("Full-text content must contain at least 40 characters of source text.")
        if len(content) > 2_000_000:
            raise ValueError("Full-text content exceeds the 2,000,000 character safety limit.")
        if item.page_count is not None and item.page_count < 1:
            raise ValueError("page_count must be positive when supplied.")
        if item.source_kind != "user_provided_full_text" and not item.source_url:
            raise ValueError("Public HTML and PDF sources require an HTTPS source_url.")
        if item.source_url and not item.source_url.startswith("https://"):
            raise ValueError("source_url must use HTTPS when supplied.")


def save_full_text_documents_record(
    session: Session,
    project_id: int,
    workflow_run_id: str,
    documents: list[FullTextDocumentCreate],
    actor: str = "mcp",
) -> list[FullTextDocument]:
    _workflow_or_raise(session, project_id, workflow_run_id)
    validate_full_text_documents(session, project_id, documents)
    saved: list[FullTextDocument] = []
    for payload in documents:
        content = _stored_full_text_content(payload)
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        record = session.exec(
            select(FullTextDocument).where(
                FullTextDocument.project_id == project_id,
                FullTextDocument.citation_id == payload.citation_id,
                FullTextDocument.source_kind == payload.source_kind,
            )
        ).first()
        if record is None:
            record = FullTextDocument(
                project_id=project_id,
                citation_id=payload.citation_id,
                source_kind=payload.source_kind,
                source_url=payload.source_url,
                content_text=content,
                content_sha256=checksum,
                page_count=payload.page_count,
                needs_human_review=True,
            )
        else:
            record.source_url = payload.source_url
            record.content_text = content
            record.content_sha256 = checksum
            record.page_count = payload.page_count
            record.needs_human_review = True
            record.updated_at = datetime.now(UTC)
        session.add(record)
        saved.append(record)
    session.commit()
    for record in saved:
        session.refresh(record)
    result = {
        "project_id": project_id,
        "saved_count": len(saved),
        "document_ids": [item.id for item in saved],
        "citation_ids": [item.citation_id for item in saved],
    }
    record_agent_workflow_event(
        session,
        workflow_run_id,
        _WORKFLOW_TYPE,
        _SUBJECT_TYPE,
        project_id,
        "save_full_text_documents",
        {"count": len(documents), "actor": actor},
        result,
    )
    return saved


def _validated_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
    required = {
        "outcome_label",
        "effect_measure",
        "intervention_events",
        "intervention_total",
        "comparator_events",
        "comparator_total",
    }
    missing = sorted(required - set(outcome))
    if missing:
        raise ValueError(f"Binary outcome is missing required fields: {missing}.")
    measure = str(outcome["effect_measure"]).lower()
    if measure not in {"rr", "or"}:
        raise ValueError("Binary outcome effect_measure must be 'rr' or 'or'.")
    normalized: dict[str, Any] = {
        "outcome_label": str(outcome["outcome_label"]).strip(),
        "effect_measure": measure,
        "timepoint": str(outcome.get("timepoint") or "not_reported").strip(),
    }
    if not normalized["outcome_label"]:
        raise ValueError("outcome_label must not be empty.")
    for name in (
        "intervention_events",
        "intervention_total",
        "comparator_events",
        "comparator_total",
    ):
        value = outcome[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
            raise ValueError(f"{name} must be an integer.")
        normalized[name] = int(value)
    if normalized["intervention_total"] <= 0 or normalized["comparator_total"] <= 0:
        raise ValueError("Binary outcome totals must be positive.")
    if not 0 <= normalized["intervention_events"] <= normalized["intervention_total"]:
        raise ValueError("intervention_events must be between zero and intervention_total.")
    if not 0 <= normalized["comparator_events"] <= normalized["comparator_total"]:
        raise ValueError("comparator_events must be between zero and comparator_total.")
    return normalized


def validate_full_text_evidence_details(
    session: Session, project_id: int, details: list[FullTextEvidenceDetailCreate]
) -> None:
    included_ids = _included_ids(session, project_id)
    submitted_ids = [item.citation_id for item in details]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise ValueError("Each citation may have only one detailed extraction per save operation.")
    unknown = sorted(set(submitted_ids) - included_ids)
    if unknown:
        raise ValueError(f"Detailed extraction requires included citations only: {unknown}.")
    for item in details:
        assert_no_phi(item.model_dump())
        _full_text_or_raise(session, project_id, item.citation_id, item.full_text_document_id)
        seen_outcomes: set[tuple[str, str, str]] = set()
        for outcome in item.outcomes:
            normalized = _validated_outcome(outcome)
            key = (
                normalized["outcome_label"].casefold(),
                normalized["effect_measure"],
                normalized["timepoint"].casefold(),
            )
            if key in seen_outcomes:
                raise ValueError("Each detailed extraction may contain an outcome once per measure and timepoint.")
            seen_outcomes.add(key)


def save_full_text_evidence_details_record(
    session: Session,
    project_id: int,
    workflow_run_id: str,
    details: list[FullTextEvidenceDetailCreate],
    actor: str = "mcp",
) -> list[FullTextEvidenceDetail]:
    _workflow_or_raise(session, project_id, workflow_run_id)
    validate_full_text_evidence_details(session, project_id, details)
    saved: list[FullTextEvidenceDetail] = []
    for payload in details:
        outcomes = [_validated_outcome(item) for item in payload.outcomes]
        record = session.exec(
            select(FullTextEvidenceDetail).where(
                FullTextEvidenceDetail.project_id == project_id,
                FullTextEvidenceDetail.citation_id == payload.citation_id,
                FullTextEvidenceDetail.full_text_document_id == payload.full_text_document_id,
            )
        ).first()
        values = {
            "baseline_json": json.dumps(payload.baseline, ensure_ascii=False, sort_keys=True),
            "outcomes_json": json.dumps(outcomes, ensure_ascii=False, sort_keys=True),
            "extraction_notes": payload.extraction_notes,
            "needs_human_review": True,
        }
        if record is None:
            record = FullTextEvidenceDetail(
                project_id=project_id,
                citation_id=payload.citation_id,
                full_text_document_id=payload.full_text_document_id,
                **values,
            )
        else:
            for field, value in values.items():
                setattr(record, field, value)
            record.updated_at = datetime.now(UTC)
        session.add(record)
        saved.append(record)
    session.commit()
    for record in saved:
        session.refresh(record)
    result = {
        "project_id": project_id,
        "saved_count": len(saved),
        "detail_ids": [item.id for item in saved],
        "citation_ids": [item.citation_id for item in saved],
    }
    record_agent_workflow_event(
        session,
        workflow_run_id,
        _WORKFLOW_TYPE,
        _SUBJECT_TYPE,
        project_id,
        "save_full_text_evidence_details",
        {"count": len(details), "actor": actor},
        result,
    )
    return saved


def validate_bias_assessments(
    session: Session, project_id: int, assessments: list[BiasAssessmentCreate]
) -> None:
    included_ids = _included_ids(session, project_id)
    for payload in assessments:
        assert_no_phi(payload.model_dump())
        if payload.citation_id not in included_ids:
            raise ValueError("Bias assessment requires an included citation.")
        _full_text_or_raise(session, project_id, payload.citation_id, payload.full_text_document_id)
        if payload.overall_judgement not in _BIAS_JUDGEMENTS[payload.instrument]:
            raise ValueError(f"Invalid overall judgement for {payload.instrument}.")
        expected_domains = _BIAS_DOMAINS[payload.instrument]
        supplied_domains = {item.get("domain") for item in payload.domains}
        if supplied_domains != expected_domains:
            raise ValueError(
                f"{payload.instrument} requires exactly these domains: {sorted(expected_domains)}."
            )
        for domain in payload.domains:
            if domain.get("judgement") not in _BIAS_JUDGEMENTS[payload.instrument]:
                raise ValueError(f"Invalid judgement for {payload.instrument} domain.")
            if not domain.get("rationale") or not domain.get("source_locator"):
                raise ValueError("Every bias domain requires a rationale and source_locator from full text.")


def save_bias_assessments_record(
    session: Session,
    project_id: int,
    workflow_run_id: str,
    assessments: list[BiasAssessmentCreate | dict[str, Any]],
    actor: str = "mcp",
) -> list[BiasAssessment]:
    _workflow_or_raise(session, project_id, workflow_run_id)
    assessments = [
        item if isinstance(item, BiasAssessmentCreate) else BiasAssessmentCreate.model_validate(item)
        for item in assessments
    ]
    validate_bias_assessments(session, project_id, assessments)
    saved: list[BiasAssessment] = []
    for payload in assessments:
        record = session.exec(
            select(BiasAssessment).where(
                BiasAssessment.project_id == project_id,
                BiasAssessment.citation_id == payload.citation_id,
                BiasAssessment.instrument == payload.instrument,
            )
        ).first()
        values = {
            "full_text_document_id": payload.full_text_document_id,
            "overall_judgement": payload.overall_judgement,
            "domains_json": json.dumps(payload.domains, ensure_ascii=False, sort_keys=True),
            "needs_human_review": True,
        }
        if record is None:
            record = BiasAssessment(
                project_id=project_id,
                citation_id=payload.citation_id,
                instrument=payload.instrument,
                **values,
            )
        else:
            for field, value in values.items():
                setattr(record, field, value)
            record.updated_at = datetime.now(UTC)
        session.add(record)
        saved.append(record)
    session.commit()
    for record in saved:
        session.refresh(record)
    result = {
        "project_id": project_id,
        "saved_count": len(saved),
        "assessment_ids": [item.id for item in saved],
    }
    record_agent_workflow_event(
        session,
        workflow_run_id,
        _WORKFLOW_TYPE,
        _SUBJECT_TYPE,
        project_id,
        "save_bias_assessments",
        {"count": len(assessments), "actor": actor},
        result,
    )
    return saved


def required_bias_skills_for_project(session: Session, project_id: int) -> set[str]:
    """Return only the appraisal methods actually recorded for this review."""
    instruments = {
        item.instrument
        for item in session.exec(
            select(BiasAssessment.instrument).where(BiasAssessment.project_id == project_id)
        ).all()
    }
    required: set[str] = set()
    for instrument in instruments:
        required.update(BIAS_SKILLS.get(instrument, set()))
    return required


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _gamma_q(shape: float, value: float) -> float:
    """Regularized upper incomplete gamma; enough for chi-square Q p-values."""
    if value <= 0:
        return 1.0
    if value < shape + 1.0:
        term = 1.0 / shape
        total = term
        current = shape
        for _ in range(200):
            current += 1.0
            term *= value / current
            total += term
            if abs(term) < abs(total) * 1e-14:
                break
        lower = total * math.exp(-value + shape * math.log(value) - math.lgamma(shape))
        return max(0.0, min(1.0, 1.0 - lower))
    tiny = 1e-300
    b = value + 1.0 - shape
    c = 1.0 / tiny
    d = 1.0 / max(b, tiny)
    fraction = d
    for index in range(1, 200):
        coefficient = -index * (index - shape)
        b += 2.0
        d = coefficient * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + coefficient / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        fraction *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    result = math.exp(-value + shape * math.log(value) - math.lgamma(shape)) * fraction
    return max(0.0, min(1.0, result))


def _binary_effect(outcome: dict[str, Any]) -> dict[str, Any]:
    a = outcome["intervention_events"]
    intervention_total = outcome["intervention_total"]
    c = outcome["comparator_events"]
    comparator_total = outcome["comparator_total"]
    b = intervention_total - a
    d = comparator_total - c
    correction_applied = any(value == 0 for value in (a, b, c, d))
    if correction_applied:
        a += 0.5
        b += 0.5
        c += 0.5
        d += 0.5
        intervention_total = a + b
        comparator_total = c + d
    if outcome["effect_measure"] == "rr":
        effect = math.log((a / intervention_total) / (c / comparator_total))
        variance = (1 / a) - (1 / intervention_total) + (1 / c) - (1 / comparator_total)
    else:
        effect = math.log((a * d) / (b * c))
        variance = (1 / a) + (1 / b) + (1 / c) + (1 / d)
    standard_error = math.sqrt(variance)
    return {
        "log_effect": effect,
        "variance": variance,
        "standard_error": standard_error,
        "estimate": math.exp(effect),
        "ci_lower": math.exp(effect - 1.96 * standard_error),
        "ci_upper": math.exp(effect + 1.96 * standard_error),
        "continuity_correction_applied": correction_applied,
    }


def _latest_details_by_citation(session: Session, project_id: int) -> dict[int, FullTextEvidenceDetail]:
    records = session.exec(
        select(FullTextEvidenceDetail)
        .where(FullTextEvidenceDetail.project_id == project_id)
        .order_by(FullTextEvidenceDetail.updated_at.desc(), FullTextEvidenceDetail.id.desc())
    ).all()
    latest: dict[int, FullTextEvidenceDetail] = {}
    for record in records:
        latest.setdefault(record.citation_id, record)
    return latest


def _binary_outcomes_for_meta(
    session: Session, project_id: int, outcome_label: str, effect_measure: str
) -> list[dict[str, Any]]:
    citations = {item.id: item for item in included_citations(session, project_id)}
    details = _latest_details_by_citation(session, project_id)
    selected: list[dict[str, Any]] = []
    wanted = outcome_label.strip().casefold()
    for citation_id, detail in details.items():
        if citation_id not in citations:
            continue
        for outcome in json.loads(detail.outcomes_json):
            normalized = _validated_outcome(outcome)
            if (
                normalized["outcome_label"].casefold() == wanted
                and normalized["effect_measure"] == effect_measure
            ):
                selected.append(
                    {
                        "citation_id": citation_id,
                        "title": citations[citation_id].title,
                        "full_text_document_id": detail.full_text_document_id,
                        **normalized,
                        **_binary_effect(normalized),
                    }
                )
    if len(selected) < 2:
        raise ValueError(
            "Binary meta-analysis requires at least two included studies with matching full-text outcome data."
        )
    return selected


def _forest_plot_svg(studies: list[dict[str, Any]], result: dict[str, Any]) -> str:
    all_limits = [1.0]
    for study in studies:
        all_limits.extend([study["ci_lower"], study["ci_upper"]])
    all_limits.extend([result["pooled_ci_lower"], result["pooled_ci_upper"]])
    lower = math.log(max(min(all_limits), 1e-9))
    upper = math.log(max(all_limits))
    margin = max((upper - lower) * 0.08, 0.12)
    lower -= margin
    upper += margin
    width, left, right = 1200, 420, 880
    height = 150 + len(studies) * 42

    def x(value: float) -> float:
        return left + (math.log(value) - lower) / (upper - lower) * (right - left)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<style>text{font-family:Arial,sans-serif;font-size:13px;fill:#15202b}.small{font-size:11px;fill:#52616b}.axis{stroke:#52616b;stroke-width:1}.ci{stroke:#1f5a7a;stroke-width:2}.square{fill:#1f5a7a}.diamond{fill:#c76b20;stroke:#813c0c}</style>',
        f'<text x="20" y="28" font-size="18" font-weight="bold">Forest plot: {escape(result["outcome_label"])}</text>',
        f'<text x="20" y="49" class="small">{escape(result["effect_measure"].upper())}; {escape(result["model_label"])}; all estimates require researcher verification</text>',
        f'<line class="axis" x1="{x(1.0):.1f}" y1="65" x2="{x(1.0):.1f}" y2="{height - 28}" stroke-dasharray="4 4"/>',
    ]
    for index, study in enumerate(studies):
        y = 92 + index * 42
        title = study["title"]
        if len(title) > 52:
            title = f"{title[:49]}..."
        lines.extend(
            [
                f'<text x="20" y="{y + 4}">{escape(title)}</text>',
                f'<line class="ci" x1="{x(study["ci_lower"]):.1f}" y1="{y}" x2="{x(study["ci_upper"]):.1f}" y2="{y}"/>',
                f'<rect class="square" x="{x(study["estimate"]) - 4:.1f}" y="{y - 4}" width="8" height="8"/>',
                f'<text x="905" y="{y + 4}">{study["estimate"]:.2f} [{study["ci_lower"]:.2f}, {study["ci_upper"]:.2f}]</text>',
            ]
        )
    pooled_y = 100 + len(studies) * 42
    center = x(result["pooled_estimate"])
    low = x(result["pooled_ci_lower"])
    high = x(result["pooled_ci_upper"])
    lines.extend(
        [
            f'<text x="20" y="{pooled_y + 4}" font-weight="bold">Pooled estimate</text>',
            f'<polygon class="diamond" points="{low:.1f},{pooled_y} {center:.1f},{pooled_y - 8} {high:.1f},{pooled_y} {center:.1f},{pooled_y + 8}"/>',
            f'<text x="905" y="{pooled_y + 4}" font-weight="bold">{result["pooled_estimate"]:.2f} [{result["pooled_ci_lower"]:.2f}, {result["pooled_ci_upper"]:.2f}]</text>',
            f'<text x="20" y="{height - 14}" class="small">I² = {result["i_squared"]:.1f}% | Q = {result["q"]:.2f} | tau² = {result["tau_squared"]:.4f} | k = {result["study_count"]}</text>',
            '</svg>',
        ]
    )
    return "".join(lines)


def run_binary_meta_analysis_record(
    session: Session,
    project_id: int,
    workflow_run_id: str,
    outcome_label: str,
    effect_measure: str = "rr",
    model: str = "random_effects",
    actor: str = "mcp",
) -> BinaryMetaAnalysisRun:
    _workflow_or_raise(session, project_id, workflow_run_id)
    effect_measure = effect_measure.lower().strip()
    if effect_measure not in {"rr", "or"}:
        raise ValueError("effect_measure must be 'rr' or 'or'.")
    if model not in {"fixed_effect", "random_effects"}:
        raise ValueError("model must be 'fixed_effect' or 'random_effects'.")
    studies = _binary_outcomes_for_meta(session, project_id, outcome_label, effect_measure)
    effects = [item["log_effect"] for item in studies]
    variances = [item["variance"] for item in studies]
    fixed_weights = [1.0 / value for value in variances]
    fixed_effect = sum(weight * effect for weight, effect in zip(fixed_weights, effects)) / sum(fixed_weights)
    q = sum(weight * (effect - fixed_effect) ** 2 for weight, effect in zip(fixed_weights, effects))
    degrees_freedom = len(studies) - 1
    c_value = sum(fixed_weights) - sum(weight**2 for weight in fixed_weights) / sum(fixed_weights)
    tau_squared = max(0.0, (q - degrees_freedom) / c_value) if c_value > 0 else 0.0
    i_squared = max(0.0, (q - degrees_freedom) / q * 100.0) if q > 0 else 0.0
    weights = (
        fixed_weights
        if model == "fixed_effect"
        else [1.0 / (variance + tau_squared) for variance in variances]
    )
    pooled_log_effect = sum(weight * effect for weight, effect in zip(weights, effects)) / sum(weights)
    pooled_se = math.sqrt(1.0 / sum(weights))
    result = {
        "outcome_label": outcome_label.strip(),
        "effect_measure": effect_measure,
        "model": model,
        "model_label": "fixed-effect" if model == "fixed_effect" else "DerSimonian-Laird random-effects",
        "study_count": len(studies),
        "pooled_log_effect": pooled_log_effect,
        "pooled_estimate": math.exp(pooled_log_effect),
        "pooled_ci_lower": math.exp(pooled_log_effect - 1.96 * pooled_se),
        "pooled_ci_upper": math.exp(pooled_log_effect + 1.96 * pooled_se),
        "pooled_p_value": 2.0 * (1.0 - _normal_cdf(abs(pooled_log_effect / pooled_se))),
        "q": q,
        "q_degrees_freedom": degrees_freedom,
        "q_p_value": _gamma_q(degrees_freedom / 2.0, q / 2.0),
        "i_squared": i_squared,
        "tau_squared": tau_squared,
        "studies": studies,
        "limitations": [
            "Only researcher-supplied full-text binary event counts are pooled.",
            "Continuity correction of 0.5 is used only when a 2x2 table has a zero cell.",
            "The pooled result and forest plot require statistical and clinical review before use.",
        ],
    }
    forest_plot_svg = _forest_plot_svg(studies, result)
    record = BinaryMetaAnalysisRun(
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        outcome_label=result["outcome_label"],
        effect_measure=effect_measure,
        model=model,
        result_json=json.dumps(result, ensure_ascii=False, sort_keys=True),
        forest_plot_svg=forest_plot_svg,
        needs_human_review=True,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    record_agent_workflow_event(
        session,
        workflow_run_id,
        _WORKFLOW_TYPE,
        _SUBJECT_TYPE,
        project_id,
        "run_binary_meta_analysis",
        {"outcome_label": outcome_label, "effect_measure": effect_measure, "model": model, "actor": actor},
        {"meta_analysis_id": record.id, "study_count": len(studies)},
    )
    return record


def build_systematic_evidence_bundle_data(
    session: Session, project_id: int, workflow_run_id: str
) -> dict[str, Any]:
    _workflow_or_raise(session, project_id, workflow_run_id)
    citations = included_citations(session, project_id)
    citation_ids = {item.id for item in citations}
    documents = {
        item.citation_id: item
        for item in session.exec(
            select(FullTextDocument).where(FullTextDocument.project_id == project_id)
        ).all()
    }
    details = _latest_details_by_citation(session, project_id)
    bias_by_citation: dict[int, list[BiasAssessment]] = {}
    for assessment in session.exec(
        select(BiasAssessment).where(BiasAssessment.project_id == project_id)
    ).all():
        bias_by_citation.setdefault(assessment.citation_id, []).append(assessment)
    missing_documents = sorted(citation_ids - documents.keys())
    missing_details = sorted(citation_ids - details.keys())
    missing_bias = sorted(citation_ids - bias_by_citation.keys())
    if missing_documents or missing_details or missing_bias:
        raise ValueError(
            "Systematic evidence export requires full text, detailed extraction, and bias assessment for every included citation. "
            f"Missing documents: {missing_documents}; details: {missing_details}; bias: {missing_bias}."
        )
    rows = []
    for citation in citations:
        document = documents[citation.id]
        detail = details[citation.id]
        rows.append(
            {
                "citation_id": citation.id,
                "title": citation.title,
                "doi": citation.doi,
                "full_text": {
                    "document_id": document.id,
                    "source_kind": document.source_kind,
                    "source_url": document.source_url,
                    "content_sha256": document.content_sha256,
                    "page_count": document.page_count,
                    "needs_human_review": document.needs_human_review,
                },
                "baseline": json.loads(detail.baseline_json),
                "outcomes": json.loads(detail.outcomes_json),
                "extraction_notes": detail.extraction_notes,
                "bias_assessments": [
                    {
                        "instrument": item.instrument,
                        "overall_judgement": item.overall_judgement,
                        "domains": json.loads(item.domains_json),
                        "needs_human_review": item.needs_human_review,
                    }
                    for item in bias_by_citation[citation.id]
                ],
            }
        )
    meta_runs = session.exec(
        select(BinaryMetaAnalysisRun)
        .where(BinaryMetaAnalysisRun.project_id == project_id)
        .order_by(BinaryMetaAnalysisRun.created_at.desc())
    ).all()
    return {
        "project_id": project_id,
        "workflow_run_id": workflow_run_id,
        "rows": rows,
        "binary_meta_analyses": [
            {
                "id": item.id,
                "result": json.loads(item.result_json),
                "forest_plot_svg": item.forest_plot_svg,
                "needs_human_review": item.needs_human_review,
            }
            for item in meta_runs
        ],
        "limitations": [
            "Full-text content remains source-bound and every extracted field must be checked against the cited location.",
            "RoB 2, NOS, and QUADAS-2 entries are preliminary structured assessments, not final review judgements.",
            "Meta-analysis output is restricted to matching binary RR or OR data from included studies.",
        ],
    }


def _systematic_bundle_digest(bundle: dict[str, Any]) -> str:
    encoded = json.dumps(bundle, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def request_systematic_evidence_review_record(
    session: Session, project_id: int, workflow_run_id: str, actor: str = "mcp"
) -> SystematicEvidenceReviewApproval:
    bundle = build_systematic_evidence_bundle_data(session, project_id, workflow_run_id)
    scope_digest = _systematic_bundle_digest(bundle)
    approval = session.exec(
        select(SystematicEvidenceReviewApproval).where(
            SystematicEvidenceReviewApproval.workflow_run_id == workflow_run_id
        )
    ).first()
    if approval is None:
        approval = SystematicEvidenceReviewApproval(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            scope_digest=scope_digest,
        )
    elif approval.scope_digest != scope_digest:
        approval.scope_digest = scope_digest
        approval.status = "pending"
        approval.approved_by = None
        approval.approved_at = None
        approval.requested_at = datetime.now(UTC)
    session.add(approval)
    session.commit()
    session.refresh(approval)
    record_agent_workflow_event(
        session, workflow_run_id, _WORKFLOW_TYPE, _SUBJECT_TYPE, project_id,
        "request_systematic_evidence_review", {"actor": actor},
        {"status": approval.status, "scope_digest": approval.scope_digest},
    )
    return approval


def systematic_evidence_review_snapshot(
    session: Session, project_id: int, workflow_run_id: str
) -> dict[str, Any]:
    _workflow_or_raise(session, project_id, workflow_run_id)
    approval = session.exec(
        select(SystematicEvidenceReviewApproval).where(
            SystematicEvidenceReviewApproval.workflow_run_id == workflow_run_id
        )
    ).first()
    if approval is None:
        return {"project_id": project_id, "workflow_run_id": workflow_run_id, "approval": None}
    current_digest = _systematic_bundle_digest(
        build_systematic_evidence_bundle_data(session, project_id, workflow_run_id)
    )
    return {
        "project_id": project_id,
        "workflow_run_id": workflow_run_id,
        "approval": {
            "status": approval.status,
            "scope_digest": approval.scope_digest,
            "scope_current": approval.scope_digest == current_digest,
            "requested_at": approval.requested_at,
            "approved_by": approval.approved_by,
            "approved_at": approval.approved_at,
        },
    }


def approve_systematic_evidence_review_record(
    session: Session, project_id: int, workflow_run_id: str, approved_by: str
) -> SystematicEvidenceReviewApproval:
    if not approved_by.strip():
        raise ValueError("approved_by is required.")
    approval = session.exec(
        select(SystematicEvidenceReviewApproval).where(
            SystematicEvidenceReviewApproval.workflow_run_id == workflow_run_id
        )
    ).first()
    if approval is None or approval.project_id != project_id:
        raise ValueError("Systematic evidence review must be requested before approval.")
    current_digest = _systematic_bundle_digest(
        build_systematic_evidence_bundle_data(session, project_id, workflow_run_id)
    )
    if approval.scope_digest != current_digest:
        raise ValueError("Systematic evidence changed after review request; request a new approval.")
    approval.status = "approved"
    approval.approved_by = approved_by.strip()
    approval.approved_at = datetime.now(UTC)
    session.add(approval)
    session.commit()
    session.refresh(approval)
    return approval


def require_systematic_evidence_approval(
    session: Session, project_id: int, workflow_run_id: str
) -> None:
    snapshot = systematic_evidence_review_snapshot(session, project_id, workflow_run_id)
    approval = snapshot["approval"]
    if not approval or approval["status"] != "approved" or not approval["scope_current"]:
        raise ValueError(
            "External researcher approval for the current systematic evidence bundle is required before export."
        )


def render_systematic_evidence_bundle_markdown(bundle: dict[str, Any]) -> str:
    lines = [
        f"# Full-Text Systematic Evidence Bundle: Review Project {bundle['project_id']}",
        "",
        "## Full-Text Evidence Rows",
        "",
        "| Citation | Full-Text Source | Baseline Fields | Binary Outcomes | Bias Assessment | Human Review |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in bundle["rows"]:
        assessment = "; ".join(
            f"{item['instrument']}: {item['overall_judgement']}" for item in row["bias_assessments"]
        )
        lines.append(
            "| {title} | {source} | {baseline} | {outcomes} | {assessment} | required |".format(
                title=(row["title"] or "").replace("|", "\\|"),
                source=row["full_text"]["source_kind"],
                baseline=", ".join(row["baseline"].keys()) or "not_reported",
                outcomes=", ".join(item["outcome_label"] for item in row["outcomes"]) or "not_reported",
                assessment=assessment or "not_assessed",
            )
        )
    lines.extend(["", "## Binary Meta-Analyses"])
    if not bundle["binary_meta_analyses"]:
        lines.append("- No binary meta-analysis has been run for this project.")
    for analysis in bundle["binary_meta_analyses"]:
        result = analysis["result"]
        lines.extend(
            [
                f"### {result['outcome_label']} ({result['effect_measure'].upper()})",
                f"- {result['model_label']}; k={result['study_count']}; pooled={result['pooled_estimate']:.2f} "
                f"[{result['pooled_ci_lower']:.2f}, {result['pooled_ci_upper']:.2f}]; I²={result['i_squared']:.1f}%.",
                "- Forest plot is included in the JSON export as SVG.",
            ]
        )
    lines.extend(["", "## Limitations"])
    lines.extend(f"- {item}" for item in bundle["limitations"])
    lines.append("")
    return "\n".join(lines)
