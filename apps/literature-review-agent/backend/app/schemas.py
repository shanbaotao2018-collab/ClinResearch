from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class ProjectCreate(BaseModel):
    title: str
    research_question: str
    pico_population: Optional[str] = None
    pico_intervention: Optional[str] = None
    pico_comparator: Optional[str] = None
    pico_outcome: Optional[str] = None
    inclusion_criteria: Optional[str] = None
    exclusion_criteria: Optional[str] = None


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str


class SearchStrategyCreate(BaseModel):
    source: str
    query_text: str
    rationale: str


class SearchStrategyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    source: str
    query_text: str
    version_number: int
    rationale: str | None = None


class ScreeningDecisionCreate(BaseModel):
    citation_id: int
    decision: Literal["include", "exclude", "human_review"]
    reason: str
    actor: str


class PrismaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    identified_count: int
    deduplicated_count: int
    screened_count: int
    included_count: int
    excluded_count: int
    full_text_assessed_count: int


class CitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    source: str
    external_id: str | None = None
    title: str
    abstract: str | None = None
    authors: str | None = None
    publication_year: int | None = None
    doi: str | None = None
    is_deduplicated: bool
    dedup_group: str | None = None


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    action: str
    actor: str
    summary: str


class StudyDesignProjectCreate(BaseModel):
    title: str
    research_question: str
    study_type: Literal["diagnostic", "efficacy", "etiology", "prognosis"]
    study_design: str
    population: str
    outcome: str
    intervention: Optional[str] = None
    comparator: Optional[str] = None
    department: Optional[str] = None
    resource_summary: Optional[str] = None


class StudyDesignProjectRead(StudyDesignProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    protocol_standard: str | None = None
    inclusion_criteria: str | None = None
    exclusion_criteria: str | None = None
    primary_outcome: str | None = None
    secondary_outcomes: str | None = None
    innovation_notes: str | None = None
    feasibility_notes: str | None = None
    proposal_outline: str | None = None
    sample_size_method: str | None = None
    sample_size_inputs_json: str | None = None
    sample_size_result_json: str | None = None
    randomization_seed: int | None = None
    randomization_schedule_json: str | None = None
    human_confirmed_by: str | None = None
    status: str


class StudyDesignContentUpdate(BaseModel):
    inclusion_criteria: str
    exclusion_criteria: str
    primary_outcome: str
    secondary_outcomes: str | None = None
    innovation_notes: str | None = None
    feasibility_notes: str | None = None
    proposal_outline: str


class StudyDesignAuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    study_design_project_id: int
    action: str
    actor: str
    summary: str


class StudyDesignApprovalRequest(BaseModel):
    approved_by: str


class StudyDesignRandomizationPlanCreate(BaseModel):
    total_subjects: int
    groups: list[str]
    block_size: int


class StudyDesignApprovalRead(BaseModel):
    project_id: int
    project_status: str
    approval: dict | None = None


class StudyDesignWorkflowEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_run_id: str
    study_design_project_id: int
    operation: str
    input_digest: str
    output_digest: str


class EvidenceExtractionCreate(BaseModel):
    citation_id: int
    study_design: str | None = None
    population: str | None = None
    sample_size: str | None = None
    intervention_or_exposure: str | None = None
    comparator: str | None = None
    outcomes: str | None = None
    effect_estimates: str | None = None
    methods_summary: str | None = None
    evidence_basis: Literal["metadata", "abstract", "full_text_excerpt"]
    missing_fields: list[str] = []
    needs_human_review: bool = True


class CitationSafetyCheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    citation_id: int
    status: str
    check_source: str
    details: str | None = None
    needs_human_review: bool


class ResearchWritingDraftCreate(BaseModel):
    title: str
    target_audience: str | None = None
    source_manifest: list[dict[str, str]]
    outline: str
    methods_draft: str | None = None
    discussion_framework: str | None = None
    proposal_draft: str | None = None
    limitations: str
    unresolved_items: str
